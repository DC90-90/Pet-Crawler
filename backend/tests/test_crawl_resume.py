"""Crawls a restart cut off run again after boot, one at a time, never for a
store already crawled today and never more than CRAWL_RESUME_MAX_PER_DAY times
(16 Oct 2026: Zarafa and Hamtaro were cut off on 15 and 16 Oct and nothing
crawled them again). Also: the KSA-midnight helper My Products' date filters
call exists."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_ksa_midnight_utc_is_21h_utc_the_day_before():
    import ledger
    assert ledger.ksa_midnight_utc("2026-10-16") == datetime(2026, 10, 15, 21, 0, tzinfo=timezone.utc)


def test_cut_off_crawls_resume_once_each_and_skip_done_stores(monkeypatch):
    import server
    import process_watch
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    client = AsyncIOMotorClient(_loopback_mongo_url())
    db = client["cr_" + uuid.uuid4().hex]
    crawled, running, peak = [], [0], [0]

    async def fake_crawl(db_, store, trigger="x"):
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        await asyncio.sleep(0.05)
        crawled.append((store["id"], trigger))
        await db.crawl_attempts.insert_one({"_id": uuid.uuid4().hex, "store_id": store["id"], "trigger": trigger,
                                            "started_at": datetime.now(timezone.utc), "status": "complete",
                                            "products_found": 10})
        running[0] -= 1
        return {"products_found": 10}

    async def noop(*a, **k):
        return None

    async def alive(db_, within=None):
        return {"live-boot"}

    async def scenario():
        try:
            monkeypatch.setattr(server, "db", db)
            monkeypatch.setattr(server, "crawl_store_waterfall", fake_crawl)
            monkeypatch.setattr(server, "_recompute_store_metrics", noop)
            monkeypatch.setattr(server, "maybe_recompute_dashboard_cache", noop)
            monkeypatch.setattr(server, "maybe_recompute_page_caches", noop)
            monkeypatch.setattr(server, "cache_clear", lambda *a, **k: None)
            monkeypatch.setattr(process_watch, "alive_boot_ids", alive)
            now = datetime.now(timezone.utc)
            for sid in ("cut", "cut2", "done", "alive", "capped"):
                await db.stores.insert_one({"id": sid, "name": sid, "is_active": True})
            attempts = [("cut", "dead", "running"), ("cut2", "dead", "running"),
                        ("done", "dead", "running"), ("done", "live-boot", "complete"),
                        ("alive", "live-boot", "running"),
                        ("capped", "dead", "running"), ("capped", "dead", "partial"), ("capped", "dead", "partial")]
            for sid, boot, status in attempts:
                await db.crawl_attempts.insert_one({"_id": uuid.uuid4().hex, "store_id": sid, "trigger": "schedule",
                                                    "boot_id": boot, "started_at": now - timedelta(minutes=5),
                                                    "status": status, "products_found": 5 if status == "complete" else None})
            await server._resume_cut_off_crawls(delay_secs=0)
            marked = await db.crawl_attempts.count_documents({"status": "cut_off_by_restart"})
            return marked
        finally:
            await client.drop_database(db.name)
            client.close()

    marked = asyncio.run(scenario())
    assert marked == 4                                   # cut, cut2, done, capped: dead boots
    assert sorted(crawled) == [("cut", "resume"), ("cut2", "resume")]   # done: crawled; capped: 3 attempts
    assert peak[0] == 1
