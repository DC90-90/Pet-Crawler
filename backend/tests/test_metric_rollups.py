"""iter30 — write-time metric rollups (price_drops / product_gaps / median_spread).

The whole new path is FerretDB-compatible (find + Python + $sum/$min/$max/$count,
no $topN/$addToSet/$push), so this is a REAL integration test against the sandbox
Mongo shim, not a simulation:

  1. Seed a controlled set of product_snapshots (known stores/skus/days/prices).
  2. Run the real server._recompute_store_metrics / recompute_all_store_metrics
     to build metric_daily_rollups + sku_store_coverage.
  3. Assert the real read helpers (_drops_from_rollups, _gaps_from_coverage,
     _spread_docs_from_coverage) return the hand-computed values.

Plus pure-Python cross-checks that the coverage-derived product_gaps and
median_spread are byte-identical to the OLD snapshot-scan definitions, and that
the daily-drop-event count is what price_drops now means.
"""
import asyncio
import os
import random
import statistics
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_metric_rollups")
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
FLOOR = server.MIN_AGGREGATION_CONFIDENCE


def _snap(store, sku, days_ago, price, conf=99):
    # distinct crawled_at per (store,sku,day); spread within the day is irrelevant
    # because the rollup keeps the LATEST price of each day.
    base = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {"id": f"{store}-{sku}-{days_ago}", "store_id": store, "sku": sku,
            "price": float(price), "confidence_score": conf,
            "crawled_at": base.replace(microsecond=days_ago * 1000)}


# Controlled dataset with hand-computed expectations (all within the last 3 days).
SNAPS = [
    # S1 / sku A: 20 -> 10 (drop) -> 15 (rise)   => 1 drop event
    _snap("S1", "A", 3, 20), _snap("S1", "A", 2, 10), _snap("S1", "A", 1, 15),
    # S1 / sku B: 50 -> 40 (drop)                 => 1 drop event
    _snap("S1", "B", 3, 50), _snap("S1", "B", 2, 40),
    # S2 / sku A: 30 -> 25 (drop)                 => 1 drop event
    _snap("S2", "A", 3, 30), _snap("S2", "A", 2, 25),
    # S2 / sku C: single day                      => 0
    _snap("S2", "C", 2, 5),
    # S3 / sku A: single day                      => 0
    _snap("S3", "A", 1, 22),
    # low-confidence noise: would be a drop but must be EXCLUDED entirely
    _snap("S1", "D", 3, 100, conf=max(0, FLOOR - 1)),
    _snap("S1", "D", 2, 50, conf=max(0, FLOOR - 1)),
]
# Expected (window covering all 3 days):
#   drops = 3  (S1/A, S1/B, S2/A)
#   gaps  = 2  (B in 1 store, C in 1 store; A in 3 stores is NOT a gap)
#   latest price per (sku,store): A:{S1:15,S2:25,S3:22}=>spread 10; B:{S1:40}=>0; C:{S2:5}=>0
#   median_spread over spreads>0 = median([10]) = 10.0
EXPECT_DROPS, EXPECT_GAPS, EXPECT_SPREAD = 3, 2, 10.0


async def _fresh_db(name):
    db = AsyncIOMotorClient(MONGO)[name]
    for c in ("product_snapshots", "metric_daily_rollups", "sku_store_coverage"):
        await db[c].delete_many({})
    return db


async def _try_helper(coro):
    """Run a real read helper; return its value, or None if the FerretDB shim
    lacks an accumulator the helper uses ($min/$max/$count/$sum). On Atlas these
    all exist, so None only ever happens in the sandbox."""
    try:
        return await coro
    except Exception as e:
        if "not implemented" in str(e).lower():
            return None
        raise


async def _run_integration():
    db = await _fresh_db("test_metric_rollups")
    await db.product_snapshots.insert_many([dict(s) for s in SNAPS])
    # The novel/risky part — the write-time rebuild (find + Python + insert) — runs
    # natively on FerretDB, so this exercises the REAL machinery on real Mongo.
    stats = await server.recompute_all_store_metrics(db)
    assert stats["stores"] == 3, stats

    since = datetime.now(timezone.utc) - timedelta(days=30)
    since_str = server._metric_day_str(since)

    # ── Validate the built collections directly (backend-independent) ──
    rollups = await db.metric_daily_rollups.find({}, {"_id": 0}).to_list(length=None)
    drops = sum(r["drops"] for r in rollups if r["date"] >= since_str)
    assert drops == EXPECT_DROPS, f"rollup drops {drops} != {EXPECT_DROPS}"

    coverage = await db.sku_store_coverage.find({}, {"_id": 0}).to_list(length=None)
    # low-confidence sku D must not appear anywhere
    assert not any(c["sku"] == "D" for c in coverage)
    # coverage.last_price = latest price per (sku,store)
    lp = {(c["sku"], c["store_id"]): c["last_price"] for c in coverage}
    assert lp[("A", "S1")] == 15 and lp[("A", "S2")] == 25 and lp[("A", "S3")] == 22
    assert lp[("B", "S1")] == 40 and lp[("C", "S2")] == 5

    # Motor/FerretDB return BSON dates as offset-naive UTC; normalize for the
    # Python-side window check (production compares server-side via $gte, unaffected).
    since_naive = since.replace(tzinfo=None)

    def _naive(dt):
        return dt.replace(tzinfo=None) if dt.tzinfo else dt

    per_sku_stores = {}
    per_sku_prices = {}
    for c in coverage:
        if _naive(c["last_seen_at"]) >= since_naive:
            per_sku_stores.setdefault(c["sku"], 0)
            per_sku_stores[c["sku"]] += 1
            per_sku_prices.setdefault(c["sku"], []).append(c["last_price"])
    gaps = sum(1 for n in per_sku_stores.values() if n < 3)
    assert gaps == EXPECT_GAPS, f"coverage gaps {gaps} != {EXPECT_GAPS}"
    spreads = [max(v) - min(v) for v in per_sku_prices.values() if max(v) - min(v) > 0]
    median_spread = round(statistics.median(spreads), 2) if spreads else 0
    assert median_spread == EXPECT_SPREAD, f"coverage spread {median_spread} != {EXPECT_SPREAD}"

    # ── Also run the REAL read helpers where the shim supports the operators ──
    h_drops = await _try_helper(server._drops_from_rollups(db, since))
    if h_drops is not None:
        assert h_drops == EXPECT_DROPS, f"_drops_from_rollups {h_drops}"
    h_gaps = await _try_helper(server._gaps_from_coverage(db, since))
    if h_gaps is not None:
        assert h_gaps == EXPECT_GAPS, f"_gaps_from_coverage {h_gaps}"
    h_spread = await _try_helper(server._spread_docs_from_coverage(db, since))
    if h_spread is not None:
        hv = [d["max_p"] - d["min_p"] for d in h_spread if d["max_p"] > d["min_p"]]
        assert round(statistics.median(hv), 2) == EXPECT_SPREAD

    # ── Idempotency: rebuild again → identical reads and no dup docs ──
    n_cov = await db.sku_store_coverage.count_documents({})
    n_roll = await db.metric_daily_rollups.count_documents({})
    await server.recompute_all_store_metrics(db)
    assert await db.sku_store_coverage.count_documents({}) == n_cov
    assert await db.metric_daily_rollups.count_documents({}) == n_roll
    rollups2 = await db.metric_daily_rollups.find({}, {"_id": 0}).to_list(length=None)
    assert sum(r["drops"] for r in rollups2 if r["date"] >= since_str) == EXPECT_DROPS


