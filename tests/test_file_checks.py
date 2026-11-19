"""Uploaded bytes are checked by their content, never by what the request or the name says."""

import gzip
import hashlib
from collections.abc import Callable
from io import BytesIO

import pytest
from PIL import Image

from app.storage.models import ObjectKind
from app.storage.service import ExpectedFile, FileRejected
from app.storage.service.file_checks import check_file


def _image(fmt: str = "PNG", size: tuple[int, int] = (4, 3)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buffer, fmt)
    return buffer.getvalue()


def _expect_image(data: bytes, **overrides: object) -> ExpectedFile:
    values: dict[str, object] = {
        "kind": ObjectKind.IMAGE,
        "sha256": hashlib.sha256(data).digest(),
        "size_bytes": len(data),
        "mime_type": "image/png",
        "width": 4,
        "height": 3,
    }
    return ExpectedFile(**(values | overrides))  # type: ignore[arg-type]


def _expect_json(data: bytes, original_bytes: int, gzipped: bool = True) -> ExpectedFile:
    return ExpectedFile(
        kind=ObjectKind.DOCUMENT_JSON,
        sha256=hashlib.sha256(data).digest(),
        size_bytes=len(data),
        mime_type="application/json",
        gzip=gzipped,
        original_bytes=original_bytes,
    )


def test_the_declared_file_passes() -> None:
    check_file(_image(), _expect_image(_image()))
    text = b'{"pages": []}'
    check_file(gzip.compress(text), _expect_json(gzip.compress(text), len(text)))
    check_file(text, _expect_json(text, len(text), gzipped=False))


@pytest.mark.parametrize(
    ("data", "expected", "code"),
    [
        # A JPEG uploaded as a PNG: the type is read from the bytes.
        (_image("JPEG"), _expect_image(_image("JPEG")), "type_mismatch"),
        (_image(size=(5, 3)), _expect_image(_image(size=(5, 3))), "dimensions_mismatch"),
        (b"<svg onload=alert(1)>", _expect_image(b"<svg onload=alert(1)>"), "invalid_image"),
        (_image()[:-20], _expect_image(_image()[:-20]), "invalid_image"),
    ],
)
def test_an_image_that_is_not_what_was_declared_is_rejected(
    data: bytes, expected: ExpectedFile, code: str
) -> None:
    with pytest.raises(FileRejected) as rejected:
        check_file(data, expected)
    assert rejected.value.code == code


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda data: data + b"x", "size_mismatch"),
        (lambda data: data[:-1] + bytes([data[-1] ^ 1]), "hash_mismatch"),
    ],
)
def test_bytes_other_than_the_declared_ones_are_rejected(
    change: Callable[[bytes], bytes], code: str
) -> None:
    with pytest.raises(FileRejected) as rejected:
        check_file(change(_image()), _expect_image(_image()))
    assert rejected.value.code == code


def _json_case(text: bytes, declared_original: int | None = None) -> tuple[bytes, ExpectedFile]:
    data = gzip.compress(text)
    return data, _expect_json(data, len(text) if declared_original is None else declared_original)


@pytest.mark.parametrize(
    ("case", "code"),
    [
        (_json_case(b"not json"), "invalid_json"),
        (_json_case(b"[1, 2]"), "invalid_json"),
        (_json_case(b"\xff\xfe{}"), "invalid_json"),
        # A small upload that would grow far past what was declared (a gzip bomb) stops at the
        # declared size instead of filling memory.
        (_json_case(b"{" + b" " * 5_000_000 + b"}", declared_original=100), "size_mismatch"),
        (_json_case(b'{"a": 1}', declared_original=100), "size_mismatch"),
        ((b"plain", _expect_json(b"plain", 5)), "invalid_gzip"),
        (
            (
                gzip.compress(b"{}") + gzip.compress(b"{}"),
                _expect_json(gzip.compress(b"{}") + gzip.compress(b"{}"), 2),
            ),
            "invalid_gzip",
        ),
    ],
)
def test_a_document_that_is_not_one_json_object_is_rejected(
    case: tuple[bytes, ExpectedFile], code: str
) -> None:
    data, expected = case
    with pytest.raises(FileRejected) as rejected:
        check_file(data, expected)
    assert rejected.value.code == code
