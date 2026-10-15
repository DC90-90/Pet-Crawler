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
from collections import OrderedDict
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


# Decoded payloads, per process, keyed by (key, written_at). Every page request
# used to download the whole compressed payload (several MB for Market Share
# and Price Intel), inflate and parse it, even when nothing had changed: 2-4 s
# per request (15 Oct 2026). A head document's `written_at` changes with every
# write, so a hit is always the current content. Callers treat payloads as
# read-only (as the Market Share live memo already did).
MEMO_ENTRIES = 8
MEMO_COMPRESSED_BYTES = 64 * 1024 * 1024
_memo = OrderedDict()            # (key, written_at) -> (payload, compressed size)
HEAD_PROJECTION = {"payload_zlib": 0}


def _memo_key(doc):
    stamp = doc.get("written_at") or doc.get("computed_at")
    return (doc.get("key"), str(stamp)) if doc.get("key") and stamp else None


def _remember(key, payload, size):
    _memo[key] = (payload, size)
    _memo.move_to_end(key)
    while len(_memo) > MEMO_ENTRIES or sum(s for _p, s in _memo.values()) > MEMO_COMPRESSED_BYTES:
        _memo.popitem(last=False)


def memo_clear():
    _memo.clear()


async def read_blob(db, doc):
    """Payload for a head document, or None when any part is missing. The head
    may be read without `payload_zlib` (HEAD_PROJECTION): the payload is then
    served from this process's memo, or fetched only when it changed."""
    if doc is None:
        return None
    if "payload" in doc:
        return doc["payload"]
    if "dataset" in doc:
        return doc["dataset"]
    mk = _memo_key(doc)
    if mk is not None and mk in _memo:
        _memo.move_to_end(mk)
        return _memo[mk][0]
    blob = doc.get("payload_zlib")
    if blob is None and not doc.get("chunks") and doc.get("encoding") == "zlib-json":
        full = await db[COLLECTION].find_one({"key": doc["key"]}, {"_id": 0, "payload_zlib": 1, "written_at": 1, "computed_at": 1})
        if not full or full.get("payload_zlib") is None:
            return None
        blob = full["payload_zlib"]
        mk = _memo_key({"key": doc["key"], **full})
    if blob is not None:
        payload = await asyncio.to_thread(unpack, blob)
        if mk is not None:
            _remember(mk, payload, len(blob))
        return payload
    if doc.get("chunks"):
        parts = await db[CHUNKS].find({"key": doc["key"]}, {"_id": 0, "n": 1, "payload_zlib": 1}).sort("n", 1).to_list(1000)
        if len(parts) != doc["chunks"] or [p["n"] for p in parts] != list(range(doc["chunks"])):
            return None
        joined = b"".join(bytes(p["payload_zlib"]) for p in parts)
        payload = await asyncio.to_thread(unpack, joined)
        if mk is not None:
            _remember(mk, payload, len(joined))
        return payload
    return None
