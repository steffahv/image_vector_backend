"""Verify the export links and permissions on the real operations table."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.db import AGENT_ROLE, PLATFORM_ROLE, set_current_account
from app.documents.models import Account, Workspace
from app.jobs.models import Export, ExportStatus, Job
from app.jobs.schemas import JobContext, JobRequest
from app.jobs.service import enqueue_job, expire_exports
from app.jobs.service.handlers import installed_handlers
from app.storage.models import ObjectKind, StoredObject
from tests.conftest import as_role
from tests.factories import make_object, make_workspace


def _new_export(
    db: Session, workspace: Workspace, job_type: str = "generate_export", *, key: str = "export"
) -> Export:
    return Export(
        account_id=workspace.owner_id,
        workspace_id=workspace.id,
        job_id=enqueue_job(
            db,
            JobRequest(type=job_type, idempotency_key=key, workspace_id=workspace.id),
        ),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


@pytest.mark.parametrize("wrong_link", ["job", "object"])
def test_export_cannot_reference_another_workspace(db: Session, wrong_link: str) -> None:
    first, second = make_workspace(db), make_workspace(db)
    export = _new_export(db, first)
    if wrong_link == "job":
        export.job_id = _new_export(db, second).job_id
        constraint = "fk_exports_workspace_id_job_id_jobs"
    else:
        export.object_id = make_object(db, second, kind=ObjectKind.EXPORT).id
        constraint = "fk_exports_workspace_id_object_id_objects"

    db.add(export)
    with pytest.raises(IntegrityError, match=constraint):
        db.flush()


def test_a_job_has_only_one_export(db: Session) -> None:
    workspace = make_workspace(db)
    db.add(_new_export(db, workspace))
    db.flush()

    db.add(_new_export(db, workspace))
    with pytest.raises(IntegrityError, match="uq_exports_job_id"):
        db.flush()


def test_completed_export_requires_a_file(db: Session) -> None:
    export = _new_export(db, make_workspace(db))
    export.status = ExportStatus.COMPLETED
    db.add(export)
    with pytest.raises(IntegrityError, match="ck_exports_completed_object"):
        db.flush()


def test_export_keeps_its_file_from_being_deleted(db: Session) -> None:
    workspace = make_workspace(db)
    stored = make_object(db, workspace, kind=ObjectKind.EXPORT)
    export = _new_export(db, workspace)
    export.object_id = stored.id
    export.status = ExportStatus.COMPLETED
    db.add(export)
    db.flush()

    with pytest.raises(IntegrityError, match="fk_exports_workspace_id_object_id_objects"):
        db.execute(delete(StoredObject).where(StoredObject.id == stored.id))


def test_removing_a_workspace_removes_both_its_export_and_job(db: Session) -> None:
    workspace = make_workspace(db)
    workspace_id, owner_id = workspace.id, workspace.owner_id
    export = _new_export(db, workspace)
    db.add(export)
    db.flush()
    export_id, job_id = export.id, export.job_id

    as_role(db, PLATFORM_ROLE)
    set_current_account(db, owner_id)
    db.execute(delete(Workspace).where(Workspace.id == workspace_id))
    db.execute(text("RESET ROLE"))
    assert db.scalar(select(Export.id).where(Export.id == export_id)) is None
    assert db.scalar(select(Job.id).where(Job.id == job_id)) is None


def test_platform_reads_and_updates_only_its_own_exports(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    first, second = make_workspace(db, ana), make_workspace(db, luis)
    as_role(db, PLATFORM_ROLE)
    assert db.scalars(select(Export.id)).all() == []

    set_current_account(db, ana.id)
    ana_export = _new_export(db, first)
    db.add(ana_export)
    db.flush()
    set_current_account(db, luis.id)
    luis_export = _new_export(db, second)
    db.add(luis_export)
    db.flush()

    assert db.scalars(select(Export.id)).all() == [luis_export.id]
    others = Export.id == ana_export.id
    assert db.execute(update(Export).where(others).values(status=ExportStatus.FAILED)).rowcount == 0
    assert db.execute(delete(Export).where(others)).rowcount == 0
    with pytest.raises(ProgrammingError, match="row-level security"):
        db.execute(update(Export).where(Export.id == luis_export.id).values(account_id=ana.id))


@pytest.mark.parametrize("wrong_value", ["account", "job_type", "object_kind"])
def test_platform_cannot_write_an_invalid_export(
    db: Session, two_accounts: tuple[Account, Account], wrong_value: str
) -> None:
    ana, luis = two_accounts
    workspace = make_workspace(db, ana)
    stored = make_object(db, workspace)
    export = _new_export(
        db, workspace, "other_job" if wrong_value == "job_type" else "generate_export"
    )

    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)
    with pytest.raises(ProgrammingError, match="row-level security"):
        db.execute(
            insert(Export).values(
                workspace_id=workspace.id,
                account_id=luis.id if wrong_value == "account" else ana.id,
                job_id=export.job_id,
                object_id=stored.id if wrong_value == "object_kind" else None,
                expires_at=export.expires_at,
            )
        )


def test_agent_cannot_read_exports(db: Session) -> None:
    as_role(db, AGENT_ROLE)
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(select(Export.id))


def test_expiration_releases_only_the_due_export_reference(db: Session) -> None:
    workspace = make_workspace(db)
    cutoff = datetime.now(UTC)
    stored = make_object(db, workspace, kind=ObjectKind.EXPORT)
    due = _new_export(db, workspace)
    due.expires_at = cutoff
    future = _new_export(db, workspace, key="future")
    future.expires_at = cutoff + timedelta(hours=1)
    for export in (due, future):
        export.object_id = stored.id
        export.status = ExportStatus.COMPLETED
        db.add(export)
    db.flush()

    job = JobContext(uuid.uuid4(), workspace.id, {"as_of": cutoff.isoformat()})
    expire_exports(db, job)
    expire_exports(db, job)
    assert due.status == ExportStatus.EXPIRED
    assert due.object_id is None
    assert future.status == ExportStatus.COMPLETED
    assert future.object_id == stored.id
    assert db.get(StoredObject, stored.id) is not None
    with pytest.raises(IntegrityError, match="fk_exports_workspace_id_object_id_objects"):
        with db.begin_nested():
            db.execute(delete(StoredObject).where(StoredObject.id == stored.id))

    later = JobContext(uuid.uuid4(), workspace.id, {"as_of": future.expires_at.isoformat()})
    expire_exports(db, later)
    assert future.status == ExportStatus.EXPIRED
    assert db.execute(delete(StoredObject).where(StoredObject.id == stored.id)).rowcount == 1


@pytest.mark.parametrize("due", [True, False])
def test_generation_only_runs_for_an_export_that_has_not_expired(
    db: Session, monkeypatch: pytest.MonkeyPatch, due: bool
) -> None:
    workspace = make_workspace(db)
    export = _new_export(db, workspace)
    offset = timedelta(hours=-1 if due else 1)
    export.expires_at = datetime.now(UTC) + offset
    db.add(export)
    db.flush()

    calls: list[uuid.UUID] = []

    def generate(_db: Session, job: JobContext) -> None:
        calls.append(job.id)

    monkeypatch.setattr("app.jobs.service.generate_export", generate, raising=False)
    installed_handlers()["generate_export"](db, JobContext(export.job_id, workspace.id, {}))
    assert calls == ([] if due else [export.job_id])
