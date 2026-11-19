"""An in-memory bucket with the same interface as S3ObjectStore, so tests need no S3."""

from datetime import timedelta
from urllib.parse import quote

from app.storage.service import ObjectStoreError, SignedUpload


class MemoryObjectStore:
    def __init__(self, bucket: str = "documents") -> None:
        self.bucket = bucket
        self.files: dict[str, bytes] = {}
        self.deleted: list[str] = []
        # Keys whose deletion fails, to test what happens when storage is down.
        self.failing_deletes: set[str] = set()

    def sign_upload(
        self, key: str, *, content_type: str, size_bytes: int, expires_in: timedelta
    ) -> SignedUpload:
        url = f"memory://{self.bucket}/{quote(key)}?size={size_bytes}&ttl={expires_in.seconds}"
        return SignedUpload(url=url, headers={"Content-Type": content_type})

    def sign_download(self, key: str, *, expires_in: timedelta) -> str:
        return f"memory://{self.bucket}/{quote(key)}?ttl={expires_in.seconds}"

    def read(self, key: str, *, max_bytes: int) -> bytes | None:
        data = self.files.get(key)
        return None if data is None else data[: max_bytes + 1]

    def write(self, key: str, data: bytes, *, content_type: str) -> None:
        self.files[key] = data

    def delete(self, key: str) -> None:
        if key in self.failing_deletes:
            raise ObjectStoreError("Storage refused delete_object (InternalError)")
        self.files.pop(key, None)
        self.deleted.append(key)

    def key_of(self, url: str) -> str:
        """The key a signed URL points to: what the browser would upload to."""
        path = url.removeprefix(f"memory://{self.bucket}/").split("?", 1)[0]
        return path.replace("%2F", "/")
