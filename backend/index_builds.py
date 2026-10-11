"""Operator-triggered index builds for the production database.

The boot path creates indexes with the request client (45 s socket timeout)
and swallows failures; on production the snapshot collection (8.45M rows) was
found with no `event_id` index at all, so every snapshot write was a full
collection scan, persistence timed out and nothing had been stored for days
(11 Oct 2026). This module builds the registry below one index at a time,
independently, on a client with no socket timeout, and records every outcome.
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, OperationFailure

logger = logging.getLogger(__name__)

# (collection, keys, options). Order: the write path first, then the reads.
REGISTRY = [
    ("product_snapshots", [("event_id", 1)], {"unique": True, "partialFilterExpression": {"event_id": {"$type": "string"}}}),
    ("product_snapshots", [("store_id", 1), ("offer_id", 1), ("crawled_at", -1)], {}),
    ("product_snapshots", [("crawled_at", -1), ("store_id", 1)], {}),
    ("product_snapshots", [("store_id", 1), ("sku", 1), ("crawled_at", -1)], {}),
    ("observation_events", [("offer_id", 1), ("observed_at", -1)], {}),
    ("sales_facts_v2", [("date", 1), ("store_id", 1)], {}),
    ("crawl_checkpoints", [("store_id", 1), ("state", 1), ("observed_at", 1)], {}),
    ("crawl_checkpoints", [("state", 1)], {}),
    ("products", [("store_id", 1), ("listing_id", 1)], {}),
    ("observation_quarantine", [("store_id", 1), ("listing_id", 1)], {}),
    ("listing_identities", [("store_id", 1), ("listing_id", 1)], {}),
    ("product_matches", [("competitor_sku", 1), ("competitor_store_id", 1)], {}),
]

STATE = {"status": "idle", "started_at": None, "finished_at": None, "results": {}}


def label(coll, keys):
    return f"{coll}:" + "_".join(f"{k}_{d}" for k, d in keys)


async def build_one(db, coll, keys, options):
    """Create one index; a unique index that meets duplicates falls back to a
    non-unique one so the write path still stops scanning, and the result says
    so. Returns a result dict, never raises."""
    started = time.perf_counter()
    try:
        name = await db[coll].create_index(keys, **options)
        return {"status": "ok", "name": name, "secs": round(time.perf_counter() - started, 1)}
    except (DuplicateKeyError, OperationFailure) as exc:
        duplicates = isinstance(exc, DuplicateKeyError) or getattr(exc, "code", None) in (11000, 11001)
        if not (options.get("unique") and duplicates):
            return {"status": "failed", "error": f"{type(exc).__name__}({getattr(exc, 'code', None)}): {str(exc)[:160]}"}
        fallback = {k: v for k, v in options.items() if k != "unique"}
        try:
            name = await db[coll].create_index(keys, **fallback)
            return {"status": "ok_non_unique", "name": name, "secs": round(time.perf_counter() - started, 1),
                    "note": "duplicates exist; built without the unique constraint"}
        except Exception as exc2:  # noqa: BLE001 — reported, never raised
            return {"status": "failed", "error": f"{type(exc2).__name__}: {str(exc2)[:160]}"}
    except Exception as exc:  # noqa: BLE001 — reported, never raised
        return {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


async def run(db, registry=REGISTRY, record=None):
    """Build every registry entry independently; `record(label, result)` is
    awaited after each so another process can read the progress."""
    STATE.update(status="running", started_at=datetime.now(timezone.utc).isoformat(), finished_at=None, results={})
    for coll, keys, options in registry:
        key = label(coll, keys)
        STATE["results"][key] = {"status": "building"}
        result = await build_one(db, coll, keys, options)
        STATE["results"][key] = result
        logger.info("[Indexes] %s → %s", key, result)
        if record is not None:
            try:
                await record(key, result)
            except Exception:  # noqa: BLE001
                logger.exception("[Indexes] progress record failed")
    STATE.update(status="done", finished_at=datetime.now(timezone.utc).isoformat())
    return STATE["results"]


def long_running_client():
    """A client for index builds only: no socket timeout, so a multi-minute
    build on a large collection is not cut off at 45 s."""
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000,
                              connectTimeoutMS=10000, socketTimeoutMS=None)


async def report(db):
    """Current index names and estimated counts for the registry collections."""
    out = {}
    for coll in sorted({c for c, _, _ in REGISTRY}):
        try:
            out[coll] = {"indexes": sorted((await db[coll].index_information()).keys()),
                         "estimated_count": await db[coll].estimated_document_count()}
        except Exception as exc:  # noqa: BLE001
            out[coll] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    return out
