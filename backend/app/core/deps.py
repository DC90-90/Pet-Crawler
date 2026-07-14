"""FastAPI dependencies: current user, role enforcement, CSRF."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.core.security import csrf_valid, decode_token
from app.repositories.collections import users_repo


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        # allow Authorization: Bearer for tooling
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(token)
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated") from None
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = await users_repo.get(payload.get("sub"))
    if not user or not user.get("isActive", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def require_role(*roles: str):
    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        if roles and user.get("role") not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _dep


async def require_owner(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return user


def verify_csrf(request: Request) -> None:
    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("x-csrf-token")
    if not csrf_valid(cookie_token, header_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")


async def csrf_protect(request: Request, user: dict = Depends(get_current_user)) -> dict:
    """Combined dependency: authenticated + CSRF double-submit for mutations."""
    verify_csrf(request)
    return user


async def csrf_protect_owner(request: Request, user: dict = Depends(get_current_user)) -> dict:
    verify_csrf(request)
    if user.get("role") != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Owner role required")
    return user
