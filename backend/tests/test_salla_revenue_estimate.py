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

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_salla_rev"
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


# ── iter56: self-tightening band + ranking wiring ────────────────────────────
def test_band_is_fixed_and_never_derived_from_coverage():
    """iter57 — ONE honest wide band. A coverage-derived band would tighten per
    store and imply a precision the ~+/-48% back-test cannot support, and these
    figures inform pricing decisions."""
    assert E.FIXED_BAND_PCT == 50.0
    # the coverage-interpolating helper is GONE, not merely unused — nothing can
    # reintroduce a per-store band by calling it
    assert not hasattr(E, "confidence_band_pct")
    assert not hasattr(E, "BAND_FLOOR_PCT")
    assert not hasattr(E, "BAND_WIDEST_PCT")

    obs = [{"store_id": "z", "sku": "KNOWN", "category": "c", "units": 30}]
    obs += [{"store_id": "z", "sku": f"C{i}", "category": "c", "units": 3}
            for i in range(E.MIN_CATEGORY_SAMPLE)]
    pools = E.build_velocity_pools(obs, DAYS)
    # 0% coverage and 100% coverage must yield the SAME band
    none_matched = [{"sku": f"NEW{i}", "price": 10, "category": "c"} for i in range(4)]
    all_matched = [{"sku": "KNOWN", "price": 10, "category": "c"} for _ in range(4)]
    _e1, b1, c1, _d1 = E.estimate_with_band(none_matched, pools, DAYS)
    _e2, b2, c2, _d2 = E.estimate_with_band(all_matched, pools, DAYS)
    assert c1 == 0.0 and c2 == 1.0, (c1, c2)
    assert b1 == b2 == 50.0, (b1, b2)


def test_coverage_is_still_computed_as_a_diagnostic():
    obs = [{"store_id": "z", "sku": "KNOWN", "category": "c", "units": 30}]
    obs += [{"store_id": "z", "sku": f"C{i}", "category": "c", "units": 3}
            for i in range(E.MIN_CATEGORY_SAMPLE)]
    pools = E.build_velocity_pools(obs, DAYS)
    # 1 of 4 products has real per-SKU velocity -> coverage 25%
    prods = [{"sku": "KNOWN", "price": 10, "category": "c"}] + [
        {"sku": f"NEW{i}", "price": 10, "category": "c"} for i in range(3)]
    est, band, cov, detail = E.estimate_with_band(prods, pools, DAYS)
    assert cov == 0.25 and detail["per_sku"] == 1 and detail["priced_products"] == 4
    # coverage is diagnostic only — it does NOT move the band
    assert band == E.FIXED_BAND_PCT == 50.0


def test_band_does_not_move_as_matching_improves():
    """The band must stay put however much coverage grows — the back-tested
    error is dominated by traffic differences between stores, which matching
    more products does nothing to reduce."""
    base = [{"store_id": "z", "sku": f"C{i}", "category": "c", "units": 3}
            for i in range(E.MIN_CATEGORY_SAMPLE)]
    prods = [{"sku": f"P{i}", "price": 10, "category": "c"} for i in range(10)]
    seen = []
    for matched in (0, 2, 5, 10):
        obs = base + [{"store_id": "z", "sku": f"P{i}", "category": "c", "units": 3}
                      for i in range(matched)]
        pools = E.build_velocity_pools(obs, DAYS)
        _e, band, cov, _d = E.estimate_with_band(prods, pools, DAYS)
        seen.append((cov, band))
    covs = [c for c, _b in seen]
    bands = [b for _c, b in seen]
    assert covs == [0.0, 0.2, 0.5, 1.0], covs
    assert bands == [50.0, 50.0, 50.0, 50.0], bands


