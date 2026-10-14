"""Per-process heartbeat: why do production processes restart?

Production restarted every few hours (12-13 Oct 2026: ~10:10, ~17:10, ~05:11,
~07:00 UTC) and the platform's logs are not reachable. Every minute each
process records its memory (own RSS, peak RSS, container cgroup usage and
limit) and its event-loop lag (how late a 1 s timer fires; a long stall fails
the platform's health checks). After a restart, the last heartbeat of the dead
process shows what it looked like just before it died.
"""
import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

BOOT_ID = uuid.uuid4().hex[:12]
STARTED_AT = datetime.now(timezone.utc)
HEARTBEAT_SECS = 60
_state = {"max_lag_ms": 0.0, "last_lag_ms": 0.0, "peak_rss_mb": None, "spikes": [], "extra": None}
SPIKE_MS = 2000      # a stall this long is recorded with what was running
MAX_SPIKES = 20
_task = None


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _proc_status_mb(field):
    text = _read("/proc/self/status")
    if not text:
        return None
    for line in text.splitlines():
        if line.startswith(field + ":"):
            try:
                return round(int(line.split()[1]) / 1024, 1)   # kB -> MB
            except (IndexError, ValueError):
                return None
    return None


def _cgroup_mb(*paths):
    for path in paths:
        raw = _read(path)
        if raw is None:
            continue
        raw = raw.strip()
        if raw == "max":
            return None
        try:
            return round(int(raw) / (1024 * 1024), 1)
        except ValueError:
            continue
    return None


def memory():
    return {
        "rss_mb": _proc_status_mb("VmRSS"),
        "peak_rss_mb": _proc_status_mb("VmHWM"),
        "cgroup_used_mb": _cgroup_mb("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"),
        "cgroup_limit_mb": _cgroup_mb("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    }


async def _lag_probe():
    """How late a 1 s sleep wakes up: the event loop's responsiveness."""
    while True:
        started = time.perf_counter()
        await asyncio.sleep(1)
        lag = (time.perf_counter() - started - 1) * 1000
        _state["last_lag_ms"] = round(lag, 1)
        _state["max_lag_ms"] = max(_state["max_lag_ms"], round(lag, 1))
        if lag >= SPIKE_MS:
            # Recorded after the stall ends: what the process was doing then
            # (rebuild step, running crawls) points at the code that blocked.
            context = {}
            try:
                context = (_state["extra"] or (lambda: {}))() or {}
            except Exception:  # noqa: BLE001
                pass
            _state["spikes"].append({"at": datetime.now(timezone.utc), "lag_ms": round(lag, 1), **context})
            del _state["spikes"][:-MAX_SPIKES]


async def _beat(db, extra):
    while True:
        try:
            now = datetime.now(timezone.utc)
            doc = {"boot_id": BOOT_ID, "pid": os.getpid(), "started_at": STARTED_AT, "last_at": now,
                   **memory(), "loop_lag_ms": _state["last_lag_ms"], "max_loop_lag_ms": _state["max_lag_ms"],
                   "lag_spikes": list(_state["spikes"])}
            try:
                doc.update(extra() or {})
            except Exception:  # noqa: BLE001 — the heartbeat never fails on its extras
                pass
            await db.process_heartbeats.update_one({"_id": BOOT_ID}, {"$set": doc}, upsert=True)
        except Exception:  # noqa: BLE001
            logger.warning("[ProcessWatch] heartbeat write failed", exc_info=True)
        await asyncio.sleep(HEARTBEAT_SECS)


def start(db, extra=None):
    global _task
    if _task is not None and not _task.done():
        return
    loop = asyncio.get_running_loop()
    _state["extra"] = extra
    loop.create_task(_lag_probe())
    _task = loop.create_task(_beat(db, extra or (lambda: {})))


async def alive_boot_ids(db, within=timedelta(minutes=3)):
    since = datetime.now(timezone.utc) - within
    return {d["_id"] async for d in db.process_heartbeats.find({"last_at": {"$gte": since}}, {"_id": 1})}


async def history(db, limit=20):
    rows = await db.process_heartbeats.find({}, {"_id": 0}).sort("started_at", -1).to_list(limit)
    now = datetime.now(timezone.utc)
    for r in rows:
        last = r.get("last_at")
        if isinstance(last, datetime) and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        started = r.get("started_at")
        if isinstance(started, datetime) and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        r["alive"] = bool(last and now - last < timedelta(minutes=3))
        r["lived_minutes"] = round((last - started).total_seconds() / 60, 1) if last and started else None
    return rows
