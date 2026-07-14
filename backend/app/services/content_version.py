"""Singleton content_meta version counter."""
from __future__ import annotations

from app.models.common import now_utc
from app.repositories.collections import content_meta_repo

META_ID = "content_meta"


async def get_version() -> dict:
    doc = await content_meta_repo.get(META_ID)
    if not doc:
        doc = {"id": META_ID, "version": 1, "updatedAt": now_utc()}
        await content_meta_repo.create(doc)
    return {"version": doc["version"], "updatedAt": doc["updatedAt"]}


async def bump_version() -> int:
    doc = await content_meta_repo.get(META_ID)
    if not doc:
        await content_meta_repo.create({"id": META_ID, "version": 2, "updatedAt": now_utc()})
        return 2
    new_version = int(doc.get("version", 1)) + 1
    await content_meta_repo.update(META_ID, {"version": new_version, "updatedAt": now_utc()})
    return new_version
