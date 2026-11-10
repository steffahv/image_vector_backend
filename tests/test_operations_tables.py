"""Database rules of the operations tables: audit log, object copies and backup runs."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import FlushError

from app.documents.models import Workspace
from app.jobs.models import AuditEntry, AuditResult, BackupRun, BackupStatus, BackupType
from tests.agent_factories import make_audit_entry, make_object_copy
from tests.factories import make_object, make_workspace


def test_an_object_has_one_copy_per_destination(db: Session) -> None:
    stored = make_object(db, make_workspace(db))
    make_object_copy(db, stored)
    make_object_copy(db, stored, destination="backup-b")

    with pytest.raises(IntegrityError, match="pk_object_copies"):
        make_object_copy(db, stored)


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"sha256": b"short"}, "ck_object_copies_sha256_length"),
        ({"size_bytes": -1}, "ck_object_copies_size_bytes_non_negative"),
    ],
)
def test_object_copy_values_are_checked(
    db: Session, values: dict[str, object], constraint: str
) -> None:
    stored = make_object(db, make_workspace(db))
    with pytest.raises(IntegrityError, match=constraint):
        make_object_copy(db, stored, **values)


def test_a_backup_run_cannot_finish_before_it_starts(db: Session) -> None:
    started_at = datetime.now(UTC)
    db.add(
        BackupRun(
            type=BackupType.DATABASE,
            started_at=started_at,
            finished_at=started_at - timedelta(seconds=1),
            status=BackupStatus.SUCCEEDED,
        )
    )
    with pytest.raises(IntegrityError, match="ck_backup_runs_finishes_after_start"):
        db.flush()


def test_a_running_backup_has_no_end_yet(db: Session) -> None:
    db.add(
        BackupRun(
            type=BackupType.OBJECTS, started_at=datetime.now(UTC), status=BackupStatus.RUNNING
        )
    )
    db.flush()


def test_deleting_a_workspace_keeps_its_audit_entries(db: Session) -> None:
    workspace = make_workspace(db)
    entry_id = make_audit_entry(db, workspace.id)

    db.execute(delete(Workspace).where(Workspace.id == workspace.id))

    # The entry stays, without its context (§IX-C).
    kept = db.execute(select(AuditEntry.workspace_id).where(AuditEntry.id == entry_id)).one()
    assert kept.workspace_id is None


def test_an_audit_entry_needs_no_workspace(db: Session) -> None:
    # A failed sign-in happens before any workspace is known.
    make_audit_entry(db, None)


def test_an_audit_entry_is_not_written_with_the_orm(db: Session) -> None:
    # db.add() needs RETURNING for the new id, which the table never asks for on its own
    # (see AuditEntry); entries go through insert() instead.
    db.add(AuditEntry(action="sign_in", entity_type="session", result=AuditResult.DENIED))
    with pytest.raises(FlushError):
        db.flush()
