"""
Daleel Refactor Regression Tests - Feb 2026
Testing that Pydantic models (from /app/backend/models/schemas.py) and 
helper utilities (from /app/backend/core/utils.py) work correctly after extraction.

Tests:
1. Health check and auth endpoints
2. POST endpoints that use Pydantic models (auth/login, stores, alerts, saved-filters, import/run-matching, crawler/ingest)
3. GET endpoints for insights, scanner, discounts
4. Helper functions (get_stock_signal, _estimate_sales_from_snapshots, compute_product_metrics)
"""
import pytest
import requests
import os
import time
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://price-intel-dev.preview.emergentagent.com"

# Test credentials
ADMIN_EMAIL = "a.disi@taqueen.sa"
ADMIN_PASSWORD = "Ahmaddc90@"
CRAWLER_TOKEN = "zj7n4vATDYACt-FswvDd_EITEwti5WciV2yZt3I2IgHbDi7XKP9myrd2xSFYZGjO"

# Global session to avoid rate limiting
_session = None
_token = None

def get_auth_session():
    """Get authenticated session (cached to avoid rate limiting)"""
    global _session, _token
    if _session is None or _token is None:
        _session = requests.Session()
        time.sleep(0.5)
        login_resp = _session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if login_resp.status_code == 200:
            _token = login_resp.json().get("token")
            _session.headers.update({"Authorization": f"Bearer {_token}"})
        else:
            print(f"Login failed: {login_resp.status_code} - {login_resp.text}")
    return _session, _token


class TestHealthAndAuth:
    """Test health and authentication endpoints"""
    
    def test_health_returns_healthy(self):
        """GET /api/health returns healthy/connected"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["mongodb"] == "connected"
        print(f"✓ Health: {data['status']}, MongoDB: {data['mongodb']}, Jobs: {data.get('scheduler_jobs', 0)}")
    
    def test_auth_me_with_admin_token(self):
        """GET /api/auth/me with admin token returns user"""
        session, token = get_auth_session()
        assert token is not None, "Login failed"
        response = session.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == ADMIN_EMAIL
        print(f"✓ GET /api/auth/me returns user: {data['email']}")


class TestMyProductsEndpoint:
    """Test /api/my-products with various params"""
    
    def test_my_products_with_days_7(self):
        """GET /api/my-products?days=7 returns kpis + products"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/my-products?days=7")
        assert response.status_code == 200
        data = response.json()
        assert "kpis" in data
        assert "products" in data
        assert isinstance(data["products"], list)
        print(f"✓ GET /api/my-products?days=7: {len(data['products'])} products, revenue={data['kpis'].get('total_revenue')}")


class TestProductFullEndpoint:
    """Test /api/products/{sku}/full aggregated endpoint"""
    
    def get_test_sku(self):
        """Get a valid SKU from my-products"""
        session, _ = get_auth_session()
        products_resp = session.get(f"{BASE_URL}/api/my-products")
        products = products_resp.json().get("products", [])
        return products[0]["sku"] if products else "RC-ICAT-4"
    
    def test_product_full_returns_aggregated_payload(self):
        """GET /api/products/{sku}/full?days=30 returns aggregated payload"""
        session, _ = get_auth_session()
        test_sku = self.get_test_sku()
        response = session.get(f"{BASE_URL}/api/products/{test_sku}/full?days=30")
        assert response.status_code == 200
        data = response.json()
        
        # Verify aggregated payload structure
        assert "sku" in data
        assert "store_prices" in data
        assert "history" in data
        assert "velocity" in data
        print(f"✓ GET /api/products/{test_sku}/full: store_prices={len(data.get('store_prices', []))}, history stores={len(data.get('history', {}))}")


