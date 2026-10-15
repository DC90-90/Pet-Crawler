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
from price_read_limits import bounded_read, unavailable, in_background, query_max_ms
from release_database import GuardedDatabase

SCHEMA = "my-products-read-v1"
MAX_ENTRIES = 4
MAX_CACHE_BYTES = 64 * 1024 * 1024
_loops = WeakKeyDictionary()
logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


REVISION_READ_MAX_MS = 15000


async def revision(db):
    """Current observation revision. A one-document read, but it runs right
    after a heavy aggregation and the database may still be busy: with a
    2 s limit it timed out on production and turned a finished 30 s rebuild
    into price_query_timeout. One retry, generous limit."""
    last = None
    # A background rebuild may wait as long as its own queries do.
    attempts, limit = (3, max(REVISION_READ_MAX_MS, query_max_ms())) if in_background() else (2, REVISION_READ_MAX_MS)
    for attempt in range(attempts):
        try:
            doc = await db.data_versions.find_one({"_id": "observations"}, {"_id": 0, "revision": 1},
                                                  max_time_ms=limit)
            return (doc or {}).get("revision", 0)
        except PyMongoError as exc:
            last = exc
            if not getattr(exc, "timeout", False) or attempt == attempts - 1:
                raise
            await asyncio.sleep(1)
    raise last


def valid(doc, source_revision, max_age, now):
    if not doc or doc.get("cache_schema") != SCHEMA or doc.get("source_revision") != source_revision:
        return False
    computed, until = aware(doc.get("computed_at")), aware(doc.get("valid_until"))
    ds = doc.get("dataset")
    return bool(computed and until and 0 <= (now-computed).total_seconds() < max_age and now < until
                and isinstance(ds, dict) and isinstance(ds.get("rows"), list)
                and ds.get("total") == len(ds["rows"]) and "kpis" in ds and "categories" in ds)


async def compute_dataset(db, compute, max_age=300, tolerate_race=False):
    """Reject revision races rather than bless mixed-version or expired prices.

    `tolerate_race` (background rebuilds only): crawls store prices for hours
    a day and every stored price bumps the revision, so a strict rebuild never
    completed while a crawl ran (12 Oct 2026). The result is then kept, stamped
    with the revision read BEFORE the compute: it can never pass for the
    current revision and is only ever served as a labelled previous result."""
    started = utcnow()
    before = await revision(db)
    dataset = await compute()
    if not tolerate_race and await revision(db) != before:
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
            "stale": source == PREVIOUS_REVISION, "valid_until": aware(doc["valid_until"]).isoformat()}


# A complete result computed for an earlier observation revision. Every stored
# competitor price bumps the revision, so while crawls run (hours a day) the
# strict check found no valid entry and every page answered "being prepared"
# (12 Oct 2026). Such a result is still served — whole, never partial, inside
# its age limit and its own pricing-freshness horizon (valid_until) — labelled
# stale with its computed_at, while the current revision rebuilds.
PREVIOUS_REVISION = "cache_previous_revision"


def usable_previous(doc, max_age, now):
    return bool(doc) and valid(doc, doc.get("source_revision"), max_age, now)


def previous_key_pattern(key):
    """Same build, policy and window on any KSA day: keys end ':YYYY-MM-DD:days=N'."""
    import re
    prefix, _day, window = key.rsplit(":", 2)
    return "^" + re.escape(prefix + ":") + r"\d{4}-\d{2}-\d{2}" + re.escape(":" + window) + "$"


def _size_of(doc):
    from bson import BSON
    from fastapi.encoders import jsonable_encoder
    return len(BSON.encode(jsonable_encoder(doc)))


def _remember(entries, key, doc, size=None):
    # A cache budget is NOT a result cap: oversized datasets are returned whole.
    size = _size_of(doc) if size is None else size
    if size > MAX_CACHE_BYTES:
        return
    entries.pop(key, None)
    while entries and (len(entries) >= MAX_ENTRIES or sum(v[1] for v in entries.values())+size > MAX_CACHE_BYTES):
        entries.popitem(last=False)
    entries[key] = (doc, size)


async def _serve(db, key, compute, max_age, on_stale=None):
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

    previous_day = [False]

    async def load():
        try:
            doc = await asyncio.wait_for(db.dashboard_cache.find_one({"key": key}, {"_id": 0, "payload_zlib": 0}, max_time_ms=2000), 2.5)
            if doc is None and on_stale is not None:
                # An earlier KSA day's entry: its sales window differs from
                # today's, so it is only ever served as a labelled previous result.
                previous_day[0] = True
                doc = await asyncio.wait_for(db.dashboard_cache.find_one(
                    {"key": {"$regex": previous_key_pattern(key)}}, {"_id": 0, "payload_zlib": 0},
                    sort=[("computed_at", -1)], max_time_ms=2000), 2.5)
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
        if previous_day[0] or not valid(doc, source_revision, max_age, utcnow()):
            if on_stale is not None and usable_previous(doc, max_age, utcnow()):
                on_stale()
                return doc, PREVIOUS_REVISION
            doc = envelope(await compute_dataset(db, compute, max_age))
            source = "live_fallback"
        elif await revision(db) != source_revision:
            raise unavailable("price_source_changed")
        _remember(entries, scoped_key, doc, size=await asyncio.to_thread(_size_of, doc))
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


async def serve(db, key, compute, max_age=300, cacheable=True, on_stale=None):
    """`on_stale`: when given, a complete result for an earlier revision is
    served (labelled stale) and `on_stale()` is called to start the rebuild;
    without it a revision change is a miss, as before."""
    if cacheable:
        return await bounded_read(_serve(db, key, compute, max_age, on_stale))
    dataset = await bounded_read(compute_dataset(db, compute, max_age))
    return dataset, metadata(envelope(dataset), "live_uncacheable")