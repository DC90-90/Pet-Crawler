"""iter25 dashboard-cache tests — the cache must be a pure performance layer.

Central guarantee: a request served from db.dashboard_cache is BYTE-IDENTICAL
(in its computed values: kpis, products, total, categories) to the same request
computed live. Also covers: cacheability gating, 24h staleness fallback, and
that recompute populates all standard windows.

Runs in-process against a real Mongo/FerretDB on 127.0.0.1:27017.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_dashcache"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_dashcache"
import server  # noqa: E402
from fastapi.encoders import jsonable_encoder  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

USER = {"id": "t", "email": "t@t", "role": "super_admin"}
MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")


async def _seed(db):
    for c in ("stores", "my_products", "products", "product_snapshots", "product_matches",
              "own_store_orders", "dashboard_cache"):
        await db[c].drop()
    now = datetime.now(timezone.utc)
    own = "own"
    await db.stores.insert_many([
        {"id": own, "name": "Pets Houses", "domain": "pets-houses.com", "platform": "zid", "is_own_store": True, "is_active": True},
        {"id": "c1", "name": "Comp1", "domain": "c1.example", "platform": "salla", "is_active": True},
        {"id": "c2", "name": "Comp2", "domain": "c2.example", "platform": "zid", "is_active": True},
    ])
    skus = [f"BC{78000000000+i}" for i in range(40)]
    await db.my_products.insert_many([
        {"sku": s, "barcode": s, "name_ar": f"م{i}", "name_en": f"P{i}", "price": round(10+i*3.5, 2),
         "sale_price": None, "present_on_store": True, "is_own_store": True, "store_id": own,
         "first_seen_at": now - timedelta(days=60)}  # datetime field → exercises BSON round-trip
        for i, s in enumerate(skus)
    ])
    await db.products.insert_many([
        {"id": f"p{i}", "sku": s, "name_ar": f"م{i}", "name_en": f"P{i}", "brand": "", "category": "cat_food",
         "animal_type": "cat", "first_seen_at": (now - timedelta(days=60)).isoformat()}
        for i, s in enumerate(skus)
    ])
    await db.product_matches.insert_many([
        {"my_sku": s, "competitor_sku": s, "competitor_store_id": ("c1" if i % 2 else "c2"),
         "confidence": 99, "match_method": "barcode"} for i, s in enumerate(skus[:25])
    ])
    snaps = []
    for i, s in enumerate(skus):
        for store, sid in ((own, own), ("Comp1", "c1"), ("Comp2", "c2")):
            qty = 60
            for d in range(0, 90, 2):  # a snapshot every 2 days over 90d
                ts = now - timedelta(days=d, hours=1)
                qty = max(0, qty - 2)
                if qty <= 4:
                    qty += 40
                snaps.append({"id": f"{sid}-{s}-{d}", "sku": s, "store_id": sid, "store_name": store,
                              "price": round(10 + i*3.5 + (0 if sid == own else 2), 2),
                              "original_price": round(10 + i*3.5, 2), "discount_pct": 0,
                              "in_stock": qty > 0, "qty_available": qty, "sold_count": 0,
                              "source_tier": 0 if sid == own else 1,
                              "confidence_score": 99 if sid == own else 95,
                              "product_url": "", "crawled_at": ts})
    await db.product_snapshots.insert_many(snaps)


def _computed_only(resp):
    """The response minus the additive 'cache' meta, JSON-normalized like FastAPI."""
    r = {k: v for k, v in resp.items() if k != "cache"}
    return jsonable_encoder(r)


def _call(**kw):
    base = dict(days=30, on_date=None, date_from=None, date_to=None, category=None, animal_type=None,
                search=None, sort_by="revenue_est", sort_order="desc", limit=100, offset=0,
                own_only=True, user=USER)
    base.update(kw)
    return server.my_products(**base)


def test_cache_is_byte_identical_to_live_across_windows_sorts_pages():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        server.db = db
        await _seed(db)
        await server.recompute_dashboard_cache(db)

        combos = [
            dict(days=7), dict(days=14), dict(days=30), dict(days=90),
            dict(days=30, sort_by="my_price", sort_order="asc"),
            dict(days=90, sort_by="market_share_pct", sort_order="desc"),
            dict(days=30, limit=10, offset=20),
            dict(days=90, limit=5, offset=0, sort_by="qty_sold_est", sort_order="asc"),
        ]
        for combo in combos:
            resp_cache = await _call(**combo)
            assert resp_cache["cache"]["source"] == "cache", (combo, resp_cache["cache"])
            # Force live by wiping the cache; endpoint falls back to live compute.
            await db.dashboard_cache.delete_many({})
            resp_live = await _call(**combo)
            assert resp_live["cache"]["source"] == "live_fallback", (combo, resp_live["cache"])
            assert _computed_only(resp_cache) == _computed_only(resp_live), f"byte mismatch for {combo}"
            # live_fallback repopulated the cache — restore full cache for next combo
            await server.recompute_dashboard_cache(db)
        print("PASS: cache == live for", len(combos), "window/sort/page combos")
    asyncio.run(main())


def test_non_default_requests_bypass_cache():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        server.db = db
        await _seed(db)
        await server.recompute_dashboard_cache(db)
        # search, on_date, filters, own_only=False, and non-standard window must NOT use cache
        assert (await _call(search="P1"))["cache"]["source"] == "live_uncacheable"
        assert (await _call(on_date="2026-07-01"))["cache"]["source"] == "live_uncacheable"
        assert (await _call(category="cat_food"))["cache"]["source"] == "live_uncacheable"
        assert (await _call(own_only=False))["cache"]["source"] == "live_uncacheable"
        assert (await _call(days=45))["cache"]["source"] == "live_uncacheable"
        print("PASS: non-default requests bypass cache")
    asyncio.run(main())


def test_stale_cache_falls_back_to_live():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        server.db = db
        await _seed(db)
        await server.recompute_dashboard_cache(db)
        # Backdate the 30D cache doc beyond the 24h max age
        await db.dashboard_cache.update_one(
            {"key": server._dashboard_cache_key(30)},
            {"$set": {"computed_at": datetime.now(timezone.utc) - timedelta(hours=25)}},
        )
        resp = await _call(days=30)
        assert resp["cache"]["source"] == "live_fallback", resp["cache"]
        print("PASS: cache stale >24h → live fallback")
    asyncio.run(main())


def test_recompute_populates_all_windows():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        server.db = db
        await _seed(db)
        stats = await server.recompute_dashboard_cache(db)
        assert set(stats.keys()) == {7, 14, 30, 90}
        for w in (7, 14, 30, 90):
            doc = await db.dashboard_cache.find_one({"key": server._dashboard_cache_key(w)})
            assert doc and doc["window_days"] == w and isinstance(doc["dataset"], dict)
            assert doc["dataset"]["total"] == 40
        print("PASS: recompute populated all standard windows")
    asyncio.run(main())


if __name__ == "__main__":
    test_recompute_populates_all_windows()
    test_non_default_requests_bypass_cache()
    test_stale_cache_falls_back_to_live()
    test_cache_is_byte_identical_to_live_across_windows_sorts_pages()
    print("ALL DASHBOARD-CACHE TESTS PASSED")
