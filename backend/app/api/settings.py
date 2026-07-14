"""Admin site settings + navigation. Secrets/analytics = owner only."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request

from app.api.helpers import client_ip
from app.core.deps import csrf_protect, get_current_user
from app.models.common import now_utc
from app.repositories.collections import navigation_repo, site_settings_repo
from app.services import audit
from app.services.content_version import bump_version

router = APIRouter(prefix="/api/admin", tags=["admin", "settings"])

# Fields only the owner may modify
OWNER_ONLY_FIELDS = {"analytics", "seoDefaults"}


@router.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    return await site_settings_repo.get("settings") or {"id": "settings"}


@router.put("/settings")
async def update_settings(
    request: Request, payload: dict = Body(...), user: dict = Depends(csrf_protect)
):
    patch = dict(payload)
    patch.pop("id", None)
    if user.get("role") != "owner":
        # editors cannot change secrets/analytics/seo defaults
        for field in OWNER_ONLY_FIELDS:
            patch.pop(field, None)
    patch["updatedAt"] = now_utc()
    patch["updatedBy"] = user["id"]
    existing = await site_settings_repo.get("settings")
    if existing:
        updated = await site_settings_repo.update("settings", patch)
    else:
        updated = await site_settings_repo.replace("settings", {"id": "settings", **patch})
    await bump_version()
    await audit.record(
        "settings_change", "settings", user_id=user["id"], user_email=user["email"],
        entity_id="settings", summary="Updated site settings", ip=client_ip(request),
    )
    return updated


@router.get("/navigation")
async def get_navigation(user: dict = Depends(get_current_user)):
    return await navigation_repo.get("navigation") or {"id": "navigation"}


@router.put("/navigation")
async def update_navigation(
    request: Request, payload: dict = Body(...), user: dict = Depends(csrf_protect)
):
    patch = dict(payload)
    patch.pop("id", None)
    existing = await navigation_repo.get("navigation")
    if existing:
        updated = await navigation_repo.update("navigation", patch)
    else:
        updated = await navigation_repo.replace("navigation", {"id": "navigation", **patch})
    await bump_version()
    await audit.record(
        "settings_change", "navigation", user_id=user["id"], user_email=user["email"],
        entity_id="navigation", summary="Updated navigation", ip=client_ip(request),
    )
    return updated
