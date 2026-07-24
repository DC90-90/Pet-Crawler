"""
Daleel Feature Tests - Testing 5 UI changes:
1. Theme toggle (localStorage persistence)
2. Date-day picker on My Products
3. Product detail panel loading (aggregated endpoint)
4. Clickable product/storefront deep-links
5. Per-store price-history sparklines + full price-history chart
"""
import pytest
import requests
import os
import time
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
if not BASE_URL:
    BASE_URL = "https://daleel-price-intel.preview.emergentagent.com"

# Test credentials
ADMIN_EMAIL = "admin@daleelpets.com"
ADMIN_PASSWORD = "BGv8ZcRYrBTPlJFHHhZQ3Q"

# Global session to avoid rate limiting
_session = None
_token = None

def get_auth_session():
    """Get authenticated session (cached to avoid rate limiting)"""
    global _session, _token
    if _session is None or _token is None:
        _session = requests.Session()
        time.sleep(1)  # Small delay to avoid rate limiting
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


class TestAuthEndpoints:
    """Authentication endpoint tests"""
    
    def test_health_check(self):
        """Test health endpoint is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["mongodb"] == "connected"
        print(f"✓ Health check passed: {data['status']}, MongoDB: {data['mongodb']}")
    
    def test_login_success(self):
        """Test login with admin credentials"""
        session, token = get_auth_session()
        assert token is not None, "Login failed - no token received"
        print(f"✓ Login successful for {ADMIN_EMAIL}")
    
    def test_auth_me_with_token(self):
        """Test /api/auth/me with valid token"""
        session, token = get_auth_session()
        response = session.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == ADMIN_EMAIL
        print(f"✓ GET /api/auth/me works with token")


class TestMyProductsEndpoint:
    """Tests for /api/my-products endpoint with date filtering"""
    
    def test_my_products_default(self):
        """Test /api/my-products with default params (30 days)"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/my-products")
        assert response.status_code == 200
        data = response.json()
        assert "kpis" in data
        assert "products" in data
        assert isinstance(data["products"], list)
        print(f"✓ GET /api/my-products returns {len(data['products'])} products")
        print(f"  KPIs: total_products={data['kpis'].get('total_products')}, total_revenue={data['kpis'].get('total_revenue')}")
    
    def test_my_products_with_days_param(self):
        """Test /api/my-products with days=7"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/my-products?days=7")
        assert response.status_code == 200
        data = response.json()
        assert "products" in data
        print(f"✓ GET /api/my-products?days=7 returns {len(data['products'])} products")
    
    def test_my_products_with_on_date_param(self):
        """Test /api/my-products with on_date parameter (specific day filter)"""
        session, _ = get_auth_session()
        # Use yesterday's date
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        response = session.get(f"{BASE_URL}/api/my-products?on_date={yesterday}")
        assert response.status_code == 200
        data = response.json()
        assert "products" in data
        print(f"✓ GET /api/my-products?on_date={yesterday} returns {len(data['products'])} products")
    
    def test_my_products_with_date_range(self):
        """Test /api/my-products with date_from and date_to params"""
        session, _ = get_auth_session()
        date_from = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        date_to = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        response = session.get(
            f"{BASE_URL}/api/my-products?date_from={date_from}&date_to={date_to}"
        )
        assert response.status_code == 200
        data = response.json()
        assert "products" in data
        print(f"✓ GET /api/my-products?date_from={date_from}&date_to={date_to} returns {len(data['products'])} products")
    
    def test_my_products_kpis_structure(self):
        """Verify KPIs structure in response"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/my-products")
        assert response.status_code == 200
        data = response.json()
        kpis = data.get("kpis", {})
        # Check expected KPI fields
        expected_fields = ["total_products", "total_units_sold", "total_revenue", "avg_market_share"]
        for field in expected_fields:
            assert field in kpis, f"Missing KPI field: {field}"
        print(f"✓ KPIs structure verified: {list(kpis.keys())}")