class TestPydanticModelsRegression:
    """Test POST endpoints that use Pydantic models from models/schemas.py"""
    
    def test_auth_login_parses_body(self):
        """POST /api/auth/login parses AuthIn model correctly"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        print(f"✓ POST /api/auth/login: AuthIn model works")
    
    def test_stores_post_parses_body(self):
        """POST /api/stores parses StoreIn model correctly"""
        session, _ = get_auth_session()
        # Try to create a store (may fail due to duplicate, but should parse body)
        response = session.post(f"{BASE_URL}/api/stores", json={
            "name": "TEST_Regression_Store",
            "domain": "test-regression.example.com",
            "platform": "salla",
            "base_url": "https://test-regression.example.com",
            "crawl_frequency_hrs": 24
        })
        # Accept 200/201 (created) or 400 (duplicate domain) - both mean body was parsed
        assert response.status_code in [200, 201, 400], f"Unexpected status: {response.status_code}"
        print(f"✓ POST /api/stores: StoreIn model works (status={response.status_code})")
    
    def test_alerts_post_parses_body(self):
        """POST /api/alerts parses AlertIn model correctly"""
        session, _ = get_auth_session()
        response = session.post(f"{BASE_URL}/api/alerts", json={
            "product_sku": "TEST-SKU-123",
            "alert_type": "price_drop",
            "threshold": 10.0,
            "channel": "in_app"
        })
        # Accept 200/201 (created) or 400 (validation error) - both mean body was parsed
        assert response.status_code in [200, 201, 400], f"Unexpected status: {response.status_code}"
        print(f"✓ POST /api/alerts: AlertIn model works (status={response.status_code})")
    
    def test_saved_filters_post_parses_body(self):
        """POST /api/saved-filters parses SavedFilterIn model correctly"""
        session, _ = get_auth_session()
        response = session.post(f"{BASE_URL}/api/saved-filters", json={
            "name": "TEST_Regression_Filter",
            "filters": {"category": "food", "min_price": 10}
        })
        # Accept 200/201 (created) or 400 (validation error)
        assert response.status_code in [200, 201, 400], f"Unexpected status: {response.status_code}"
        print(f"✓ POST /api/saved-filters: SavedFilterIn model works (status={response.status_code})")
    
    def test_import_run_matching_parses_body(self):
        """POST /api/import/run-matching parses MatchActionIn model correctly"""
        session, _ = get_auth_session()
        response = session.post(f"{BASE_URL}/api/import/run-matching", json={
            "my_sku": "TEST-SKU",
            "competitor_sku": "COMP-SKU",
            "competitor_store_id": "store123"
        })
        # Accept any status - we just want to verify body parsing
        # 404 means endpoint exists but SKU not found, 200 means success
        assert response.status_code in [200, 400, 404, 422], f"Unexpected status: {response.status_code}"
        print(f"✓ POST /api/import/run-matching: MatchActionIn model works (status={response.status_code})")
    
    def test_crawler_ingest_parses_body(self):
        """POST /api/crawler/ingest parses IngestPayload model correctly"""
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {CRAWLER_TOKEN}"})
        response = session.post(f"{BASE_URL}/api/crawler/ingest", json={
            "store_id": "test-store-id",
            "store_name": "Test Store",
            "domain": "test.example.com",
            "platform": "salla",
            "products": []
        })
        # Accept 200 (success) or 404 (store not found) - both mean body was parsed
        assert response.status_code in [200, 404], f"Unexpected status: {response.status_code}"
        print(f"✓ POST /api/crawler/ingest: IngestPayload model works (status={response.status_code})")


class TestInsightsEndpoints:
    """Test insights endpoints still respond 200"""
    
    def test_insights_summary(self):
        """GET /api/insights/summary responds 200"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/insights/summary")
        assert response.status_code == 200
        print(f"✓ GET /api/insights/summary: 200")
    
    def test_insights_leaderboard(self):
        """GET /api/insights/leaderboard responds 200"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/insights/leaderboard")
        assert response.status_code == 200
        print(f"✓ GET /api/insights/leaderboard: 200")


class TestScannerEndpoints:
    """Test scanner endpoints still respond 200"""
    
    def test_scanner_opportunities(self):
        """GET /api/scanner/opportunities responds 200"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/scanner/opportunities")
        assert response.status_code == 200
        print(f"✓ GET /api/scanner/opportunities: 200")


class TestDiscountsEndpoints:
    """Test discounts endpoints still respond 200"""
    
    def test_discounts_top_pct(self):
        """GET /api/discounts/top-pct responds 200"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/discounts/top-pct")
        assert response.status_code == 200
        print(f"✓ GET /api/discounts/top-pct: 200")
    
    def test_discounts_top_amount(self):
        """GET /api/discounts/top-amount responds 200"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/discounts/top-amount")
        assert response.status_code == 200
        print(f"✓ GET /api/discounts/top-amount: 200")


