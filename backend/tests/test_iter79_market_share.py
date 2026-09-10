"""iter79 — MARKET SHARE.

Client ask, verbatim in spirit: *"Do NOT fabricate numbers. If a number is
estimated, label it. If data is unavailable or confidence is low, show
Unavailable or Low confidence with the exact reason."*

So these tests are mostly about what the module REFUSES to say:
  * a seller with no sales signal contributes `None`, never 0
  * a share is withheld (None) when no seller of that product has sales data
  * the headline share counts only CONTESTED products, so a catalogue full of
    products nobody else stocks cannot drift it toward 100%
  * the ±50% Salla velocity estimate never reaches this module

plus the arithmetic that must hold: identity resolution across barcode / exact
SKU / variant array / matcher alias, share = mine ÷ market, trend vs the
previous equal-length window, and the pack-size guard applied BEFORE any of it.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["DB_NAME"] = "test_iter79_market_share"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_iter79_market_share"
import pytest  # noqa: E402
import market_share as ms  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
W_END = datetime(2026, 9, 10, tzinfo=timezone.utc)
W_START = W_END - timedelta(days=30)
DAY1 = "2026-08-25"
DAY2 = "2026-09-05"

OWN = "own-store"
COMP_A = "comp-a"          # publishes a sold counter
COMP_B = "comp-b"          # publishes stock only
COMP_C = "comp-c"          # publishes nothing measurable
COMP_D = "comp-d"          # crawled once only


def _db():
    asyncio.set_event_loop(_LOOP)   # motor captures the CURRENT loop at construction
    return AsyncIOMotorClient(MONGO)[_TEST_DB]


# A loop this module OWNS. Other suites in the same pytest process close or
# replace the default loop, so asyncio.get_event_loop() raises here when the
# whole suite runs in one go (it passed in isolation, which is how it hid).
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _price_fn(mp):
    return float(mp.get("price") or 0)


def _brand_fn(name_ar, name_en, existing=""):
    if existing:
        return existing
    for b in ("Royal Canin", "Beso"):
        if b.lower() in f"{name_ar} {name_en}".lower():
            return b
    return ""


def _cat_fn(name):
    return "cat_food" if "cat" in (name or "").lower() else "accessories"


def _snap(store, sku, price, day, **kw):
    return {"store_id": store, "sku": sku, "price": price,
            "store_name": store, "confidence_score": 95,
            "crawled_at": datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
            "in_stock": True, "qty_available": kw.pop("qty", 12),
            "product_url": kw.pop("url", f"https://{store}.com/p/{sku}"),
            **kw}


async def _seed(db):
    for c in ("stores", "product_snapshots", "my_products", "products",
              "product_matches", "sku_sales_daily", "metric_daily_rollups",
              "daily_ledger", "daily_ledger_store"):
        await db[c].delete_many({})

    await db.stores.insert_many([
        {"id": OWN, "name": "Pets Houses", "platform": "zid", "is_own_store": True, "is_active": True},
        {"id": COMP_A, "name": "Aleef", "platform": "zid", "is_active": True},
        {"id": COMP_B, "name": "Petsy", "platform": "zid", "is_active": True},
        {"id": COMP_C, "name": "Caty", "platform": "salla", "is_active": True},
        {"id": COMP_D, "name": "Zarafa", "platform": "salla", "is_active": True},
    ])

    # my catalogue: SKU IS the EAN (how the Zid own store stores them)
    await db.my_products.insert_many([
        {"sku": "3182550702362", "name_en": "Royal Canin Cat 15kg", "name_ar": "رويال كانين",
         "price": 563.5, "price_basis": "storefront_inc_vat", "in_stock": True, "quantity": 5},
        {"sku": "8595602540877", "name_en": "Beso Cat Treat 15g", "name_ar": "بيسو",
         "price": 23.45, "price_basis": "storefront_inc_vat", "in_stock": True, "quantity": 9},
        {"sku": "HL-ONLY-MINE", "name_en": "House brand cat bowl", "name_ar": "صحن",
         "price": 30.0, "price_basis": "storefront_inc_vat", "in_stock": True, "quantity": 3},
    ])
    await db.products.insert_many([
        {"sku": "3182550702362", "name_en": "Royal Canin Cat 15kg", "category": "cat_food",
         "brand": "Royal Canin"},
        {"sku": "8595602540877", "name_en": "Beso Cat Treat 15g", "category": "cat_food"},
        {"sku": "COMP-ONLY-1", "name_en": "Rival exclusive cat litter", "category": "litter",
         "barcode": "1234567890123"},
    ])
    # a matcher row links a NON-numeric competitor SKU to our product
    await db.product_matches.insert_one({
        "my_sku": "3182550702362", "competitor_sku": "RC-15KG-ALIAS",
        "competitor_store_id": COMP_B, "confidence": 88, "match_method": "name_brand_weight"})

    snaps = [
        # our own store, both days
        _snap(OWN, "3182550702362", 563.5, DAY1), _snap(OWN, "3182550702362", 563.5, DAY2, qty=3),
        _snap(OWN, "8595602540877", 23.45, DAY1), _snap(OWN, "8595602540877", 23.45, DAY2, qty=7),
        _snap(OWN, "HL-ONLY-MINE", 30.0, DAY1), _snap(OWN, "HL-ONLY-MINE", 30.0, DAY2, qty=1),
        # competitor A: same GTIN in `barcode`, own SKU string
        _snap(COMP_A, "RC-A-1", 599.0, DAY1, barcode="3182550702362"),
        _snap(COMP_A, "RC-A-1", 589.0, DAY2, barcode="3182550702362"),
        # competitor B: matcher alias
        _snap(COMP_B, "RC-15KG-ALIAS", 575.0, DAY1), _snap(COMP_B, "RC-15KG-ALIAS", 570.0, DAY2),
        # competitor C: our GTIN inside a variant array, no measurable sales
        _snap(COMP_C, "C-VAR", 560.0, DAY2, variant_barcodes=["03182550702362".zfill(14)]),
        # competitor D: crawled once — a diff cannot exist
        _snap(COMP_D, "8595602540877", 21.0, DAY2),
        # a 3.5g single sachet against our 15g pack — the pack guard must drop it
        _snap(COMP_A, "8595602540877", 4.30, DAY2,
              url="https://aleef.com/p/Beso-Sticks-Atlantic-Salmon-3-5-g-Cat"),
        # a product only competitors sell
        _snap(COMP_A, "COMP-ONLY-1", 45.0, DAY1, barcode="1234567890123"),
        _snap(COMP_A, "COMP-ONLY-1", 44.0, DAY2, barcode="1234567890123"),
        _snap(COMP_B, "COMP-ONLY-1", 47.0, DAY2, barcode="1234567890123"),
    ]
    await db.product_snapshots.insert_many(snaps)

    # per-store per-day markers (what "days observed" reads)
    rows = []
    for sid, days in ((OWN, (DAY1, DAY2)), (COMP_A, (DAY1, DAY2)), (COMP_B, (DAY1, DAY2)),
                      (COMP_C, (DAY1, DAY2)), (COMP_D, (DAY2,))):
        for d in days:
            rows.append({"_id": f"{sid}|{d}", "store_id": sid, "ksa_date": d, "status": "ok"})
    await db.daily_ledger_store.insert_many(rows)

    # signal capability: A publishes a counter, B/OWN publish stock, C/D neither
    await db.daily_ledger.insert_many([
        {"_id": f"{COMP_A}|x|{DAY2}", "store_id": COMP_A, "sku": "RC-A-1", "ksa_date": DAY2,
         "sold_count_cumulative": 40, "qty_available": 0},
        {"_id": f"{COMP_B}|x|{DAY2}", "store_id": COMP_B, "sku": "RC-15KG-ALIAS", "ksa_date": DAY2,
         "sold_count_cumulative": 0, "qty_available": 8},
        {"_id": f"{OWN}|x|{DAY2}", "store_id": OWN, "sku": "3182550702362", "ksa_date": DAY2,
         "sold_count_cumulative": 0, "qty_available": 3},
        {"_id": f"{COMP_C}|x|{DAY2}", "store_id": COMP_C, "sku": "C-VAR", "ksa_date": DAY2,
         "sold_count_cumulative": 0, "qty_available": 0},
        {"_id": f"{COMP_D}|x|{DAY2}", "store_id": COMP_D, "sku": "8595602540877", "ksa_date": DAY2,
         "sold_count_cumulative": 0, "qty_available": 0},
    ])

    # measured sales rollups for the CURRENT window
    await db.sku_sales_daily.insert_many([
        # competitor A sold 10 of the Royal Canin via its counter
        {"_id": f"{COMP_A}|RC-A-1|{DAY2}", "store_id": COMP_A, "sku": "RC-A-1", "date": DAY2,
         "units_sold": 10, "rev_sold": 5890.0, "units_qty": 0, "rev_qty": 0.0},
        # competitor B: stock depletion only
        {"_id": f"{COMP_B}|RC-15KG-ALIAS|{DAY2}", "store_id": COMP_B, "sku": "RC-15KG-ALIAS",
         "date": DAY2, "units_sold": 0, "rev_sold": 0.0, "units_qty": 4, "rev_qty": 2280.0},
        # us: stock depletion
        {"_id": f"{OWN}|3182550702362|{DAY2}", "store_id": OWN, "sku": "3182550702362",
         "date": DAY2, "units_sold": 0, "rev_sold": 0.0, "units_qty": 2, "rev_qty": 1127.0},
        # the competitor-only product
        {"_id": f"{COMP_A}|COMP-ONLY-1|{DAY2}", "store_id": COMP_A, "sku": "COMP-ONLY-1",
         "date": DAY2, "units_sold": 6, "rev_sold": 264.0, "units_qty": 0, "rev_qty": 0.0},
        # PREVIOUS window row (for the trend) — dated before W_START
        {"_id": f"{COMP_A}|RC-A-1|2026-07-20", "store_id": COMP_A, "sku": "RC-A-1",
         "date": "2026-07-20", "units_sold": 5, "rev_sold": 2995.0, "units_qty": 0, "rev_qty": 0.0},
    ])


async def _dataset(db, orders=None):
    return await ms.build_dataset(
        db, 30, OWN, own_price_fn=_price_fn, brand_fn=_brand_fn, category_fn=_cat_fn,
        orders_by_sku=orders or {}, min_confidence=70,
        window_start=W_START, window_end=W_END, now=NOW)


@pytest.fixture(scope="module")
def data():
    db = _db()

    async def _go():
        await _seed(db)
        return await _dataset(db)

    return _run(_go())


def _row(data, sku):
    return next(r for r in data["my_products"] if r["sku"] == sku)


# ── pure units: what the resolver refuses to claim ──────────────────────────
def test_orders_ledger_wins_for_own_store():
    u, rev, src, reason = ms._resolve_units(
        (OWN, "S"), {}, {OWN: {"days_observed": 5, "signal": "stock"}}, True,
        {"units": 7, "revenue": 700.0})
    assert (u, rev, src, reason) == (7, 700.0, ms.SRC_ORDERS, None)


def test_counter_beats_stock_for_the_same_pair():
    sales = {("s", "k"): {"units": 3, "revenue": 30.0, "source": ms.SRC_COUNTER}}
    u, rev, src, _ = ms._resolve_units(("s", "k"), sales, {}, False, None)
    assert (u, src) == (3, ms.SRC_COUNTER)


def test_zero_is_a_fact_only_when_the_store_publishes_a_signal():
    u, rev, src, reason = ms._resolve_units(
        ("s", "k"), {}, {"s": {"days_observed": 4, "signal": "counter"}}, False, None)
    assert (u, rev, src, reason) == (0, 0.0, ms.SRC_ZERO, None)


def test_no_signal_is_unavailable_not_zero():
    u, rev, src, reason = ms._resolve_units(
        ("s", "k"), {}, {"s": {"days_observed": 9, "signal": "none"}}, False, None)
    assert u is None and rev is None
    assert src == ms.SRC_NONE and reason == ms.REASON_NO_SIGNAL


def test_one_crawl_cannot_produce_a_difference():
    _, _, src, reason = ms._resolve_units(
        ("s", "k"), {}, {"s": {"days_observed": 1, "signal": "counter"}}, False, None)
    assert src == ms.SRC_NONE and reason == ms.REASON_ONE_CRAWL


def test_store_absent_from_the_window_says_so():
    _, _, src, reason = ms._resolve_units(("s", "k"), {}, {}, False, None)
    assert src == ms.SRC_NONE and reason == ms.REASON_NOT_CRAWLED


# ── confidence ─────────────────────────────────────────────────────────────
def _seller(**kw):
    base = {"units": 1, "match_strength": 99, "is_own": False,
            "last_crawl_at": NOW - timedelta(days=1)}
    base.update(kw)
    return base


def test_confidence_high_needs_invoiced_units_full_coverage_and_fresh_prices():
    lvl, reason = _row_conf([_seller(is_own=True), _seller()], ms.SRC_ORDERS)
    assert lvl == "high" and reason is None


def test_confidence_drops_to_medium_without_the_orders_ledger():
    lvl, _ = _row_conf([_seller(is_own=True), _seller()], ms.SRC_STOCK)
    assert lvl == "medium"


def test_confidence_low_when_half_the_sellers_have_no_sales_data():
    sellers = [_seller(is_own=True), _seller(units=None), _seller(units=None)]
    lvl, reason = _row_conf(sellers, ms.SRC_STOCK)
    assert lvl == "low" and "1 of 3" in reason


def test_confidence_unavailable_when_nobody_has_sales_data():
    lvl, reason = _row_conf([_seller(units=None), _seller(units=None)], ms.SRC_NONE)
    assert lvl == "unavailable" and reason == ms.REASON_NO_SELLER_DATA


def _row_conf(sellers, src):
    return ms._row_confidence(sellers, src, now=NOW)


# ── pack guard runs BEFORE any share arithmetic ────────────────────────────
def test_pack_guard_drops_a_single_sachet_from_a_multipack_market():
    sellers = [
        {"store_id": OWN, "is_own": True, "price": 23.45, "product_url": None},
        {"store_id": COMP_A, "is_own": False, "price": 4.30,
         "product_url": "https://a.com/p/Beso-Sticks-Atlantic-Salmon-3-5-g"},
        {"store_id": COMP_B, "is_own": False, "price": 22.0,
         "product_url": "https://b.com/p/Beso-Cat-Treat-15-g"},
    ]
    kept, excluded = ms._apply_pack_guard("Beso Cat Treat 15 g", sellers, 23.45)
    assert [s["store_id"] for s in excluded] == [COMP_A]
    assert {s["store_id"] for s in kept} == {OWN, COMP_B}
    assert excluded[0]["excluded_reason"].startswith("slug_weight_3.5g")


def test_pack_guard_never_excludes_our_own_row():
    sellers = [{"store_id": OWN, "is_own": True, "price": 1.0, "product_url": None},
               {"store_id": COMP_A, "is_own": False, "price": 100.0, "product_url": None},
               {"store_id": COMP_B, "is_own": False, "price": 110.0, "product_url": None}]
    kept, _ = ms._apply_pack_guard("x", sellers, 1.0)
    assert any(s["is_own"] for s in kept)


# ── identity resolution ────────────────────────────────────────────────────
def test_gtin_in_the_barcode_field_links_to_our_numeric_sku(data):
    row = _row(data, "3182550702362")
    a = next(s for s in row["sellers"] if s["store_id"] == COMP_A)
    assert a["match_source"] == "barcode" and a["match_strength"] == 99


def test_matcher_alias_links_a_non_numeric_competitor_sku(data):
    row = _row(data, "3182550702362")
    b = next(s for s in row["sellers"] if s["store_id"] == COMP_B)
    assert b["match_source"] == "product_match"
    assert b["sku_at_store"] == "RC-15KG-ALIAS"


def test_variant_array_carrying_our_gtin_is_found(data):
    row = _row(data, "3182550702362")
    c = next(s for s in row["sellers"] if s["store_id"] == COMP_C)
    assert c["match_source"] == "variant_barcode"


def test_every_seller_is_listed_even_without_sales_data(data):
    row = _row(data, "3182550702362")
    ids = {s["store_id"] for s in row["sellers"]}
    assert {OWN, COMP_A, COMP_B, COMP_C} <= ids
    c = next(s for s in row["sellers"] if s["store_id"] == COMP_C)
    assert c["units"] is None and c["unavailable_reason"] == ms.REASON_NO_SIGNAL
    assert c["price"] == 560.0        # it still carries a price and stock state


# ── share arithmetic ───────────────────────────────────────────────────────
def test_market_totals_sum_only_sellers_with_sales_data(data):
    row = _row(data, "3182550702362")
    assert row["market_units"] == 16          # 10 counter + 4 stock + 2 ours
    assert row["market_revenue"] == round(5890.0 + 2280.0 + 1127.0, 2)
    assert row["sellers_with_sales"] == 3 and row["sellers_total"] == 4


def test_my_share_is_mine_over_the_measurable_market(data):
    row = _row(data, "3182550702362")
    assert row["my_units"] == 2
    assert row["unit_share_pct"] == round(2 / 16 * 100, 2)
    assert row["revenue_share_pct"] == round(1127.0 / row["market_revenue"] * 100, 2)


def test_top_competitor_and_price_range_are_reported(data):
    row = _row(data, "3182550702362")
    assert row["top_competitor"]["store_name"] == COMP_A
    assert row["competitor_price_min"] == 560.0
    assert row["competitor_price_max"] == 589.0
    assert row["price_rank"] == 2 and row["price_rank_of"] == 4   # 560 < 563.5


def test_trend_compares_the_previous_equal_length_window(data):
    row = _row(data, "3182550702362")
    # current 9297.0 vs previous 2995.0
    assert row["trend"]["prev_revenue"] == 2995.0
    assert row["trend"]["revenue_pct"] == round((row["market_revenue"] - 2995.0) / 2995.0 * 100, 1)


def test_a_product_only_we_sell_is_flagged_not_hidden(data):
    row = _row(data, "HL-ONLY-MINE")
    assert row["competitor_count"] == 0
    assert row["sole_seller"] is True and row["contested"] is False


def test_headline_share_ignores_sole_seller_products(data):
    k = data["kpis"]
    contested = [r for r in data["my_products"] if r["contested"]]
    assert k["products_contested"] == len(contested)
    assert k["market_revenue"] == round(sum(r["market_revenue"] or 0 for r in contested), 2)
    assert "HL-ONLY-MINE" not in [r["sku"] for r in contested]


def test_a_product_no_seller_can_be_measured_for_withholds_the_share(data):
    row = _row(data, "8595602540877")
    # our own store publishes stock, so we DO have units; the 3.5g sachet was
    # dropped by the pack guard and Zarafa has a single crawl
    z = [s for s in row["sellers"] if s["store_id"] == COMP_D]
    assert z and z[0]["units"] is None
    assert z[0]["unavailable_reason"] == ms.REASON_ONE_CRAWL
    assert row["excluded_sellers"] and row["excluded_sellers"][0]["store_name"] == COMP_A


# ── missing products ───────────────────────────────────────────────────────
def test_competitor_only_product_becomes_an_opportunity(data):
    m = next(r for r in data["missing_products"] if r["sku"] == "COMP-ONLY-1")
    assert m["in_catalog"] is False
    assert m["my_unit_share_pct"] == 0.0 and m["my_revenue_share_pct"] == 0.0
    assert m["competitor_count"] == 2
    assert m["market_units"] == 6 and m["market_revenue"] == 264.0
    assert m["min_price"] == 44.0 and m["max_price"] == 47.0
    assert 0 <= m["opportunity_score"] <= 100
    assert m["recommended_action"]


def test_missing_rows_carry_a_transparent_score_formula(data):
    for m in data["missing_products"]:
        assert "0.5×measured revenue" in m["opportunity_formula"]


def test_missing_product_with_no_measurable_seller_says_watch(data):
    rows = [r for r in data["missing_products"] if not r["sellers_with_sales"]]
    for r in rows:
        assert r["market_revenue"] is None
        assert r["unavailable_reason"] == ms.REASON_NO_SELLER_DATA
        assert r["recommended_action"].startswith("Watch")


# ── brands / categories ────────────────────────────────────────────────────
def test_brand_rows_never_bucket_an_unresolved_brand(data):
    assert all(b["brand"] for b in data["brands"])
    assert "Unknown" not in [b["brand"] for b in data["brands"]]


def test_brand_share_percentages_are_shares_of_the_resolved_total(data):
    total = sum(b["revenue"] for b in data["brands"])
    if total > 0:
        s = sum(b["revenue_share_pct"] or 0 for b in data["brands"])
        assert abs(s - 100) < 1.5


def test_category_rows_report_measurement_coverage(data):
    for c in data["categories"]:
        assert "products have measurable sales" in c["coverage"]
        if c["measured_products"] == 0:
            assert c["confidence"] == "unavailable"


# ── store honesty ──────────────────────────────────────────────────────────
def test_every_tracked_store_is_listed_with_its_observability(data):
    by_name = {s["store_id"]: s for s in data["stores"]}
    assert set(by_name) == {OWN, COMP_A, COMP_B, COMP_C, COMP_D}
    assert by_name[COMP_A]["sales_data_available"] is True
    assert by_name[COMP_C]["sales_data_available"] is False       # no signal
    assert by_name[COMP_D]["days_observed"] == 1                  # one crawl
    assert by_name[COMP_D]["sales_data_available"] is False


def test_orders_ledger_flips_my_source_to_actual():
    db = _db()

    async def _go():
        await _seed(db)
        return await _dataset(db, orders={"3182550702362": {"units": 9, "revenue": 5071.5}})

    ds = _run(_go())
    row = next(r for r in ds["my_products"] if r["sku"] == "3182550702362")
    assert row["my_units"] == 9
    assert row["my_units_source"] == ms.SRC_ORDERS
    assert row["confidence"] in ("high", "medium")
    assert ds["data_quality"]["own_orders_ledger_connected"] is True


# ── fences ─────────────────────────────────────────────────────────────────
def test_the_salla_velocity_estimate_never_reaches_this_module():
    src = (Path(__file__).parent.parent / "market_share.py").read_text()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "import salla_revenue_estimate" not in code
    assert "from salla_revenue_estimate" not in code
    assert "estimate_store_revenue(" not in code
    assert "estimate_with_band(" not in code
    assert not hasattr(ms, "estimate_store_revenue")


def test_no_row_reports_a_share_without_a_denominator(data):
    for r in data["my_products"]:
        if r["market_revenue"] is None:
            assert r["revenue_share_pct"] is None
            assert r["unit_share_pct"] is None
            assert r["unavailable_reason"]


def test_unavailable_rows_always_carry_a_human_reason(data):
    for r in data["my_products"]:
        for s in r["sellers"]:
            if s["units"] is None:
                assert s["unavailable_reason"] in (
                    ms.REASON_NO_SIGNAL, ms.REASON_ONE_CRAWL, ms.REASON_NOT_CRAWLED)


def test_source_labels_are_the_documented_set(data):
    allowed = {ms.SRC_ORDERS, ms.SRC_COUNTER, ms.SRC_STOCK, ms.SRC_ZERO, ms.SRC_NONE, None}
    for r in data["my_products"]:
        assert r["my_units_source"] in allowed
        for s in r["sellers"]:
            assert s["units_source"] in allowed


def test_endpoints_and_page_key_are_registered():
    import server
    paths = {r.path for r in server.app.routes}
    for p in ("/api/market-share/overview", "/api/market-share/my-products",
              "/api/market-share/product/{key}", "/api/market-share/missing-products",
              "/api/market-share/brands", "/api/market-share/categories",
              "/api/market-share/methodology", "/api/market-share/export"):
        assert p in paths, p
    assert "market_share" in server.ALL_PAGES
