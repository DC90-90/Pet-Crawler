"""Auth API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.helpers import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    client_ip,
    set_auth_cookies,
)
from app.core.deps import csrf_protect, get_current_user
from app.core.rate_limit import enforce
from app.schemas.dto import (
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
)
from app.services import auth as auth_service
from app.services.email import send_password_reset

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "role": user.get("role"),
        "forcePasswordChange": user.get("forcePasswordChange", False),
        "lastLoginAt": user.get("lastLoginAt"),
    }


@router.post("/login")
async def login(request: Request, response: Response, body: LoginRequest):
    enforce(request, "login", 10, 60)
    ip = client_ip(request)
    try:
        user = await auth_service.authenticate(body.email, body.password, ip)
    except auth_service.AuthError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials") from None
    tokens = await auth_service.issue_session(user, ip, request.headers.get("user-agent"))
    set_auth_cookies(response, tokens)
    return {"user": _public_user(user), "csrfToken": tokens["csrf_token"]}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        tokens = await auth_service.rotate_refresh(
            token, client_ip(request), request.headers.get("user-agent")
        )
    except auth_service.AuthError:
        clear_auth_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated") from None
    set_auth_cookies(response, tokens)
    return {"ok": True, "csrfToken": tokens["csrf_token"]}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await auth_service.revoke_by_refresh(token)
    clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {"user": _public_user(user)}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest, user: dict = Depends(csrf_protect)
):
    try:
        await auth_service.change_password(user["id"], body.old_password, body.new_password)
    except auth_service.AuthError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid credentials") from None
    return {"ok": True}


@router.post("/password-reset/request")
async def password_reset_request(request: Request, body: PasswordResetRequest):
    enforce(request, "pwreset", 5, 60)
    token = await auth_service.request_password_reset(body.email)
    if token:
        await send_password_reset(body.email, token)
    # Always generic response to avoid account enumeration
    return {"ok": True, "detail": "If the account exists, a reset link has been sent."}


@router.post("/password-reset/confirm")
async def password_reset_confirm(body: PasswordResetConfirm):
    try:
        await auth_service.confirm_password_reset(body.token, body.new_password)
    except auth_service.AuthError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token") from None
    return {"ok": True}
