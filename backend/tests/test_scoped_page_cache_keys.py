"""The rebuild stores Market Share and the Price Intel dashboard under the same
scoped key the request path reads (12 Oct 2026: the request looked up
'market-share/dataset:<scope_id>', the rebuild wrote 'market-share/dataset',
so those pages never found a cache entry)."""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _server():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "test_scoped_keys")
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    from cryptography.fernet import Fernet
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import server
    return server


def test_rebuilt_entries_are_found_by_the_request_path(monkeypatch):
    server = _server()
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["scoped_" + uuid.uuid4().hex]
        try:
            await db.stores.insert_many([
                {"id": "own", "name": "Own", "is_own_store": True, "is_active": True},
                {"id": "c1", "name": "C1", "is_active": True},
                {"id": "c2", "name": "C2", "is_active": True},
            ])
            await db.data_versions.insert_one({"_id": "observations", "revision": 4})
            computed = []

            async def ms(db_, d):
                computed.append(("ms", d))
                return {"window": d, "my_products": [], "missing_products": []}

            async def intel(db_):
                computed.append(("intel", None))
                return {"intel": True}
            monkeypatch.setattr(server, "_WINDOW_CACHE_SPECS", [("market-share/dataset:{scope}", ms)])
            monkeypatch.setattr(server, "_SINGLE_CACHE_SPECS", [("price-intel/dashboard:{scope}", intel)])
            await server.recompute_page_caches(db, windows=(30,))
            assert computed == [("ms", 30), ("intel", None)]

            async def must_not_compute():
                raise AssertionError("request path computed instead of reading the rebuilt cache")
            monkeypatch.setattr(server, "CACHE_MISS_POLICY", "rebuild")
            monkeypatch.setattr(server, "_market_share_compute", lambda *a, **k: must_not_compute())
            body, meta = await server._market_share_dataset(db, 30)
            assert body == {"window": 30, "my_products": [], "missing_products": []} and meta["source"] == "cache"
            from comparison_scope import resolve
            scope = await resolve(db, "all", None)
            body, meta = await server._serve_page_cache(db, "price-intel/dashboard:" + scope["scope_id"], None,
                                                        must_not_compute, True)
            assert body == {"intel": True} and meta["source"] == "cache"
        finally:
            await client.drop_database(db.name)
            client.close()
    asyncio.run(scenario())


def test_uncovered_views_are_built_on_demand_not_on_the_request(monkeypatch):
    """A competitor selection or 'include today' is not part of the standard
    rebuild: under the rebuild policy the request answers 'rebuilding' at once
    and one background build stores the entry; the next request is a hit."""
    server = _server()
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["ondemand_" + uuid.uuid4().hex]
        try:
            await db.stores.insert_many([
                {"id": "own", "name": "Own", "is_own_store": True, "is_active": True},
                {"id": "c1", "name": "C1", "is_active": True},
                {"id": "c2", "name": "C2", "is_active": True},
            ])
            await db.data_versions.insert_one({"_id": "observations", "revision": 1})
            monkeypatch.setattr(server, "CACHE_MISS_POLICY", "rebuild")
            full_rebuilds, computed = [], []
            monkeypatch.setattr(server, "_schedule_cache_rebuild", lambda *a, **k: full_rebuilds.append(1) or True)

            async def compute_ms(db_, days, include_today=False, comparison_mode="all", competitor_ids=None):
                computed.append((days, include_today, comparison_mode, competitor_ids))
                return {"days": days, "today": include_today, "mode": comparison_mode}
            monkeypatch.setattr(server, "_market_share_compute", compute_ms)
            from fastapi import HTTPException
            for kwargs in ({"include_today": True}, {"comparison_mode": "selected", "competitor_ids": "c1"}):
                try:
                    await server._market_share_dataset(db, 30, **kwargs)
                except HTTPException as exc:
                    assert exc.detail["code"] == "price_cache_rebuilding"
                else:
                    raise AssertionError("first request must not compute on the request path")
                for task in list(server._ON_DEMAND_TASKS.values()):
                    await task
                body, meta = await server._market_share_dataset(db, 30, **kwargs)
                assert meta["source"] == "cache"
            assert full_rebuilds == []                       # never the whole rebuild for these
            assert computed == [(30, True, "all", None), (30, False, "selected", "c1")]
        finally:
            server._ON_DEMAND_TASKS.clear()
            await client.drop_database(db.name)
            client.close()
    asyncio.run(scenario())
