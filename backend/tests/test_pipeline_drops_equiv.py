"""iter28 — prove the pipeline_drops rewrite is output-identical.

The FerretDB sandbox shim implements neither $push (old pipeline) nor $topN
(new pipeline), so this validates the SEMANTIC equivalence with a faithful
Python model of each pipeline's documented behavior, across many randomized
snapshot sets. The drop COUNT must be identical.

OLD: $match → $sort(sku,store,crawled_at desc) → $group $push(all prices) →
     $match(size>=2 AND prices[0] < prices[1]) → $count
NEW: $match → $group $topN(n=2, sortBy crawled_at desc, output price) →
     $match(size>=2 AND prices[0] < prices[1]) → $count

Both reduce to: per (sku,store), take the latest two prices by crawled_at; it's
a drop iff latest < second-latest. $topN(2) == first 2 of the desc-sorted list.
"""
import random


def _old_pipeline_drops(snaps):
    # $sort by (sku, store_id, crawled_at desc), then $push all prices per group
    ordered = sorted(snaps, key=lambda s: (s["sku"], s["store_id"], -s["crawled_at"]))
    groups = {}
    for s in ordered:
        groups.setdefault((s["sku"], s["store_id"]), []).append(s["price"])
    drops = 0
    for prices in groups.values():
        if len(prices) >= 2 and prices[0] < prices[1]:
            drops += 1
    return drops


def _new_pipeline_drops(snaps):
    # $group $topN(n=2, sortBy crawled_at desc): latest two prices per group
    groups = {}
    for s in snaps:
        groups.setdefault((s["sku"], s["store_id"]), []).append((s["crawled_at"], s["price"]))
    drops = 0
    for rows in groups.values():
        top2 = [p for _, p in sorted(rows, key=lambda cp: -cp[0])[:2]]
        if len(top2) >= 2 and top2[0] < top2[1]:
            drops += 1
    return drops


def _chunked_by_store_drops(snaps):
    """iter29 model — _price_drops_count(): partition snapshots by store_id, run
    the $topN drop-count per store (grouping by sku alone, since store is fixed),
    and SUM. Must equal the single-pass count because every (sku,store) group
    lives in exactly one store's partition — no group spans a store boundary."""
    by_store = {}
    for s in snaps:
        by_store.setdefault(s["store_id"], []).append(s)
    total = 0
    for sid, store_snaps in by_store.items():
        # per store: group by sku, latest two prices, drop iff latest < previous
        groups = {}
        for s in store_snaps:
            groups.setdefault(s["sku"], []).append((s["crawled_at"], s["price"]))
        for rows in groups.values():
            top2 = [p for _, p in sorted(rows, key=lambda cp: -cp[0])[:2]]
            if len(top2) >= 2 and top2[0] < top2[1]:
                total += 1
    return total


def _rand_snaps(rng, n_groups, max_per_group):
    snaps = []
    for g in range(n_groups):
        sku = f"SKU{g % 7}"          # deliberate sku collisions across stores
        store = f"S{g // 7}"
        base_t = rng.randint(1_000_000, 2_000_000)
        for k in range(rng.randint(0, max_per_group)):
            # distinct crawled_at per snapshot within a group (as in production:
            # one snapshot per crawl) — spaced so no ties
            t = base_t - k * rng.randint(1, 50)
            snaps.append({"sku": sku, "store_id": store, "crawled_at": t,
                          "price": round(rng.uniform(5, 300), 2)})
    rng.shuffle(snaps)  # pipelines must not depend on input order
    return snaps


def test_old_and_new_drops_identical_random():
    rng = random.Random(20260728)
    for _ in range(2000):
        snaps = _rand_snaps(rng, n_groups=rng.randint(1, 40), max_per_group=8)
        old = _old_pipeline_drops(snaps)
        # iter28 ($topN single pass) and iter29 (per-store chunked sum) must both
        # equal the original $sort+$push count.
        assert old == _new_pipeline_drops(snaps)
        assert old == _chunked_by_store_drops(snaps)