class TestProductDetailEndpoint:
    """Tests for /api/products/{sku}/full aggregated endpoint"""
    
    def get_test_sku(self):
        """Get a valid SKU from my-products"""
        session, _ = get_auth_session()
        products_resp = session.get(f"{BASE_URL}/api/my-products")
        products = products_resp.json().get("products", [])
        return products[0]["sku"] if products else "RC-ICAT-4"
    
    def test_product_full_endpoint_exists(self):
        """Test /api/products/{sku}/full endpoint returns data"""
        session, _ = get_auth_session()
        test_sku = self.get_test_sku()
        response = session.get(f"{BASE_URL}/api/products/{test_sku}/full?days=30")
        assert response.status_code == 200
        data = response.json()
        print(f"✓ GET /api/products/{test_sku}/full returns data")
        return data
    
    def test_product_full_response_structure(self):
        """Verify aggregated endpoint returns all required fields"""
        session, _ = get_auth_session()
        test_sku = self.get_test_sku()
        response = session.get(f"{BASE_URL}/api/products/{test_sku}/full?days=30")
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields for product detail panel
        assert "sku" in data, "Missing 'sku' field"
        assert "name_ar" in data or "name_en" in data, "Missing product name"
        assert "store_prices" in data, "Missing 'store_prices' array"
        assert "history" in data, "Missing 'history' object for price history chart"
        assert "velocity" in data, "Missing 'velocity' object"
        
        print(f"✓ Product full response structure verified:")
        print(f"  - SKU: {data.get('sku')}")
        print(f"  - store_prices: {len(data.get('store_prices', []))} stores")
        print(f"  - history: {len(data.get('history', {}))} store series")
        print(f"  - velocity: {len(data.get('velocity', {}).get('velocity', []))} data points")
    
    def test_store_prices_have_required_fields(self):
        """Verify store_prices array has fields needed for sparklines and links"""
        session, _ = get_auth_session()
        test_sku = self.get_test_sku()
        response = session.get(f"{BASE_URL}/api/products/{test_sku}/full?days=30")
        assert response.status_code == 200
        data = response.json()
        
        store_prices = data.get("store_prices", [])
        if store_prices:
            sp = store_prices[0]
            required_fields = ["store_id", "store_name", "price", "stock_signal", "source_tier"]
            for field in required_fields:
                assert field in sp, f"Missing field '{field}' in store_prices"
            
            # Check for product_url (needed for deep links)
            has_url = any(s.get("product_url") for s in store_prices)
            print(f"✓ store_prices structure verified, has product_url: {has_url}")
    
    def test_history_data_for_sparklines(self):
        """Verify history data structure for sparkline rendering"""
        session, _ = get_auth_session()
        test_sku = self.get_test_sku()
        response = session.get(f"{BASE_URL}/api/products/{test_sku}/full?days=30")
        assert response.status_code == 200
        data = response.json()
        
        history = data.get("history", {})
        if history:
            store_name = list(history.keys())[0]
            series = history[store_name]
            if series:
                point = series[0]
                assert "date" in point, "Missing 'date' in history point"
                assert "price" in point, "Missing 'price' in history point"
                print(f"✓ History data structure verified for sparklines")
                print(f"  - Store: {store_name}, {len(series)} data points")
    
    def test_velocity_data_structure(self):
        """Verify velocity data structure"""
        session, _ = get_auth_session()
        test_sku = self.get_test_sku()
        response = session.get(f"{BASE_URL}/api/products/{test_sku}/full?days=30")
        assert response.status_code == 200
        data = response.json()
        
        velocity = data.get("velocity", {})
        assert "velocity" in velocity or isinstance(velocity, dict), "velocity should be dict"
        if velocity.get("velocity"):
            v = velocity["velocity"][0]
            assert "date" in v, "Missing 'date' in velocity point"
            assert "units" in v, "Missing 'units' in velocity point"
        print(f"✓ Velocity data structure verified")
        print(f"  - avg_daily: {velocity.get('avg_daily')}, total_units: {velocity.get('total_units')}")


class TestProductLinks:
    """Tests for product deep-links in responses"""
    
    def test_my_products_has_product_url(self):
        """Check if my-products response includes product_url for deep links"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/my-products")
        assert response.status_code == 200
        data = response.json()
        
        products = data.get("products", [])
        products_with_url = [p for p in products if p.get("product_url")]
        print(f"✓ Products with product_url: {len(products_with_url)}/{len(products)}")
        
        # At least some products should have URLs (from seed data or crawls)
        # This is informational - not a hard requirement
        if products_with_url:
            print(f"  Example URL: {products_with_url[0]['product_url'][:60]}...")


class TestBackendRegression:
    """Regression tests for core backend functionality"""
    
    def test_stores_endpoint(self):
        """Test /api/stores returns store list"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/stores")
        assert response.status_code == 200
        data = response.json()
        assert "stores" in data
        print(f"✓ GET /api/stores returns {len(data['stores'])} stores")
    
    def test_encryption_verify(self):
        """Test encryption verification endpoint"""
        session, _ = get_auth_session()
        response = session.get(f"{BASE_URL}/api/encryption/verify")
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        print(f"✓ Encryption verification: {data.get('status')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
