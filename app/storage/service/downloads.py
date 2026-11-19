"""Signed downloads of stored files (Arquitectura §III-B).

The bucket is private: the editor downloads each file with a URL that allows one GET of that one
key and expires in 10 minutes at most.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.models import ObjectEncoding, ObjectStatus, StoredObject
from app.storage.service.object_store import MAX_SIGNED_URL_TTL, ObjectStore
from app.storage.service.objects import ObjectUnavailable
from app.storage.service.saves import now


@dataclass(frozen=True)
class SignedDownload:
    url: str
    expires_at: datetime
    sha256: str
    size_bytes: int
    mime_type: str
    gzip: bool


def sign_downloads(
    db: Session,
    store: ObjectStore,
    workspace_id: uuid.UUID,
    object_ids: Collection[uuid.UUID],
) -> dict[uuid.UUID, SignedDownload]:
    """A signed GET for each of the workspace's files, by id.

    Raises `ObjectUnavailable` if one is not a ready file of the workspace: a URL is only ever
    signed for a file the caller's workspace owns.
    """
    found = db.scalars(
        select(StoredObject).where(
            StoredObject.workspace_id == workspace_id,
            StoredObject.id.in_(object_ids),
            StoredObject.status == ObjectStatus.READY,
        )
    ).all()
    if len(found) != len(set(object_ids)):
        raise ObjectUnavailable(str(workspace_id))
    expires_at = now() + MAX_SIGNED_URL_TTL
    return {
        stored.id: SignedDownload(
            url=store.sign_download(stored.key, expires_in=MAX_SIGNED_URL_TTL),
            expires_at=expires_at,
            sha256=stored.sha256.hex(),
            size_bytes=stored.size_bytes,
            mime_type=stored.mime_type,
            gzip=stored.encoding == ObjectEncoding.GZIP,
        )
        for stored in found
    }