async def _seed_ranking(db):
    """Two Zid stores with real sales, three Salla stores with none."""
    for c in ("stores", "products", "sku_store_coverage", "sku_sales_daily",
              "product_matches", "own_store_orders", "my_products"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": "zid1", "name": "Aleef", "domain": "aleef.com", "platform": "zid"},
        {"id": "zid2", "name": "Petsy", "domain": "petsysa.com", "platform": "zid"},
        {"id": "sal1", "name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla"},
        {"id": "sal2", "name": "Caty", "domain": "caty-store.com", "platform": "salla"},
        {"id": "sal3", "name": "Hamtaro", "domain": "hamtaro.sa", "platform": "salla"},
    ])
    now = server.datetime.now(server.timezone.utc)
    # iter76 — the ranking's Salla velocity POOL reads the SEALED KSA window
    # (`ledger.sealed_ksa_window`), which excludes TODAY by design, so a rollup
    # row dated today is invisible to it and every estimate comes out 0.
    sealed_day = server._metric_day_str(now - server.timedelta(days=1))
    prods, cov, sales = [], [], []
    for i in range(60):
        sku = f"SKU-{i}"
        prods.append({"id": f"p{i}", "sku": sku, "category": "cat_food"})
        for sid in ("zid1", "zid2", "sal1"):
            cov.append({"_id": f"{sku}|{sid}", "sku": sku, "store_id": sid,
                        "last_priced_price": 100.0, "last_priced_at": now,
                        "last_in_stock": True, "last_seen_any_at": now})
        for sid in ("zid1", "zid2"):
            sales.append({"store_id": sid, "sku": sku, "date": sealed_day,
                          "units_sold": 3, "rev_sold": 300.0,
                          "units_qty": 0, "rev_qty": 0.0, "qty_drop": 0})
    # sal2 carries products NO Zid store sells -> 0% coverage -> widest band
    for i in range(40):
        sku = f"ONLY-{i}"
        prods.append({"id": f"o{i}", "sku": sku, "category": "cat_food"})
        cov.append({"_id": f"{sku}|sal2", "sku": sku, "store_id": "sal2",
                    "last_priced_price": 50.0, "last_priced_at": now,
                    "last_in_stock": True, "last_seen_any_at": now})
    # sal3 half-and-half -> mid band
    for i in range(20):
        cov.append({"_id": f"SKU-{i}|sal3", "sku": f"SKU-{i}", "store_id": "sal3",
                    "last_priced_price": 80.0, "last_priced_at": now,
                    "last_in_stock": True, "last_seen_any_at": now})
    for i in range(20):
        cov.append({"_id": f"ONLY-{i}|sal3", "sku": f"ONLY-{i}", "store_id": "sal3",
                    "last_priced_price": 80.0, "last_priced_at": now,
                    "last_in_stock": True, "last_seen_any_at": now})
    await db.products.insert_many(prods)
    await db.sku_store_coverage.insert_many(cov)
    await db.sku_sales_daily.insert_many(sales)
    server.db = db


