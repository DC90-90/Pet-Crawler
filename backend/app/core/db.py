"""MongoDB connection management (Motor async client)."""
from __future__ import annotations

import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def _use_mock() -> bool:
    """Dev/test-only in-process mock DB (never in production)."""
    return (
        os.getenv("USE_MOCK_DB", "").lower() == "true"
        or settings.mongodb_uri.startswith("mock://")
    ) and not settings.is_production


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        if _use_mock():
            from mongomock_motor import AsyncMongoMockClient

            _client = AsyncMongoMockClient()
        else:
            _client = AsyncIOMotorClient(settings.mongodb_uri, uuidRepresentation="standard")
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        _db = get_client()[settings.mongodb_db]
    return _db


def set_db(db: AsyncIOMotorDatabase) -> None:
    """Override the active database (used by tests to inject mongomock)."""
    global _db
    _db = db


async def close_client() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


# Index definitions derived from DATA_MODEL.md
async def ensure_indexes(db: AsyncIOMotorDatabase | None = None) -> None:
    from pymongo import ASCENDING, DESCENDING

    db = db or get_db()
    await db.users.create_index([("email", ASCENDING)], unique=True)
    await db.tours.create_index([("slug", ASCENDING)], unique=True)
    await db.destinations.create_index([("slug", ASCENDING)], unique=True)
    await db.articles.create_index([("slug", ASCENDING)], unique=True)
    await db.gallery_albums.create_index([("slug", ASCENDING)], unique=True)
    await db.redirects.create_index([("fromPath", ASCENDING)], unique=True)

    await db.tours.create_index(
        [("status", ASCENDING), ("featured", DESCENDING), ("displayOrder", ASCENDING)]
    )
    await db.inquiries.create_index([("status", ASCENDING), ("createdAt", DESCENDING)])
    await db.audit_logs.create_index([("at", DESCENDING)])
    await db.banners.create_index([("active", ASCENDING), ("priority", DESCENDING)])
    await db.offers.create_index([("status", ASCENDING), ("priority", DESCENDING)])
    await db.sessions.create_index([("userId", ASCENDING)])
    await db.sessions.create_index([("refreshTokenHash", ASCENDING)])
