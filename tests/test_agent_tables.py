"""Database rules of the agent tables: conversations, runs, calls, quotas, reservations, usage."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.models import Message, PeriodQuota, Run, RunStatus
from app.documents.models import Document, DocumentVersion, VersionSource, Workspace
from tests.agent_factories import (
    make_conversation,
    make_message,
    make_pending_call,
    make_period_quota,
    make_rate,
    make_reservation,
    make_run,
    make_usage,
)
from tests.factories import make_document, make_object, make_revision, make_workspace


@pytest.fixture
def workspace(db: Session) -> Workspace:
    return make_workspace(db)


@pytest.fixture
def document(db: Session, workspace: Workspace) -> Document:
    return make_document(db, workspace)


def _run(db: Session, document: Document, **overrides: object) -> Run:
    return make_run(db, make_conversation(db, document), **overrides)


def _version(db: Session, workspace: Workspace, document: Document) -> DocumentVersion:
    make_revision(db, document, make_object(db, workspace))
    version = DocumentVersion(
        workspace_id=workspace.id,
        document_id=document.id,
        revision=1,
        source=VersionSource.PRE_AGENT,
    )
    db.add(version)
    db.flush()
    return version


# Quotas: what is reserved plus what was used never passes what was given.


def test_a_reservation_cannot_take_more_than_the_quota_has_left(
    db: Session, document: Document
) -> None:
    quota = make_period_quota(db, _run(db, document).account_id, allocated=100, consumed=60)

    def reserve(amount: int) -> None:
        db.execute(
            update(PeriodQuota)
            .where(PeriodQuota.period_id == quota.period_id)
            .values(reserved=PeriodQuota.reserved + amount)
        )

    reserve(40)  # exactly what is left
    with pytest.raises(IntegrityError, match="ck_period_quotas_within_allocated"):
        reserve(1)


@pytest.mark.parametrize("column", ["allocated", "reserved", "consumed"])
def test_quota_amounts_cannot_be_negative(db: Session, document: Document, column: str) -> None:
    account_id = _run(db, document).account_id
    with pytest.raises(IntegrityError, match=f"ck_period_quotas_{column}_non_negative"):
        make_period_quota(db, account_id, **{column: -1})


def test_a_period_must_end_after_it_starts(db: Session, document: Document) -> None:
    account_id = _run(db, document).account_id
    now = datetime.now(UTC)
    with pytest.raises(IntegrityError, match="ck_period_quotas_ends_after_start"):
        make_period_quota(db, account_id, starts_at=now, ends_at=now)


# Reservations


def test_a_run_reserves_each_resource_once(db: Session, document: Document) -> None:
    run = _run(db, document)
    quota = make_period_quota(db, run.account_id)
    make_reservation(db, run, quota)

    with pytest.raises(IntegrityError, match="uq_reservations_run_id_resource"):
        make_reservation(db, run, quota)


def test_a_reservation_amount_must_be_positive(db: Session, document: Document) -> None:
    run = _run(db, document)
    quota = make_period_quota(db, run.account_id)
    with pytest.raises(IntegrityError, match="ck_reservations_amount_positive"):
        make_reservation(db, run, quota, amount=0)


def test_a_reservation_cannot_use_the_quota_of_another_account(
    db: Session, document: Document
) -> None:
    run = _run(db, document)
    other_run = _run(db, make_document(db, make_workspace(db)))
    others_quota = make_period_quota(db, other_run.account_id)

    # The run is one account's, the quota another's: no (account, run) pair matches.
    with pytest.raises(IntegrityError, match="fk_reservations_account_id_run_id_runs"):
        make_reservation(db, run, others_quota)


def test_a_reservation_needs_an_existing_quota(db: Session, document: Document) -> None:
    run = _run(db, document)
    quota = make_period_quota(db, run.account_id)
    with pytest.raises(IntegrityError, match="fk_reservations_account_id_period_id_resource"):
        make_reservation(db, run, quota, period_id=uuid.uuid4())


# Runs


def test_a_document_has_one_active_run_per_editor_session(db: Session, document: Document) -> None:
    first = _run(db, document)
    with pytest.raises(IntegrityError, match="uq_runs_document_id_editor_session_id_active"):
        with db.begin_nested():
            _run(db, document, editor_session_id=first.editor_session_id)

    # Once the first one ends, the same tab may start another.
    db.execute(update(Run).where(Run.id == first.id).values(status=RunStatus.COMPLETED))
    _run(db, document, editor_session_id=first.editor_session_id)


def test_a_run_must_belong_to_a_conversation_of_its_account(
    db: Session, document: Document
) -> None:
    conversation = make_conversation(db, document)
    other = make_conversation(db, make_document(db, make_workspace(db)))

    with pytest.raises(IntegrityError, match="fk_runs_account_id_workspace_id_conversation_id"):
        make_run(db, conversation, conversation_id=other.id)


def test_the_pre_agent_version_must_be_of_the_same_document(
    db: Session, workspace: Workspace, document: Document
) -> None:
    other_version = _version(db, workspace, make_document(db, workspace))

    with pytest.raises(IntegrityError, match="fk_runs_workspace_id_document_id_pre_agent_version"):
        _run(db, document, pre_agent_version_id=other_version.id)


def test_pruning_the_pre_agent_version_keeps_the_run_and_its_evidence(
    db: Session, workspace: Workspace, document: Document
) -> None:
    version = _version(db, workspace, document)
    run = _run(
        db,
        document,
        pre_agent_version_id=version.id,
        recorded_pre_agent_version_id=version.id,
    )

    db.execute(delete(DocumentVersion).where(DocumentVersion.id == version.id))
    db.refresh(run)

    # Only the link goes; the document and the recorded id stay (§VII).
    assert run.pre_agent_version_id is None
    assert run.recorded_pre_agent_version_id == version.id
    assert run.document_id == document.id


def test_the_initial_revision_cannot_be_negative(db: Session, document: Document) -> None:
    with pytest.raises(IntegrityError, match="ck_runs_initial_revision_non_negative"):
        _run(db, document, initial_revision=-1)


# Conversations and messages


def test_a_conversation_document_must_be_in_its_workspace(db: Session, document: Document) -> None:
    other_document = make_document(db, make_workspace(db))
    with pytest.raises(IntegrityError, match="fk_conversations_workspace_id_document_id"):
        make_conversation(db, document, document_id=other_document.id)


def test_messages_are_numbered_once_and_from_one(db: Session, document: Document) -> None:
    conversation = make_conversation(db, document)
    make_message(db, conversation, sequence=1)

    with pytest.raises(IntegrityError, match="uq_messages_conversation_id_sequence"):
        with db.begin_nested():
            make_message(db, conversation, sequence=1)
    with pytest.raises(IntegrityError, match="ck_messages_sequence_positive"):
        make_message(db, conversation, sequence=0)


def test_deleting_a_conversation_deletes_its_messages(db: Session, document: Document) -> None:
    conversation = make_conversation(db, document)
    make_message(db, conversation)

    db.delete(conversation)
    db.flush()

    assert db.scalars(select(Message)).all() == []


# Pending calls and usage


def test_a_call_id_is_used_once_per_run(db: Session, document: Document) -> None:
    run = _run(db, document)
    make_pending_call(db, run)
    with pytest.raises(IntegrityError, match="uq_pending_calls_run_id_call_id"):
        make_pending_call(db, run)


def test_a_usage_event_is_counted_once(db: Session, document: Document) -> None:
    run = _run(db, document)
    rate = make_rate(db)
    make_usage(db, run, rate)

    # The agent retrying to record the same event must not charge it twice.
    with pytest.raises(IntegrityError, match="uq_usage_run_id_event_id_resource"):
        make_usage(db, run, rate)


@pytest.mark.parametrize(
    "column", ["input_tokens", "output_tokens", "units", "estimated_cost_micro", "duration_ms"]
)
def test_usage_amounts_cannot_be_negative(db: Session, document: Document, column: str) -> None:
    run = _run(db, document)
    with pytest.raises(IntegrityError, match=f"ck_usage_{column}_non_negative"):
        make_usage(db, run, make_rate(db), **{column: -1})


def test_a_run_with_usage_cannot_be_deleted(db: Session, document: Document) -> None:
    # Usage is accounting: deleting the run must not erase what it cost (§IX-C).
    run = _run(db, document)
    make_usage(db, run, make_rate(db))

    with pytest.raises(IntegrityError, match="fk_usage_run_id_runs"):
        db.execute(delete(Run).where(Run.id == run.id))


# Rates


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"input_price_micro": -1}, "input_price_micro_non_negative"),
        ({"output_price_micro": -1}, "output_price_micro_non_negative"),
        ({"token_basis": 0}, "token_basis_positive"),
    ],
)
def test_rate_values_are_checked(db: Session, values: dict[str, int], constraint: str) -> None:
    with pytest.raises(IntegrityError, match=f"ck_rates_{constraint}"):
        make_rate(db, **values)


# Closed lists of values


@pytest.mark.parametrize(
    ("column", "constraint"),
    [("status", "ck_runs_status"), ("mode", "ck_runs_mode")],
)
def test_run_statuses_and_modes_only_accept_known_values(
    db: Session, document: Document, column: str, constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        _run(db, document, **{column: "anything"})
