"""Stored stale-while-revalidate cache for slow, read-only API answers.

Discounts and the Scanner recomputed from the price snapshots every 60 s
(`ttl_cache(60)`): 8-14 s on almost every visit, per process, lost on every
restart (15 Oct 2026). Their inputs change once a night. An answer is now kept
in `api_cache` (shared by every backend process, survives restarts) and in a
per-process memo:

* younger than `fresh_secs`   -> served as is;
* older, up to `max_stale_secs` -> served at once, refreshed in the background
  (one refresh per key per process);
* missing                     -> computed on the request (once per key, shared
  by concurrent callers) and stored.

Answers are stored as JSON text, so any key or value shape is safe.
"""
import asyncio
import functools
import inspect
import json
import logging
import time

from fastapi.encoders import jsonable_encoder

logger = logging.getLogger(__name__)

COLLECTION = "api_cache"
MAX_STALE_SECS = 7 * 24 * 3600
SKIP_PARAMS = {"user", "_", "request", "response", "db"}
_memo = {}          # key -> (value, computed_ts)
_inflight = {}      # key -> asyncio.Task
_errors = {}        # key -> last failure (this process)


def _encode(value):
    return json.dumps(jsonable_encoder(value), ensure_ascii=False)


async def _compute_and_store(db, key, compute):
    # Runs as background work: the request read budget (15-20 s) made the
    # Discounts query fail outright under load (15 Oct 2026). A visitor waits
    # for this only on the first visit ever; everyone else gets the stored copy.
    from price_read_limits import _background
    token = _background.set(True)
    started = time.time()
    try:
        value = await compute()
    except BaseException as exc:
        _errors[key] = {"at": time.time(), "after_s": round(time.time() - started, 1),
                        "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
        logger.warning("[ApiCache] compute failed for %s", key, exc_info=True)
        raise
    finally:
        _background.reset(token)
    _errors.pop(key, None)
    text = await asyncio.to_thread(_encode, value)
    now = time.time()
    clean = json.loads(text)
    _memo[key] = (clean, now)
    try:
        await db[COLLECTION].replace_one({"_id": key}, {"_id": key, "json": text, "computed_ts": now}, upsert=True)
    except Exception:  # noqa: BLE001 — the answer is still served from memory
        logger.warning("[ApiCache] store failed for %s", key, exc_info=True)
    return clean


def _log_failure(task):
    if not task.cancelled() and task.exception() is not None:
        logger.warning("[ApiCache] background refresh failed: %r", task.exception())


def _single_flight(db, key, compute):
    task = _inflight.get(key)
    if task is None or task.done():
        task = asyncio.get_running_loop().create_task(_compute_and_store(db, key, compute))
        task.add_done_callback(lambda t, k=key: _inflight.pop(k, None) if _inflight.get(k) is t else None)
        _inflight[key] = task
    return task


async def get(db, key, compute, fresh_secs, max_stale_secs=MAX_STALE_SECS):
    now = time.time()
    hit = _memo.get(key)
    if hit is None:
        try:
            doc = await db[COLLECTION].find_one({"_id": key})
        except Exception:  # noqa: BLE001
            doc = None
        if doc and doc.get("json"):
            hit = (json.loads(doc["json"]), float(doc.get("computed_ts") or 0))
            _memo[key] = hit
    if hit is not None:
        age = now - hit[1]
        if age < fresh_secs:
            return hit[0]
        if age < max_stale_secs:
            if key not in _inflight:                           # refresh for the next visitor
                _single_flight(db, key, compute).add_done_callback(_log_failure)
            return hit[0]
    return await asyncio.shield(_single_flight(db, key, compute))


def stored(fresh_secs, db_getter, key_prefix=""):
    """Decorator for endpoint handlers: cache by the non-dependency arguments."""
    def decorator(func):
        sig = inspect.signature(func)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            bound = sig.bind_partial(*args, **kwargs)
            parts = [key_prefix or func.__name__] + [f"{k}={v!r}" for k, v in sorted(bound.arguments.items())
                                                     if k not in SKIP_PARAMS]
            return await get(db_getter(), "|".join(parts), lambda: func(*args, **kwargs), fresh_secs)
        return wrapper
    return decorator


def clear_memo():
    _memo.clear()


async def status(db):
    """Stored answers (age) and this process's last failures, for the admin."""
    now = time.time()
    stored = [{"key": d["_id"], "age_s": round(now - float(d.get("computed_ts") or 0)), "bytes": len(d.get("json") or "")}
              async for d in db[COLLECTION].find({}, {"_id": 1, "computed_ts": 1, "json": 1})]
    return {"stored": sorted(stored, key=lambda r: r["key"]),
            "failures": [{"key": k, **v, "age_s": round(now - v["at"])} for k, v in _errors.items()],
            "inflight": sorted(_inflight)}
