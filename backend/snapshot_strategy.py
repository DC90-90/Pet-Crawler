"""Transient, fail-closed physical-plan fallback after an actual read timeout.

Never builds indexes or changes a query's filters/history. Partial, sparse,
hidden and non-simple-collation indexes are never candidates.
"""
import asyncio
import logging
import time
from collections import OrderedDict
from weakref import WeakKeyDictionary
from release_database import GuardedDatabase
from read_plan_policy import safe_name

logger = logging.getLogger(__name__)
_loops = WeakKeyDictionary()
TTL_SECONDS = 300
STORE_TIME_KEYS = [("store_id", 1), ("crawled_at", -1)]


def safe_store_index(spec):
    collation = spec.get("collation")
    return (list(spec.get("key", [])) == STORE_TIME_KEYS
            and not spec.get("sparse") and "partialFilterExpression" not in spec
            and not spec.get("hidden")
            and (not collation or isinstance(collation, dict) and collation.get("locale") == "simple"))


def state(db):
    raw = db.raw if isinstance(db, GuardedDatabase) else db
    entries = _loops.setdefault(asyncio.get_running_loop(), OrderedDict())
    key = (id(raw.client), raw.name)
    if key not in entries:
        if len(entries) >= 32:
            entries.popitem(last=False)
        entries[key] = {"hint": None, "until": 0, "blocked": {}, "logged_success": False}
    entries.move_to_end(key)
    return entries[key]


def select_after_timeout(db, name):
    current = state(db)
    if current["blocked"].get(name, 0) > time.monotonic():
        return False
    current.update(hint=name, until=time.monotonic()+TTL_SECONDS, logged_success=False)
    return True


async def selected_hint(db):
    try:
        current = state(db)
    except Exception:
        return None
    name = current["hint"]
    if not name or current["until"] <= time.monotonic():
        current["hint"] = None
        return None
    try:
        indexes = await asyncio.wait_for(db.product_snapshots.index_information(), timeout=1)
        if name == safe_name(name) and name in indexes and safe_store_index(indexes[name]):
            return name
    except Exception:
        pass
    current["hint"] = None  # Metadata uncertainty must not force an incomplete index.
    return None


def failed_hint(db, name):
    if name:
        current = state(db)
        current["hint"] = None
        current["blocked"][name] = time.monotonic()+TTL_SECONDS
        logger.warning("ANALYTICS_READ_ALTERNATIVE_FAILED index=%s", safe_name(name))


def completed_hint(db, name, elapsed_ms):
    if name:
        current = state(db)
        current["until"] = time.monotonic()+TTL_SECONDS
        if not current["logged_success"]:
            logger.info("ANALYTICS_READ_ALTERNATIVE_COMPLETED index=%s elapsed_ms=%.1f", safe_name(name), elapsed_ms)
            current["logged_success"] = True