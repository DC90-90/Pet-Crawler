"""Bounded process-local read-through cache; GETs never acquire write permits.

Keys already include build, policy, KSA day and sales window. Every hit checks
the source revision. Values expire at TTL OR the earliest pricing transition.
No stale-on-error, partial result, or database-write fallback is permitted.
"""
import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from weakref import WeakKeyDictionary
from pymongo.errors import PyMongoError

from price_cohort import aware
from price_read_limits import bounded_read, unavailable
from release_database import GuardedDatabase

SCHEMA = "my-products-read-v1"
MAX_ENTRIES = 4
MAX_CACHE_BYTES = 64 * 1024 * 1024
_loops = WeakKeyDictionary()
logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


async def revision(db):
    doc = await db.data_versions.find_one({"_id": "observations"}, {"_id": 0, "revision": 1}, max_time_ms=2000)
    return (doc or {}).get("revision", 0)


def valid(doc, source_revision, max_age, now):
    if not doc or doc.get("cache_schema") != SCHEMA or doc.get("source_revision") != source_revision:
        return False
    computed, until = aware(doc.get("computed_at")), aware(doc.get("valid_until"))
    ds = doc.get("dataset")
    return bool(computed and until and 0 <= (now-computed).total_seconds() < max_age and now < until
                and isinstance(ds, dict) and isinstance(ds.get("rows"), list)
                and ds.get("total") == len(ds["rows"]) and "kpis" in ds and "categories" in ds)


async def compute_dataset(db, compute, max_age=300):
    """Reject revision races rather than bless mixed-version or expired prices."""
    started = utcnow()
    before = await revision(db)
    dataset = await compute()
    if await revision(db) != before:
        raise unavailable("price_source_changed")
    until = min(aware(dataset.get("_valid_until")) or started, started+timedelta(seconds=max_age))
    if utcnow() >= until:
        raise unavailable("price_freshness_changed")
    return {**dataset, "_source_revision": before, "_computed_at": started, "_valid_until": until}


def envelope(dataset):
    return {"cache_schema": SCHEMA, "dataset": dataset,
            "source_revision": dataset["_source_revision"], "computed_at": dataset["_computed_at"],
            "valid_until": dataset["_valid_until"]}


def metadata(doc, source):
    return {"source": source, "computed_at": aware(doc["computed_at"]).isoformat(),
            "age_seconds": round((utcnow()-aware(doc["computed_at"])).total_seconds(), 1),
            "stale": False, "valid_until": aware(doc["valid_until"]).isoformat()}


def _remember(entries, key, doc):
    # A cache budget is NOT a result cap: oversized datasets are returned whole.
    from bson import BSON
    from fastapi.encoders import jsonable_encoder
    size = len(BSON.encode(jsonable_encoder(doc)))
    if size > MAX_CACHE_BYTES:
        return
    entries.pop(key, None)
    while entries and (len(entries) >= MAX_ENTRIES or sum(v[1] for v in entries.values())+size > MAX_CACHE_BYTES):
        entries.popitem(last=False)
    entries[key] = (doc, size)


async def _serve(db, key, compute, max_age):
    entries, flights = _loops.setdefault(asyncio.get_running_loop(), (OrderedDict(), {}))
    # Client identity prevents cross-database/cluster reuse in tests and workers.
    raw = db.raw if isinstance(db, GuardedDatabase) else db
    scoped_key = (id(raw.client), raw.name, key)
    source_revision = await revision(db)
    cached = entries.get(scoped_key)
    if cached and valid(cached[0], source_revision, max_age, utcnow()):
        entries.move_to_end(scoped_key)
        return cached[0]["dataset"], metadata(cached[0], "memory_cache")
    entries.pop(scoped_key, None)
    if scoped_key in flights:
        doc = await asyncio.shield(flights[scoped_key])
        if not valid(doc, await revision(db), max_age, utcnow()):
            raise unavailable("price_source_changed")
        return doc["dataset"], metadata(doc, "memory_coalesced")

    async def load():
        try:
            doc = await asyncio.wait_for(db.dashboard_cache.find_one({"key": key}, {"_id": 0}, max_time_ms=2000), 2.5)
            if doc is not None and "dataset" not in doc:
                # Compressed / chunked storage (cache_blobs); None when incomplete.
                import cache_blobs
                dataset = await asyncio.wait_for(cache_blobs.read_blob(db, doc), 10)
                # Keep the envelope fields plus the decoded dataset; the raw
                # blob must not travel into the in-memory copy (not JSON-safe).
                doc = ({k: v for k, v in doc.items() if k not in ("payload_zlib", "chunks")} | {"dataset": dataset}
                       if dataset is not None else None)
        except (TimeoutError, PyMongoError):
            logger.warning("Optional dashboard cache read failed; computing from source")
            doc = None
        source = "cache"
        if not valid(doc, source_revision, max_age, utcnow()):
            doc = envelope(await compute_dataset(db, compute, max_age))
            source = "live_fallback"
        elif await revision(db) != source_revision:
            raise unavailable("price_source_changed")
        _remember(entries, scoped_key, doc)
        return doc, source

    async def shared_load():
        doc, source = await load()
        sources.append(source)
        return doc

    sources = []
    task = asyncio.create_task(bounded_read(shared_load()))
    flights[scoped_key] = task

    def completed(done):
        flights.pop(scoped_key, None)
        if not done.cancelled():
            done.exception()  # Consume an error even if all waiting clients left.

    task.add_done_callback(completed)
    doc = await asyncio.shield(task)
    if not valid(doc, doc["source_revision"], max_age, utcnow()):
        raise unavailable("price_freshness_changed")
    return doc["dataset"], metadata(doc, sources[0])


async def serve(db, key, compute, max_age=300, cacheable=True):
    if cacheable:
        return await bounded_read(_serve(db, key, compute, max_age))
    dataset = await bounded_read(compute_dataset(db, compute, max_age))
    return dataset, metadata(envelope(dataset), "live_uncacheable")