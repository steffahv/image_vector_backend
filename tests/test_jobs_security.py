"""Queue policies and the worker login in the same entry points used by the jobs process."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, insert, select, text, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import AuthUser
from app.core.db import AGENT_ROLE, PLATFORM_ROLE, check_app_role, engine, set_current_account
from app.documents.models import Account, Document, Workspace
from app.documents.service import maintenance_workspaces
from app.jobs.models import Export, ExportStatus, Job, JobStatus
from app.jobs.schemas import JobContext, JobRequest
from app.jobs.service import schedule
from app.jobs.service.queue import enqueue_job
from app.jobs.worker import installed_handlers, run_cycle
from app.storage.models import ObjectKind, StoredObject
from tests.conftest import as_role
from tests.factories import make_account, make_document, make_object, make_workspace


def test_platform_reads_only_own_jobs_and_scopes_retry_keys(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    first, second = make_workspace(db, ana), make_workspace(db, luis)
    common = {"type": "generate_export", "idempotency_key": "same-key"}
    system = enqueue_job(db, JobRequest(workspace_id=None, **common))
    as_role(db, PLATFORM_ROLE)
    assert db.scalars(select(Job.id)).all() == []

    set_current_account(db, ana.id)
    first_id = enqueue_job(db, JobRequest(workspace_id=first.id, **common))
    set_current_account(db, luis.id)
    second_id = enqueue_job(db, JobRequest(workspace_id=second.id, **common))
    assert len({system, first_id, second_id}) == 3
    assert db.scalars(select(Job.id)).all() == [second_id]
    assert db.execute(update(Job).values(status=JobStatus.COMPLETED)).rowcount == 0


@pytest.mark.parametrize(
    "target",
    [
        "global",
        "other_workspace",
        "foreign_key_prefix",
        "state",
        "schedule_key",
        "maintenance_type",
    ],
)
def test_platform_cannot_spoof_job_scope_or_worker_state(
    db: Session, two_accounts: tuple[Account, Account], target: str
) -> None:
    ana, luis = two_accounts
    first, second = make_workspace(db, ana), make_workspace(db, luis)
    workspace_id = {"global": None, "other_workspace": second.id}.get(target, first.id)
    scope = second.id if target == "foreign_key_prefix" else workspace_id or "global"
    suffix = (
        "scheduled:purge_trash:2026-11-10T00:00:00+00:00" if target == "schedule_key" else "job"
    )
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    with pytest.raises(ProgrammingError, match="row-level security"):
        db.execute(
            insert(Job).values(
                workspace_id=workspace_id,
                idempotency_key=f"{scope}:{suffix}",
                type="purge_trash" if target == "maintenance_type" else "generate_export",
                payload={},
                status=JobStatus.COMPLETED if target == "state" else JobStatus.PENDING,
            )
        )


def test_agent_cannot_read_or_claim_jobs(db: Session) -> None:
    as_role(db, AGENT_ROLE)
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(select(Job))


def test_worker_refuses_the_api_role(db: Session) -> None:
    as_role(db, PLATFORM_ROLE)
    with pytest.raises(RuntimeError, match="is not a member of vectoredit_worker"):
        check_app_role(db.connection(), worker=True)


def test_maintenance_is_scheduled_once_per_workspace_with_its_cutoff(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = make_workspace(db)
    now = datetime(2026, 11, 10, 13, 7, tzinfo=UTC)
    monkeypatch.setattr(schedule, "queue_time", lambda _db: now)

    for _ in range(2):
        schedule.enqueue_maintenance(db, {"purge_trash", "delete_unused_objects"})

    jobs = {job.type: job for job in db.scalars(select(Job))}
    assert set(jobs) == {"purge_trash", "delete_unused_objects"}
    assert all(job.workspace_id == workspace.id for job in jobs.values())
    assert jobs["purge_trash"].payload == {
        "as_of": "2026-11-10T00:00:00+00:00",
        "older_than": "2026-10-11T00:00:00+00:00",
    }
    assert jobs["delete_unused_objects"].payload["older_than"] == "2026-11-02T00:00:00+00:00"


@pytest.mark.skipif(
    "WORKER_DATABASE_URL" not in os.environ, reason="WORKER_DATABASE_URL is not set (set in CI)"
)
def test_real_worker_process_executes_in_the_jobs_account(monkeypatch: pytest.MonkeyPatch) -> None:
    with Session(engine) as setup:
        accounts = [make_account(setup, f"{uuid.uuid4().hex}@example.com") for _ in range(2)]
        account_ids = [account.id for account in accounts]
        user_ids = [account.auth_user_id for account in accounts]
        workspaces = [make_workspace(setup, account) for account in accounts]
        workspace_ids = [workspace.id for workspace in workspaces]
        document_ids = [make_document(setup, workspace).id for workspace in workspaces]
        job_id = enqueue_job(
            setup,
            JobRequest(
                type="generate_export", idempotency_key="export-1", workspace_id=workspace_ids[0]
            ),
        )
        now = datetime.now(UTC)
        stored_id = make_object(setup, workspaces[1], kind=ObjectKind.EXPORT).id
        old_job_id = enqueue_job(
            setup,
            JobRequest(
                type="generate_export", idempotency_key="old", workspace_id=workspace_ids[1]
            ),
        )
        setup.execute(update(Job).where(Job.id == old_job_id).values(status=JobStatus.COMPLETED))
        setup.add_all(
            [
                Export(
                    account_id=account_ids[0],
                    workspace_id=workspace_ids[0],
                    job_id=job_id,
                    expires_at=now + timedelta(days=1),
                ),
                Export(
                    account_id=account_ids[1],
                    workspace_id=workspace_ids[1],
                    job_id=old_job_id,
                    expires_at=now - timedelta(hours=2),
                    object_id=stored_id,
                    status=ExportStatus.COMPLETED,
                ),
            ]
        )
        setup.commit()

    worker_engine = create_engine(os.environ["WORKER_DATABASE_URL"])
    sessions = sessionmaker(worker_engine, expire_on_commit=False)
    try:
        with worker_engine.connect() as connection:
            check_app_role(connection, worker=True)
            with pytest.raises(RuntimeError, match="reserved for the jobs process"):
                check_app_role(connection)
        with sessions.begin() as db:
            assert set(maintenance_workspaces.list_maintenance_workspaces(db)) >= set(workspace_ids)
            assert db.scalars(select(Document.id)).all() == []
            with db.begin_nested() as transaction:
                schedule.enqueue_maintenance(db, {"purge_trash"})
                scheduled = db.scalars(
                    select(Job.workspace_id).where(
                        Job.type == "purge_trash", Job.workspace_id.in_(workspace_ids)
                    )
                ).all()
                assert set(scheduled) == set(workspace_ids)
                transaction.rollback()

        def generate_export(db: Session, context: JobContext) -> None:
            assert context.workspace_id == workspace_ids[0]
            assert db.scalars(select(Document.id)).all() == [document_ids[0]]
            db.execute(
                update(Document).where(Document.id.in_(document_ids)).values(name="Exported")
            )
            db.commit()
            assert db.scalars(select(Document.id)).all() == [document_ids[0]]

        monkeypatch.setattr("app.jobs.service.generate_export", generate_export, raising=False)
        assert run_cycle(sessions, installed_handlers(), schedule=True) == 3
        assert run_cycle(sessions, installed_handlers()) == 0
        with Session(engine) as observer:
            assert observer.get_one(Job, job_id).status == JobStatus.COMPLETED
            assert observer.get_one(Document, document_ids[0]).name == "Exported"
            assert observer.get_one(Document, document_ids[1]).name == "Poster"
            expired = observer.scalars(select(Export).where(Export.job_id == old_job_id)).one()
            assert expired.status == ExportStatus.EXPIRED
            assert expired.object_id is None
            assert observer.get(StoredObject, stored_id) is not None
    finally:
        worker_engine.dispose()
        with Session(engine) as cleanup:
            cleanup.execute(delete(Export).where(Export.workspace_id.in_(workspace_ids)))
            cleanup.execute(delete(Job).where(Job.workspace_id.in_(workspace_ids)))
            cleanup.execute(delete(StoredObject).where(StoredObject.id == stored_id))
            cleanup.execute(delete(Document).where(Document.id.in_(document_ids)))
            cleanup.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
            cleanup.execute(delete(Account).where(Account.id.in_(account_ids)))
            cleanup.execute(delete(AuthUser).where(AuthUser.id.in_(user_ids)))
            cleanup.commit()


@pytest.mark.parametrize(
    ("module", "name"),
    [("documents", "purge_trash"), ("storage", "delete_unused_objects")],
)
def test_cleanup_handlers_receive_an_aware_cutoff_and_validate_signature(
    db: Session, monkeypatch: pytest.MonkeyPatch, module: str, name: str
) -> None:
    path = f"app.{module}.service.{name}"

    def wrong(_db: Session, _job: JobContext) -> None:
        raise AssertionError("startup should reject this handler")

    monkeypatch.setattr(path, wrong, raising=False)
    with pytest.raises(RuntimeError, match=r"must accept \(db, older_than\)"):
        installed_handlers()

    async def async_cleanup(_db: Session, older_than: datetime) -> None:
        raise AssertionError("startup should reject asynchronous handlers")

    monkeypatch.setattr(path, async_cleanup)
    with pytest.raises(RuntimeError, match="must be a synchronous function"):
        installed_handlers()

    received: list[datetime] = []

    def cleanup(_db: Session, older_than: datetime) -> None:
        received.append(older_than)

    monkeypatch.setattr(path, cleanup)
    cutoff = datetime(2026, 11, 10, tzinfo=UTC)
    installed_handlers()[name](
        db, JobContext(uuid.uuid4(), None, {"older_than": cutoff.isoformat()})
    )
    assert received == [cutoff]


def test_deleting_a_workspace_also_deletes_its_jobs(db: Session) -> None:
    workspace = make_workspace(db)
    workspace_id, owner_id = workspace.id, workspace.owner_id
    job_id = enqueue_job(
        db,
        JobRequest(type="generate_export", idempotency_key="export", workspace_id=workspace_id),
    )
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, owner_id)

    db.execute(delete(Workspace).where(Workspace.id == workspace_id))
    db.execute(text("RESET ROLE"))
    assert db.get(Job, job_id) is None


@pytest.mark.skipif(
    "WORKER_DATABASE_URL" not in os.environ, reason="WORKER_DATABASE_URL is not set (set in CI)"
)
def test_worker_retires_only_old_terminal_scheduled_jobs() -> None:
    prefix = uuid.uuid4().hex
    now = datetime.now(UTC)
    with Session(engine) as setup:
        rows = [
            (JobStatus.COMPLETED, "scheduled", now - timedelta(days=31)),
            (JobStatus.FAILED, "scheduled", now - timedelta(days=31)),
            (JobStatus.CANCELLED, "scheduled", now - timedelta(days=31)),
            (JobStatus.PENDING, "scheduled", now - timedelta(days=31)),
            (JobStatus.COMPLETED, "scheduled", now - timedelta(days=29)),
            (JobStatus.COMPLETED, "on_demand", now - timedelta(days=31)),
        ]
        jobs = [
            Job(
                type="purge_trash" if scope == "scheduled" else "generate_export",
                idempotency_key=f"global:{scope}:{prefix}:{index}",
                payload={},
                status=status,
                updated_at=updated_at,
            )
            for index, (status, scope, updated_at) in enumerate(rows)
        ]
        setup.add_all(jobs)
        setup.flush()
        ids = [job.id for job in jobs]
        setup.commit()

    worker_engine = create_engine(os.environ["WORKER_DATABASE_URL"])
    try:
        with Session(worker_engine) as worker:
            # Even direct DELETE is scoped by the worker's retention policy.
            removed = worker.execute(delete(Job).where(Job.id.in_(ids[3:])))
            assert removed.rowcount == 0

        assert run_cycle(sessionmaker(worker_engine), {}, schedule=True) == 0
        with Session(engine) as observer:
            remaining = observer.scalars(select(Job.id).where(Job.id.in_(ids)))
            assert set(remaining) == set(ids[3:])
    finally:
        worker_engine.dispose()
        with Session(engine) as cleanup:
            cleanup.execute(delete(Job).where(Job.id.in_(ids)))
            cleanup.commit()


def test_platform_cannot_delete_its_own_job(db: Session) -> None:
    workspace = make_workspace(db)
    workspace_id, owner_id = workspace.id, workspace.owner_id
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, owner_id)
    job_id = enqueue_job(
        db,
        JobRequest(type="generate_export", idempotency_key="export", workspace_id=workspace_id),
    )

    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(delete(Job).where(Job.id == job_id))
