"""iter25 load test — dashboard cache at production density.

Measures the two numbers the perf task asks for:
  1. recompute_dashboard_cache() wall time (the background cost after a
     crawl/sync) for all four standard windows.
  2. cached /api/my-products read latency per window — target < 2s.

Also re-proves byte-identicality (cache == live) at scale for one window.

The FerretDB/SQLite shim used in the sandbox wedges near ~2.3GB (~0.5-0.8M
docs), so full 5M-density must be run on real Mongo; this exercises the
largest scale that completes and the cache-read path (which is O(catalogue),
independent of snapshot count, so its latency is representative regardless).

Usage:
    python3 tests/loadtest_dashboard_cache.py [--skus 2177] [--days 90]
                                              [--db-name loadtest_dashcache]
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.loadtest_my_products_scale import seed, rss_mb  # reuse the production-density seeder


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skus", type=int, default=800)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--db-name", default="loadtest_dashcache")
    ap.add_argument("--skip-seed", action="store_true")
    args = ap.parse_args()

    os.environ["DB_NAME"] = args.db_name
    import server
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[args.db_name]
    server.db = db

    if not args.skip_seed:
        await seed(db, args.skus, args.days)
    n = await db.product_snapshots.estimated_document_count()
    print(f"\nDB: {args.db_name} — {n:,} snapshots, {args.skus} SKUs. Baseline RSS {rss_mb():.0f}MB")

    user = {"id": "lt", "email": "t@t", "role": "super_admin"}

    def call(**kw):
        base = dict(days=30, on_date=None, date_from=None, date_to=None, category=None, animal_type=None,
                    search=None, sort_by="revenue_est", sort_order="desc", limit=100, offset=0,
                    own_only=True, user=user)
        base.update(kw)
        return server.my_products(**base)

    # ── 1. Recompute (the background cost after a crawl/sync) ──
    await db.dashboard_cache.delete_many({})
    t0 = time.time()
    stats = await server.recompute_dashboard_cache(db)
    recompute_secs = time.time() - t0
    print("\n=== RECOMPUTE (all 4 windows, background job) ===")
    for w, s in stats.items():
        print(f"  {w:>2}D: {s['secs']:6.1f}s  ({s['rows']} rows)")
    print(f"  TOTAL recompute: {recompute_secs:.1f}s   peakRSS={rss_mb():.0f}MB")

    # ── 2. Cached read latency (target < 2s) ──
    print("\n=== CACHED READ latency (target < 2s) ===")
    worst = 0.0
    for w in (7, 14, 30, 90):
        t0 = time.time()
        r = await call(days=w)
        dt = time.time() - t0
        worst = max(worst, dt)
        src = r["cache"]["source"]
        assert src == "cache", f"days={w} not served from cache: {src}"
        print(f"  {w:>2}D: {dt*1000:7.1f}ms  source={src}  rows={r['total']}")
    print(f"  WORST cached read: {worst*1000:.1f}ms")
    assert worst < 2.0, f"cached read exceeded 2s target: {worst:.2f}s"
    print("  PASS: all cached reads < 2s")

    # ── 3. Byte-identical cache vs live at scale (90D) ──
    def _no_cache(r):
        return {k: v for k, v in r.items() if k != "cache"}
    resp_cache = await call(days=90)
    await db.dashboard_cache.delete_many({})
    resp_live = await call(days=90)
    a = json.dumps(_no_cache(resp_cache), default=str, sort_keys=True)
    b = json.dumps(_no_cache(resp_live), default=str, sort_keys=True)
    assert a == b, "cache output differs from live at scale"
    print("\n  PASS: cache == live byte-identical at 90D scale")

    # ── 4. Speedup summary ──
    await server.recompute_dashboard_cache(db)
    t0 = time.time(); await call(days=90); cached = time.time() - t0
    await db.dashboard_cache.delete_many({})
    t0 = time.time(); await call(days=90); live = time.time() - t0
    print(f"\n=== SPEEDUP (90D) ===  live={live:.1f}s  cached={cached*1000:.0f}ms  "
          f"speedup={live/max(cached,1e-6):.0f}x")


if __name__ == "__main__":
    asyncio.run(main())