def test_edge_cases():
    # single snapshot in a group → no drop (size < 2) in both
    s = [{"sku": "A", "store_id": "S", "crawled_at": 100, "price": 10.0}]
    assert _old_pipeline_drops(s) == _new_pipeline_drops(s) == 0
    # exactly a drop: latest (t=200) cheaper than previous (t=100)
    s = [{"sku": "A", "store_id": "S", "crawled_at": 100, "price": 20.0},
         {"sku": "A", "store_id": "S", "crawled_at": 200, "price": 10.0}]
    assert _old_pipeline_drops(s) == _new_pipeline_drops(s) == 1
    # a rise (latest dearer) → not a drop
    s = [{"sku": "A", "store_id": "S", "crawled_at": 100, "price": 10.0},
         {"sku": "A", "store_id": "S", "crawled_at": 200, "price": 20.0}]
    assert _old_pipeline_drops(s) == _new_pipeline_drops(s) == 0
    # 3+ snapshots: only the latest TWO matter — an older rise must be ignored.
    # prices over time: t100=5 (oldest), t200=30, t300=10 (latest) → 10<30 = drop
    s = [{"sku": "A", "store_id": "S", "crawled_at": 100, "price": 5.0},
         {"sku": "A", "store_id": "S", "crawled_at": 200, "price": 30.0},
         {"sku": "A", "store_id": "S", "crawled_at": 300, "price": 10.0}]
    assert _old_pipeline_drops(s) == _new_pipeline_drops(s) == _chunked_by_store_drops(s) == 1
    # same sku in two stores, one drops one rises → exactly one drop, and the
    # per-store chunking must not merge or split the two stores' groups.
    s = [{"sku": "A", "store_id": "S1", "crawled_at": 100, "price": 20.0},
         {"sku": "A", "store_id": "S1", "crawled_at": 200, "price": 10.0},   # drop
         {"sku": "A", "store_id": "S2", "crawled_at": 100, "price": 10.0},
         {"sku": "A", "store_id": "S2", "crawled_at": 200, "price": 25.0}]   # rise
    assert _old_pipeline_drops(s) == _new_pipeline_drops(s) == _chunked_by_store_drops(s) == 1


if __name__ == "__main__":
    test_old_and_new_drops_identical_random()
    test_edge_cases()
    print("PASS: pipeline_drops old ≡ new ≡ chunked-by-store across 2000 random sets + edge cases")


# ── iter29: structural test of the real _price_drops_count helper ──────────────
# FerretDB can't run $topN, so we drive server._price_drops_count with a mock db
# that records the pipelines it receives and returns canned per-store counts.
# This proves: one aggregate per store, each scoped to that store_id, grouped by
# sku with a bounded $topN(2), and the per-store counts summed.
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, n):
        return self._rows[:n]


class _FakeSnapshots:
    def __init__(self, drops_by_store):
        self.drops_by_store = drops_by_store
        self.pipelines = []

    async def distinct(self, field, flt):
        assert field == "store_id"
        assert "crawled_at" in flt and "$gte" in flt["crawled_at"]
        return list(self.drops_by_store.keys())

    def aggregate(self, pipeline, allowDiskUse=False):
        assert allowDiskUse is True
        self.pipelines.append(pipeline)
        sid = pipeline[0]["$match"]["store_id"]
        n = self.drops_by_store[sid]
        return _FakeCursor([{"drops": n}] if n else [])


class _FakeDB:
    def __init__(self, drops_by_store):
        self.product_snapshots = _FakeSnapshots(drops_by_store)


def test_price_drops_count_helper_partitions_and_sums():
    os.environ.setdefault("DB_NAME", "equiv_probe")
    import server
    from datetime import datetime, timezone, timedelta

    drops_by_store = {"storeA": 5, "storeB": 0, "storeC": 12}
    db = _FakeDB(drops_by_store)
    since = datetime.now(timezone.utc) - timedelta(days=30)

    total = asyncio.get_event_loop().run_until_complete(server._price_drops_count(db, since))
    assert total == 17, total  # 5 + 0 + 12

    snaps = db.product_snapshots
    assert len(snaps.pipelines) == 3  # exactly one aggregation per store
    for pipe in snaps.pipelines:
        assert pipe[0]["$match"]["store_id"] in drops_by_store
        assert pipe[0]["$match"]["confidence_score"]["$gte"] == server.MIN_AGGREGATION_CONFIDENCE
        grp = pipe[1]["$group"]
        assert grp["_id"] == "$sku"                       # store fixed → group by sku
        assert grp["prices"]["$topN"]["n"] == 2           # bounded to latest two
        assert grp["prices"]["$topN"]["sortBy"] == {"crawled_at": -1}
        assert pipe[-1] == {"$count": "drops"}


def test_price_drops_count_empty_window():
    import server
    from datetime import datetime, timezone, timedelta
    db = _FakeDB({})
    since = datetime.now(timezone.utc) - timedelta(days=30)
    total = asyncio.get_event_loop().run_until_complete(server._price_drops_count(db, since))
    assert total == 0
