"""Generic content CRUD with sanitization, audit, and version bumping."""
from __future__ import annotations

from typing import Optional

from app.models.common import is_effectively_published, new_id, now_utc
from app.repositories.base import BaseRepository
from app.services import audit
from app.services.content_version import bump_version
from app.services.sanitize import RICH_TEXT_FIELDS, sanitize_localized


def _sanitize_payload(payload: dict) -> dict:
    payload = dict(payload)
    for field in RICH_TEXT_FIELDS:
        if field in payload and isinstance(payload[field], dict):
            payload[field] = sanitize_localized(payload[field])
    return payload


async def create_doc(
    repo: BaseRepository, entity: str, payload: dict, actor: dict, ip: Optional[str] = None
) -> dict:
    payload = _sanitize_payload(payload)
    payload.setdefault("id", new_id())
    payload["createdAt"] = now_utc()
    payload["updatedAt"] = now_utc()
    payload["createdBy"] = actor.get("id")
    payload["lastEditedBy"] = actor.get("id")
    created = await repo.create(payload)
    await audit.record(
        "create", entity, user_id=actor.get("id"), user_email=actor.get("email"),
        entity_id=created["id"], summary=f"Created {entity}", ip=ip,
    )
    if is_effectively_published(created):
        await bump_version()
    return created


async def update_doc(
    repo: BaseRepository, entity: str, doc_id: str, patch: dict, actor: dict,
    ip: Optional[str] = None,
) -> Optional[dict]:
    existing = await repo.get(doc_id)
    if not existing:
        return None
    patch = _sanitize_payload(patch)
    patch.pop("id", None)
    patch["lastEditedBy"] = actor.get("id")
    updated = await repo.update(doc_id, patch)
    await audit.record(
        "edit", entity, user_id=actor.get("id"), user_email=actor.get("email"),
        entity_id=doc_id, summary=f"Edited {entity}", ip=ip,
    )
    # bump if the content is (or was) publicly visible
    if is_effectively_published(existing) or is_effectively_published(updated or {}):
        await bump_version()
    return updated


async def delete_doc(
    repo: BaseRepository, entity: str, doc_id: str, actor: dict, ip: Optional[str] = None
) -> bool:
    existing = await repo.get(doc_id)
    if not existing:
        return False
    ok = await repo.delete(doc_id)
    if ok:
        await audit.record(
            "delete", entity, user_id=actor.get("id"), user_email=actor.get("email"),
            entity_id=doc_id, summary=f"Deleted {entity}", ip=ip,
        )
        if is_effectively_published(existing) or existing.get("published") or existing.get("active"):
            await bump_version()
    return ok
