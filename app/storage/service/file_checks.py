"""Check uploaded bytes against what the editor declared before they become a stored file.

Everything is checked on the bytes themselves, never trusted from the request or the extension:
size, SHA-256, and for each kind its format (gzip and JSON for documents, the image format and
its dimensions for images and thumbnails).
"""

import hashlib
import hmac
import json
import zlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from app.storage.models import ObjectKind

DOCUMENT_JSON_TYPE = "application/json"
# Pillow format name -> the only media type accepted for it.
IMAGE_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}
THUMBNAIL_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
# gzip framing for zlib (16 + the largest window).
_GZIP = 31


class FileRejected(Exception):
    """The bytes do not match what was declared. `code` is stored on the upload."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExpectedFile:
    kind: ObjectKind
    sha256: bytes
    size_bytes: int
    mime_type: str
    gzip: bool = False
    # Size of the document JSON once uncompressed.
    original_bytes: int | None = None
    width: int | None = None
    height: int | None = None


def check_file(data: bytes, expected: ExpectedFile) -> None:
    """Raise `FileRejected` unless `data` is exactly the file that was declared."""
    if len(data) != expected.size_bytes:
        raise FileRejected("size_mismatch")
    if not hmac.compare_digest(hashlib.sha256(data).digest(), expected.sha256):
        raise FileRejected("hash_mismatch")
    if expected.kind == ObjectKind.DOCUMENT_JSON:
        _check_document_json(data, expected)
    else:
        _check_image(data, expected)


def _check_document_json(data: bytes, expected: ExpectedFile) -> None:
    if expected.original_bytes is None:
        raise ValueError("A document JSON needs its uncompressed size")
    text = _gunzip(data, expected.original_bytes) if expected.gzip else data
    if len(text) != expected.original_bytes:
        raise FileRejected("size_mismatch")
    try:
        document = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FileRejected("invalid_json") from error
    if not isinstance(document, dict):
        raise FileRejected("invalid_json")


def _gunzip(data: bytes, original_bytes: int) -> bytes:
    """Uncompress at most one byte past the declared size, so a gzip bomb stops early."""
    decompressor = zlib.decompressobj(_GZIP)
    try:
        text = decompressor.decompress(data, original_bytes + 1)
    except zlib.error as error:
        raise FileRejected("invalid_gzip") from error
    if len(text) <= original_bytes and not decompressor.eof:
        raise FileRejected("invalid_gzip")
    if decompressor.unused_data:
        # A second gzip member or trailing bytes: not the single file that was declared.
        raise FileRejected("invalid_gzip")
    return text


def _check_image(data: bytes, expected: ExpectedFile) -> None:
    try:
        with Image.open(BytesIO(data)) as image:
            media_type = IMAGE_TYPES.get(image.format or "")
            size = image.size
            image.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as error:
        raise FileRejected("invalid_image") from error
    if media_type is None or media_type != expected.mime_type:
        raise FileRejected("type_mismatch")
    if size != (expected.width, expected.height):
        raise FileRejected("dimensions_mismatch")
