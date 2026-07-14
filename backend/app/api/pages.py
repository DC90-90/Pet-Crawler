"""Admin page-builder routes (modular sections)."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request

from app.api.helpers import client_ip
from app.core.deps import csrf_protect, get_current_user
from app.models.common import new_id, now_utc
from app.repositories.collections import pages_repo
from app.services import audit
from app.services.content_version import bump_version

router = APIRouter(prefix="/api/admin/pages", tags=["admin", "pages"])


@router.get("/{key}")
async def get_page(key: str, user: dict = Depends(get_current_user)):
    page = await pages_repo.get_by(key=key)
    if not page:
        return {"key": key, "title": key.title(), "sections": []}
    return page


@router.put("/{key}")
async def update_page(
    key: str, request: Request, payload: dict = Body(...), user: dict = Depends(csrf_protect)
):
    existing = await pages_repo.get_by(key=key)
    sections = payload.get("sections", [])
    for section in sections:
        section.setdefault("id", new_id())
    doc = {
        "key": key,
        "title": payload.get("title", key.title()),
        "sections": sections,
        "updatedAt": now_utc(),
        "updatedBy": user["id"],
    }
    if existing:
        updated = await pages_repo.update(existing["id"], doc)
    else:
        doc["id"] = new_id()
        updated = await pages_repo.create(doc)
    await bump_version()
    await audit.record(
        "edit", "page", user_id=user["id"], user_email=user["email"],
        entity_id=updated["id"], summary=f"Edited page {key}", ip=client_ip(request),
    )
    return updated
