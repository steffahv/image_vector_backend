"""Shared rules for token hashes stored in auth tables."""

from app.core.model_base import SHA256_BYTES, sha256_check

__all__ = ["SHA256_BYTES", "TOKEN_HASH_CHECK"]

TOKEN_HASH_CHECK = sha256_check("token_hash")
