"""Security primitives: argon2 password hashing, JWT, CSRF, token helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher(
    time_cost=settings.argon2_time_cost,
    memory_cost=settings.argon2_memory_kb,
    parallelism=settings.argon2_parallelism,
)

JWT_ALG = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, Exception):  # noqa: BLE001 - generic on purpose
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:  # noqa: BLE001
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: str, role: str, extra: dict | None = None) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALG])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Deterministic hash for refresh/reset tokens stored in the DB."""
    return hashlib.sha256((settings.jwt_secret + token).encode()).hexdigest()


def hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256((settings.csrf_secret + ip).encode()).hexdigest()


# --- CSRF (double-submit) ---------------------------------------------------
def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_valid(cookie_token: str | None, header_token: str | None) -> bool:
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)


# --- Signed preview tokens --------------------------------------------------
def sign_preview_token(resource: str, doc_id: str, ttl_minutes: int = 60) -> str:
    payload = {
        "type": "preview",
        "r": resource,
        "id": doc_id,
        "exp": int((_now() + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.csrf_secret, algorithm=JWT_ALG)


def verify_preview_token(token: str, resource: str, doc_id: str) -> bool:
    try:
        payload = jwt.decode(token, settings.csrf_secret, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return False
    return (
        payload.get("type") == "preview"
        and payload.get("r") == resource
        and payload.get("id") == doc_id
    )
