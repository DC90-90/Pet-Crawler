"""Every crawl attempt is recorded from start to finish (14 Oct 2026: eight
scheduled crawls left no trace)."""
import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_attempts_record_success_deferral_and_failure(monkeypatch):
    import crawlers
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    outcomes = iter([{"status": "complete", "products_found": 12, "snapshots_created": 10},
                     {"status": "deferred", "error": "store_job_already_running"},
                     RuntimeError("boom")])

    async def fake_attempt(db, store):
        nxt = next(outcomes)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
    monkeypatch.setattr(crawlers, "_crawl_store_waterfall_attempt", fake_attempt)

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["attempts_" + uuid.uuid4().hex]
        store = {"id": "s1", "name": "Store1"}
        try:
            await crawlers.crawl_store_waterfall(db, store, trigger="schedule")
            await crawlers.crawl_store_waterfall(db, store, trigger="schedule")
            with pytest.raises(RuntimeError):
                await crawlers.crawl_store_waterfall(db, store, trigger="backfill")
            return [r async for r in db.crawl_attempts.find({}, {"_id": 0}).sort("started_at", 1)]
        finally:
            await client.drop_database(db.name)
            client.close()
    rows = asyncio.run(scenario())
    assert [r["status"] for r in rows] == ["complete", "deferred", "failed"]
    assert [r["trigger"] for r in rows] == ["schedule", "schedule", "backfill"]
    assert rows[0]["products_found"] == 12 and rows[1]["error"] == "store_job_already_running"
    assert "boom" in rows[2]["error"] and all("finished_at" in r for r in rows)
