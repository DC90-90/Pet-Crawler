"""Authentication service: login, sessions, refresh rotation, password reset."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_csrf_token,
    generate_refresh_token,
    hash_ip,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.common import new_id, now_utc
from app.repositories.collections import (
    password_resets_repo,
    sessions_repo,
    users_repo,
)
from app.services import audit

MAX_FAILED = 5
LOCKOUT_MINUTES = 15


class AuthError(Exception):
    pass


async def get_user_by_email(email: str) -> Optional[dict]:
    return await users_repo.get_by(email=email.lower().strip())


async def authenticate(email: str, password: str, ip: str | None) -> dict:
    """Return the user doc or raise AuthError (generic message on caller side)."""
    user = await get_user_by_email(email)
    now = now_utc()
    if not user or not user.get("isActive", True):
        raise AuthError("Invalid credentials")

    locked_until = user.get("lockedUntil")
    if locked_until is not None:
        lu = locked_until if locked_until.tzinfo else locked_until.replace(tzinfo=now.tzinfo)
        if lu > now:
            raise AuthError("Invalid credentials")

    if not verify_password(password, user["passwordHash"]):
        failed = int(user.get("failedLoginCount", 0)) + 1
        patch = {"failedLoginCount": failed}
        if failed >= MAX_FAILED:
            patch["lockedUntil"] = now + timedelta(minutes=LOCKOUT_MINUTES)
            patch["failedLoginCount"] = 0
        await users_repo.update(user["id"], patch)
        await audit.record(
            "login_failed", "user", user_id=user["id"], user_email=user["email"],
            summary="Failed login", ip=hash_ip(ip),
        )
        raise AuthError("Invalid credentials")

    await users_repo.update(
        user["id"], {"failedLoginCount": 0, "lockedUntil": None, "lastLoginAt": now}
    )
    await audit.record(
        "login", "user", user_id=user["id"], user_email=user["email"],
        summary="Login success", ip=hash_ip(ip),
    )
    return await users_repo.get(user["id"])


async def issue_session(user: dict, ip: str | None, user_agent: str | None) -> dict:
    """Create access token + refresh session + csrf token."""
    refresh = generate_refresh_token()
    session_doc = {
        "id": new_id(),
        "userId": user["id"],
        "refreshTokenHash": hash_token(refresh),
        "userAgent": user_agent,
        "ip": hash_ip(ip),
        "expiresAt": now_utc() + timedelta(days=settings.refresh_token_ttl_days),
        "createdAt": now_utc(),
        "revokedAt": None,
    }
    await sessions_repo.create(session_doc)
    access = create_access_token(user["id"], user.get("role", "editor"), {"sid": session_doc["id"]})
    csrf = generate_csrf_token()
    return {"access_token": access, "refresh_token": refresh, "csrf_token": csrf,
            "session_id": session_doc["id"]}


async def rotate_refresh(refresh_token: str, ip: str | None, user_agent: str | None) -> dict:
    token_hash = hash_token(refresh_token)
    session = await sessions_repo.get_by(refreshTokenHash=token_hash)
    now = now_utc()
    if not session or session.get("revokedAt") is not None:
        raise AuthError("Invalid session")
    exp = session["expiresAt"]
    exp = exp if exp.tzinfo else exp.replace(tzinfo=now.tzinfo)
    if exp <= now:
        raise AuthError("Session expired")
    user = await users_repo.get(session["userId"])
    if not user or not user.get("isActive", True):
        raise AuthError("Invalid session")
    # revoke old, issue new
    await sessions_repo.update(session["id"], {"revokedAt": now})
    return await issue_session(user, ip, user_agent)


async def revoke_session(session_id: str | None) -> None:
    if session_id:
        await sessions_repo.update(session_id, {"revokedAt": now_utc()})


async def revoke_by_refresh(refresh_token: str) -> None:
    session = await sessions_repo.get_by(refreshTokenHash=hash_token(refresh_token))
    if session:
        await sessions_repo.update(session["id"], {"revokedAt": now_utc()})


async def change_password(user_id: str, old_password: str, new_password: str) -> None:
    user = await users_repo.get(user_id)
    if not user or not verify_password(old_password, user["passwordHash"]):
        raise AuthError("Invalid credentials")
    await users_repo.update(
        user_id,
        {"passwordHash": hash_password(new_password), "forcePasswordChange": False},
    )


async def request_password_reset(email: str) -> Optional[str]:
    user = await get_user_by_email(email)
    if not user:
        return None
    token = generate_refresh_token()
    await password_resets_repo.create(
        {
            "id": new_id(),
            "userId": user["id"],
            "tokenHash": hash_token(token),
            "expiresAt": now_utc() + timedelta(hours=1),
            "usedAt": None,
            "createdAt": now_utc(),
        }
    )
    return token  # returned to caller; email send is optional/no-op


async def confirm_password_reset(token: str, new_password: str) -> None:
    rec = await password_resets_repo.get_by(tokenHash=hash_token(token))
    now = now_utc()
    if not rec or rec.get("usedAt") is not None:
        raise AuthError("Invalid or expired token")
    exp = rec["expiresAt"]
    exp = exp if exp.tzinfo else exp.replace(tzinfo=now.tzinfo)
    if exp <= now:
        raise AuthError("Invalid or expired token")
    await users_repo.update(
        rec["userId"],
        {"passwordHash": hash_password(new_password), "forcePasswordChange": False},
    )
    await password_resets_repo.update(rec["id"], {"usedAt": now})
