"""Generic base repository: CRUD + effective-published filtering."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.db import get_db
from app.models.common import new_id, now_utc


def _out(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc = dict(doc)
    if "_id" in doc:
        doc["id"] = doc.pop("_id")
    return doc


def _in(doc: dict) -> dict:
    doc = dict(doc)
    if "id" in doc:
        doc["_id"] = doc.pop("id")
    if "_id" not in doc:
        doc["_id"] = new_id()
    return doc


def effective_published_query(now: datetime | None = None) -> dict:
    now = now or now_utc()
    return {
        "status": "published",
        "$and": [
            {"$or": [{"publishAt": None}, {"publishAt": {"$lte": now}}]},
            {"$or": [{"unpublishAt": None}, {"unpublishAt": {"$gt": now}}]},
        ],
    }


class BaseRepository:
    collection_name: str = ""
    publishable: bool = False

    def __init__(self, collection_name: str | None = None, publishable: bool | None = None):
        if collection_name:
            self.collection_name = collection_name
        if publishable is not None:
            self.publishable = publishable

    @property
    def col(self):
        return get_db()[self.collection_name]

    async def create(self, doc: dict) -> dict:
        payload = _in(doc)
        await self.col.insert_one(payload)
        return _out(payload)

    async def get(self, doc_id: str) -> Optional[dict]:
        return _out(await self.col.find_one({"_id": doc_id}))

    async def get_by(self, **kwargs) -> Optional[dict]:
        return _out(await self.col.find_one(kwargs))

    async def update(self, doc_id: str, patch: dict) -> Optional[dict]:
        patch = {k: v for k, v in patch.items() if k not in ("id", "_id")}
        patch["updatedAt"] = now_utc()
        await self.col.update_one({"_id": doc_id}, {"$set": patch})
        return await self.get(doc_id)

    async def replace(self, doc_id: str, doc: dict) -> Optional[dict]:
        payload = _in({**doc, "id": doc_id})
        await self.col.replace_one({"_id": doc_id}, payload, upsert=True)
        return await self.get(doc_id)

    async def delete(self, doc_id: str) -> bool:
        res = await self.col.delete_one({"_id": doc_id})
        return res.deleted_count > 0

    async def list(
        self,
        query: dict | None = None,
        *,
        sort: list[tuple[str, int]] | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        query = query or {}
        cursor = self.col.find(query)
        if sort:
            cursor = cursor.sort(sort)
        skip = max(0, (page - 1)) * page_size
        cursor = cursor.skip(skip).limit(page_size)
        return [_out(d) for d in await cursor.to_list(length=page_size)]

    async def count(self, query: dict | None = None) -> int:
        return await self.col.count_documents(query or {})

    # --- publish helpers ---
    async def list_public(
        self,
        extra_query: dict | None = None,
        *,
        sort: list[tuple[str, int]] | None = None,
        page: int = 1,
        page_size: int = 50,
        now: datetime | None = None,
    ) -> list[dict]:
        query = effective_published_query(now)
        if extra_query:
            query = {"$and": [query, extra_query]}
        return await self.list(query, sort=sort, page=page, page_size=page_size)

    async def get_public(self, doc_id: str, now: datetime | None = None) -> Optional[dict]:
        doc = await self.get(doc_id)
        if doc and self._is_public(doc, now):
            return doc
        return None

    async def get_public_by_slug(self, slug: str, now: datetime | None = None) -> Optional[dict]:
        doc = await self.get_by(slug=slug)
        if doc and self._is_public(doc, now):
            return doc
        return None

    @staticmethod
    def _is_public(doc: dict, now: datetime | None = None) -> bool:
        from app.models.common import is_effectively_published

        return is_effectively_published(doc, now)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
