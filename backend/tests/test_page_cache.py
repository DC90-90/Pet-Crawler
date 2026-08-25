"""iter26 — Insights + Price-Intel page cache tests.

Central guarantee (same as iter25): a response served from db.dashboard_cache is
BYTE-IDENTICAL to the same request computed live. Cache metadata rides in
X-Cache-* headers, so the response BODY is unchanged vs the pre-cache endpoint.

Backend note: the FerretDB/SQLite shim used in the sandbox does not implement the
$push / $addToSet / $first group accumulators, so the four aggregation endpoints
(summary, gaps, price-wars, restock) cannot execute here — their real
byte-identicality must be confirmed on MongoDB (the load test does this). Their
shared cache WRAPPER (store / serve / stale-fallback / headers) is proven here
via a mocked compute, since the wrapper is compute-agnostic and identical for
all nine endpoints. The five find-based endpoints (leaderboard, top-sellers,
trending, sales, price-intel/dashboard) run fully on the shim and are tested
end-to-end.
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_pagecache"
import server  # noqa: E402
from starlette.responses import Response  # noqa: E402
from fastapi.encoders import jsonable_encoder  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from tests.loadtest_my_products_scale import seed  # noqa: E402

USER = {"id": "t", "email": "t@t", "role": "super_admin"}
MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")

# Endpoints whose compute is find/Python-based → run on the FerretDB shim.
RUNNABLE = [
    ("insights/leaderboard", lambda r: server.insights_leaderboard(days=30, response=r, user=USER)),
    ("insights/top-sellers", lambda r: server.insights_top_sellers(days=30, store_id=None, response=r, user=USER)),
    ("insights/trending",    lambda r: server.insights_trending(days=30, response=r, user=USER)),
    ("insights/sales",       lambda r: server.insights_sales(days=30, response=r, user=USER)),
    ("price-intel/dashboard", lambda r: server.price_intel_dashboard(response=r, user=USER)),
]


def _norm(body):
    return json.dumps(jsonable_encoder(body), sort_keys=True, default=str)


async def _fresh_db():
    db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
    server.db = db
    # iter70 — isolation guard (reconciled from the workspace copy): the cached
    # endpoints read the sales rollups, and rows left behind by OTHER suites on
    # the shared FerretDB instance made byte-identity flake. Clear them so
    # every run computes from exactly the seeded state.
    for _c in ("sku_sales_daily", "metric_daily_rollups", "sku_store_coverage",
               "metric_rollup_meta"):
        await db[_c].delete_many({})
    await seed(db, 40, 30)
    await db.dashboard_cache.drop()
    await db.dashboard_cache.create_index("key", unique=True)
    return db


def test_cache_byte_identical_runnable_endpoints():
    async def main():
        db = await _fresh_db()
        for label, call in RUNNABLE:
            base = label
            # warm just this endpoint's cache via its own compute path (live_fallback stores it)
            r0 = Response(); await call(r0)
            r1 = Response(); body_cache = await call(r1)
            assert r1.headers["x-cache-source"] == "cache", (label, dict(r1.headers))
            await db.dashboard_cache.delete_many({})
            r2 = Response(); body_live = await call(r2)
            assert r2.headers["x-cache-source"] == "live_fallback", (label, dict(r2.headers))
            assert _norm(body_cache) == _norm(body_live), f"byte mismatch: {label}"
            # header envelope shape
            assert r1.headers.get("x-cache-computed-at")
            assert r1.headers.get("x-cache-stale") == "false"
        print("PASS: cache == live byte-identical for", len(RUNNABLE), "find-based endpoints")
    asyncio.run(main())


def test_wrapper_byte_identical_with_mocked_aggregation_compute():
    """Prove the shared cache wrapper (used by summary/gaps/price-wars/restock)
    is byte-identical for both list and dict payloads, independent of backend."""
    async def main():
        db = await _fresh_db()
        list_payload = [{"sku": f"S{i}", "spread_pct": 10.5 + i, "prices": [{"store": "A", "price": 1.0}]} for i in range(30)]
        dict_payload = {"total_skus": 2177, "price_drops": 12, "freshness_breakdown": {"today": 5, "stale": 1}, "median_spread": 3.14}
        for base, payload in [("insights/price-wars", list_payload), ("insights/summary", dict_payload)]:
            calls = {"n": 0}
            async def compute():
                calls["n"] += 1
                return payload
            # miss → live_fallback + store
            b1, m1 = await server._serve_page_cache(db, base, 30, compute, True)
            assert m1["source"] == "live_fallback"
            # hit → cache, no recompute
            b2, m2 = await server._serve_page_cache(db, base, 30, compute, True)
            assert m2["source"] == "cache" and calls["n"] == 1
            assert _norm(b1) == _norm(b2) == _norm(payload), base
        print("PASS: cache wrapper byte-identical for list + dict payloads")
    asyncio.run(main())


def test_non_default_requests_bypass_cache():
    async def main():
        db = await _fresh_db()
        r = Response(); await server.insights_top_sellers(days=30, store_id="own", response=r, user=USER)
        assert r.headers["x-cache-source"] == "live_uncacheable"
        r = Response(); await server.insights_sales(days=30, search="RC", response=r, user=USER)
        assert r.headers["x-cache-source"] == "live_uncacheable"
        r = Response(); await server.insights_sales(days=30, sort="sales_asc", response=r, user=USER)
        assert r.headers["x-cache-source"] == "live_uncacheable"
        r = Response(); await server.insights_leaderboard(days=45, response=r, user=USER)
        assert r.headers["x-cache-source"] == "live_uncacheable"
        print("PASS: filtered/search/non-standard requests bypass cache")
    asyncio.run(main())


def test_stale_cache_falls_back_to_live():
    async def main():
        db = await _fresh_db()
        r0 = Response(); await server.insights_leaderboard(days=30, response=r0, user=USER)  # populate
        await db.dashboard_cache.update_one(
            {"key": server._page_cache_key("insights/leaderboard", 30)},
            {"$set": {"computed_at": datetime.now(timezone.utc) - timedelta(hours=25)}},
        )
        r = Response(); await server.insights_leaderboard(days=30, response=r, user=USER)
        assert r.headers["x-cache-source"] == "live_fallback"
        print("PASS: cache stale >24h → live fallback")
    asyncio.run(main())


if __name__ == "__main__":
    test_wrapper_byte_identical_with_mocked_aggregation_compute()
    test_non_default_requests_bypass_cache()
    test_stale_cache_falls_back_to_live()
    test_cache_byte_identical_runnable_endpoints()
    print("ALL PAGE-CACHE TESTS PASSED")
