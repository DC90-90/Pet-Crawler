"""Compressed, chunked storage for large cache payloads.

MongoDB caps a document at 16 MB. The My Products dataset (≈3,000 rows with
their sellers) and the Market Share dataset both exceed it on production, so
a cache payload is stored as zlib-compressed JSON: inline on the head
document when small, otherwise as ordered chunks in `dashboard_cache_chunks`
with the head document holding the count. Chunks are written before the
head, so a reader never sees a head that points at chunks that do not exist
yet. Legacy inline `payload` / `dataset` documents still read.
"""
import asyncio
import json
import zlib
from datetime import datetime, timezone

INLINE_LIMIT = 12 * 1024 * 1024
CHUNK_BYTES = 12 * 1024 * 1024
COLLECTION = "dashboard_cache"
CHUNKS = "dashboard_cache_chunks"


def pack(payload):
    return zlib.compress(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"), 6)


def unpack(blob):
    return json.loads(zlib.decompress(bytes(blob)).decode("utf-8"))


async def write_blob(db, key, payload, head_fields):
    """Replace the cache entry `key` with `payload` plus `head_fields`."""
    from bson import Binary
    # JSON + zlib of a multi-MB payload took seconds of event-loop time; on
    # production a backend stalled for 63 s and was restarted (14 Oct 2026).
    blob = await asyncio.to_thread(pack, payload)
    now = datetime.now(timezone.utc)
    doc = {**head_fields, "key": key, "encoding": "zlib-json", "size_bytes": len(blob), "written_at": now}
    await db[CHUNKS].delete_many({"key": key})
    if len(blob) <= INLINE_LIMIT:
        doc["payload_zlib"] = Binary(blob)
    else:
        parts = [blob[i:i + CHUNK_BYTES] for i in range(0, len(blob), CHUNK_BYTES)]
        for n, part in enumerate(parts):
            await db[CHUNKS].replace_one({"key": key, "n": n},
                                         {"key": key, "n": n, "written_at": now, "payload_zlib": Binary(part)}, upsert=True)
        doc["chunks"] = len(parts)
    await db[COLLECTION].replace_one({"key": key}, doc, upsert=True)
    return doc


async def read_blob(db, doc):
    """Payload for a head document, or None when any part is missing."""
    if doc is None:
        return None
    if "payload" in doc:
        return doc["payload"]
    if "dataset" in doc:
        return doc["dataset"]
    if doc.get("payload_zlib") is not None:
        return await asyncio.to_thread(unpack, doc["payload_zlib"])
    if doc.get("chunks"):
        parts = await db[CHUNKS].find({"key": doc["key"]}, {"_id": 0, "n": 1, "payload_zlib": 1}).sort("n", 1).to_list(1000)
        if len(parts) != doc["chunks"] or [p["n"] for p in parts] != list(range(doc["chunks"])):
            return None
        return await asyncio.to_thread(unpack, b"".join(bytes(p["payload_zlib"]) for p in parts))
    return None
