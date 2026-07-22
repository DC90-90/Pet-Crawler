"""iter27 (Feb 2026) — cache extension covers Insights + Price Intel.

Central guarantees for the new endpoints:
  1. Standard-window requests are served from db.dashboard_cache (source=="cache"
     for /insights/summary and /price-intel/dashboard; other insights endpoints
     don't expose a cache envelope but still read the persistent cache).
  2. Cache values are byte-identical to live computation (modulo the
     legacy `price_drops` random-fallback which is non-deterministic when no
     real drops exist — normalized in _canonical below).
  3. Non-default variants (custom store_id, custom date range, non-standard `days`)
     bypass the persistent cache.
  4. recompute_dashboard_cache() walks every registered endpoint × window.

Runs in-process against a real Mongo/FerretDB on 127.0.0.1:27017.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_iter27_insights_cache")
import server  # noqa: E402
from fastapi.encoders import jsonable_encoder  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

USER = {"id": "t", "email": "t@t", "role": "super_admin"}
MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")


async def _seed(db):
    """Richer seed than test_dashboard_cache: also populates competitor_price on
    product_matches so /price-intel/dashboard has real data to reason about."""
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
         "sale_price": None, "quantity": 5, "present_on_store": True, "is_own_store": True, "store_id": own,
         "first_seen_at": now - timedelta(days=60)}
        for i, s in enumerate(skus)
    ])
    await db.products.insert_many([
        {"id": f"p{i}", "sku": s, "name_ar": f"م{i}", "name_en": f"P{i}", "brand": "", "category": "cat_food",
         "animal_type": "cat", "first_seen_at": (now - timedelta(days=60)).isoformat()}
        for i, s in enumerate(skus)
    ])
    # Product matches now include competitor_price so /price-intel works.
    await db.product_matches.insert_many([
        {"my_sku": s, "competitor_sku": s, "competitor_store_id": ("c1" if i % 2 else "c2"),
         "competitor_store_name": ("Comp1" if i % 2 else "Comp2"),
         "competitor_price": round(10 + i*3.5 + 2, 2),  # 2 SAR more than my price
         "competitor_in_stock": True, "confidence": 99, "match_method": "barcode"}
        for i, s in enumerate(skus[:25])
    ])
    snaps = []
    for i, s in enumerate(skus):
        for store, sid in ((own, own), ("Comp1", "c1"), ("Comp2", "c2")):
            qty = 60
            for d in range(0, 90, 2):
                ts = now - timedelta(days=d, hours=1)
                # Introduce a real price drop on d=30, d=60 so /insights/summary's
                # drops aggregation returns a non-random value.
                base_price = round(10 + i*3.5 + (0 if sid == own else 2), 2)
                if d in (30, 60):
                    base_price = round(base_price * 0.9, 2)
                qty = max(0, qty - 2)
                if qty <= 4:
                    qty += 40
                snaps.append({"id": f"{sid}-{s}-{d}", "sku": s, "store_id": sid, "store_name": store,
                              "price": base_price,
                              "original_price": round(10 + i*3.5, 2), "discount_pct": 0,
                              "in_stock": qty > 0, "qty_available": qty, "sold_count": 0,
                              "source_tier": 0 if sid == own else 1,
                              "confidence_score": 99 if sid == own else 95,
                              "product_url": "", "crawled_at": ts})
    await db.product_snapshots.insert_many(snaps)


def _canonical(payload):
    """Strip cache envelope + drop non-deterministic `price_drops` random fallback."""
    if isinstance(payload, dict):
        p = {k: v for k, v in payload.items() if k != "cache"}
        # Legacy random fallback — only stable when the aggregation found >0 drops.
        if "price_drops" in p:
            p = {**p, "price_drops": None}
    else:
        p = payload
    return json.dumps(jsonable_encoder(p), sort_keys=True, default=str)


async def _fresh_db():
    db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
    server.db = db
    await _seed(db)
    return db


def test_insights_summary_cache_envelope_and_byte_identical():
    async def main():
        db = await _fresh_db()
        await server.recompute_dashboard_cache(db)

        for w in (7, 14, 30, 90):
            resp_cache = await server.insights_summary(days=w, user=USER)
            assert isinstance(resp_cache, dict) and "cache" in resp_cache, resp_cache
            assert resp_cache["cache"]["source"] == "cache", (w, resp_cache["cache"])

            # Wipe cache and re-fetch — must be a live_fallback with identical payload
            await db.dashboard_cache.delete_one({"key": server._cache_key("insights_summary", w)})
            resp_live = await server.insights_summary(days=w, user=USER)
            assert resp_live["cache"]["source"] == "live_fallback", (w, resp_live["cache"])
            assert _canonical(resp_cache) == _canonical(resp_live), f"drift at days={w}"

        # Non-standard window is uncacheable
        resp_45 = await server.insights_summary(days=45, user=USER)
        assert resp_45["cache"]["source"] == "live_uncacheable"
        print("PASS: /insights/summary cache envelope + byte-identical to live")
    asyncio.run(main())


def test_insights_list_endpoints_served_from_cache():
    """Leaderboard / trending / top-sellers / gaps / price-wars / restock / sales
    return lists (or a dict for sales) and don't expose a cache envelope, but
    they must still transparently serve from the persistent cache when hot."""
    async def main():
        db = await _fresh_db()
        await server.recompute_dashboard_cache(db)

        pairs = [
            ("insights_leaderboard", lambda: server.insights_leaderboard(days=30, user=USER)),
            ("insights_top_sellers", lambda: server.insights_top_sellers(days=30, store_id=None, user=USER)),
            ("insights_trending",    lambda: server.insights_trending(days=30, user=USER)),
            ("insights_gaps",        lambda: server.insights_gaps(days=30, user=USER)),
            ("insights_price_wars",  lambda: server.insights_price_wars(days=30, user=USER)),
            ("insights_restock",     lambda: server.insights_restock(days=30, user=USER)),
            # insights_sales uses FastAPI Query defaults — must be passed
            # explicitly when calling the endpoint fn directly (Query() defaults
            # aren't unwrapped outside HTTP context).
            ("insights_sales",       lambda: server.insights_sales(
                days=30, date_from=None, date_to=None, search=None,
                sort="revenue_desc", user=USER)),
        ]
        for endpoint, call in pairs:
            # Prime by reading directly from the cache doc — must exist
            doc = await db.dashboard_cache.find_one({"key": server._cache_key(endpoint, 30)})
            assert doc is not None, f"cache doc missing for {endpoint}"

            # Fresh copy of cached data (byte-normalized)
            cached_payload = doc["dataset"]

            # Wipe + call endpoint — this triggers live_fallback + repopulates.
            await db.dashboard_cache.delete_one({"key": server._cache_key(endpoint, 30)})
            server.cache_clear()  # bust the endpoint-level ttl_cache
            live_resp = await call()

            # After live_fallback, the doc is re-written; must be byte-identical.
            new_doc = await db.dashboard_cache.find_one({"key": server._cache_key(endpoint, 30)})
            assert new_doc is not None, f"live_fallback did not repopulate {endpoint}"
            assert _canonical(cached_payload) == _canonical(new_doc["dataset"]), \
                f"drift between recompute and live_fallback for {endpoint}"
            # The endpoint response itself matches the cache
            assert _canonical(live_resp) == _canonical(new_doc["dataset"]), \
                f"endpoint response != cache doc for {endpoint}"
        print("PASS: all insights list endpoints hit cache byte-identically")
    asyncio.run(main())


def test_price_intel_dashboard_cache_envelope_and_byte_identical():
    async def main():
        db = await _fresh_db()
        await server.recompute_dashboard_cache(db)

        resp_cache = await server.price_intel_dashboard(user=USER)
        assert isinstance(resp_cache, dict) and "cache" in resp_cache
        assert resp_cache["cache"]["source"] == "cache", resp_cache["cache"]

        # Wipe cache → live_fallback with identical payload
        await db.dashboard_cache.delete_one({"key": server._cache_key("price_intel_dashboard")})
        resp_live = await server.price_intel_dashboard(user=USER)
        assert resp_live["cache"]["source"] == "live_fallback", resp_live["cache"]
        assert _canonical(resp_cache) == _canonical(resp_live), "price-intel cache/live drift"
        print("PASS: /price-intel/dashboard cache envelope + byte-identical to live")
    asyncio.run(main())


def test_non_default_top_sellers_bypasses_cache():
    async def main():
        db = await _fresh_db()
        await server.recompute_dashboard_cache(db)
        # store_id filter is non-default → must NOT be cached (goes live)
        server.cache_clear()
        _ = await server.insights_top_sellers(days=30, store_id="c1", user=USER)
        # No cache doc for the non-default variant
        assert await db.dashboard_cache.find_one(
            {"key": server._cache_key("insights_top_sellers", 30) + ":store_id=c1"}
        ) is None
        # But the default variant is still cached
        assert await db.dashboard_cache.find_one(
            {"key": server._cache_key("insights_top_sellers", 30)}
        ) is not None
        print("PASS: non-default top-sellers variant bypasses persistent cache")
    asyncio.run(main())


def test_stale_cache_falls_back_to_live_for_insights_summary():
    async def main():
        db = await _fresh_db()
        await server.recompute_dashboard_cache(db)
        # Backdate the 30D insights_summary cache beyond 24h
        await db.dashboard_cache.update_one(
            {"key": server._cache_key("insights_summary", 30)},
            {"$set": {"computed_at": datetime.now(timezone.utc) - timedelta(hours=25)}},
        )
        server.cache_clear()
        resp = await server.insights_summary(days=30, user=USER)
        assert resp["cache"]["source"] == "live_fallback", resp["cache"]
        print("PASS: stale insights_summary cache falls back to live")
    asyncio.run(main())


def test_recompute_registry_covers_expected_endpoints():
    plan = server._dashboard_cache_recompute_plan()
    endpoints = {e for e, _needs_window, _factory in plan}
    expected = {
        "my_products", "insights_summary", "insights_leaderboard",
        "insights_top_sellers", "insights_trending", "insights_gaps",
        "insights_price_wars", "insights_restock", "insights_sales",
        "price_intel_dashboard",
    }
    missing = expected - endpoints
    assert not missing, f"missing endpoints in recompute plan: {missing}"
    # Every non-price-intel endpoint is window-aware
    for endpoint, needs_window, _factory in plan:
        if endpoint == "price_intel_dashboard":
            assert not needs_window
        else:
            assert needs_window, endpoint
    print(f"PASS: recompute plan covers {len(endpoints)} endpoints")


if __name__ == "__main__":
    test_recompute_registry_covers_expected_endpoints()
    test_insights_summary_cache_envelope_and_byte_identical()
    test_insights_list_endpoints_served_from_cache()
    test_price_intel_dashboard_cache_envelope_and_byte_identical()
    test_non_default_top_sellers_bypasses_cache()
    test_stale_cache_falls_back_to_live_for_insights_summary()
    print("ALL iter27 INSIGHTS-CACHE TESTS PASSED")
