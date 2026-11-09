"""Random tokens for sessions and email links. The database only ever stores their hash."""

import hashlib
import secrets

TOKEN_BYTES = 32
# token_urlsafe(32) is always 43 characters from the URL-safe base64 alphabet.
TOKEN_PATTERN = r"^[A-Za-z0-9_-]{43}$"


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    """SHA-256 of the token: what `token_hash` columns store and are searched by.

    The lookup is an index search by hash, so no comparison in Python leaks timing.
    """
    return hashlib.sha256(token.encode()).digest()
