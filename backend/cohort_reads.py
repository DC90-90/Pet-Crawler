"""Complete, store-partitioned cohort reads using existing indexes only.

All partitions share the caller's deadline. No rows escape before ALL reads
succeed; ambiguous global grouping falls back to the original Mongo pipeline.
"""
import asyncio
import logging
import time
from weakref import WeakKeyDictionary

from pymongo.errors import PyMongoError

from price_read_limits import close_read_cursor, read_budget_expired
from read_plan_policy import safe_name
from snapshot_strategy import safe_store_index, selected_hint, failed_hint, completed_hint

logger = logging.getLogger(__name__)
MAX_PARALLEL_READS = 2
_gates = WeakKeyDictionary()


def _gate():
    loop = asyncio.get_running_loop()
    if loop not in _gates:
        _gates[loop] = asyncio.Semaphore(MAX_PARALLEL_READS)
    return _gates[loop]


async def _partition_index(db):
    """Never hint an incomplete index or split non-simple collation groups."""
    try:
        indexes, options = await asyncio.wait_for(asyncio.gather(
            db.product_snapshots.index_information(),
            db.product_snapshots.options()), timeout=2)
        collation = options.get("collation")
        if collation and collation.get("locale") != "simple":
            return None
        return next((name for name, spec in indexes.items()
                     if name == safe_name(name) and safe_store_index(spec)), None)
    except Exception as exc:
        logger.warning("COHORT_PARTITION_METADATA_UNAVAILABLE %s", type(exc).__name__)
        return None


async def _query(db, pipeline, max_time_ms, hint=None, *, legacy=False):
    from read_diagnostics import capture_after_timeout
    cursor = None
    started = time.perf_counter()
    async with _gate():
        try:
            options = {"hint": hint} if hint else {}
            cursor = db.product_snapshots.aggregate(pipeline, allowDiskUse=True,
                maxTimeMS=max_time_ms, **options).batch_size(2000)
            rows = [row async for row in cursor]
        except (PyMongoError, TimeoutError, asyncio.CancelledError) as exc:
            timed_out = not isinstance(exc, asyncio.CancelledError) or read_budget_expired()
            if legacy and timed_out:
                failed_hint(db, hint)
            if not isinstance(exc, PyMongoError) or exc.timeout:
                capture_after_timeout(db, "cohort", pipeline, applied_hint=hint,
                                      confirmed_timeout=timed_out)
            raise
        finally:
            if cursor is not None:
                await close_read_cursor(cursor)
    if legacy:
        completed_hint(db, hint, (time.perf_counter()-started)*1000)
    return rows


def _independent_groups(partitions):
    """Null/missing offer IDs use (store, SKU); strings must be store-unique.

Mongo handles collisions, numeric/BSON IDs and collation in the legacy path;
do not approximate its grouping/min/max rules with Python comparisons.
"""
    seen = set()
    for rows in partitions:
        for row in rows:
            oid = row.get("offer_id")
            if oid is None:
                continue
            if not isinstance(oid, str) or oid in seen:
                return False
            seen.add(oid)
    return True


async def read_cohort_snapshots(db, active, now, pipeline_factory, *, max_time_ms):
    """The pipeline/history is unchanged; only store scope is partitioned."""
    async def legacy():
        return await _query(db, pipeline_factory(active, now), max_time_ms,
                            await selected_hint(db), legacy=True)

    if not active:
        return []
    if any(not isinstance(sid, str) for sid in active):
        return await legacy()
    active = list(dict.fromkeys(active))
    if len(active) == 1:
        return await legacy()
    hint = await _partition_index(db)
    if not hint:
        return await legacy()

    started = time.perf_counter()
    partitions = [None] * len(active)
    pending = iter(enumerate(active))

    async def worker():
        for position, sid in pending:
            partitions[position] = await _query(
                db, pipeline_factory([sid], now), max_time_ms, hint)

    tasks = [asyncio.create_task(worker()) for _ in range(min(MAX_PARALLEL_READS, len(active)))]
    try:
        await asyncio.gather(*tasks)
    finally:
        # gather doesn't cancel siblings on a child's failure. Explicitly drain
        # them so a failed HTTP request cannot leave queued partition work.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    if not _independent_groups(partitions):
        logger.info("COHORT_PARTITION_LEGACY_GROUPING")
        return await legacy()
    rows = [row for partition in partitions for row in partition]
    logger.info("COHORT_PARTITION_COMPLETED stores=%d rows=%d elapsed_ms=%.1f",
                len(active), len(rows), (time.perf_counter()-started)*1000)
    return rows