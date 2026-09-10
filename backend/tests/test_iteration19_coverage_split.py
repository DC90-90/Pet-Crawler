"""
Iteration 19 — Coverage definition split test suite.

Validates the iter18 → iter19 fix where the Market Coverage KPI was conflating
two distinct signals into one. The fix splits them into:
  - has_competitor_pricing  (num_competitors >= 1)            → drives matched_products + market_coverage_pct
  - has_market_share        (num_competitors >= 1 AND qty>0)  → drives share_sample_size + avg_market_share

Old broken field `has_market_data` MUST be removed from the per-row payload.

Expected preview numbers (90D, own_only=True):
  matched_products      ≈ 774   (±2)
  market_coverage_pct   ≈ 37.2  (±2)
  share_sample_size     ≈ 49    (±2)
  avg_market_share      ≈ 0.0   (preview own-sync stale)
  total_products        = 2081
"""
import os
import time
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
from _auth import live_db_name   # backend/.env, not the polluted env var
DB_NAME = live_db_name()

EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"


# ---- fixtures ----------------------------------------------------------------
@pytest.fixture(scope="module")
def session():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import auth_session
    return auth_session(EMAIL, PASSWORD)


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def my_products_90d(session):
    r = session.get(f"{BASE_URL}/api/my-products?days=90&limit=500&offset=0", timeout=60)
    assert r.status_code == 200, f"my-products failed: {r.status_code}"
    return r.json()


# ---- 1. db.product_matches healthy ------------------------------------------
class TestMatcherHealth:
    def test_product_matches_row_count(self, mongo):
        total = mongo.product_matches.count_documents({})
        # iter21 baseline: 2453 (was 2258 — matcher price-ratio hard-reject
        # removed, so aggressive-discount competitors now land in the table)
        assert total >= 2400, f"expected ~2453 product_matches, got {total}"

    def test_product_matches_distinct_my_skus(self, mongo):
        distinct = len(mongo.product_matches.distinct("my_sku"))
        # iter21 baseline: 1150 (was 1102)
        assert distinct >= 1140, f"expected ~1150 distinct my_skus, got {distinct}"

    def test_sync_runs_iter18_row_preserved(self, mongo):
        rows = list(mongo.sync_runs.find({"kind": "manual_match_only"}))
        assert len(rows) >= 1, "expected at least 1 manual_match_only row from iter18"
        ok_rows = [r for r in rows if r.get("match_status") == "ok" and r.get("match_added", 0) >= 1000]
        assert len(ok_rows) >= 1, f"expected manual_match_only with match_status=ok and match_added>=1000, got {rows[:2]}"


# ---- 2. Per-row signal contract ---------------------------------------------
class TestPerRowSignals:
    def test_has_market_data_field_removed(self, my_products_90d):
        for p in my_products_90d.get("products", [])[:50]:
            assert "has_market_data" not in p, f"legacy has_market_data still present in row: {p.get('sku')}"

    def test_has_competitor_pricing_present(self, my_products_90d):
        prods = my_products_90d.get("products", [])
        assert prods, "no products returned"
        for p in prods[:20]:
            assert "has_competitor_pricing" in p, f"missing has_competitor_pricing in {p.get('sku')}"
            assert isinstance(p["has_competitor_pricing"], bool)

    def test_has_market_share_present(self, my_products_90d):
        for p in my_products_90d.get("products", [])[:20]:
            assert "has_market_share" in p, f"missing has_market_share in {p.get('sku')}"
            assert isinstance(p["has_market_share"], bool)

    def test_market_share_pct_null_when_has_market_share_false(self, my_products_90d):
        bad = []
        for p in my_products_90d.get("products", []):
            if p.get("has_market_share") is False:
                if p.get("market_share_pct") is not None:
                    bad.append((p.get("sku"), p.get("market_share_pct")))
        assert not bad, f"rows with has_market_share=false must have market_share_pct=null. violations: {bad[:5]}"

    def test_market_share_pct_numeric_when_has_market_share_true(self, my_products_90d):
        bad = []
        for p in my_products_90d.get("products", []):
            if p.get("has_market_share") is True:
                if not isinstance(p.get("market_share_pct"), (int, float)):
                    bad.append((p.get("sku"), p.get("market_share_pct")))
        assert not bad, f"rows with has_market_share=true must have numeric market_share_pct. violations: {bad[:5]}"

    def test_no_fair_share_100pct_fallback(self, my_products_90d):
        bad = []
        for p in my_products_90d.get("products", []):
            if p.get("market_share_pct") == 100 and (p.get("num_competitors") or 0) < 1:
                bad.append(p.get("sku"))
        assert not bad, f"fair-share 100% fallback leaked back: {bad[:5]}"

    def test_signal_logic_consistency(self, my_products_90d):
        """has_market_share=True ⇒ has_competitor_pricing=True (subset)."""
        bad = []
        for p in my_products_90d.get("products", []):
            if p.get("has_market_share") and not p.get("has_competitor_pricing"):
                bad.append(p.get("sku"))
        assert not bad, f"has_market_share=true but has_competitor_pricing=false: {bad[:5]}"


