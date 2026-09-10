"""iter80 — Market Share: filters move every KPI, and every exported number
carries the method that produced it.

The client's rules this file fences:
  * no fabricated numbers — the ±50% Salla velocity estimate never touches a share
  * a share is computed ONLY from measured data, over a stated denominator
  * an unavailable number is withheld WITH a reason, never rendered as zero
  * "stores carrying it" is a different column from "sales data available"
  * every filter (window, category, brand, store, product, in/out of catalog)
    re-computes the KPIs, not just the table underneath them
  * the CSV carries source label, confidence, unavailable reason AND the
    calculation method
  * the Methodology tab states the tracked-market caveat verbatim
"""
import csv
import io
from pathlib import Path

import pytest
import requests

import market_share
from _auth import auth_headers, base_url

BASE = base_url()
API = f"{BASE}/api"
DAYS = 30
LIVE = {"days": DAYS, "include_today": "true"}     # preview only has today's rollups sealed-window-wise

CLIENT_SENTENCE = ("Market share is based on tracked measured data inside Daleel, "
                   "not the total Saudi market")


@pytest.fixture(scope="module")
def H():
    return auth_headers()


def _get(H, path, **params):
    r = requests.get(f"{API}{path}", headers=H, params={**LIVE, **params}, timeout=180)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:400]}"
    return r.json()


# ── unit: the shared arithmetic ──────────────────────────────────────────────
def _row(sku, brand, category, market_rev, my_rev, in_catalog=True, contested=True,
         market_units=10, my_units=2, prev_units=0, prev_rev=0.0):
    return {
        "sku": sku, "name": sku, "brand": brand, "category": category,
        "in_catalog": in_catalog, "contested": contested, "sole_seller": False,
        "market_revenue": market_rev, "market_units": market_units,
        "my_revenue": my_rev, "my_units": my_units,
        "my_units_source": market_share.SRC_COUNTER,
        "competitor_count": 2, "sellers_total": 3, "sellers_with_sales": 3,
        "confidence": "medium", "brand_source": "catalog", "price_spread_warning": None,
        "excluded_sellers": [],
        "trend": {"prev_units": prev_units, "prev_revenue": prev_rev},
        "sellers": [{"store_name": "Rival", "is_own": False, "units": 8, "revenue": 800.0}],
    }


def test_summarize_is_the_same_arithmetic_on_a_subset():
    rows = [_row("a", "X", "cat_food", 1000.0, 250.0),
            _row("b", "Y", "litter", 500.0, 100.0)]
    stores = [{"sales_data_available": True}, {"sales_data_available": False}]
    whole = market_share.summarize(rows, [], stores, catalog_total=2, orders_connected=False)
    assert whole["market_revenue"] == 1500.0 and whole["my_revenue"] == 350.0
    assert whole["my_revenue_share_pct"] == pytest.approx(350 / 1500 * 100, abs=0.01)

    subset = market_share.summarize(rows[:1], [], stores, catalog_total=1, orders_connected=False)
    assert subset["market_revenue"] == 1000.0 and subset["my_revenue"] == 250.0
    assert subset["my_revenue_share_pct"] == 25.0
    assert subset["my_catalog_products"] == 1


def test_summarize_withholds_rather_than_zeroes():
    unmeasurable = _row("a", "X", "cat_food", None, None, contested=False)
    unmeasurable["market_units"] = None
    k = market_share.summarize([unmeasurable], [], [], catalog_total=1, orders_connected=False)
    assert k["market_revenue"] is None and k["my_revenue"] is None
    assert k["my_revenue_share_pct"] is None, "a share with no denominator must be withheld, not 0"


def test_orders_ledger_upgrades_the_source_label():
    rows = [_row("a", "X", "cat_food", 100.0, 50.0)]
    assert market_share.summarize(rows, [], [], catalog_total=1,
                                  orders_connected=True)["my_units_source"] == market_share.SRC_ORDERS
    assert market_share.summarize(rows, [], [], catalog_total=1,
                                  orders_connected=False)["my_units_source"] == market_share.SRC_COUNTER


