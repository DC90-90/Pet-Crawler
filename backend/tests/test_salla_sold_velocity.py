"""iter59 — Salla sold-count capture, diffed velocity, and the three revenue tiers.

Salla publishes a CUMULATIVE units-sold counter (`sold_quantity`, the number
behind "تم بيعه أكثر من N مرة"). _normalize_raw_product checked five field names
and none of them was Salla's, so every Salla product read 0 and those stores
were reported "not measurable". The value was parsed and thrown away before the
snapshot was written.

With it persisted, velocity is a diff between crawls — the same shape as the Zid
path — which makes Salla revenue MEASURED. It is labelled "measured (approx.)"
rather than plain measured because Salla buckets and caps the badge, so a diff
is a real observation but not an exact unit count.

Three tiers, three separate fields, so nothing can conflate them:
    revenue_30d        exact             Zid ledger / stock signals
    revenue_approx     measured (approx) Salla sold-badge diff
    revenue_est_salla  estimated ±50%    category velocity fallback
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_salla_sold")
import crawlers  # noqa: E402
import salla_sold_velocity as V  # noqa: E402
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}


def _at(days_ago):
    return server.datetime.now(server.timezone.utc) - server.timedelta(days=days_ago)


# ── 1. capture: the field name that was missing ─────────────────────────────
def test_salla_sold_quantity_is_extracted_and_no_longer_discarded():
    """The whole bug: sold_quantity was not in the candidate tuple."""
    assert "sold_quantity" in crawlers.SOLD_FIELD_CANDIDATES
    assert crawlers.SOLD_FIELD_CANDIDATES[0] == "sold_quantity", \
        "Salla's name must win over a decoy sold_count: 0"

    salla = {"id": 1, "name": "X", "sku": "S1", "price": {"amount": 50},
             "sold_quantity": 120, "quantity": "5", "status": "sale"}
    norm = crawlers._normalize_raw_product(salla, "Zarafa")
    assert norm["sold_count"] == 120
    assert norm["sold_count_cumulative"] == 120
    assert norm["sold_count_capped"] is False

    # Zid keeps working through the same extractor
    zid = {"id": 2, "name": "Y", "sku": "S2", "price": 30, "sold_count": 42}
    assert crawlers._normalize_raw_product(zid, "Aleef")["sold_count_cumulative"] == 42


def test_capped_badge_readings_are_flagged():
    for raw_val, expect in [("1000+", 1000), ("أكثر من 1000", 1000),
                            ("more than 500", 500), ("over 250", 250)]:
        units, capped = crawlers._extract_sold_count({"sold_quantity": raw_val})
        assert units == expect and capped is True, (raw_val, units, capped)
    # a plain number is NOT capped — flagging every exact 1000 would bin real data
    assert crawlers._extract_sold_count({"sold_quantity": 1000}) == (1000, False)
    assert crawlers._extract_sold_count({"sold_quantity": "1,250"}) == (1250, False)
    assert crawlers._extract_sold_count({"sold_quantity": "n/a"}) == (0, False)
    assert crawlers._extract_sold_count({}) == (0, False)


def test_snapshot_carries_the_cumulative_counter():
    """It must reach product_snapshots — the field was parsed then dropped."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        for c in ("products", "product_snapshots"):
            await db[c].delete_many({})
        store = {"id": "sal", "name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla"}
        raw = [{"id": 7, "name": "Whiskas", "sku": "W-1", "price": {"amount": 12.0},
                "sold_quantity": "1000+", "quantity": "3", "status": "sale"},
               {"id": 8, "name": "Felix", "sku": "F-1", "price": {"amount": 9.0},
                "sold_quantity": 44, "quantity": "9", "status": "sale"}]
        await crawlers.process_crawled_products(
            db, store, raw, server.datetime.now(server.timezone.utc), tier=1, confidence=95)

        f = await db.product_snapshots.find_one({"sku": "F-1"}, {"_id": 0})
        assert f["sold_count_cumulative"] == 44 and f["sold_count_capped"] is False
        w = await db.product_snapshots.find_one({"sku": "W-1"}, {"_id": 0})
        assert w["sold_count_cumulative"] == 1000 and w["sold_count_capped"] is True
    asyncio.run(main())


# ── 2. velocity by diffing ─────────────────────────────────────────────────
def test_two_crawls_yield_real_velocity():
    d = V.diff_series([
        {"at": _at(7), "value": 100, "capped": False},
        {"at": _at(0), "value": 137, "capped": False},
    ])
    assert d["units"] == 37 and d["status"] == "measured_approx"
    assert d["steps"] == 1 and d["resets"] == 0


def test_first_crawl_is_a_baseline_not_zero_sales():
    d = V.diff_series([{"at": _at(0), "value": 100, "capped": False}])
    assert d["status"] == "baseline_only"
    assert d["units"] is None, "one reading must be 'no data', never 0 sales"


