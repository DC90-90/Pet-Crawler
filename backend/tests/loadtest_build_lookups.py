"""Load test for matcher._build_competitor_lookups at production scale.

Usage:
    python tests/loadtest_build_lookups.py seed    # seed 1.2M synthetic snapshots (separate DB)
    python tests/loadtest_build_lookups.py old     # run the OLD (pre-iter22) pipeline — expect failure/slow
    python tests/loadtest_build_lookups.py new     # run the NEW _build_competitor_lookups — measure time+memory
    python tests/loadtest_build_lookups.py verify  # correctness: latest-per-pair contract + explain plan
    python tests/loadtest_build_lookups.py drop    # drop the loadtest DB

Runs against a SEPARATE database (daleel_loadtest) on the same Mongo instance.
Never touches the preview/production application database.
"""
import asyncio, os, sys, time, resource, random, json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

LOADTEST_DB = "daleel_loadtest"
N_STORES = 15
N_SKUS_PER_STORE = 3000          # 45,000 distinct (sku, store) pairs
TARGET_DOCS = 1_200_000          # > production's ~1M
OWN_STORE_ID = "own-store-loadtest"


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[LOADTEST_DB]


async def seed():
    db = _db()
    await db.product_snapshots.drop()
    now = datetime.now(timezone.utc)
    snaps_per_pair = TARGET_DOCS // (N_STORES * N_SKUS_PER_STORE)  # ~26
    total = 0
    batch = []
    for st in range(N_STORES):
        store_id = f"store-{st}"
        store_name = f"Store {st}"
        for sk in range(N_SKUS_PER_STORE):
            sku = str(6000000000000 + st * N_SKUS_PER_STORE + sk)
            for i in range(snaps_per_pair):
                # WORST CASE: every doc inside the 14-day window
                crawled = now - timedelta(days=random.uniform(0, 13.5))
                batch.append({
                    "sku": sku, "store_id": store_id, "store_name": store_name,
                    "crawled_at": crawled,
                    "price": round(random.uniform(5, 300), 2),
                    "original_price": round(random.uniform(5, 300), 2),
                    "discount_pct": 0,
                    "qty_available": random.randint(0, 50),
                    "in_stock": True, "sold_count": 0,
                    "confidence_score": 95, "source_tier": 1,
                    "product_url": "https://example.com/p",
                })
                total += 1
                if len(batch) >= 20000:
                    await db.product_snapshots.insert_many(batch, ordered=False)
                    batch = []
                    print(f"  inserted {total:,}", flush=True)
    if batch:
        await db.product_snapshots.insert_many(batch, ordered=False)
    # Same index set as production startup + the new iter22 index
    await db.product_snapshots.create_index("crawled_at")
    await db.product_snapshots.create_index([("sku", 1), ("crawled_at", -1)])
    await db.product_snapshots.create_index([("store_id", 1), ("crawled_at", -1)])
    await db.product_snapshots.create_index([("crawled_at", -1), ("store_id", 1)])
    await db.product_snapshots.create_index([("crawled_at", -1), ("sku", 1)])
    await db.product_snapshots.create_index([("crawled_at", -1), ("confidence_score", 1)])
    await db.product_snapshots.create_index([("store_id", 1), ("sku", 1), ("crawled_at", -1)])
    n = await db.product_snapshots.count_documents({})
    print(f"SEEDED {n:,} snapshot docs across {N_STORES} stores x {N_SKUS_PER_STORE} skus")


async def run_old():
    """The pre-iter22 pipeline exactly as it was in matcher.py."""
    db = _db()
    pipeline = [
        {"$match": {"store_id": {"$ne": OWN_STORE_ID}}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {
            "_id": {"sku": "$sku", "store_id": "$store_id"},
            "sku": {"$first": "$sku"}, "store_id": {"$first": "$store_id"},
            "store_name": {"$first": "$store_name"}, "price": {"$first": "$price"},
            "original_price": {"$first": "$original_price"}, "in_stock": {"$first": "$in_stock"},
            "qty_available": {"$first": "$qty_available"}, "source_tier": {"$first": "$source_tier"},
            "crawled_at": {"$first": "$crawled_at"},
        }},
    ]
    t0 = time.monotonic()
    try:
        res = await db.product_snapshots.aggregate(pipeline).to_list(100000)
        print(f"OLD pipeline COMPLETED: {len(res):,} groups in {time.monotonic()-t0:.1f}s")
    except Exception as e:
        print(f"OLD pipeline FAILED after {time.monotonic()-t0:.1f}s: {type(e).__name__}: {e}")


async def run_new():
    from matcher import _build_competitor_lookups
    db = _db()
    await db.products.insert_one({"sku": "x"})  # products lookup non-empty
    t0 = time.monotonic()
    snapshots, products = await _build_competitor_lookups(db, OWN_STORE_ID)
    dt = time.monotonic() - t0
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"NEW _build_competitor_lookups COMPLETED: {len(snapshots):,} candidate pairs in {dt:.1f}s | peak RSS {peak_mb:.0f} MB")
    await db.products.delete_many({})


async def verify():
    from matcher import MATCH_WINDOW_DAYS
    db = _db()
    # Correctness: for a sampled pair, aggregation result must equal the true latest doc
    from matcher import _build_competitor_lookups
    snapshots, _ = await _build_competitor_lookups(db, OWN_STORE_ID)
    by_pair = {(s["sku"], s["store_id"]): s for s in snapshots}
    ok = 0
    for (sku, sid), s in random.sample(list(by_pair.items()), 20):
        truth = await db.product_snapshots.find_one(
            {"sku": sku, "store_id": sid}, sort=[("crawled_at", -1)])
        assert abs((truth["crawled_at"] - s["crawled_at"]).total_seconds()) < 1, f"latest mismatch for {sku}/{sid}"
        ok += 1
    print(f"CORRECTNESS: {ok}/20 sampled pairs return their true latest snapshot")
    # Own store excluded
    assert not any(s["store_id"] == OWN_STORE_ID for s in snapshots)
    print("OWN-STORE EXCLUSION: pass")
    # Explain: confirm no in-memory blocking sort
    since = datetime.now(timezone.utc) - timedelta(days=MATCH_WINDOW_DAYS)
    exp = await db.command(
        "explain",
        {"aggregate": "product_snapshots",
         "pipeline": [{"$match": {"crawled_at": {"$gte": since}, "store_id": {"$ne": OWN_STORE_ID}}},
                      {"$sort": {"crawled_at": -1}}],
         "cursor": {}},
        verbosity="queryPlanner",
    )
    qp = exp.get("queryPlanner") or {}
    wp = json.dumps(qp.get("winningPlan", {}), default=str)
    import re as _re
    stages = _re.findall(r'"stage": "([A-Z_]+)"', wp)
    idx = _re.findall(r'"indexName": "([^"]+)"', wp)
    print(f"EXPLAIN winningPlan: stages={stages} | index={idx} | blocking-sort={'YES (BAD)' if 'SORT' in stages else 'NO (index-backed)'}")


async def drop():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await client.drop_database(LOADTEST_DB)
    print("dropped", LOADTEST_DB)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "new"
    asyncio.run({"seed": seed, "old": run_old, "new": run_new, "verify": verify, "drop": drop}[mode]())
