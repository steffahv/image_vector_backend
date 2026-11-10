"""Workspace references for the internal maintenance worker."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.models import Workspace


def list_maintenance_workspaces(db: Session) -> Sequence[uuid.UUID]:
    return db.scalars(select(Workspace.id).order_by(Workspace.id)).all()


def find_maintenance_workspace_owner(db: Session, workspace_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(select(Workspace.owner_id).where(Workspace.id == workspace_id))
