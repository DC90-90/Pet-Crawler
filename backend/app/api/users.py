"""Admin user management (owner only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.helpers import client_ip
from app.core.deps import csrf_protect_owner, require_owner
from app.core.security import hash_password
from app.models.common import new_id, now_utc
from app.repositories.collections import users_repo
from app.schemas.dto import UserCreateRequest, UserUpdateRequest
from app.services import audit

router = APIRouter(prefix="/api/admin/users", tags=["admin", "users"])


def _public(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "role": user.get("role"),
        "isActive": user.get("isActive", True),
        "forcePasswordChange": user.get("forcePasswordChange", False),
        "lastLoginAt": user.get("lastLoginAt"),
        "createdAt": user.get("createdAt"),
    }


@router.get("")
async def list_users(user: dict = Depends(require_owner)):
    items = await users_repo.list(sort=[("createdAt", 1)], page_size=500)
    return {"items": [_public(u) for u in items]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request, body: UserCreateRequest, user: dict = Depends(csrf_protect_owner)
):
    if body.role not in ("owner", "editor"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid role")
    existing = await users_repo.get_by(email=body.email.lower())
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already exists")
    doc = {
        "id": new_id(),
        "email": body.email.lower(),
        "passwordHash": hash_password(body.password),
        "role": body.role,
        "name": body.name,
        "isActive": True,
        "forcePasswordChange": body.forcePasswordChange,
        "failedLoginCount": 0,
        "createdAt": now_utc(),
        "updatedAt": now_utc(),
    }
    created = await users_repo.create(doc)
    await audit.record(
        "user_change", "user", user_id=user["id"], user_email=user["email"],
        entity_id=created["id"], summary=f"Created user {body.email}", ip=client_ip(request),
    )
    return _public(created)


@router.put("/{user_id}")
async def update_user(
    user_id: str, request: Request, body: UserUpdateRequest,
    user: dict = Depends(csrf_protect_owner),
):
    target = await users_repo.get(user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    patch: dict = {}
    if body.name is not None:
        patch["name"] = body.name
    if body.role is not None:
        if body.role not in ("owner", "editor"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid role")
        patch["role"] = body.role
    if body.isActive is not None:
        patch["isActive"] = body.isActive
    if body.forcePasswordChange is not None:
        patch["forcePasswordChange"] = body.forcePasswordChange
    if body.password:
        patch["passwordHash"] = hash_password(body.password)
    updated = await users_repo.update(user_id, patch)
    await audit.record(
        "user_change", "user", user_id=user["id"], user_email=user["email"],
        entity_id=user_id, summary=f"Updated user {target['email']}", ip=client_ip(request),
    )
    return _public(updated)


@router.delete("/{user_id}")
async def delete_user(
    user_id: str, request: Request, user: dict = Depends(csrf_protect_owner)
):
    if user_id == user["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")
    target = await users_repo.get(user_id)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    await users_repo.delete(user_id)
    await audit.record(
        "user_change", "user", user_id=user["id"], user_email=user["email"],
        entity_id=user_id, summary=f"Deleted user {target['email']}", ip=client_ip(request),
    )
    return {"ok": True}