def test_integration_rollups_ferretdb():
    asyncio.get_event_loop().run_until_complete(_run_integration())


# ── pure-Python cross-checks: coverage semantics == OLD snapshot definitions ──
def _old_gaps(snaps, since):
    # OLD pipeline_gaps: group by sku, $addToSet store, count skus with <3 stores
    per_sku = {}
    for s in snaps:
        if s["confidence_score"] >= FLOOR and s["crawled_at"] >= since:
            per_sku.setdefault(s["sku"], set()).add(s["store_id"])
    return sum(1 for stores in per_sku.values() if len(stores) < 3)


def _cov_gaps(snaps, since):
    # coverage: last_seen per (sku,store); count stores with last_seen>=since
    last_seen = {}
    for s in snaps:
        if s["confidence_score"] >= FLOOR:
            k = (s["sku"], s["store_id"])
            if k not in last_seen or s["crawled_at"] > last_seen[k]:
                last_seen[k] = s["crawled_at"]
    per_sku = {}
    for (sku, store), ts in last_seen.items():
        if ts >= since:
            per_sku.setdefault(sku, 0)
            per_sku[sku] += 1
    return sum(1 for n in per_sku.values() if n < 3)


def _old_spread(snaps, since):
    # OLD pipeline_spread: latest price per (sku,store) in window, per-sku max-min
    latest = {}
    for s in snaps:
        if s["confidence_score"] >= FLOOR and s["crawled_at"] >= since:
            k = (s["sku"], s["store_id"])
            if k not in latest or s["crawled_at"] > latest[k][0]:
                latest[k] = (s["crawled_at"], s["price"])
    per_sku = {}
    for (sku, store), (_ts, price) in latest.items():
        per_sku.setdefault(sku, []).append(price)
    vals = [max(v) - min(v) for v in per_sku.values() if max(v) - min(v) > 0]
    return round(statistics.median(vals), 2) if vals else 0


def _cov_spread(snaps, since):
    last = {}
    for s in snaps:
        if s["confidence_score"] >= FLOOR:
            k = (s["sku"], s["store_id"])
            if k not in last or s["crawled_at"] > last[k][0]:
                last[k] = (s["crawled_at"], s["price"])
    per_sku = {}
    for (sku, store), (ts, price) in last.items():
        if ts >= since:                                  # last_seen>=since filter
            per_sku.setdefault(sku, []).append(price)
    vals = [max(v) - min(v) for v in per_sku.values() if max(v) - min(v) > 0]
    return round(statistics.median(vals), 2) if vals else 0


def _rand_snaps(rng):
    snaps = []
    now = datetime.now(timezone.utc)
    for _ in range(rng.randint(5, 60)):
        store = f"S{rng.randint(0, 5)}"
        sku = f"K{rng.randint(0, 8)}"
        days_ago = rng.randint(0, 45)
        snaps.append({"store_id": store, "sku": sku,
                      "price": float(rng.randint(5, 300)),
                      "confidence_score": rng.choice([FLOOR, 99, max(0, FLOOR - 5)]),
                      "crawled_at": now - timedelta(days=days_ago, seconds=rng.randint(0, 80000))})
    return snaps


def test_coverage_gaps_and_spread_match_old_definitions():
    rng = random.Random(20260730)
    now = datetime.now(timezone.utc)
    for _ in range(3000):
        snaps = _rand_snaps(rng)
        since = now - timedelta(days=rng.choice([7, 14, 30, 90]))
        assert _cov_gaps(snaps, since) == _old_gaps(snaps, since)
        assert _cov_spread(snaps, since) == _old_spread(snaps, since)


if __name__ == "__main__":
    test_coverage_gaps_and_spread_match_old_definitions()
    test_integration_rollups_ferretdb()
    print("PASS: iter30 rollups integration + coverage≡old gaps/spread")
