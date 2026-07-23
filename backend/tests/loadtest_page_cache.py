"""iter26 load test — Insights / Price-Intel page cache at production density.

Measures, per endpoint:
  • live compute time (the current on-request cost — the ~40s / timeout class)
  • recompute time (background, after crawl/sync)
  • cached read latency (target < 2s)

Reuses the iter25 production-density seeder.

Backend caveat: the FerretDB/SQLite shim does not implement $push / $addToSet /
$first, so the FOUR aggregation endpoints (summary, gaps, price-wars, restock)
cannot execute here — recompute reports them as ERROR and they must be timed on
real MongoDB. The five find-based endpoints (leaderboard, top-sellers, trending,
sales, price-intel/dashboard) run fully and are measured end-to-end. The cached
READ path is O(one cache doc) and backend-independent, so its latency is
representative for all nine.

Usage:
    python3 tests/loadtest_page_cache.py [--skus 2177] [--days 90] [--db-name loadtest_pagecache]
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tests.loadtest_my_products_scale import seed, rss_mb  # noqa: E402


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skus", type=int, default=800)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--db-name", default="loadtest_pagecache")
    ap.add_argument("--skip-seed", action="store_true")
    args = ap.parse_args()

    os.environ["DB_NAME"] = args.db_name
    import server
    from starlette.responses import Response
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[args.db_name]
    server.db = db

    if not args.skip_seed:
        await seed(db, args.skus, args.days)
    n = await db.product_snapshots.estimated_document_count()
    print(f"\nDB: {args.db_name} — {n:,} snapshots, {args.skus} SKUs. Baseline RSS {rss_mb():.0f}MB")

    USER = {"id": "lt", "email": "t", "role": "super_admin"}
    # (label, live-compute coro-factory, cached-read coro-factory(Response))
    endpoints = [
        ("insights/summary",   lambda: server._insights_summary_compute(db, 30),
                               lambda r: server.insights_summary(days=30, response=r, user=USER)),
        ("insights/leaderboard", lambda: server._insights_leaderboard_compute(db, 30),
                               lambda r: server.insights_leaderboard(days=30, response=r, user=USER)),
        ("insights/top-sellers", lambda: server._insights_top_sellers_compute(db, 30, None),
                               lambda r: server.insights_top_sellers(days=30, store_id=None, response=r, user=USER)),
        ("insights/trending",  lambda: server._insights_trending_compute(db, 30),
                               lambda r: server.insights_trending(days=30, response=r, user=USER)),
        ("insights/gaps",      lambda: server._insights_gaps_compute(db, 30),
                               lambda r: server.insights_gaps(days=30, response=r, user=USER)),
        ("insights/price-wars", lambda: server._insights_price_wars_compute(db, 30),
                               lambda r: server.insights_price_wars(days=30, response=r, user=USER)),
        ("insights/restock",   lambda: server._insights_restock_compute(db, 30),
                               lambda r: server.insights_restock(days=30, response=r, user=USER)),
        ("insights/sales",     lambda: server._insights_sales_compute(db, 30, None, None, None, "revenue_desc", USER),
                               lambda r: server.insights_sales(days=30, response=r, user=USER)),
        ("price-intel/dashboard", lambda: server._price_intel_dashboard_compute(db),
                               lambda r: server.price_intel_dashboard(response=r, user=USER)),
    ]

    print("\n=== LIVE COMPUTE time (current on-request cost) ===")
    live = {}
    for label, compute, _ in endpoints:
        t0 = time.time()
        try:
            await compute()
            live[label] = time.time() - t0
            print(f"  {label:26} {live[label]*1000:8.0f} ms")
        except Exception as e:
            live[label] = None
            print(f"  {label:26} UNSUPPORTED on this backend: {str(e)[:44]}")

    print("\n=== RECOMPUTE (background job, all specs) ===")
    await db.dashboard_cache.delete_many({})
    t0 = time.time()
    stats = await server.recompute_page_caches(db)
    print(f"  total recompute: {time.time()-t0:.1f}s   peakRSS={rss_mb():.0f}MB")
    for k, v in stats.items():
        if isinstance(v, str):
            print(f"    {k:34} {v}")

    print("\n=== CACHED READ latency (target < 2s) ===  before → after")
    worst = 0.0
    for label, _, read in endpoints:
        r = Response()
        t0 = time.time()
        try:
            await read(r)
            dt = time.time() - t0
        except Exception as e:
            print(f"  {label:26} read-unsupported: {str(e)[:40]}")
            continue
        src = r.headers.get("x-cache-source", "-")
        worst = max(worst, dt)
        b = f"{live[label]*1000:.0f}ms" if live.get(label) is not None else "n/a(shim)"
        flag = "" if src == "cache" else f"  [{src}]"
        print(f"  {label:26} {b:>10} → {dt*1000:7.1f}ms  src={src}{flag}")
    print(f"\n  WORST cached read: {worst*1000:.1f}ms  →  {'PASS < 2s' if worst < 2 else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
