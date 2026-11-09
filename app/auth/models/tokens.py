"""Shared rules for token hashes stored in auth tables."""

SHA256_BYTES = 32
TOKEN_HASH_CHECK = f"octet_length(token_hash) = {SHA256_BYTES}"