def test_counter_reset_is_skipped_not_counted_as_negative():
    """A republish resets the counter. One reset must not wipe out the window."""
    d = V.diff_series([
        {"at": _at(9), "value": 500, "capped": False},
        {"at": _at(6), "value": 540, "capped": False},   # +40
        {"at": _at(3), "value": 12, "capped": False},    # RESET — skipped
        {"at": _at(0), "value": 30, "capped": False},    # +18
    ])
    assert d["resets"] == 1
    assert d["units"] == 58, d          # 40 + 18, the -528 never applied
    assert d["units"] > 0


def test_capped_readings_are_excluded_from_the_diff():
    d = V.diff_series([
        {"at": _at(6), "value": 1000, "capped": True},
        {"at": _at(3), "value": 1000, "capped": True},
        {"at": _at(0), "value": 1000, "capped": True},
    ])
    assert d["status"] == "all_capped"
    assert d["units"] is None, "a pinned ceiling must not read as 0 sales"
    assert d["capped_readings"] == 3

    # mixed: only the uncapped readings diff
    d2 = V.diff_series([
        {"at": _at(9), "value": 900, "capped": False},
        {"at": _at(6), "value": 1000, "capped": True},    # ignored
        {"at": _at(0), "value": 990, "capped": False},
    ])
    assert d2["units"] == 90 and d2["capped_readings"] == 1


def test_absurd_step_is_clamped():
    d = V.diff_series([
        {"at": _at(3), "value": 10, "capped": False},
        {"at": _at(0), "value": 999999, "capped": False},
    ])
    assert d["clamped_steps"] == 1 and d["units"] == V.MAX_SOLD_STEP


def test_store_revenue_counts_only_diffable_products():
    agg = V.store_revenue_from_velocity([
        {"sku": "a", "units": 10, "price": 20.0, "status": "measured_approx"},
        {"sku": "b", "units": 5, "price": 10.0, "status": "measured_approx"},
        {"sku": "c", "units": None, "price": 30.0, "status": "baseline_only"},
        {"sku": "d", "units": None, "price": 30.0, "status": "all_capped"},
        {"sku": "e", "units": None, "price": None, "status": "no_data"},
    ])
    assert agg["revenue"] == 250.0                 # 10*20 + 5*10
    assert agg["products_measured"] == 2 and agg["products_total"] == 5
    assert agg["products_baseline_only"] == 1 and agg["products_capped"] == 1
    assert agg["coverage_pct"] == 40.0 and agg["usable"] is True
    # nothing diffable -> not usable, so the estimate stays in place
    assert V.store_revenue_from_velocity(
        [{"sku": "z", "units": None, "price": 5, "status": "baseline_only"}])["usable"] is False


# ── 3 & 4. three tiers in the ranking ──────────────────────────────────────
async def _seed_tiers(db):
    for c in ("stores", "products", "product_snapshots", "sku_store_coverage",
              "sku_sales_daily", "my_products", "own_store_orders", "product_matches"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": "zid1", "name": "Aleef", "domain": "aleef.com", "platform": "zid"},
        {"id": "sal_badge", "name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla"},
        {"id": "sal_none", "name": "Caty", "domain": "caty-store.com", "platform": "salla"},
    ])
    now = server.datetime.now(server.timezone.utc)
    prods, cov, snaps, sales = [], [], [], []
    for i in range(40):
        sku = f"K-{i}"
        prods.append({"id": f"p{i}", "sku": sku, "category": "cat_food"})
        for sid, price in (("zid1", 100.0), ("sal_badge", 90.0), ("sal_none", 80.0)):
            cov.append({"_id": f"{sku}|{sid}", "sku": sku, "store_id": sid,
                        "last_priced_price": price, "last_priced_at": now,
                        "last_in_stock": True, "last_seen_any_at": now})
        sales.append({"store_id": "zid1", "sku": sku, "date": server._metric_day_str(now),
                      "units_sold": 2, "rev_sold": 200.0, "units_qty": 0,
                      "rev_qty": 0.0, "qty_drop": 0})
        # the badge store: two readings per product -> a real diff of 5 units
        snaps.append({"id": f"b0-{i}", "store_id": "sal_badge", "store_name": "Zarafa",
                      "sku": sku, "price": 90.0, "confidence_score": 95,
                      "crawled_at": now - server.timedelta(days=7),
                      "sold_count_cumulative": 100, "sold_count_capped": False})
        snaps.append({"id": f"b1-{i}", "store_id": "sal_badge", "store_name": "Zarafa",
                      "sku": sku, "price": 90.0, "confidence_score": 95,
                      "crawled_at": now, "sold_count_cumulative": 105,
                      "sold_count_capped": False})
        # the no-badge store: snapshots exist but carry no counter at all
        snaps.append({"id": f"n0-{i}", "store_id": "sal_none", "store_name": "Caty",
                      "sku": sku, "price": 80.0, "confidence_score": 95, "crawled_at": now})
    await db.products.insert_many(prods)
    await db.sku_store_coverage.insert_many(cov)
    await db.product_snapshots.insert_many(snaps)
    await db.sku_sales_daily.insert_many(sales)
    server.db = db