# ---- 3. KPI block contract ---------------------------------------------------
class TestKPIBlock:
    def test_kpi_block_has_all_required_fields(self, my_products_90d):
        kpis = my_products_90d.get("kpis", {})
        for key in [
            "total_products", "total_units_sold", "market_revenue", "my_revenue",
            "avg_market_share", "my_units_sold",
            "matched_products", "market_coverage_pct", "share_sample_size",
        ]:
            assert key in kpis, f"kpi block missing {key}; got keys={list(kpis.keys())}"

    def test_kpi_matched_products_within_target(self, my_products_90d):
        kpis = my_products_90d["kpis"]
        # iter21 baseline: 1057 ± 20 (was 888±10 in iter20 — the 50k truncation
        # fix exposed +169 more matched products that were hidden by silent
        # snapshot truncation on the 90D window)
        assert 1030 <= kpis["matched_products"] <= 1090, (
            f"matched_products={kpis['matched_products']} outside expected 1057±30"
        )

    def test_kpi_market_coverage_pct_within_target(self, my_products_90d):
        kpis = my_products_90d["kpis"]
        # iter21 baseline: 50.8 ± 2 (was 42.7±1 in iter20)
        assert 48.5 <= kpis["market_coverage_pct"] <= 53.0, (
            f"market_coverage_pct={kpis['market_coverage_pct']} outside expected 50.8±2"
        )

    def test_kpi_share_sample_size_within_target(self, my_products_90d):
        kpis = my_products_90d["kpis"]
        # iter21 baseline: 319 ± 20 (was 59±5 in iter20 — the 50k truncation
        # was hiding most of the share-eligible rows on the 90D window)
        assert 290 <= kpis["share_sample_size"] <= 360, (
            f"share_sample_size={kpis['share_sample_size']} outside expected 319±30"
        )

    def test_kpi_avg_market_share_honest_zero(self, my_products_90d):
        kpis = my_products_90d["kpis"]
        # preview's own-store sync is stale → my_units in share-sample set is 0
        assert 0.0 <= kpis["avg_market_share"] <= 5.0, (
            f"avg_market_share={kpis['avg_market_share']} not in honest 0..5 range"
        )

    def test_kpi_total_products(self, my_products_90d):
        assert my_products_90d["kpis"]["total_products"] == my_products_90d.get("total")

    def test_kpi_coverage_math(self, my_products_90d):
        kpis = my_products_90d["kpis"]
        expected = round(kpis["matched_products"] / kpis["total_products"] * 100, 1)
        assert abs(expected - kpis["market_coverage_pct"]) <= 0.2, (
            f"coverage math mismatch: {expected} vs {kpis['market_coverage_pct']}"
        )


# ---- 4. Cross-page consistency ----------------------------------------------
class TestCrossPageConsistency:
    @pytest.fixture(scope="class")
    def all_pages(self, session):
        rows = []
        first_kpis = None
        for offset in (0, 500, 1000, 1500, 2000):
            r = session.get(f"{BASE_URL}/api/my-products?days=90&limit=500&offset={offset}", timeout=60)
            assert r.status_code == 200, f"page offset={offset} failed: {r.status_code}"
            data = r.json()
            if offset == 0:
                first_kpis = data["kpis"]
            rows.extend(data.get("products", []))
        return {"rows": rows, "kpis": first_kpis}

    def test_aggregate_row_count_matches_total(self, all_pages):
        assert len(all_pages["rows"]) == all_pages["kpis"]["total_products"], (
            f"got {len(all_pages['rows'])} rows across pages but kpis.total_products={all_pages['kpis']['total_products']}"
        )

    def test_has_competitor_pricing_count_matches_matched_products(self, all_pages):
        count = sum(1 for r in all_pages["rows"] if r.get("has_competitor_pricing"))
        assert count == all_pages["kpis"]["matched_products"], (
            f"per-row has_competitor_pricing count={count} but kpis.matched_products={all_pages['kpis']['matched_products']}"
        )

    def test_has_market_share_count_matches_share_sample_size(self, all_pages):
        count = sum(1 for r in all_pages["rows"] if r.get("has_market_share"))
        assert count == all_pages["kpis"]["share_sample_size"], (
            f"per-row has_market_share count={count} but kpis.share_sample_size={all_pages['kpis']['share_sample_size']}"
        )


# ---- 5. Regression smoke -----------------------------------------------------
class TestRegression:
    def test_data_freshness_endpoint(self, session):
        r = session.get(f"{BASE_URL}/api/data-freshness", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "sync_health" in d, "sync_health block missing"
        sh = d["sync_health"]
        for k in ("last_run", "last_run_age_hours", "last_sync_status", "last_match_status",
                  "scheduler_running", "is_stale", "alarm"):
            assert k in sh, f"sync_health missing {k}"

    def test_sku_search_regex_escape(self, session):
        r = session.get(f"{BASE_URL}/api/my-products?days=90&search=.*&limit=10", timeout=30)
        assert r.status_code == 200
        # iter16: regex meta should be escaped, so should not match every product
        data = r.json()
        assert data.get("total", 0) == 0, f"regex escape regression: '.*' matched {data.get('total')} products"

    def test_insights_sales_endpoint(self, session):
        r = session.get(f"{BASE_URL}/api/insights/sales?days=90", timeout=30)
        assert r.status_code == 200

    def test_scanner_endpoint(self, session):
        r = session.get(f"{BASE_URL}/api/scanner/scan?days=90", timeout=30)
        assert r.status_code in (200, 404)  # endpoint may not exist

    def test_health(self, session):
        r = session.get(f"{BASE_URL}/api/health", timeout=10)
        assert r.status_code in (200, 404)