def test_aggregate_groups_shares_sum_to_100_and_are_measured_only():
    rows = [_row("a", "Royal", "cat_food", 800.0, 200.0),
            _row("b", "Royal", "cat_food", 200.0, 100.0),
            _row("c", "Hills", "cat_food", 1000.0, 0.0)]
    unmeasured = _row("d", "Hills", "cat_food", None, None, contested=False)
    groups = market_share.aggregate_groups(rows + [unmeasured], [], "brand")
    by = {g["brand"]: g for g in groups}
    assert round(sum(g["revenue_share_pct"] for g in groups), 1) == 100.0
    assert by["Royal"]["revenue"] == 1000.0 and by["Royal"]["my_revenue_share_pct"] == 30.0
    # the unmeasurable product counts as a product but adds no revenue
    assert by["Hills"]["products"] == 2 and by["Hills"]["measured_products"] == 1
    assert "1 of 2" in by["Hills"]["coverage"]


def test_missing_rows_are_counted_as_not_mine():
    mine = [_row("a", "Royal", "cat_food", 100.0, 40.0)]
    theirs = [_row("z", "Royal", "cat_food", 300.0, 0.0, in_catalog=False)]
    theirs[0].pop("my_revenue")
    g = market_share.aggregate_groups(mine, theirs, "brand")[0]
    assert g["products"] == 2 and g["my_products_count"] == 1
    assert g["missing_products"] == 1 and g["missing_opportunity_value"] == 300.0


def test_the_velocity_estimate_is_not_wired_into_shares():
    src = Path(market_share.__file__).read_text()
    assert "salla_revenue_estimate" not in src.split('"""', 2)[2], (
        "the ±50% estimate must never feed a share calculation")
    assert market_share.ACTUAL_SOURCES == {market_share.SRC_ORDERS}
    assert "estimate" not in "".join(market_share.APPROX_SOURCES)


# ── live: filters move the KPIs ──────────────────────────────────────────────
def test_overview_unfiltered_reports_no_filters(H):
    d = _get(H, "/market-share/overview")
    assert d["filtered"] is False and d["filters_applied"] == {}
    assert d["kpis"]["tracked_stores"] >= 1
    assert isinstance(d["filters"]["categories"], list)
    assert isinstance(d["filters"]["brands"], list)
    assert d["filters"]["stores"], "the store filter must be populated"


def test_category_filter_moves_the_kpis_and_the_table_together(H):
    whole = _get(H, "/market-share/overview")
    cats = whole["filters"]["categories"]
    if not cats:
        pytest.skip("no category resolved in this window")
    cat = cats[0]
    filtered = _get(H, "/market-share/overview", category=cat)
    assert filtered["filtered"] is True and filtered["filters_applied"]["category"] == cat
    assert filtered["kpis"]["my_catalog_products"] <= whole["kpis"]["my_catalog_products"]
    assert filtered["kpis"]["products_contested"] <= whole["kpis"]["products_contested"]
    assert [c["category"] for c in filtered["top_categories"]] == [cat]

    table = _get(H, "/market-share/my-products", category=cat, limit=500)
    assert table["total"] == filtered["kpis"]["my_catalog_products"], (
        "the KPI count and the table count must be the same selection")
    assert all(r["category"] == cat for r in table["rows"])


def test_brand_filter_moves_the_kpis(H):
    whole = _get(H, "/market-share/overview")
    brands = whole["filters"]["brands"]
    if not brands:
        pytest.skip("no brand resolved in this window")
    brand = next((b for b in brands if b), None)
    filtered = _get(H, "/market-share/overview", brand=brand)
    assert filtered["filtered"] is True
    assert filtered["kpis"]["my_catalog_products"] <= whole["kpis"]["my_catalog_products"]
    assert all(b["brand"] == brand for b in filtered["top_brands"])


def test_store_filter_restricts_to_products_that_store_carries(H):
    ov = _get(H, "/market-share/overview")
    sid = ov["filters"]["stores"][-1]["store_id"]
    table = _get(H, "/market-share/my-products", store_id=sid, limit=50)
    for r in table["rows"]:
        assert any(s["store_id"] == sid for s in r["sellers"])


def test_catalog_filter_splits_mine_from_not_mine(H):
    mine = _get(H, "/market-share/my-products", catalog="mine", limit=20)
    assert all(r["in_catalog"] for r in mine["rows"])
    not_mine = _get(H, "/market-share/my-products", catalog="not_mine", limit=20)
    assert not_mine["total"] == 0, "my-products only ever holds my catalogue"
    ov_mine = _get(H, "/market-share/overview", catalog="mine")
    assert ov_mine["filters_applied"]["catalog"] == "mine"
    assert ov_mine["top_opportunities"] == [], (
        "a product outside my catalogue cannot be inside an 'in my catalog' selection")


