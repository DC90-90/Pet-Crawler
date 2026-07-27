"""iter55 — Salla revenue estimate (Option B) + its leave-one-out back-test.

Salla exposes no sold-counter, so the ranking marks those stores
`not_measurable`. This estimates their revenue from velocity observed on Zid
stores. The estimate must NEVER be merged into the measured `revenue_30d`.

The two modelling choices that decide whether the number means anything:

  * products with NO detected sales contribute velocity 0. Averaging only the
    movers would inflate the rate by the share of the catalogue that never
    sells — most of it, in pet retail.
  * the back-test is LEAVE-ONE-OUT. Estimating a store from a pool that
    includes itself is testing on training data and reports an error far better
    than the method achieves.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_salla_rev")
import salla_revenue_estimate as E  # noqa: E402
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}
DAYS = 30


# ── the modelling choices ────────────────────────────────────────────────────
def test_non_movers_count_as_zero_velocity():
    """The single most consequential choice. 1 product selling 30 units and 9
    selling nothing is 0.1 units/product-day, not 1.0."""
    obs = [{"store_id": "z", "sku": "A", "category": "cat_food", "units": 30}]
    obs += [{"store_id": "z", "sku": f"N{i}", "category": "cat_food", "units": 0}
            for i in range(9)]
    pools = E.build_velocity_pools(obs, DAYS)
    assert pools["global"] == 30 / DAYS / 10
    assert abs(pools["global"] - 0.1) < 1e-9
    # dropping the non-movers would have given 1.0 — a 10x overestimate
    movers_only = E.build_velocity_pools([o for o in obs if o["units"]], DAYS)
    assert abs(movers_only["global"] - 1.0) < 1e-9


def test_mean_not_median_because_we_estimate_a_sum():
    """A catalogue where most products never sell has a MEDIAN velocity of 0,
    which would estimate every Salla store at zero revenue."""
    obs = [{"store_id": "z", "sku": f"N{i}", "category": "c", "units": 0} for i in range(9)]
    obs.append({"store_id": "z", "sku": "A", "category": "c", "units": 300})
    pools = E.build_velocity_pools(obs, DAYS)
    assert pools["global"] > 0, "mean must stay positive where the median is 0"
    import statistics
    assert statistics.median([0] * 9 + [10.0]) == 0.0


def test_pool_precedence_and_confidence():
    obs = [{"store_id": "z", "sku": "KNOWN", "category": "cat_food", "units": 30}]
    obs += [{"store_id": "z", "sku": f"C{i}", "category": "cat_food", "units": 3}
            for i in range(E.MIN_CATEGORY_SAMPLE)]
    pools = E.build_velocity_pools(obs, DAYS)

    # per-SKU wins where we have it
    est, d = E.estimate_store_revenue([{"sku": "KNOWN", "price": 100, "category": "cat_food"}],
                                      pools, DAYS)
    assert d["per_sku"] == 1 and est == round(1.0 * 100 * DAYS, 2)

    # unseen SKU in a well-sampled category -> category pool
    _e, d = E.estimate_store_revenue([{"sku": "NEW", "price": 100, "category": "cat_food"}],
                                     pools, DAYS)
    assert d["per_category"] == 1 and d["confidence"] == "high"

    # unseen category -> global fallback, and the confidence says so
    _e, d = E.estimate_store_revenue([{"sku": "NEW", "price": 100, "category": "toys"}],
                                     pools, DAYS)
    assert d["global"] == 1 and d["confidence"] == "low"


def test_thin_categories_fall_back_to_global():
    obs = [{"store_id": "z", "sku": f"T{i}", "category": "thin", "units": 3} for i in range(5)]
    obs += [{"store_id": "z", "sku": f"B{i}", "category": "big", "units": 1}
            for i in range(E.MIN_CATEGORY_SAMPLE)]
    pools = E.build_velocity_pools(obs, DAYS)
    assert "thin" not in pools["per_category"], "5 observations must not define a category rate"
    assert "big" in pools["per_category"]
    assert pools["category_sample_sizes"]["thin"] == 5


def test_unpriced_products_are_skipped_not_zero_filled():
    pools = E.build_velocity_pools(
        [{"store_id": "z", "sku": "A", "category": "c", "units": 30}], DAYS)
    est, d = E.estimate_store_revenue(
        [{"sku": "A", "price": None, "category": "c"},
         {"sku": "A", "price": 0, "category": "c"},
         {"sku": "A", "price": 10, "category": "c"}], pools, DAYS)
    assert d["unpriced"] == 2 and d["priced_products"] == 1
    assert est == round(1.0 * 10 * DAYS, 2)


# ── the back-test ────────────────────────────────────────────────────────────
def test_back_test_is_leave_one_out():
    """A store must not contribute to the pool used to estimate itself."""
    # z_fast sells 10x what the others do; if it were in its own pool it would
    # be estimated near-perfectly, which is exactly the illusion to avoid.
    obs, prods, actual = [], {}, {}
    for sid, units in (("z_slow1", 1), ("z_slow2", 1), ("z_fast", 10)):
        prods[sid] = [{"sku": f"S{i}", "price": 100, "category": "c"} for i in range(50)]
        for i in range(50):
            obs.append({"store_id": sid, "sku": f"S{i}", "category": "c", "units": units})
        actual[sid] = 50 * units * 100

    bt = E.back_test(obs, prods, actual, DAYS)
    assert bt["summary"]["leave_one_out"] is True
    fast = next(r for r in bt["per_store"] if r["store_id"] == "z_fast")
    # estimated from the SLOW stores only -> badly underestimated. That honesty
    # is the point of the test.
    assert fast["ratio"] < 0.5, fast
    slow = next(r for r in bt["per_store"] if r["store_id"] == "z_slow1")
    # the slow store is estimated from a pool containing the fast one -> over
    assert slow["ratio"] > 1.5, slow


def test_verdict_bands():
    assert "trustworthy" in E._verdict(12.0, 5)
    assert E._verdict(55.0, 5).startswith("WEAK")
    assert "TOO WEAK" in E._verdict(180.0, 5)
    # too few stores to conclude anything
    assert "inconclusive" in E._verdict(5.0, 2)
    assert "inconclusive" in E._verdict(None, 0)


def test_back_test_reports_near_zero_error_when_stores_are_homogeneous():
    """Sanity floor: identical stores must back-test almost perfectly."""
    obs, prods, actual = [], {}, {}
    for sid in ("a", "b", "c", "d"):
        prods[sid] = [{"sku": f"S{i}", "price": 50, "category": "c"} for i in range(60)]
        for i in range(60):
            obs.append({"store_id": sid, "sku": f"S{i}", "category": "c", "units": 6})
        actual[sid] = 60 * 6 * 50
    bt = E.back_test(obs, prods, actual, DAYS)
    assert bt["summary"]["median_abs_error_pct"] == 0.0, bt["summary"]
    assert bt["summary"]["within_30pct"] == 4
    assert "trustworthy" in bt["summary"]["verdict"]


# ── the endpoint ─────────────────────────────────────────────────────────────
async def _seed(db):
    for c in ("stores", "products", "sku_store_coverage", "sku_sales_daily"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": "zid1", "name": "Aleef", "domain": "aleef.com", "platform": "zid"},
        {"id": "zid2", "name": "Petsy", "domain": "petsysa.com", "platform": "zid"},
        {"id": "zid3", "name": "Hobba", "domain": "hobbapet.com", "platform": "zid"},
        {"id": "sal1", "name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla"},
        {"id": "sal2", "name": "Caty", "domain": "caty-store.com", "platform": "salla"},
    ])
    now = server.datetime.now(server.timezone.utc)
    prods, cov, sales = [], [], []
    for i in range(60):
        sku = f"SKU-{i}"
        prods.append({"id": f"p{i}", "sku": sku, "category": "cat_food"})
        for sid in ("zid1", "zid2", "zid3", "sal1", "sal2"):
            cov.append({"_id": f"{sku}|{sid}", "sku": sku, "store_id": sid,
                        "last_priced_price": 100.0, "last_priced_at": now,
                        "last_in_stock": True, "last_seen_any_at": now})
        for sid in ("zid1", "zid2", "zid3"):
            sales.append({"store_id": sid, "sku": sku, "date": server._metric_day_str(now),
                          "units_sold": 3, "rev_sold": 300.0,
                          "units_qty": 0, "rev_qty": 0.0, "qty_drop": 0})
    await db.products.insert_many(prods)
    await db.sku_store_coverage.insert_many(cov)
    await db.sku_sales_daily.insert_many(sales)
    server.db = db


def test_preview_is_read_only_and_keeps_the_estimate_separate():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        counts_before = {c: await db[c].count_documents({})
                         for c in ("stores", "products", "sku_store_coverage", "sku_sales_daily")}

        out = await server.salla_revenue_estimate_preview(days=DAYS, user=SUPER)

        assert out["read_only"] is True and out["wired_into_ranking"] is False
        # the estimate is its own field on its own basis — never revenue_30d
        for r in out["projected_salla_stores"]:
            assert "revenue_est" in r and "revenue_30d" not in r
            assert r["basis"] == "category_velocity_estimate"
            assert r["confidence"] in ("high", "medium", "low", "none")
        # only Salla stores are projected; Zid stores keep their measured figure
        assert {r["name"] for r in out["projected_salla_stores"]} == {"Zarafa", "Caty"}
        assert {r["name"] for r in out["measured_stores"]} == {"Aleef", "Petsy", "Hobba"}
        for r in out["measured_stores"]:
            assert "revenue_est" not in r

        # back-test ran leave-one-out over the 3 Zid stores
        bt = out["back_test"]
        assert bt["summary"]["stores_tested"] == 3
        assert bt["summary"]["leave_one_out"] is True
        # homogeneous fixture -> the estimate should land on the money
        assert bt["summary"]["median_abs_error_pct"] == 0.0, bt["summary"]

        # each Salla store: 60 products x 100 SAR x 0.1 units/day x 30 days
        z = next(r for r in out["projected_salla_stores"] if r["name"] == "Zarafa")
        assert z["products_priced"] == 60
        assert z["revenue_est"] == round(60 * 100 * (3 / DAYS) * DAYS, 2)
        assert z["est_rank_among_salla"] in (1, 2)

        # ZERO writes
        for c, n in counts_before.items():
            assert await db[c].count_documents({}) == n, c
    asyncio.run(main())


def test_preview_requires_super_admin():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        try:
            await server.salla_revenue_estimate_preview(days=DAYS,
                                                        user={"role": "viewer", "email": "v@v"})
            raise AssertionError("viewer must be rejected")
        except HTTPException as e:
            assert e.status_code == 403
    asyncio.run(main())


def test_ranking_is_untouched_by_this_change():
    """Contract: Salla stores still report not_measurable until this is wired in
    deliberately."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        out = await server._store_ranking_compute(db)
        rows = {r["name"]: r for r in out["stores"]}
        for name in ("Zarafa", "Caty"):
            assert rows[name]["revenue_30d"] is None, rows[name]
            assert rows[name]["revenue_status"] == "not_measurable", rows[name]
            assert "revenue_est" not in rows[name]
    asyncio.run(main())


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
    print("PASS: iter55 salla revenue estimate")
