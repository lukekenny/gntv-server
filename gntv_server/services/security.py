import hashlib
import hmac
import secrets


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_opaque_token(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_opaque_token(token), expected_hash)
