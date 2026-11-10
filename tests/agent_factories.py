"""Builders for rows of the agent and operations tables. Each one inserts and flushes.

The platform and storage builders are in tests/factories.py.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.agent.models import (
    Conversation,
    Message,
    MessageRole,
    PendingCall,
    PendingCallStatus,
    PeriodQuota,
    Rate,
    Reservation,
    ReservationStatus,
    Run,
    RunStatus,
    Usage,
    UsageResult,
)
from app.documents.models import AgentMode, Document, Workspace
from app.jobs.models import AuditEntry, AuditResult, ObjectCopy
from app.storage.models import StoredObject
from tests.factories import in_one_hour


def _owner_id(db: Session, workspace_id: uuid.UUID) -> uuid.UUID:
    workspace = db.get(Workspace, workspace_id)
    assert workspace is not None
    return workspace.owner_id


def _add(db: Session, row: object) -> None:
    db.add(row)
    db.flush()


def make_conversation(db: Session, document: Document, **overrides: object) -> Conversation:
    values: dict[str, object] = {
        "account_id": _owner_id(db, document.workspace_id),
        "workspace_id": document.workspace_id,
        "document_id": document.id,
        "title": "Poster",
    }
    conversation = Conversation(**(values | overrides))
    _add(db, conversation)
    return conversation


def make_message(db: Session, conversation: Conversation, sequence: int = 1) -> Message:
    message = Message(
        conversation_id=conversation.id,
        sequence=sequence,
        role=MessageRole.USER,
        content={"text": "Make it blue"},
    )
    _add(db, message)
    return message


def make_run(db: Session, conversation: Conversation, **overrides: object) -> Run:
    values: dict[str, object] = {
        "conversation_id": conversation.id,
        "account_id": conversation.account_id,
        "workspace_id": conversation.workspace_id,
        "document_id": conversation.document_id,
        "editor_session_id": uuid.uuid4(),
        "initial_revision": 0,
        "mode": AgentMode.PLATFORM,
        "variant": "base",
        "model": "model-a",
        "prompt_version": "1",
        "catalog_fingerprint": "catalog-1",
        "status": RunStatus.RUNNING,
    }
    run = Run(**(values | overrides))
    _add(db, run)
    return run


def make_pending_call(db: Session, run: Run, call_id: str = "call-1") -> PendingCall:
    call = PendingCall(
        run_id=run.id,
        call_id=call_id,
        tool="set_fill",
        arguments_fingerprint=hashlib.sha256(call_id.encode()).digest(),
        status=PendingCallStatus.PENDING,
        expires_at=in_one_hour(),
    )
    _add(db, call)
    return call


def make_period_quota(
    db: Session, account_id: uuid.UUID, resource: str = "tokens", **overrides: object
) -> PeriodQuota:
    starts_at = datetime.now(UTC)
    values: dict[str, object] = {
        "account_id": account_id,
        "period_id": uuid.uuid4(),
        "resource": resource,
        "starts_at": starts_at,
        "ends_at": starts_at + timedelta(days=30),
        "allocated": 1000,
        "reserved": 0,
        "consumed": 0,
    }
    quota = PeriodQuota(**(values | overrides))
    _add(db, quota)
    return quota


def make_reservation(db: Session, run: Run, quota: PeriodQuota, **overrides: object) -> Reservation:
    values: dict[str, object] = {
        "run_id": run.id,
        "account_id": quota.account_id,
        "period_id": quota.period_id,
        "resource": quota.resource,
        "amount": 10,
        "status": ReservationStatus.RESERVED,
        "expires_at": in_one_hour(),
    }
    reservation = Reservation(**(values | overrides))
    _add(db, reservation)
    return reservation


def make_rate(db: Session, **overrides: object) -> Rate:
    values: dict[str, object] = {
        "provider": "provider-a",
        "model": "model-a",
        "input_price_micro": 3,
        "output_price_micro": 15,
        "currency": "USD",
        "token_basis": 1000,
        "effective_from": datetime.now(UTC),
    }
    rate = Rate(**(values | overrides))
    _add(db, rate)
    return rate


def make_usage(db: Session, run: Run, rate: Rate, **overrides: object) -> Usage:
    values: dict[str, object] = {
        "run_id": run.id,
        "rate_id": rate.id,
        "event_id": "event-1",
        "resource": "tokens",
        "provider": rate.provider,
        "model": rate.model,
        "input_tokens": 100,
        "output_tokens": 50,
        "units": 0,
        "estimated_cost_micro": 1,
        "charged": False,
        "result": UsageResult.SUCCESS,
        "duration_ms": 1200,
    }
    usage = Usage(**(values | overrides))
    _add(db, usage)
    return usage


def make_object_copy(db: Session, stored_object: StoredObject, **overrides: object) -> ObjectCopy:
    values: dict[str, object] = {
        "object_id": stored_object.id,
        "destination": "backup-a",
        "key": f"copies/{stored_object.id}",
        "sha256": stored_object.sha256,
        "size_bytes": stored_object.size_bytes,
        "verified_at": datetime.now(UTC),
    }
    copy = ObjectCopy(**(values | overrides))
    _add(db, copy)
    return copy


def make_audit_entry(db: Session, workspace_id: uuid.UUID | None) -> uuid.UUID:
    """Adds an entry and returns its id. Reading the id back needs to see the row."""
    entry_id = db.scalar(
        insert(AuditEntry)
        .values(
            actor_ref="actor-1",
            workspace_id=workspace_id,
            action="document.share",
            entity_type="document",
            result=AuditResult.SUCCESS,
        )
        .returning(AuditEntry.id)
    )
    assert entry_id is not None
    return entry_id
