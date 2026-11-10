"""Exercise durable queue behavior against PostgreSQL."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import engine
from app.documents.models import Document
from app.jobs.models import Job, JobStatus
from app.jobs.schemas import JobContext, JobRequest
from app.jobs.service import queue
from app.jobs.service.execution import execute_claim
from app.jobs.service.queue import BATCH_SIZE, MAX_ATTEMPTS, claim_jobs, enqueue_job, queue_time
from tests.factories import make_document, make_workspace


def _request(key: str, **values: object) -> JobRequest:
    return JobRequest.model_validate(
        {"type": "test_job", "workspace_id": None, "idempotency_key": key} | values
    )


def test_enqueue_is_idempotent_and_uses_the_callers_transaction(db: Session) -> None:
    request = _request("save-1", payload={"revision": 1})
    with db.begin_nested() as transaction:
        job_id = enqueue_job(db, request)
        assert enqueue_job(db, request) == job_id
        with pytest.raises(ValueError, match="idempotency key"):
            enqueue_job(db, _request("save-1", payload={"revision": 2}))
        transaction.rollback()

    assert db.get(Job, job_id) is None


def test_idempotency_distinguishes_json_booleans_from_numbers(db: Session) -> None:
    request = _request("same-key", payload={"options": {"include_archived": True}})
    job_id = enqueue_job(db, request)

    with pytest.raises(ValueError, match="idempotency key"):
        enqueue_job(db, _request("same-key", payload={"options": {"include_archived": 1}}))
    assert enqueue_job(db, request) == job_id


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"attempts": -1}, "attempts_non_negative"),
        ({"status": JobStatus.RUNNING}, "running_lease"),
        ({"payload": []}, "payload_object"),
        ({"status": "unknown"}, "status"),
    ],
)
def test_database_rejects_invalid_queue_rows(
    db: Session, values: dict[str, object], constraint: str
) -> None:
    row: dict[str, object] = {"type": "test_job", "idempotency_key": "global:job", "payload": {}}
    with pytest.raises(IntegrityError, match=f"ck_jobs_{constraint}"):
        db.execute(insert(Job).values(row | values))


def test_claim_waits_until_due_and_only_claims_installed_job_types(db: Session) -> None:
    future = enqueue_job(db, _request("future", next_run_at=datetime.now(UTC) + timedelta(days=1)))
    other_type = enqueue_job(db, _request("export", type="generate_export"))
    due = enqueue_job(db, _request("due"))

    claims = claim_jobs(db, {"test_job"})
    assert [(claim.job_id, claim.attempt) for claim in claims] == [(due, 1)]
    assert db.get_one(Job, future).status == JobStatus.PENDING
    assert db.get_one(Job, other_type).status == JobStatus.PENDING


@pytest.mark.parametrize("reclaimed", [False, True])
def test_expired_lease_can_only_run_with_the_current_attempt(db: Session, reclaimed: bool) -> None:
    job_id = enqueue_job(db, _request("abandoned"))
    old = claim_jobs(db, {"test_job"})[0]
    assert claim_jobs(db, {"test_job"}) == []

    job = db.get_one(Job, job_id)
    job.lease_until = queue_time(db) - timedelta(seconds=1)
    db.flush()

    calls: list[uuid.UUID] = []

    def handler(_db: Session, context: JobContext) -> None:
        calls.append(context.id)

    active = claim_jobs(db, {"test_job"})[0] if reclaimed else old
    if reclaimed:
        assert active.attempt == 2
        assert not execute_claim(db, old, {"test_job": handler})
    assert execute_claim(db, active, {"test_job": handler})
    assert not execute_claim(db, active, {"test_job": handler})
    assert calls == [job_id]
    assert job.status == JobStatus.COMPLETED
    assert job.lease_until is None


@pytest.mark.parametrize("handler_commits", [False, True])
def test_failed_handler_rolls_back_effects_before_retry(db: Session, handler_commits: bool) -> None:
    workspace = make_workspace(db)
    document = make_document(db, workspace)
    document_id = document.id
    job_id = enqueue_job(db, _request("rollback", workspace_id=workspace.id))
    job = db.get_one(Job, job_id)
    original_name = document.name
    stored_name = select(Document.name).where(Document.id == document_id)

    def fail(db: Session, _context: JobContext) -> None:
        db.execute(update(Document).where(Document.id == document_id).values(name="Partial"))
        if handler_commits:
            db.commit()
        raise RuntimeError("error details may contain private data")

    assert execute_claim(db, claim_jobs(db, {"test_job"})[0], {"test_job": fail})
    assert db.scalar(stored_name) == original_name
    assert job.status == JobStatus.PENDING
    assert job.error_code == "handler_failed"
    assert job.lease_until is None
    assert job.next_run_at > queue_time(db)

    job.next_run_at = queue_time(db) - timedelta(seconds=1)
    db.flush()

    def succeed(db: Session, _context: JobContext) -> None:
        db.execute(update(Document).where(Document.id == document_id).values(name="Done"))

    assert execute_claim(db, claim_jobs(db, {"test_job"})[0], {"test_job": succeed})
    assert db.scalar(stored_name) == "Done"
    assert job.status == JobStatus.COMPLETED
    assert job.error_code is None


@pytest.mark.parametrize("interrupted", [False, True])
def test_attempts_are_limited_even_after_a_worker_dies(db: Session, interrupted: bool) -> None:
    job = db.get_one(Job, enqueue_job(db, _request("exhausted")))
    job.attempts = MAX_ATTEMPTS - 1
    db.flush()
    claim = claim_jobs(db, {"test_job"})[0]
    assert claim.attempt == MAX_ATTEMPTS

    def fail(_db: Session, _context: JobContext) -> None:
        raise RuntimeError

    if interrupted:
        job.lease_until = queue_time(db) - timedelta(seconds=1)
        db.flush()
    else:
        execute_claim(db, claim, {"test_job": fail})

    assert claim_jobs(db, {"test_job"}) == []
    assert job.status == JobStatus.FAILED
    assert job.attempts == MAX_ATTEMPTS
    assert job.lease_until is None
    assert job.error_code == ("lease_exhausted" if interrupted else "handler_failed")


def test_workers_claim_disjoint_batches_without_waiting() -> None:
    batch = uuid.uuid4().hex
    job_type = "test_" + batch
    with Session(engine) as setup:
        ids = {
            enqueue_job(setup, _request(f"{batch}-{index}", type=job_type))
            for index in range(BATCH_SIZE + 1)
        }
        setup.commit()

    try:
        with Session(engine) as first, Session(engine) as second:
            batch_one = {claim.job_id for claim in claim_jobs(first, {job_type})}
            second.execute(text("SET LOCAL statement_timeout = '500ms'"))
            batch_two = {claim.job_id for claim in claim_jobs(second, {job_type})}
            assert len(batch_one) == BATCH_SIZE
            assert len(batch_two) == 1
            assert batch_one.isdisjoint(batch_two)
            assert batch_one | batch_two == ids
            first.commit()
            second.commit()

        with Session(engine) as observer:
            assert claim_jobs(observer, {job_type}) == []
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(Job).where(Job.id.in_(ids)))
            cleanup.commit()


def test_executing_job_keeps_its_lock_even_after_the_lease_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = uuid.uuid4().hex
    job_type = f"test_{key}"
    with Session(engine) as setup:
        job_id = enqueue_job(setup, _request(key, type=job_type))
        claim = claim_jobs(setup, {job_type})[0]
        lease_until = setup.get_one(Job, job_id).lease_until
        assert lease_until is not None
        setup.commit()
    after_expiry = lease_until + timedelta(seconds=1)

    def work(_db: Session, _context: JobContext) -> None:
        with monkeypatch.context() as patch, Session(engine) as competing_worker:
            patch.setattr(queue, "queue_time", lambda _db: after_expiry)
            competing_worker.execute(text("SET LOCAL statement_timeout = '500ms'"))
            assert claim_jobs(competing_worker, {job_type}) == []

    try:
        with Session(engine) as first:
            assert execute_claim(first, claim, {job_type: work})
            assert first.get_one(Job, job_id).status == JobStatus.COMPLETED
            first.commit()
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(delete(Job).where(Job.id == job_id))
            cleanup.commit()
