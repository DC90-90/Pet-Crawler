"""Load test for /api/my-products at REAL production density (iter24).

The iter23 load test underestimated snapshot density by 2.6x and the change
shipped broken (30D/90D → Cloudflare 520). This test seeds the DENSITY THE
PRODUCTION INCIDENT ACTUALLY EXHIBITED, per the incident report:

    own store:    2,175 SKUs x 5.2 snapshots/day x 90 days   = 1,017,900 docs
    competitors:  12 stores x ~40% sku coverage x 1.2/day x 90 days
                  (870 skus/store)                            = 1,127,520 docs
    total                                                     ~ 2.1M docs

Usage (destructive — uses its own database name, never the app DB):
    python3 tests/loadtest_my_products_scale.py [--skus 2175] [--days 90]
                                                [--db-name loadtest_myproducts]

Measures wall time, peak RSS, and snapshot docs scanned for days=7/14/30/90,
asserts row counts and window monotonicity, and proves chunking-invariance by
re-running 30D with one giant chunk vs the production chunk size and diffing
the full JSON output.
"""
import argparse
import asyncio
import json
import os
import random
import resource
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

N_SKUS = 2175
OWN_SNAPS_PER_DAY = 5.2
N_COMP_STORES = 12
COMP_COVERAGE = 0.40
COMP_SNAPS_PER_DAY = 1.2
HISTORY_DAYS = 90


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