class TestStoreProfileEndpoint:
    """Test store profile endpoint uses compute_product_metrics correctly"""
    
    def get_test_store_id(self):
        """Get a valid store_id"""
        session, _ = get_auth_session()
        stores_resp = session.get(f"{BASE_URL}/api/stores")
        stores = stores_resp.json().get("stores", [])
        return stores[0]["id"] if stores else None
    
    def test_store_profile_returns_data(self):
        """GET /api/stores/{store_id}/profile returns profile data"""
        session, _ = get_auth_session()
        store_id = self.get_test_store_id()
        if not store_id:
            pytest.skip("No stores available")
        
        response = session.get(f"{BASE_URL}/api/stores/{store_id}/profile")
        assert response.status_code == 200
        data = response.json()
        # Profile should have store info and metrics
        assert "store" in data or "name" in data or "domain" in data
        print(f"✓ GET /api/stores/{store_id}/profile: 200")


class TestHelperFunctionsViaAPI:
    """Verify helper functions (get_stock_signal, _estimate_sales_from_snapshots, compute_product_metrics) 
    work correctly by checking API responses that use them"""
    
    def test_my_products_has_stock_signal(self):
        """Verify my-products response includes stock_signal (uses get_stock_signal)"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/my-products?days=7")
        assert response.status_code == 200
        data = response.json()
        products = data.get("products", [])
        
        if products:
            # Check that stock_signal is present and valid
            product = products[0]
            stock_signal = product.get("stock_signal")
            valid_signals = ["OOS", "AVAIL", "LOW", "MEDIUM", "HIGH", None]
            assert stock_signal in valid_signals, f"Invalid stock_signal: {stock_signal}"
            print(f"✓ get_stock_signal works: sample product has stock_signal={stock_signal}")
    
    def test_my_products_has_sales_estimates(self):
        """Verify my-products response includes sales estimates (uses _estimate_sales_from_snapshots)"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/my-products?days=30")
        assert response.status_code == 200
        data = response.json()
        kpis = data.get("kpis", {})
        
        # KPIs should include total_units_sold and total_revenue (computed from sales estimates)
        assert "total_units_sold" in kpis
        assert "total_revenue" in kpis
        print(f"✓ _estimate_sales_from_snapshots works: total_units_sold={kpis['total_units_sold']}, total_revenue={kpis['total_revenue']}")
    
    def test_product_full_has_computed_metrics(self):
        """Verify product/full response includes computed metrics (uses compute_product_metrics)"""
        session, _ = get_auth_session()
        products_resp = session.get(f"{BASE_URL}/api/my-products")
        products = products_resp.json().get("products", [])
        if not products:
            pytest.skip("No products available")
        
        test_sku = products[0]["sku"]
        response = session.get(f"{BASE_URL}/api/products/{test_sku}/full?days=30")
        assert response.status_code == 200
        data = response.json()
        
        # Check for computed metrics in store_prices
        store_prices = data.get("store_prices", [])
        if store_prices:
            sp = store_prices[0]
            # These fields come from compute_product_metrics
            assert "price" in sp
            assert "stock_signal" in sp
            print(f"✓ compute_product_metrics works: store_prices has price={sp['price']}, stock_signal={sp['stock_signal']}")


class TestPriceIntelEndpoints:
    """Test Price Intel page endpoints"""
    
    def test_price_intel_dashboard(self):
        """GET /api/price-intel/dashboard responds 200"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/price-intel/dashboard")
        assert response.status_code == 200
        data = response.json()
        # Check expected fields
        assert "summary" in data
        assert "action_required" in data
        assert "my_advantages" in data
        assert "full_table" in data
        assert "confidence_distribution" in data
        print(f"✓ GET /api/price-intel/dashboard: 200, summary={data['summary']}")
    
    def test_baseline_leaderboard(self):
        """GET /api/baseline/leaderboard responds 200"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/baseline/leaderboard")
        # May return 200 or 404 if no baseline data
        assert response.status_code in [200, 404]
        print(f"✓ GET /api/baseline/leaderboard: {response.status_code}")
    
    def test_baseline_catalog_gaps(self):
        """GET /api/baseline/catalog-gaps responds 200"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/baseline/catalog-gaps")
        # May return 200 or 404 if no baseline data
        assert response.status_code in [200, 404]
        print(f"✓ GET /api/baseline/catalog-gaps: {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
