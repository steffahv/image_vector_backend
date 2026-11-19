"""The S3-compatible bucket where document files live, behind a small interface.

Only this file talks to S3. The rest of the code uses `ObjectStore`, so tests run with an
in-memory store and the provider (AWS S3, Cloudflare R2, MinIO...) is a setting, not code.

The bucket is private: browsers upload and download with signed URLs that allow one operation on
one key and expire in 10 minutes at most.
"""

from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings

MAX_SIGNED_URL_TTL = timedelta(minutes=10)

# S3 error codes for a key that does not exist, and for a range on an empty object.
_MISSING = frozenset({"NoSuchKey", "404", "NotFound"})
_EMPTY = "InvalidRange"


class StorageUnavailable(Exception):
    """No storage is configured (only allowed in development)."""


class ObjectStoreError(Exception):
    """Storage refused or failed a request. The message never includes keys or URLs."""


@dataclass(frozen=True)
class SignedUpload:
    url: str
    # The browser must send them exactly as given, or storage rejects the signature.
    headers: dict[str, str]


class ObjectStore(Protocol):
    bucket: str

    def sign_upload(
        self, key: str, *, content_type: str, size_bytes: int, expires_in: timedelta
    ) -> SignedUpload:
        """A URL for one PUT of exactly `size_bytes` bytes of `content_type` to `key`."""
        ...

    def sign_download(self, key: str, *, expires_in: timedelta) -> str:
        """A URL for one GET of `key`."""
        ...

    def read(self, key: str, *, max_bytes: int) -> bytes | None:
        """The object's bytes, at most `max_bytes + 1` of them; `None` if there is no object.

        Reading one byte past the limit lets the caller tell "exactly the limit" from "more".
        """
        ...

    def write(self, key: str, data: bytes, *, content_type: str) -> None: ...

    def delete(self, key: str) -> None:
        """Delete `key`. Deleting a key that does not exist is not an error."""
        ...


def _seconds(expires_in: timedelta) -> int:
    return int(min(expires_in, MAX_SIGNED_URL_TTL).total_seconds())


class S3ObjectStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self.bucket = bucket

    def sign_upload(
        self, key: str, *, content_type: str, size_bytes: int, expires_in: timedelta
    ) -> SignedUpload:
        # Content-Type and Content-Length are part of the signature, so storage refuses a body
        # of another size or type: the declared size is enforced before any byte is stored.
        url = self._call(
            "generate_presigned_url",
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": size_bytes,
            },
            ExpiresIn=_seconds(expires_in),
            HttpMethod="PUT",
        )
        return SignedUpload(url=url, headers={"Content-Type": content_type})

    def sign_download(self, key: str, *, expires_in: timedelta) -> str:
        url: str = self._call(
            "generate_presigned_url",
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=_seconds(expires_in),
        )
        return url

    def read(self, key: str, *, max_bytes: int) -> bytes | None:
        try:
            response = self._client.get_object(
                Bucket=self.bucket, Key=key, Range=f"bytes=0-{max_bytes}"
            )
            data: bytes = response["Body"].read(max_bytes + 1)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code in _MISSING:
                return None
            if code == _EMPTY:
                return b""
            raise ObjectStoreError(f"Storage refused a read ({code})") from error
        except BotoCoreError as error:
            raise ObjectStoreError(f"Storage read failed ({type(error).__name__})") from error
        return data

    def write(self, key: str, data: bytes, *, content_type: str) -> None:
        self._call("put_object", Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def delete(self, key: str) -> None:
        self._call("delete_object", Bucket=self.bucket, Key=key)

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(self._client, method)(*args, **kwargs)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            raise ObjectStoreError(f"Storage refused {method} ({code})") from error
        except BotoCoreError as error:
            raise ObjectStoreError(f"Storage {method} failed ({type(error).__name__})") from error


@lru_cache
def get_object_store() -> ObjectStore:
    """The configured bucket. Raises `StorageUnavailable` if storage is not configured."""
    settings = get_settings()
    if not settings.s3_configured or settings.s3_secret_access_key is None:
        raise StorageUnavailable("S3 storage is not configured")
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        # Path-style URLs work with every provider, including MinIO on localhost.
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return S3ObjectStore(client, str(settings.s3_bucket))
