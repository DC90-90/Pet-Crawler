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
        assert _old_pipeline_drops(snaps) == _new_pipeline_drops(snaps)


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
    assert _old_pipeline_drops(s) == _new_pipeline_drops(s) == 1


if __name__ == "__main__":
    test_old_and_new_drops_identical_random()
    test_edge_cases()
    print("PASS: pipeline_drops old ≡ new across 2000 random sets + edge cases")