def test_brands_and_categories_tables_follow_the_filters(H):
    ov = _get(H, "/market-share/overview")
    cats = ov["filters"]["categories"]
    if not cats:
        pytest.skip("no category resolved")
    cat = cats[0]
    brands = _get(H, "/market-share/brands", category=cat)
    assert brands["filtered"] is True
    if brands["rows"]:
        pcts = [r["revenue_share_pct"] for r in brands["rows"] if r["revenue_share_pct"]]
        if pcts:
            assert 95 <= round(sum(pcts)) <= 105, "shares inside a selection must sum to ~100%"
    categories = _get(H, "/market-share/categories", category=cat)
    assert categories["filtered"] is True
    assert [r["category"] for r in categories["rows"]] in ([cat], [])


def test_search_filter_applies_to_every_surface(H):
    table = _get(H, "/market-share/my-products", limit=1)
    if not table["rows"]:
        pytest.skip("no rows in this window")
    sku = table["rows"][0]["sku"]
    hit = _get(H, "/market-share/my-products", search=sku)
    assert hit["total"] >= 1 and any(r["sku"] == sku for r in hit["rows"])
    ov = _get(H, "/market-share/overview", search=sku)
    assert ov["kpis"]["my_catalog_products"] == hit["total"]


# ── live: honesty of the numbers ─────────────────────────────────────────────
def test_every_share_states_its_denominator(H):
    rows = _get(H, "/market-share/my-products", limit=200)["rows"]
    for r in rows:
        assert r["sellers_total"] >= r["sellers_with_sales"] >= 0
        if r["revenue_share_pct"] is not None:
            assert r["market_revenue"] is not None and r["sellers_with_sales"] >= 1
        else:
            assert r["market_revenue"] is None or r["my_revenue"] is None


def test_unavailable_always_carries_a_reason(H):
    rows = _get(H, "/market-share/my-products", limit=200)["rows"]
    seen = 0
    for r in rows:
        if r["market_revenue"] is None:
            assert r["unavailable_reason"], f"{r['sku']} withheld with no reason"
            seen += 1
        for s in r["sellers"]:
            if s["units"] is None:
                assert s["unavailable_reason"], f"{r['sku']}/{s['store_name']} silent unavailable"
                assert s["unavailable_reason"] in (
                    market_share.REASON_NO_SIGNAL, market_share.REASON_ONE_CRAWL,
                    market_share.REASON_NOT_CRAWLED)
                seen += 1
    assert seen >= 0


def test_a_seller_without_sales_data_is_still_listed(H):
    """Stores carrying it and stores whose sales we can measure are two
    different facts — the seller must never disappear because of the second."""
    rows = _get(H, "/market-share/my-products", limit=300)["rows"]
    partial = [r for r in rows if r["sellers_with_sales"] < r["sellers_total"]]
    if not partial:
        pytest.skip("every tracked seller publishes sales data in this window")
    r = partial[0]
    silent = [s for s in r["sellers"] if s["units"] is None]
    assert silent, "row claims a gap between carrying and measurable but lists no silent seller"
    assert all(s["price"] is not None for s in silent), "a silent seller still shows its price"


def test_missing_products_are_opportunities_not_omissions(H):
    d = _get(H, "/market-share/missing-products", limit=20)
    assert d["total_untruncated"] >= d["total"]
    for r in d["rows"]:
        assert r["in_catalog"] is False
        assert r["competitor_count"] >= 1 and r["competitors"]
        assert r["opportunity_score"] is not None and r["opportunity_formula"]
        assert r["recommended_action"]
        assert r["my_unit_share_pct"] == 0.0


def test_product_breakdown_lists_every_seller(H):
    table = _get(H, "/market-share/my-products", limit=25)["rows"]
    row = next((r for r in table if r["competitor_count"] >= 1), None)
    if not row:
        pytest.skip("no product with a tracked competitor in this window")
    d = _get(H, f"/market-share/product/{row['sku']}")["product"]
    assert d["sku"] == row["sku"]
    assert len(d["sellers"]) == row["sellers_total"]
    assert any(s["is_own"] for s in d["sellers"])
    for s in d["sellers"]:
        if not s["is_own"]:
            assert s["match_source"] and s["match_strength"] >= 85


