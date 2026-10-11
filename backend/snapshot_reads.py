"""Deadline-bounded latest reads, with caller-specific compact projections.

No row cap, stale-result fallback or implicit historical window. Callers opt
into a time range only where their existing output already rejects older data.
"""
from price_read_limits import query_max_ms, bounded_read, close_read_cursor, read_budget_expired
import asyncio
from pymongo.errors import PyMongoError


def latest_pipeline(query, projection=None):
    pipeline = [{"$match": query}]
    if projection is not None:
        pipeline.append({"$project": {**projection, "_id": 0, "offer_id": 1, "crawled_at": 1}})
    return pipeline + [
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": "$offer_id", "row": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$row"}}, {"$project": {"_id": 0}},
    ]


async def complete_latest(db, pipeline):
    async def read():
        cursor = db.product_snapshots.aggregate(pipeline, allowDiskUse=True,
                    maxTimeMS=query_max_ms())
        try:
            return [row async for row in cursor]
        except (PyMongoError, TimeoutError, asyncio.CancelledError) as exc:
            if not isinstance(exc, PyMongoError) or exc.timeout:
                from read_diagnostics import capture_after_timeout
                capture_after_timeout(db, "latest", pipeline,
                                      confirmed_timeout=not isinstance(exc, asyncio.CancelledError) or read_budget_expired())
            raise
        finally:
            await close_read_cursor(cursor)
    return await bounded_read(read())