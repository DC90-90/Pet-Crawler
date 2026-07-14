"""Publishing lifecycle for envelope resources; bumps content_meta.version."""
from __future__ import annotations

from typing import Optional

from app.models.common import now_utc
from app.repositories.base import BaseRepository
from app.services import audit
from app.services.content_version import bump_version


async def publish(
    repo: BaseRepository, entity: str, doc_id: str, actor: dict, ip: Optional[str] = None
) -> Optional[dict]:
    doc = await repo.get(doc_id)
    if not doc:
        return None
    patch = {
        "status": "published",
        "publishedAt": doc.get("publishedAt") or now_utc(),
        "lastEditedBy": actor.get("id"),
    }
    updated = await repo.update(doc_id, patch)
    await bump_version()
    await audit.record(
        "publish", entity, user_id=actor.get("id"), user_email=actor.get("email"),
        entity_id=doc_id, summary=f"Published {entity}", ip=ip,
    )
    return updated


async def unpublish(
    repo: BaseRepository, entity: str, doc_id: str, actor: dict, ip: Optional[str] = None
) -> Optional[dict]:
    doc = await repo.get(doc_id)
    if not doc:
        return None
    updated = await repo.update(doc_id, {"status": "draft", "lastEditedBy": actor.get("id")})
    await bump_version()
    await audit.record(
        "unpublish", entity, user_id=actor.get("id"), user_email=actor.get("email"),
        entity_id=doc_id, summary=f"Unpublished {entity}", ip=ip,
    )
    return updated