def test_unknown_sku_is_a_404_not_an_empty_row(H):
    r = requests.get(f"{API}/market-share/product/NOT-A-REAL-SKU-iter80",
                     headers=H, params=LIVE, timeout=60)
    assert r.status_code == 404


# ── live: CSV carries the provenance ────────────────────────────────────────
def _csv(H, section, **params):
    r = requests.get(f"{API}/market-share/export", headers=H,
                     params={**LIVE, "section": section, **params}, timeout=180)
    assert r.status_code == 200, r.text[:300]
    assert "text/csv" in r.headers.get("content-type", "")
    assert f"daleel_market_share_{section}" in r.headers.get("content-disposition", "")
    return list(csv.reader(io.StringIO(r.text)))


def test_my_products_csv_carries_source_confidence_reason_and_method(H):
    rows = _csv(H, "my_products")
    head = rows[0]
    for col in ("My units source", "Confidence", "Confidence reason", "Unavailable reason",
                "Calculation method", "Stores carrying it (competitors)",
                "Sales data available (sellers)"):
        assert col in head, f"CSV missing column: {col}"
    if len(rows) > 1:
        rec = dict(zip(head, rows[1]))
        assert rec["Calculation method"], "every row must state how it was calculated"
        assert rec["My units source"] in (market_share.SRC_ORDERS, market_share.SRC_COUNTER,
                                          market_share.SRC_STOCK, market_share.SRC_ZERO,
                                          market_share.SRC_NONE)


def test_missing_and_group_csvs_carry_the_method(H):
    for section in ("missing", "brands", "categories"):
        rows = _csv(H, section)
        assert "Calculation method" in rows[0], f"{section} CSV has no method column"
        assert "Confidence" in rows[0]
        assert "Unavailable reason" in rows[0], f"{section} CSV has no unavailable-reason column"
        if len(rows) > 1:
            assert dict(zip(rows[0], rows[1]))["Calculation method"]


def test_group_csv_states_why_a_row_is_withheld(H):
    """A brand/category with no measurable product must say so in the CSV, not
    just carry confidence=unavailable."""
    rows = _csv(H, "brands")
    head = rows[0]
    withheld = [dict(zip(head, r)) for r in rows[1:]
                if dict(zip(head, r)).get("Products with measurable sales") in ("0", "")]
    if not withheld:
        pytest.skip("every brand has at least one measurable product in this window")
    assert withheld[0]["Unavailable reason"], (
        f"withheld brand row with no reason: {withheld[0].get('Brand')}")


def test_csv_honours_the_filters(H):
    ov = _get(H, "/market-share/overview")
    cats = ov["filters"]["categories"]
    if not cats:
        pytest.skip("no category resolved")
    rows = _csv(H, "my_products", category=cats[0])
    head = rows[0]
    for r in rows[1:]:
        assert dict(zip(head, r))["Category"] == cats[0]


def test_bad_section_is_rejected(H):
    r = requests.get(f"{API}/market-share/export", headers=H,
                     params={**LIVE, "section": "nonsense"}, timeout=60)
    assert r.status_code == 400


# ── live: methodology states the caveat verbatim ────────────────────────────
def test_methodology_states_the_client_sentence(H):
    d = _get(H, "/market-share/methodology")
    assert d["tracked_market"].startswith(CLIENT_SENTENCE), d["tracked_market"]
    labels = {s["label"] for s in d["sources"]}
    assert {"Actual", "Measured (approx.)", "Unavailable"} <= labels
    assert any("salla" in n["id"] for n in d["not_used"]), (
        "the estimate we refuse to use must be named")
    assert d["formulas"]["revenue_share_pct"]
    assert d["confidence"]["unavailable"]
    assert "connected" in d["own_orders_connection"]


def test_frontend_separates_carrying_from_measurable():
    src = Path("/app/frontend/src/components/marketShare/MyProductsShare.jsx").read_text()
    assert '"Stores carrying"' in src and '"Sales data available"' in src
    assert "ms-stores-carrying-" in src and "ms-sales-data-available-" in src
    page = Path("/app/frontend/src/pages/MarketSharePage.jsx").read_text()
    assert 'tab !== "methodology" && (' in page, "the filter bar must render on the Overview too"
    assert "filters={filters}" in page