async def seed(db, n_skus, history_days):
    random.seed(42)
    now = datetime.now(timezone.utc)
    for coll in ("stores", "my_products", "products", "product_matches", "product_snapshots"):
        await db[coll].drop()

    own_id = "own-store-id"
    stores = [{"id": own_id, "name": "Pets Houses", "domain": "pets-houses.com",
               "platform": "zid", "is_own_store": True, "is_active": True}]
    comp_ids = []
    for i in range(N_COMP_STORES):
        cid = f"comp-{i}"
        comp_ids.append(cid)
        stores.append({"id": cid, "name": f"Comp {i}", "domain": f"comp{i}.example",
                       "platform": "salla" if i % 2 else "zid", "is_active": True})
    await db.stores.insert_many(stores)

    skus = [f"BC{78000000000 + i}" for i in range(n_skus)]  # barcode-style skus
    await db.my_products.insert_many([
        {"sku": s, "barcode": s if i % 10 else "", "name_ar": f"منتج {i}", "name_en": f"Product {i}",
         "price": round(random.uniform(10, 300), 2), "sale_price": None,
         "present_on_store": True, "is_own_store": True}
        for i, s in enumerate(skus)
    ])
    await db.products.insert_many([
        {"id": f"p{i}", "sku": s, "name_ar": f"منتج {i}", "name_en": f"Product {i}",
         "brand": "", "category": "cat_food", "animal_type": "cat",
         "first_seen_at": (now - timedelta(days=60)).isoformat()}
        for i, s in enumerate(skus)
    ])
    # ~800 skus matched to 2 competitor stores each (competitor sku == barcode,
    # the common Salla barcode-as-sku case → also exercises the barcode union)
    matches = []
    for i, s in enumerate(skus[:800]):
        for j in range(2):
            matches.append({"my_sku": s, "competitor_sku": s,
                            "competitor_store_id": comp_ids[(i + j) % N_COMP_STORES],
                            "confidence": 99, "match_method": "barcode"})
    await db.product_matches.insert_many(matches)

    def snap(sku, store_id, store_name, ts, price, qty, sold):
        return {"id": f"{store_id}-{sku}-{ts.timestamp()}", "sku": sku, "store_id": store_id,
                "store_name": store_name, "price": price, "original_price": price,
                "discount_pct": 0, "in_stock": qty > 0, "qty_available": qty,
                "sold_count": sold, "source_tier": 0 if store_id == own_id else 1,
                "confidence_score": 99 if store_id == own_id else 95,
                "product_url": "", "crawled_at": ts}

    total = 0
    batch = []
    t0 = time.time()

    async def flush():
        nonlocal batch, total
        if batch:
            await db.product_snapshots.insert_many(batch, ordered=False)
            total += len(batch)
            batch = []
            if total % 100_000 < 10_000:
                print(f"  seeded {total:,} snapshots ({time.time()-t0:.0f}s, RSS {rss_mb():.0f}MB)", flush=True)

    # Own store: 5.2/day — realistic sync cadence with duplicate-heavy values
    own_intervals = int(history_days * OWN_SNAPS_PER_DAY)
    for i, sku in enumerate(skus):
        qty = random.randint(5, 60)
        sold = random.randint(0, 500)
        price = round(random.uniform(10, 300), 2)
        for k in range(own_intervals):
            ts = datetime.now(timezone.utc) - timedelta(days=history_days) + timedelta(hours=k * 24 / OWN_SNAPS_PER_DAY)
            if random.random() < 0.2:  # ~20% of syncs observe a change
                delta = random.randint(0, 3)
                sold += delta
                qty = max(0, qty - delta)
                if qty <= 3 and random.random() < 0.4:
                    qty += random.randint(20, 60)
            batch.append(snap(sku, "own-store-id", "Pets Houses", ts, price, qty, sold))
            if len(batch) >= 10_000:
                await flush()

    # Competitors: 12 stores x 40% coverage x 1.2/day
    comp_intervals = int(history_days * COMP_SNAPS_PER_DAY)
    per_store = int(len(skus) * COMP_COVERAGE)
    for ci, cid in enumerate([f"comp-{i}" for i in range(N_COMP_STORES)]):
        carried = skus[(ci * 137) % len(skus):][:per_store] or skus[:per_store]
        for sku in carried:
            qty = random.randint(10, 150)
            price = round(random.uniform(10, 300), 2)
            for k in range(comp_intervals):
                ts = datetime.now(timezone.utc) - timedelta(days=history_days) + timedelta(hours=k * 24 / COMP_SNAPS_PER_DAY)
                if random.random() < 0.3:
                    qty = max(0, qty - random.randint(0, 4))
                    if qty <= 5 and random.random() < 0.3:
                        qty += random.randint(20, 80)
                batch.append(snap(sku, cid, f"Comp {ci}", ts, price, qty, 0))
                if len(batch) >= 10_000:
                    await flush()
    await flush()

    await db.product_snapshots.create_index([("sku", 1), ("crawled_at", -1)])
    await db.product_snapshots.create_index("crawled_at")
    print(f"SEEDED: {total:,} snapshots in {time.time()-t0:.0f}s")
    return total


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skus", type=int, default=N_SKUS)
    ap.add_argument("--days", type=int, default=HISTORY_DAYS)
    ap.add_argument("--db-name", default="loadtest_myproducts")
    ap.add_argument("--skip-seed", action="store_true")
    args = ap.parse_args()

    os.environ["DB_NAME"] = args.db_name  # must be set before importing server
    import server
    from motor.motor_asyncio import AsyncIOMotorClient
    db = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[args.db_name]
    server.db = db  # point the endpoint at the loadtest DB

    if not args.skip_seed:
        await seed(db, args.skus, args.days)
    n_total = await db.product_snapshots.estimated_document_count()
    print(f"\nDB: {args.db_name} — {n_total:,} snapshot docs. Baseline RSS {rss_mb():.0f}MB")

    user = {"id": "loadtest", "email": "t@t", "role": "super_admin"}

    def call(**kw):
        base = dict(days=30, on_date=None, date_from=None, date_to=None, category=None,
                    animal_type=None, search=None, sort_by="revenue_est", sort_order="desc",
                    limit=100, offset=0, own_only=True, user=user)
        base.update(kw)
        return server.my_products(**base)

    results = {}
    for d in (7, 14, 30, 90):
        t0 = time.time()
        r = await call(days=d)
        dt = time.time() - t0
        results[d] = r
        k = r["kpis"]
        print(f"days={d:>2}: {dt:6.1f}s  rows={r['total']:>5}  units={k['total_units_sold']:>7,}  "
              f"mkt_rev={k['market_revenue']:>14,.2f}  peakRSS={rss_mb():.0f}MB")

    # Assertions: all windows render the full catalogue; units monotone non-decreasing
    for d in (7, 14, 30, 90):
        assert results[d]["total"] == args.skus, f"days={d} rendered {results[d]['total']} rows, expected {args.skus}"
    u = {d: results[d]["kpis"]["total_units_sold"] for d in (7, 14, 30, 90)}
    assert u[7] <= u[14] <= u[30] <= u[90], f"window monotonicity violated: {u}"
    print("PASS: all windows render full catalogue; units monotone:", u)

    # Chunking-invariance: giant single chunk (≡ iter23's one global query)
    # must produce byte-identical output to production chunking. iter25 note:
    # wipe the dashboard cache before each call so BOTH recompute live with the
    # chunk size under test (otherwise the 2nd call would be served from the
    # cache the 1st populated, defeating the comparison). Ignore the additive
    # 'cache' meta key in the diff.
    def _no_cache_key(r):
        return {k: v for k, v in r.items() if k != "cache"}
    await db.dashboard_cache.delete_many({})
    server.MY_PRODUCTS_CHUNK_SIZE = 10**9
    one_chunk = await call(days=30)
    await db.dashboard_cache.delete_many({})
    server.MY_PRODUCTS_CHUNK_SIZE = 100
    chunked = await call(days=30)
    a = json.dumps(_no_cache_key(one_chunk), default=str, sort_keys=True)
    b = json.dumps(_no_cache_key(chunked), default=str, sort_keys=True)
    assert a == b, "chunked output differs from single-query output"
    print("PASS: chunked output byte-identical to single-query output (30D)")


if __name__ == "__main__":
    asyncio.run(main())
