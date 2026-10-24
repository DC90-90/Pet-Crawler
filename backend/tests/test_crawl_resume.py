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


def test_store_locks_of_stopped_processes_are_freed_live_ones_kept():
    """23 Oct 2026: a Republish killed Zarafa's crawl; its store lock outlived
    the process and the resume 2.5 minutes after boot was deferred."""
    import job_control
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    client = AsyncIOMotorClient(_loopback_mongo_url())
    db = client["fd_" + uuid.uuid4().hex]

    async def scenario():
        try:
            later = datetime.now(timezone.utc) + timedelta(minutes=8)
            await db.job_leases.insert_many([
                {"_id": "store:zarafa", "owner": "aaaaaaaaaaaa:1234abcd", "expires_at": later},   # dead process
                {"_id": "store:lana", "owner": "bbbbbbbbbbbb:1234abcd", "expires_at": later},     # live process
                {"_id": "store:old", "owner": str(uuid.uuid4()), "expires_at": later},            # old owner form
                {"_id": "cache-rebuild", "owner": "aaaaaaaaaaaa:1234abcd", "expires_at": later}])  # not a store
            freed = await job_control.free_dead(db, {"bbbbbbbbbbbb"})
            left = sorted(d["_id"] for d in await db.job_leases.find({}, {"_id": 1}).to_list(10))
            return freed, left
        finally:
            await client.drop_database(db.name)
            client.close()

    freed, left = asyncio.run(scenario())
    assert freed == 1 and left == ["cache-rebuild", "store:lana", "store:old"]
    import process_watch
    assert job_control.process_owner().startswith(process_watch.BOOT_ID + ":")


def test_a_resume_refused_by_a_lock_is_tried_once_more(monkeypatch):
    import server
    import job_control
    import process_watch
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    client = AsyncIOMotorClient(_loopback_mongo_url())
    db = client["rr_" + uuid.uuid4().hex]
    calls = []

    async def fake_crawl(db_, store, trigger="x"):
        calls.append(store["id"])
        if len(calls) == 1:
            await db.crawl_attempts.insert_one({"_id": uuid.uuid4().hex, "store_id": store["id"], "trigger": trigger,
                                                "started_at": datetime.now(timezone.utc), "status": "deferred"})
            return {"status": "deferred", "error": "store_job_already_running"}
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
            monkeypatch.setattr(job_control, "LEASE_TTL", timedelta(seconds=-29.9))
            await db.stores.insert_one({"id": "zarafa", "name": "Zarafa", "is_active": True})
            await db.crawl_attempts.insert_one({"_id": uuid.uuid4().hex, "store_id": "zarafa", "trigger": "schedule",
                                                "boot_id": "dead", "started_at": datetime.now(timezone.utc) - timedelta(minutes=5),
                                                "status": "running"})
            await server._resume_cut_off_crawls(delay_secs=0)
        finally:
            await client.drop_database(db.name)
            client.close()

    asyncio.run(scenario())
    assert calls == ["zarafa", "zarafa"]


def test_a_store_whose_crawl_never_started_is_caught_up(monkeypatch):
    """23 Oct 2026: four stores queued behind Zarafa and Petsy when a Republish
    killed the process; they left no attempt and nothing crawled them."""
    import server
    import ledger
    import process_watch
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    now = datetime.now(timezone.utc)
    since = ledger.ksa_midnight_utc(ledger.ksa_day_str(now))
    past = max(since + timedelta(minutes=1), now - timedelta(minutes=40))
    if now - past < timedelta(minutes=16):
        return                                  # just after KSA midnight: no slot has passed yet today
    future = now + timedelta(hours=1)
    client = AsyncIOMotorClient(_loopback_mongo_url())
    db = client["cu_" + uuid.uuid4().hex]
    crawled = []

    async def fake_crawl(db_, store, trigger="x"):
        crawled.append((store["id"], trigger))
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
            monkeypatch.setattr(server, "DAILY_CRAWL_BY_DOMAIN", {
                "missed.sa": (past.hour, past.minute), "crawled.sa": (past.hour, past.minute),
                "running.sa": (past.hour, past.minute), "later.sa": (future.hour, future.minute)})
            for sid in ("missed", "crawled", "running", "later"):
                await db.stores.insert_one({"id": sid, "name": sid, "domain": sid + ".sa", "is_active": True})
            await db.stores.insert_one({"id": "off", "name": "off", "domain": "missed.sa", "is_active": False})
            await db.crawl_attempts.insert_many([
                {"_id": uuid.uuid4().hex, "store_id": "crawled", "trigger": "schedule", "boot_id": "live-boot",
                 "started_at": now - timedelta(minutes=10), "status": "complete", "products_found": 9},
                {"_id": uuid.uuid4().hex, "store_id": "running", "trigger": "schedule", "boot_id": "live-boot",
                 "started_at": now - timedelta(minutes=10), "status": "running"}])
            await server._resume_cut_off_crawls(delay_secs=0)
        finally:
            await client.drop_database(db.name)
            client.close()

    asyncio.run(scenario())
    ids = [c[0] for c in crawled]
    assert ("missed", "resume") in crawled
    assert not {"crawled", "running", "off"} & set(ids)        # done today, crawling now, inactive
    if future.date() == now.date():
        assert "later" not in ids                               # its slot has not come yet
