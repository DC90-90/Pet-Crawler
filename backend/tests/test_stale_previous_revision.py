"""While crawls store prices the observation revision moves every few seconds.
Pages serve the last complete result, labelled stale with its time, and
rebuild in the background; background rebuilds keep results computed during
a crawl stamped with the revision read before them (12 Oct 2026)."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import my_products_cache as mpc  # noqa: E402
from price_read_limits import bounded_read  # noqa: E402


def _client():
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    return AsyncIOMotorClient(_loopback_mongo_url())


def _dataset(rev, now, rows=2):
    return {"rows": [{"sku": f"S{i}"} for i in range(rows)], "total": rows, "kpis": {}, "categories": [],
            "_source_revision": rev, "_computed_at": now, "_valid_until": now + timedelta(hours=2)}


KEY = "my_products:my-products-read-v1:pv:abcdef123456:{day}:days=30"


def test_previous_key_pattern_matches_any_day_and_build_same_window():
    import re
    pat = re.compile(mpc.previous_key_pattern(KEY.format(day="2026-10-12")))
    assert pat.match(KEY.format(day="2026-10-11"))
    assert pat.match(KEY.format(day="2026-10-11").replace("abcdef123456", "000000000000"))   # the last Republish
    assert not pat.match(KEY.format(day="2026-10-11").replace("days=30", "days=7"))
    assert not pat.match(KEY.format(day="2026-10-11").replace(":pv:", ":pv2:"))                # another price policy
    assert not pat.match(KEY.format(day="2026-10-11").replace("read-v1", "read-v2"))           # another schema


def test_compute_dataset_tolerates_a_race_only_when_asked():
    class _Versions:
        def __init__(self):
            self.rev = 10

        async def find_one(self, q, proj=None, max_time_ms=None):
            return {"revision": self.rev}

    class _DB:
        data_versions = _Versions()

    db = _DB()

    async def compute():
        db.data_versions.rev += 3          # a crawl stores prices meanwhile
        return {"rows": [], "_valid_until": datetime.now(timezone.utc) + timedelta(hours=1)}
    with pytest.raises(Exception) as exc:
        asyncio.run(mpc.compute_dataset(db, compute, max_age=600))
    assert exc.value.detail["code"] == "price_source_changed"
    ds = asyncio.run(mpc.compute_dataset(db, compute, max_age=600, tolerate_race=True))
    assert ds["_source_revision"] == 13      # read before this compute (10 + 3 from the first run)


def test_previous_revision_served_stale_and_rebuild_requested():
    async def scenario():
        client = _client()
        db = client["stale_" + uuid.uuid4().hex]
        try:
            now = datetime.now(timezone.utc)
            day = "2026-10-12"
            await db.data_versions.insert_one({"_id": "observations", "revision": 50})
            await db.dashboard_cache.insert_one({"key": KEY.format(day=day), **mpc.envelope(_dataset(42, now - timedelta(minutes=5)))})
            computed, stale_calls = [], []

            async def compute():
                computed.append(1)
                raise AssertionError("must not compute on the request path")

            ds, meta = await mpc.serve(db, KEY.format(day=day), compute, max_age=6 * 3600,
                                       on_stale=lambda: stale_calls.append(1))
            assert ds["total"] == 2 and meta["source"] == mpc.PREVIOUS_REVISION and meta["stale"] is True
            assert stale_calls == [1] and computed == []
            # Strict callers (no on_stale) still treat the revision change as a miss.
            with pytest.raises(AssertionError):
                await mpc.serve(db, KEY.format(day=day), compute, max_age=6 * 3600)
            # Too old for the age limit → not served.
            await db.dashboard_cache.update_one({"key": KEY.format(day=day)},
                                                {"$set": {"computed_at": now - timedelta(hours=7)}})
            with pytest.raises(AssertionError):
                await mpc.serve(db, KEY.format(day=day), compute, max_age=6 * 3600, on_stale=lambda: None)
        finally:
            await client.drop_database(db.name)
            client.close()
    asyncio.run(bounded_read(scenario()))


def test_previous_day_entry_is_stale_even_at_the_same_revision():
    async def scenario():
        client = _client()
        db = client["staleday_" + uuid.uuid4().hex]
        try:
            now = datetime.now(timezone.utc)
            await db.data_versions.insert_one({"_id": "observations", "revision": 42})
            await db.dashboard_cache.insert_one({"key": KEY.format(day="2026-10-11"), **mpc.envelope(_dataset(42, now - timedelta(minutes=30)))})
            calls = []

            async def compute():
                raise AssertionError("must not compute")
            ds, meta = await mpc.serve(db, KEY.format(day="2026-10-12"), compute, max_age=6 * 3600,
                                       on_stale=lambda: calls.append(1))
            assert meta["stale"] is True and calls == [1] and ds["total"] == 2
        finally:
            await client.drop_database(db.name)
            client.close()
    asyncio.run(bounded_read(scenario()))


def _server():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "test_stale_previous")
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    from cryptography.fernet import Fernet
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import server
    return server


def test_page_cache_serves_previous_entry_under_the_rebuild_policy(monkeypatch):
    server = _server()

    async def scenario():
        client = _client()
        db = client["stalepage_" + uuid.uuid4().hex]
        try:
            await db.data_versions.insert_one({"_id": "observations", "revision": 7})
            payload = {"rows": [1, 2, 3], "kpis": {"x": 1}}
            base = "market-share/dataset:" + await server._default_scope_id(db)
            await server._store_page_cache(db, base, 30, payload)
            await db.data_versions.update_one({"_id": "observations"}, {"$inc": {"revision": 9}})
            starts = []
            monkeypatch.setattr(server, "_schedule_cache_rebuild", lambda **kw: starts.append(kw) or True)

            async def compute():
                raise AssertionError("must not compute on the request path")
            monkeypatch.setattr(server, "CACHE_MISS_POLICY", "rebuild")
            body, meta = await server._serve_page_cache(db, base, 30, compute)
            assert body == payload and meta["stale"] is True and meta["source"] == "cache_previous_revision"
            assert starts and starts[0]["trigger"] == "stale_serve" and starts[0]["min_gap_secs"] > 0
            # Live policy keeps the strict behaviour (computes).
            monkeypatch.setattr(server, "CACHE_MISS_POLICY", "live")

            async def live():
                return {"live": True}
            body, meta = await server._serve_page_cache(db, base, 30, live)
            assert body == {"live": True}
        finally:
            await client.drop_database(db.name)
            client.close()
    asyncio.run(scenario())


def test_page_cache_is_stamped_with_the_revision_read_before_the_compute():
    server = _server()

    async def scenario():
        client = _client()
        db = client["stamp_" + uuid.uuid4().hex]
        try:
            await db.data_versions.insert_one({"_id": "observations", "revision": 3})
            before = await db.data_versions.find_one({"_id": "observations"})
            await db.data_versions.update_one({"_id": "observations"}, {"$inc": {"revision": 1}})
            await server._store_page_cache(db, "insights/summary", 7, {"a": 1}, revision=before)
            head = await db.dashboard_cache.find_one({"key": server._page_cache_key("insights/summary", 7)})
            return head["source_revision"]
        finally:
            await client.drop_database(db.name)
            client.close()
    assert asyncio.run(scenario()) == 3


def test_stale_rebuilds_respect_the_minimum_gap(monkeypatch):
    server = _server()
    monkeypatch.setattr(server, "_CACHE_REBUILD_TASK", None)
    monkeypatch.setitem(server._CACHE_REBUILD_STATE, "finished_at", datetime.now(timezone.utc).isoformat())
    assert server._schedule_cache_rebuild(trigger="stale_serve", min_gap_secs=300) is False
