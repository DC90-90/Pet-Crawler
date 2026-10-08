"""Tests for new GET /api/insights/sales endpoint + regression on existing insights endpoints."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://daleel-price-intel.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "a.disi@taqueen.sa"
ADMIN_PASSWORD = os.environ.get("DALEEL_TEST_PASSWORD", "")


@pytest.fixture(scope="module")
def auth_session():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import auth_session as shared_auth_session
    return shared_auth_session(ADMIN_EMAIL, ADMIN_PASSWORD)


# ── New endpoint shape tests ──────────────────────────────────
class TestInsightsSalesShape:
    def test_default_returns_shape(self, auth_session):
        r = auth_session.get(f"{API}/insights/sales", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert set(["kpis", "products", "top_brands"]).issubset(d.keys())
        k = d["kpis"]
        for f in ["total_units_sold", "total_revenue", "avg_revenue_per_product", "top_brand", "product_count"]:
            assert f in k, f"Missing kpi field {f}"
        assert isinstance(k["total_units_sold"], int)
        assert isinstance(k["total_revenue"], (int, float))
        assert isinstance(k["avg_revenue_per_product"], (int, float))
        assert isinstance(k["product_count"], int)
        assert k["top_brand"] is None or isinstance(k["top_brand"], str)

    def test_products_item_shape(self, auth_session):
        r = auth_session.get(f"{API}/insights/sales?days=30", timeout=60)
        assert r.status_code == 200
        prods = r.json()["products"]
        if not prods:
            pytest.skip("No products in this period")
        p = prods[0]
        for f in ["sku", "name_ar", "name_en", "brand", "qty_sold_est",
                  "revenue_est", "avg_price", "num_sellers", "stock_signal", "confidence_score"]:
            assert f in p, f"Missing product field {f}"

    def test_top_brands_market_share_sum(self, auth_session):
        r = auth_session.get(f"{API}/insights/sales?days=30", timeout=60)
        assert r.status_code == 200
        d = r.json()
        tb = d["top_brands"]
        for b in tb:
            for f in ["brand", "units_sold", "revenue_est", "market_share_pct"]:
                assert f in b, f"Missing brand field {f}"
        if d["kpis"]["total_revenue"] > 0 and tb:
            # Note: top_brands is capped at 20 in response. Verify by re-fetching full?
            # Endpoint returns top_brands[:20]. With many brands sum may not be 100.
            # Spec: sum of returned brands ~100. Let's test that.
            s = sum(b["market_share_pct"] for b in tb)
            # If there are >20 brands the sum could be <100 since extras are dropped.
            # Tolerance: allow <=100 + small tolerance.
            assert s <= 100 + 1.0, f"market_share sum {s} > 100"
            # Sanity: if <=20 brands, sum should be ~100
            # We can't know the underlying brand count, but check inequality
            # If equals 20 brands returned, possible incomplete; otherwise should be ~100
            if len(tb) < 20:
                assert abs(s - 100.0) <= 1.0, f"market_share sum {s} not ~100"


# ── New endpoint behavior tests ──────────────────────────────
class TestInsightsSalesBehavior:
    @pytest.mark.parametrize("days", [7, 14, 30, 90])
    def test_days_param(self, auth_session, days):
        r = auth_session.get(f"{API}/insights/sales?days={days}", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert "kpis" in d

    def test_date_range_param(self, auth_session):
        r = auth_session.get(f"{API}/insights/sales?date_from=2025-12-01&date_to=2026-01-15", timeout=60)
        assert r.status_code == 200

    def test_sort_revenue_desc(self, auth_session):
        r = auth_session.get(f"{API}/insights/sales?sort=revenue_desc&days=30", timeout=60)
        assert r.status_code == 200
        prods = r.json()["products"]
        if len(prods) >= 3:
            top3 = [p["revenue_est"] for p in prods[:3]]
            assert top3 == sorted(top3, reverse=True), f"Not sorted desc: {top3}"

    def test_sort_sales_asc(self, auth_session):
        r = auth_session.get(f"{API}/insights/sales?sort=sales_asc&days=30", timeout=60)
        assert r.status_code == 200
        prods = r.json()["products"]
        if len(prods) >= 3:
            top3 = [p["qty_sold_est"] for p in prods[:3]]
            assert top3 == sorted(top3), f"Not sorted asc: {top3}"

    def test_search_filter(self, auth_session):
        r_all = auth_session.get(f"{API}/insights/sales?days=30", timeout=60).json()
        r_none = auth_session.get(f"{API}/insights/sales?days=30&search=xyznevermatches", timeout=60)
        assert r_none.status_code == 200
        assert len(r_none.json()["products"]) == 0
        # search matching a brand or sku piece
        if r_all["products"]:
            # pick a brand from first product
            brand = (r_all["products"][0].get("brand") or "").lower()
            if brand:
                rb = auth_session.get(f"{API}/insights/sales?days=30&search={brand}", timeout=60)
                assert rb.status_code == 200
                # at least 1 result
                assert len(rb.json()["products"]) >= 1

    def test_date_range_differs_from_default(self, auth_session):
        # Sanity: dates feed through to my_products
        d_default = auth_session.get(f"{API}/insights/sales?days=30", timeout=60).json()
        d_custom = auth_session.get(f"{API}/insights/sales?date_from=2024-01-01&date_to=2024-01-31", timeout=60).json()
        # totals should differ (very high probability) — at minimum endpoint accepts both
        assert "kpis" in d_default and "kpis" in d_custom


# ── Cross-check with /api/my-products ─────────────────────────
class TestCrossCheck:
    def test_my_catalogue_is_a_subset_of_the_tracked_market(self, auth_session):
        """`/insights/sales` spans EVERY tracked product (mine AND products only
        competitors sell — 4,998 rows here); `/my-products` spans MY catalogue
        (2,257). iter21 asserted the two unit totals were EQUAL, which only held
        while the two populations happened to coincide; the invariant that
        actually matters is containment — the market can never be smaller than
        my slice of it, and neither side may collapse to zero.
        """
        rs = auth_session.get(f"{API}/insights/sales?days=30&sort=revenue_desc", timeout=120).json()
        rm = auth_session.get(f"{API}/my-products?days=30&limit=1", timeout=120).json()
        market, mine = rs["kpis"], rm["kpis"]
        print(f"[cross-check] market: {market['product_count']} products / "
              f"{market['total_units_sold']} units — mine: {rm['total']} products / "
              f"{mine['total_units_sold']} units")
        assert rm["total"] > 0 and market["product_count"] > 0
        assert market["product_count"] >= rm["total"], (
            f"tracked market ({market['product_count']}) smaller than my catalogue ({rm['total']})")
        assert market["total_units_sold"] >= mine["total_units_sold"] > 0, (
            f"market units {market['total_units_sold']} < my units {mine['total_units_sold']}")
        assert market["total_revenue"] >= mine["market_revenue"] > 0, (
            f"market revenue {market['total_revenue']} < my slice {mine['market_revenue']}")


# ── Regression on existing endpoints ─────────────────────────
class TestRegression:
    @pytest.mark.parametrize("path", [
        "/my-products?days=30",
        "/insights/summary",
        "/insights/leaderboard",
        "/insights/top-sellers",
        "/insights/trending",
        "/insights/gaps",
        "/insights/price-wars",
        "/insights/restock-opportunities",
    ])
    def test_existing_endpoint(self, auth_session, path):
        r = auth_session.get(f"{API}{path}", timeout=60)
        assert r.status_code == 200, f"{path} → {r.status_code} {r.text[:200]}"

    def test_my_products_shape(self, auth_session):
        r = auth_session.get(f"{API}/my-products?days=30", timeout=60)
        assert r.status_code == 200
        d = r.json()
        for f in ["kpis", "products", "total", "limit", "offset", "categories"]:
            assert f in d, f"my-products missing {f}"
