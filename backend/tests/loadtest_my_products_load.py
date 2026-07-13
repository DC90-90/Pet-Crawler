"""Load test for the iter23 /api/my-products bounded snapshot load.

Simulates the EXACT query + grouping pattern shipped in server.py my_products():
find() with {crawled_at window, confidence floor, sku $in <relevant set>},
streamed cursor, by_sku grouping, per-group Python sort.

Usage (loadtest DB must already be seeded by loadtest_build_lookups.py seed):
    python tests/loadtest_my_products_load.py seed-own   # add heavy own-store history (2,600 skus x 180 snaps)
    python tests/loadtest_my_products_load.py run        # measure runtime + peak RSS + explain
"""
import asyncio, os, sys, time, resource, random, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

LOADTEST_DB = "daleel_loadtest"
OWN_STORE_ID = "own-store-loadtest"
N_OWN_SKUS = 2600
OWN_SNAPS_PER_SKU = 180          # 90d x 2 syncs/day — worst case history depth


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[LOADTEST_DB]


def _own_sku(i):
    return str(7000000000000 + i)


async def seed_own():
    db = _db()
    await db.product_snapshots.delete_many({"store_id": OWN_STORE_ID})
    now = datetime.now(timezone.utc)
    batch, total = [], 0
    for i in range(N_OWN_SKUS):
        sku = _own_sku(i)
        for k in range(OWN_SNAPS_PER_SKU):
            batch.append({
                "sku": sku, "store_id": OWN_STORE_ID, "store_name": "Own Store",
                "crawled_at": now - timedelta(days=random.uniform(0, 89)),
                "price": round(random.uniform(5, 300), 2),
                "original_price": None, "discount_pct": 0,
                "qty_available": random.randint(0, 50), "in_stock": True,
                "sold_count": random.randint(0, 5000),
                "confidence_score": 99, "source_tier": 0,
                "product_url": "https://own.example.com/p",
            })
            total += 1
            if len(batch) >= 20000:
                await db.product_snapshots.insert_many(batch, ordered=False)
                batch = []
    if batch:
        await db.product_snapshots.insert_many(batch, ordered=False)
    n = await db.product_snapshots.count_documents({})
    print(f"seeded {total:,} own-store docs | collection total now {n:,}")


async def run():
    db = _db()
    # relevant set = 2,600 own skus + 2,400 matched competitor skus + barcodes
    comp_skus = [str(6000000000000 + s * 3000 + k) for s in range(12) for k in range(200)]  # 2,400
    relevant = [_own_sku(i) for i in range(N_OWN_SKUS)] + comp_skus
    print(f"relevant sku set: {len(relevant):,}")
    for label, window_days in [("days=30", 30), ("days=90", 90)]:
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        snap_query = {"crawled_at": {"$gte": since}, "confidence_score": {"$gte": 60}, "sku": {"$in": relevant}}
        t0 = time.monotonic()
        by_sku, count = {}, 0
        cursor = db.product_snapshots.find(snap_query, {
            "_id": 0, "sku": 1, "store_id": 1, "store_name": 1,
            "crawled_at": 1, "price": 1, "original_price": 1, "discount_pct": 1,
            "qty_available": 1, "in_stock": 1, "sold_count": 1,
            "confidence_score": 1, "source_tier": 1, "product_url": 1,
        })
        async for s in cursor:
            count += 1
            by_sku.setdefault(s["sku"], {}).setdefault(s["store_id"], []).append(s)
        for sku in by_sku:
            for sid in by_sku[sku]:
                by_sku[sku][sid].sort(key=lambda x: x["crawled_at"])
        dt = time.monotonic() - t0
        peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"{label}: fetched+grouped {count:,} docs across {len(by_sku):,} skus in {dt:.1f}s | peak RSS {peak_mb:.0f} MB")
        by_sku = None
    # explain: confirm index-backed
    since = datetime.now(timezone.utc) - timedelta(days=90)
    exp = await db.command("explain", {
        "find": "product_snapshots",
        "filter": {"crawled_at": {"$gte": since}, "confidence_score": {"$gte": 60}, "sku": {"$in": relevant[:100]}},
        "projection": {"_id": 0, "sku": 1, "crawled_at": 1},
    }, verbosity="queryPlanner")
    wp = json.dumps(exp.get("queryPlanner", {}).get("winningPlan", {}), default=str)
    import re
    print("EXPLAIN winningPlan: stages=", re.findall(r'"stage": "([A-Z_]+)"', wp), "| index=", set(re.findall(r'"indexName": "([^"]+)"', wp)))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    asyncio.run({"seed-own": seed_own, "run": run}[mode]())
