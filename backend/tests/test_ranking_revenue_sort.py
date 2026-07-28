"""iter62 — the Market Strength Ranking sorts by REVENUE, not by the score.

Client requirement: highest sales first. All three revenue tiers reduce to one
comparable axis, so a Salla store's ±50% estimate competes directly with a Zid
store's measured figure and the leaderboard reads as a sales leaderboard.

Two things this must NOT do:

no fake zero        a store with no revenue figure of any kind goes last for
                    HAVING NO FIGURE. Assigning it 0.0 would assert we looked
                    and it sold nothing, which we did not and it may not have.
                    A genuine measured 0 — an active Zid ledger with no orders
                    in the window — keeps its 0.0 and still outranks it.
no laundering       sorting measured and estimated values together must not
                    make them LOOK alike. The three revenue fields stay
                    separate, `revenue_tier` still names the basis, the row
                    still carries `revenue_is_estimate`, and the UI still
                    renders an estimate in amber with its "ESTIMATE · ±50%"
                    tag. The client has to be able to read which ranking
                    positions rest on measurement and which on a projection.

iter56 shipped with "the leaderboard order stays on measured strength, so a
±52% estimate cannot reorder anyone". That protection is deliberately being
traded away here on an explicit client instruction; the labelling is what
replaces it, so these tests pin the labelling hardest.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_rank_revenue")
import server  # noqa: E402

_rev = server._ranking_revenue_value


def _row(name, score=50.0, exact=None, approx=None, est=None, products=10):
    r = {
        "store_id": f"s-{name}", "name": name, "platform": "salla",
        "is_own_store": False, "score": score,
        "components": {"breadth": {"score": 0.5, "products": products},
                       "price": {"score": 0.5, "avg_percentile": None,
                                 "cheapest_rate": None, "shared_products": 0},
                       "stock": {"score": 0.5, "in_stock": 5},
                       "freshness": {"score": 0.5, "fresh_products": 5}},
        "revenue_30d": exact,
        "revenue_status": "computed" if exact is not None else "accumulating",
        "revenue_approx": ({"revenue": approx, "usable": True, "coverage_pct": 40.0,
                            "products_measured": 4, "products_total": 10}
                           if approx is not None else None),
        "revenue_est_salla": ({"revenue_est": est, "band_pct": 50.0,
                               "range_low": est * 0.5, "range_high": est * 1.5,
                               "products_priced": 10, "basis": "category_velocity_estimate",
                               "label": "rough_estimate"} if est is not None else None),
        "overlap": 0, "stale": False,
    }
    r["revenue_tier"] = ("exact" if exact is not None
                         else "measured_approx" if approx is not None
                         else "estimated" if est is not None else "none")
    return r


def _sorted(rows):
    """The exact sort _store_ranking_compute applies."""
    for r in rows:
        val, basis = _rev(r)
        r["revenue_rank_value"] = val
        r["revenue_rank_basis"] = basis
        r["revenue_is_estimate"] = basis == "estimated"
    rows.sort(key=lambda r: (r["revenue_rank_value"] is None,
                             -(r["revenue_rank_value"] or 0.0),
                             -r["score"],
                             -r["components"]["breadth"]["products"],
                             r["name"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ── Primary requirement: revenue descending ─────────────────────────────────

def test_stores_sort_by_revenue_descending():
    rows = _sorted([
        _row("Petsy", exact=507_000),
        _row("Mowkly", est=715_000),
        _row("Aleef", approx=180_000),
        _row("Hobba", est=42_000),
    ])
    assert [r["name"] for r in rows] == ["Mowkly", "Petsy", "Aleef", "Hobba"]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4]


def test_the_strength_score_no_longer_drives_the_order():
    """A weak store with high sales must outrank a strong store with low sales
    — that is the whole point of the change."""
    rows = _sorted([
        _row("StrongButSmall", score=98.0, exact=10_000),
        _row("WeakButHuge", score=12.0, exact=900_000),
    ])
    assert [r["name"] for r in rows] == ["WeakButHuge", "StrongButSmall"]


def test_measured_507k_ranks_above_estimated_400k():
    """The unified axis: a bigger ESTIMATE still loses to a bigger MEASURED
    figure only because of the numbers, not because of the tier."""
    rows = _sorted([_row("EstimatedStore", est=400_000),
                    _row("MeasuredStore", exact=507_000)])
    assert [r["name"] for r in rows] == ["MeasuredStore", "EstimatedStore"]
    assert rows[0]["revenue_rank_basis"] == "exact"
    assert rows[1]["revenue_rank_basis"] == "estimated"


def test_a_bigger_estimate_does_outrank_a_smaller_measured_figure():
    """Mixed together really means mixed — the tiers are not a pre-sort."""
    rows = _sorted([_row("MeasuredSmall", exact=100_000),
                    _row("EstimatedBig", est=715_000)])
    assert [r["name"] for r in rows] == ["EstimatedBig", "MeasuredSmall"]


def test_score_breaks_ties_at_equal_revenue():
    rows = _sorted([_row("LowScore", score=20.0, exact=100_000),
                    _row("HighScore", score=90.0, exact=100_000)])
    assert [r["name"] for r in rows] == ["HighScore", "LowScore"]


# ── Requirement 5: no fake zero ─────────────────────────────────────────────

def test_a_store_with_no_revenue_figure_sorts_last():
    rows = _sorted([_row("NoData"), _row("Small", exact=1.0), _row("Big", est=500.0)])
    assert [r["name"] for r in rows] == ["Big", "Small", "NoData"]
    assert rows[-1]["revenue_rank_basis"] == "none"


def test_no_revenue_is_none_not_a_fabricated_zero():
    row = _row("NoData")
    assert _rev(row) == (None, "none")
    _sorted([row])
    assert row["revenue_rank_value"] is None      # NOT 0.0
    assert row["revenue_30d"] is None
    assert row["revenue_tier"] == "none"


def test_a_genuinely_measured_zero_outranks_a_store_with_no_figure():
    """0 SAR from a live ledger is a measurement; absence is not. They must not
    collapse to the same rank."""
    rows = _sorted([_row("NoData"), _row("MeasuredZero", exact=0.0)])
    assert [r["name"] for r in rows] == ["MeasuredZero", "NoData"]
    assert rows[0]["revenue_rank_value"] == 0.0 and rows[0]["revenue_rank_basis"] == "exact"
    assert rows[1]["revenue_rank_value"] is None


def test_stores_with_no_figure_keep_their_strength_order_among_themselves():
    rows = _sorted([_row("WeakNoData", score=10.0), _row("StrongNoData", score=80.0),
                    _row("HasRevenue", exact=5.0)])
    assert [r["name"] for r in rows] == ["HasRevenue", "StrongNoData", "WeakNoData"]


# ── Requirement 3: the honesty guard survives the re-sort ───────────────────

def test_estimate_labels_survive_the_resort():
    rows = _sorted([_row("Est", est=715_000), _row("Measured", exact=507_000)])
    est = next(r for r in rows if r["name"] == "Est")
    assert est["revenue_tier"] == "estimated"
    assert est["revenue_is_estimate"] is True
    assert est["revenue_est_salla"]["band_pct"] == 50.0
    assert est["revenue_est_salla"]["label"] == "rough_estimate"
    assert est["revenue_est_salla"]["range_low"] < est["revenue_est_salla"]["range_high"]
    # the estimate is NOT laundered into the measured field
    assert est["revenue_30d"] is None


def test_the_three_revenue_fields_stay_separate():
    """Nothing in the re-sort may collapse them into one column — that is what
    would let a +/-50% projection read as a measurement."""
    for kwargs, tier, populated in (
            ({"exact": 1.0}, "exact", "revenue_30d"),
            ({"approx": 1.0}, "measured_approx", "revenue_approx"),
            ({"est": 1.0}, "estimated", "revenue_est_salla")):
        r = _sorted([_row("X", **kwargs)])[0]
        assert r["revenue_tier"] == tier
        assert r[populated] is not None
        for other in ("revenue_30d", "revenue_approx", "revenue_est_salla"):
            if other != populated:
                assert r[other] is None, (tier, other)


def test_measured_approx_is_not_reported_as_an_estimate():
    """The Salla sold-badge diff is a real observation and keeps its own tier
    even though it is also approximate."""
    r = _sorted([_row("Approx", approx=180_000)])[0]
    assert r["revenue_rank_basis"] == "measured_approx"
    assert r["revenue_is_estimate"] is False


def test_an_unusable_approx_falls_through_to_the_estimate():
    r = _row("X", est=400.0)
    r["revenue_approx"] = {"revenue": 0.0, "usable": False, "coverage_pct": 0.0}
    assert _rev(r) == (400.0, "estimated")


# ── Requirement 4: the strength score is still there ────────────────────────

def test_every_row_still_carries_the_strength_score_and_components():
    rows = _sorted([_row("A", score=71.4, exact=10.0), _row("B", score=33.0)])
    for r in rows:
        assert isinstance(r["score"], float)
        assert set(r["components"]) == {"breadth", "price", "stock", "freshness"}


# ── Precedence of the tiers ────────────────────────────────────────────────

def test_evidence_quality_decides_which_figure_is_used_not_size():
    """A store carrying more than one tier ranks on the BEST evidence, even
    when a weaker tier would give it a flattering bigger number."""
    r = _row("Multi", exact=100.0, approx=999_999.0, est=888_888.0)
    assert _rev(r) == (100.0, "exact")
    r2 = _row("Multi2", approx=100.0, est=888_888.0)
    assert _rev(r2) == (100.0, "measured_approx")


# ── End-to-end through the real endpoint ───────────────────────────────────
# The cases above pin the ordering rule. These run _store_ranking_compute
# itself, because requirement 2 — the own store getting an estimate while its
# Zid orders ledger is still empty — is a property of that function, not of the
# sort key.

from datetime import timedelta  # noqa: E402

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
OWN = "own-store-id"

# (store_id, name, platform, products, unit price) — enough coverage rows for
# the estimator to have a catalogue to project onto.
FIXTURE_STORES = [
    (OWN, "Pets houses", "zid", 40, 120.0),
    ("mowkly", "Mowkly", "salla", 60, 150.0),
    ("petsy", "Petsy", "zid", 50, 130.0),
    ("hobba", "Hobba", "salla", 12, 90.0),
    ("empty", "EmptyStore", "salla", 3, 0.0),      # priced 0 -> no estimate
]


async def _seed(db):
    for c in ("stores", "my_products", "products", "sku_store_coverage",
              "product_matches", "product_snapshots"):
        await db[c].delete_many({})
    now = server.datetime.now(server.timezone.utc)
    await db.stores.insert_many([
        {"id": sid, "name": nm, "platform": pf, "domain": f"{sid}.com",
         "is_own_store": sid == OWN}
        for sid, nm, pf, _n, _p in FIXTURE_STORES])
    prods, cov, mine = [], [], []
    for sid, _nm, _pf, n, price in FIXTURE_STORES:
        for i in range(n):
            sku = f"{sid}-SKU-{i}"
            prods.append({"sku": sku, "name_ar": "منتج", "name_en": f"Product {i}",
                          "category": "cat_food"})
            cov.append({"sku": sku, "store_id": sid, "last_priced_price": price,
                        "last_in_stock": True, "last_priced_at": now - timedelta(days=1),
                        "last_seen_any_at": now - timedelta(hours=2),
                        "last_sold_pos_at": now - timedelta(days=2),
                        "last_usable_qty_at": now - timedelta(days=2)})
            if sid == OWN:
                mine.append({"sku": sku, "price": price, "in_stock": True,
                             "quantity": 5, "is_own_store": True, "store_id": OWN,
                             "last_synced_at": now - timedelta(hours=1)})
    await db.products.insert_many(prods)
    await db.sku_store_coverage.insert_many(cov)
    await db.my_products.insert_many(mine)
    return db


async def _compute(db, *, own_revenue, sales_pairs):
    """Run the real ranking with the three external revenue sources stubbed.

    _own_orders_aggregate (Zid ledger), _sales_pairs_from_rollups (competitor
    rollups) and _compute_market_position_summary each own a large aggregation
    of their own; substituting them keeps this test about the RANKING.
    """
    real = (server._own_orders_aggregate, server._sales_pairs_from_rollups,
            server._compute_market_position_summary)

    async def _own(_db, _since, _end=None):
        return None if own_revenue is None else {"revenue": own_revenue, "orders": 3}

    async def _pairs(_db, _since, store_id=None):
        return sales_pairs

    async def _mp(_db):
        return {"avg_percentile": 45.0, "ranked_products": 10, "cheapest_count": 3}

    server._own_orders_aggregate = _own
    server._sales_pairs_from_rollups = _pairs
    server._compute_market_position_summary = _mp
    try:
        return await server._store_ranking_compute(db)
    finally:
        (server._own_orders_aggregate, server._sales_pairs_from_rollups,
         server._compute_market_position_summary) = real


def _by_name(out):
    return {r["name"]: r for r in out["stores"]}


def test_endpoint_sorts_by_revenue_and_reports_the_basis():
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _compute(db, own_revenue=None, sales_pairs=[
            {"store_id": "petsy", "sku": "petsy-SKU-0", "units": 3900, "revenue": 507_000.0},
        ])
        assert out["sorted_by"] == "revenue_desc"
        names = [r["name"] for r in out["stores"]]
        vals = [r["revenue_rank_value"] for r in out["stores"]]
        # descending, with every None at the end
        seen_none = False
        for v in vals:
            if v is None:
                seen_none = True
            else:
                assert not seen_none, vals
        numeric = [v for v in vals if v is not None]
        assert numeric == sorted(numeric, reverse=True), list(zip(names, vals))
        assert _by_name(out)["Petsy"]["revenue_rank_basis"] == "exact"
        assert out["ranked_on_measured"] >= 1
    asyncio.run(main())


def test_own_store_gets_an_estimate_while_its_ledger_is_empty():
    """Requirement 2 — 'Accumulating' with no number would sink us to the
    bottom under a revenue sort as though we sold nothing."""
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _compute(db, own_revenue=None, sales_pairs=[
            {"store_id": "petsy", "sku": "petsy-SKU-0", "units": 100, "revenue": 13_000.0},
        ])
        own = _by_name(out)["Pets houses"]
        assert own["revenue_30d"] is None                  # ledger still empty
        assert own["revenue_est_salla"] is not None        # but we have a value
        assert own["revenue_est_salla"]["band_pct"] == 50.0
        assert own["revenue_rank_basis"] == "estimated"    # ...and it is tagged
        assert own["revenue_is_estimate"] is True
        assert own["revenue_rank_value"] > 0
        assert own["revenue_tier"] == "estimated"
    asyncio.run(main())


def test_own_store_uses_the_real_ledger_once_it_syncs():
    """The estimate is a stand-in, not a permanent substitute."""
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _compute(db, own_revenue=88_000.0, sales_pairs=[])
        own = _by_name(out)["Pets houses"]
        assert own["revenue_30d"] == 88_000.0
        assert own["revenue_est_salla"] is None            # no estimate alongside
        assert own["revenue_rank_basis"] == "exact"
        assert own["revenue_is_estimate"] is False
    asyncio.run(main())


def test_own_store_products_do_not_poison_the_velocity_pool():
    """Found while wiring requirement 2. _units_by comes from the COMPETITOR
    sales rollups, which by construction hold nothing for our own store, so
    every own product was entering the pool as a units=0 "non-mover". Those
    zeros are an artefact of where the data comes from, not evidence that we
    sold nothing: they dragged the category mean down for every store estimated
    from it, and pinned our own per-SKU velocity at exactly 0 — which is why the
    own-store estimate came out 0.0.

    Asserted via a competitor, so this cannot pass just because the own store
    is now excluded from its own estimate."""
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _compute(db, own_revenue=None, sales_pairs=[
            {"store_id": "petsy", "sku": "petsy-SKU-0", "units": 100, "revenue": 13_000.0},
        ])
        hobba = _by_name(out)["Hobba"]
        # 12 products x 90 SAR x category velocity. With our 40 phantom zeros in
        # the pool the mean was 100/(90*30); without them it is 100/(50*30).
        assert hobba["revenue_est_salla"]["revenue_est"] == 2160.0
        assert _by_name(out)["Pets houses"]["revenue_rank_value"] == 9600.0
    asyncio.run(main())


def test_endpoint_counts_how_much_of_the_order_rests_on_estimates():
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _compute(db, own_revenue=None, sales_pairs=[
            {"store_id": "petsy", "sku": "petsy-SKU-0", "units": 100, "revenue": 13_000.0},
        ])
        total = (out["ranked_on_measured"] + out["ranked_on_estimate"]
                 + out["no_revenue_value"])
        assert total == out["total_stores"]
        assert out["ranked_on_estimate"] >= 1              # own store at minimum
        for r in out["stores"]:
            assert r["revenue_is_estimate"] == (r["revenue_rank_basis"] == "estimated")
    asyncio.run(main())


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception:
            bad += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