def test_ranking_exposes_the_estimate_as_a_labelled_sort_value():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_ranking(db)

        out = await server._store_ranking_compute(db)
        rows = {r["name"]: r for r in out["stores"]}
        order_with = [r["name"] for r in out["stores"]]
        scores_with = {r["name"]: r["score"] for r in out["stores"]}

        # measured stores keep a plain measured figure and NO estimate
        for n in ("Aleef", "Petsy"):
            assert rows[n]["revenue_30d"] is not None
            assert rows[n]["revenue_est_salla"] is None, rows[n]

        # Salla stores: measured stays not_measurable, estimate is separate
        for n in ("Zarafa", "Caty", "Hamtaro"):
            r = rows[n]
            assert r["revenue_30d"] is None and r["revenue_status"] == "not_measurable"
            e = r["revenue_est_salla"]
            assert e and e["revenue_est"] > 0
            assert e["basis"] == "category_velocity_estimate"
            assert e["label"] == "rough_estimate"
            assert e["band_pct"] == 50.0
            assert e["range_low"] == round(e["revenue_est"] * 0.5, 2)
            assert e["range_high"] == round(e["revenue_est"] * 1.5, 2)
            # nothing downstream can rebuild a tighter, per-store band
            assert "matched_coverage_pct" not in e, e
            assert "products_with_real_velocity" not in e, e
            assert "band_floor_pct" not in e and "band_widest_pct" not in e, e

        # these three stores have 100% / 0% / 50% matched coverage respectively,
        # and all three carry the IDENTICAL band
        assert {rows[n]["revenue_est_salla"]["band_pct"]
                for n in ("Zarafa", "Caty", "Hamtaro")} == {50.0}

        # ── THE CONTRACT (rewritten, iter62) ──
        # This used to assert that the estimate could NOT reorder anyone — the
        # leaderboard ran on the strength score, so a +/-50% number was purely
        # informational. The client has since required a sales leaderboard, so
        # the estimate now PLACES the row. That protection is gone by
        # instruction; what replaces it is labelling, and that is what this now
        # pins hardest.
        #
        # Caty has the HIGHEST strength score (97.6) in this fixture and the
        # smallest revenue, so it moves from the top of the old order to last —
        # exactly the reordering the previous contract forbade.
        caty = rows["Caty"]
        assert caty["score"] == max(r["score"] for r in out["stores"])
        assert caty["rank"] == out["total_stores"]
        order_by_revenue = [r["name"] for r in sorted(
            out["stores"],
            key=lambda r: (r["revenue_rank_value"] is None,
                           -(r["revenue_rank_value"] or 0.0),
                           -r["score"], -r["components"]["breadth"]["products"], r["name"]))]
        assert order_with == order_by_revenue, (order_with, order_by_revenue)
        assert out["sorted_by"] == "revenue_desc"

        # An estimate placing a row must still be READABLE as an estimate — the
        # whole honesty guard now rests here.
        for n in ("Zarafa", "Caty", "Hamtaro"):
            assert rows[n]["revenue_rank_basis"] == "estimated"
            assert rows[n]["revenue_is_estimate"] is True
            assert rows[n]["revenue_tier"] == "estimated"
            assert rows[n]["revenue_30d"] is None       # never laundered
        for n in ("Aleef", "Petsy"):
            assert rows[n]["revenue_is_estimate"] is False
        assert out["ranked_on_estimate"] == 3 and out["ranked_on_measured"] == 2

        # Zarafa's estimate ties with the two MEASURED stores at 18000 and is
        # placed among them — the tiers are genuinely interleaved, not grouped.
        assert rows["Zarafa"]["revenue_rank_value"] == rows["Aleef"]["revenue_rank_value"]

        # score never references the estimate: recompute by hand from components
        for r in out["stores"]:
            c = r["components"]
            expect = round(100 * (server._RANKING_WEIGHTS["breadth"] * c["breadth"]["score"]
                                  + server._RANKING_WEIGHTS["price"] * c["price"]["score"]
                                  + server._RANKING_WEIGHTS["stock"] * c["stock"]["score"]
                                  + server._RANKING_WEIGHTS["freshness"] * c["freshness"]["score"]), 1)
            assert r["score"] == expect, (r["name"], r["score"], expect)
        assert scores_with  # sanity
    asyncio.run(main())


def test_estimate_failure_never_breaks_the_ranking():
    """The estimate is best-effort: if it raises, the leaderboard still renders."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_ranking(db)
        orig = server.salla_build_velocity_pools

        def _boom(*a, **k):
            raise RuntimeError("pools exploded")

        server.salla_build_velocity_pools = _boom
        try:
            out = await server._store_ranking_compute(db)
        finally:
            server.salla_build_velocity_pools = orig
        assert len(out["stores"]) == 5
        for r in out["stores"]:
            assert r["revenue_est_salla"] is None
            assert r["score"] is not None
    asyncio.run(main())