def test_three_tiers_are_distinct_fields_and_never_conflated():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_tiers(db)
        out = await server._store_ranking_compute(db)
        rows = {r["name"]: r for r in out["stores"]}

        # TIER 1 — exact (Zid)
        z = rows["Aleef"]
        assert z["revenue_30d"] is not None and z["revenue_tier"] == "exact"
        assert z["revenue_approx"] is None and z["revenue_est_salla"] is None

        # TIER 2 — measured (approx.) from the Salla badge
        b = rows["Zarafa"]
        assert b["revenue_tier"] == "measured_approx", b
        assert b["revenue_30d"] is None, "must NOT be passed off as exact"
        ap = b["revenue_approx"]
        assert ap and ap["usable"] is True
        assert ap["revenue"] == 40 * 5 * 90.0        # 40 products x 5 units x 90 SAR
        assert ap["products_measured"] == 40 and ap["coverage_pct"] == 100.0
        # the estimate is SUPPRESSED once a real figure exists
        assert b["revenue_est_salla"] is None, b["revenue_est_salla"]

        # TIER 3 — estimate, only where there is no badge
        c = rows["Caty"]
        assert c["revenue_tier"] == "estimated"
        assert c["revenue_30d"] is None and c["revenue_approx"] is None
        assert c["revenue_est_salla"] and c["revenue_est_salla"]["band_pct"] == 50.0
    asyncio.run(main())


def test_badge_store_with_only_one_reading_stays_on_the_estimate():
    """A cumulative counter needs two points; until then, nothing changes."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_tiers(db)
        # drop the older reading -> baseline only
        await db.product_snapshots.delete_many({"id": {"$regex": "^b0-"}})
        out = await server._store_ranking_compute(db)
        rows = {r["name"]: r for r in out["stores"]}
        b = rows["Zarafa"]
        assert b["revenue_approx"] is None, b["revenue_approx"]
        assert b["revenue_tier"] == "estimated"
        assert b["revenue_est_salla"] is not None
    asyncio.run(main())


def test_ranking_order_follows_revenue_tiers():
    # iter62 — ranking now sorts by the unified revenue axis (exact >
    # measured_approx > estimated > none) with the strength score kept only as a
    # tie-break. This test predates iter62 and asserted the score-only order.
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_tiers(db)
        out = await server._store_ranking_compute(db)
        order = [r["name"] for r in out["stores"]]
        by_revenue = [r["name"] for r in sorted(
            out["stores"],
            key=lambda r: (r["revenue_rank_value"] is None,
                           -(r["revenue_rank_value"] or 0.0),
                           -r["score"],
                           -r["components"]["breadth"]["products"],
                           r["name"]))]
        assert order == by_revenue, (order, by_revenue)
        for r in out["stores"]:
            c = r["components"]
            expect = round(100 * (server._RANKING_WEIGHTS["breadth"] * c["breadth"]["score"]
                                  + server._RANKING_WEIGHTS["price"] * c["price"]["score"]
                                  + server._RANKING_WEIGHTS["stock"] * c["stock"]["score"]
                                  + server._RANKING_WEIGHTS["freshness"] * c["freshness"]["score"]), 1)
            assert r["score"] == expect, (r["name"], r["score"], expect)
    asyncio.run(main())


# ── 5. coverage report ─────────────────────────────────────────────────────
def test_coverage_report_says_which_stores_expose_the_badge():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_tiers(db)
        rep = await server.salla_sold_badge_coverage(days=30, user=SUPER)

        assert rep["read_only"] is True
        assert rep["salla_stores"] == 2
        assert rep["salla_exposing_badge"] == 1
        assert rep["salla_measured_approx"] == 1
        by = {r["store"]: r for r in rep["stores"]}

        z = by["Zarafa"]
        assert z["exposes_sold_badge"] is True
        assert z["products_diffable"] == 40
        assert z["units_in_window"] == 200          # 40 x 5
        assert z["verdict"] == "measured_approx"
        assert z["sample"]["values"][:2] == [100, 105]

        c = by["Caty"]
        assert c["exposes_sold_badge"] is False
        assert c["products_diffable"] == 0
        assert c["verdict"] == "no_badge_stays_estimated"

        # a badge store with only a baseline is reported as WAITING, not absent
        await db.product_snapshots.delete_many({"id": {"$regex": "^b0-"}})
        rep2 = await server.salla_sold_badge_coverage(days=30, user=SUPER)
        z2 = next(r for r in rep2["stores"] if r["store"] == "Zarafa")
        assert z2["verdict"] == "awaiting_second_crawl"
        assert z2["exposes_sold_badge"] is True and z2["products_diffable"] == 0
    asyncio.run(main())


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
    print("PASS: iter59 salla sold velocity")
