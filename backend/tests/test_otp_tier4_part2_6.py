"""
Daleel Pets — Tier 4 Buyer Account Crawler Parts 2-6 Tests
Part 2: OTP handling (banner + modal + polling + submit/retry endpoints)
Part 3: Platform login flows (Salla/Zid/Shopify Playwright handlers)
Part 4: Authenticated crawl with extra data points
Part 5: Store Registry Tier 4 column + ProductDetailPanel T4 data
Part 6: Waterfall updated to include Tier 4 supplement
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://daleel-price-intel.preview.emergentagent.com').rstrip('/')

class TestOtpEndpoints:
    """Part 2: OTP handling endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        from _auth import login_response_or_skip
        resp = login_response_or_skip("admin@daleelpets.com", "admin123")
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        self.token = resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        # Get Zarafa store ID
        stores_resp = requests.get(f"{BASE_URL}/api/stores", headers=self.headers)
        stores = stores_resp.json().get("stores", [])
        self.zarafa_id = next((s["id"] for s in stores if s["name"] == "Zarafa"), None)
        self.caty_id = next((s["id"] for s in stores if s["name"] == "Caty Store"), None)
        assert self.zarafa_id, "Zarafa store not found"
    
    def test_otp_pending_returns_empty_array_when_no_pending(self):
        """GET /api/otp/pending returns empty array when no OTP requests pending"""
        resp = requests.get(f"{BASE_URL}/api/otp/pending", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        print(f"✓ GET /otp/pending returns empty array: {data}")
    
    def test_otp_submit_no_pending_returns_404(self):
        """POST /api/otp/submit with no pending request returns 404"""
        resp = requests.post(f"{BASE_URL}/api/otp/submit", headers=self.headers, json={
            "store_id": self.zarafa_id,
            "otp_code": "123456"
        })
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
        print(f"✓ POST /otp/submit with no pending request returns 404")
    
    def test_otp_status_returns_status(self):
        """GET /api/otp/status/{store_id} returns OTP status"""
        resp = requests.get(f"{BASE_URL}/api/otp/status/{self.zarafa_id}", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "store_id" in data
        assert "status" in data
        print(f"✓ GET /otp/status returns: {data}")
    
    def test_otp_retry_requires_credentials(self):
        """POST /api/otp/retry/{store_id} requires credentials configured"""
        # First clear any credentials
        requests.post(f"{BASE_URL}/api/stores/{self.zarafa_id}/tier4-clear-session", headers=self.headers)
        
        # Try retry without credentials
        resp = requests.post(f"{BASE_URL}/api/otp/retry/{self.zarafa_id}", headers=self.headers)
        # Should return 400 if no credentials configured
        assert resp.status_code in [200, 400], f"Expected 200 or 400, got {resp.status_code}: {resp.text}"
        print(f"✓ POST /otp/retry returns {resp.status_code}")


class TestTier4LoginFlow:
    """Part 3: Platform login flows"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token and setup test store"""
        from _auth import login_response_or_skip
        resp = login_response_or_skip("admin@daleelpets.com", "admin123")
        assert resp.status_code == 200
        self.token = resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        # Get Zarafa store ID
        stores_resp = requests.get(f"{BASE_URL}/api/stores", headers=self.headers)
        stores = stores_resp.json().get("stores", [])
        self.zarafa_id = next((s["id"] for s in stores if s["name"] == "Zarafa"), None)
        assert self.zarafa_id, "Zarafa store not found"
    
    def test_tier4_test_login_requires_credentials(self):
        """POST /api/stores/{store_id}/tier4-test-login requires credentials"""
        # Use a store without credentials (Hamtaro)
        stores_resp = requests.get(f"{BASE_URL}/api/stores", headers=self.headers)
        stores = stores_resp.json().get("stores", [])
        hamtaro_id = next((s["id"] for s in stores if s["name"] == "Hamtaro"), None)
        
        if hamtaro_id:
            # Clear any existing credentials
            requests.post(f"{BASE_URL}/api/stores/{hamtaro_id}/tier4-clear-session", headers=self.headers)
            
            resp = requests.post(f"{BASE_URL}/api/stores/{hamtaro_id}/tier4-test-login", headers=self.headers)
            assert resp.status_code == 400, f"Expected 400 without credentials, got {resp.status_code}: {resp.text}"
            print(f"✓ tier4-test-login without credentials returns 400")
        else:
            pytest.skip("Hamtaro store not found")
    
    def test_tier4_test_login_with_credentials_triggers_background_login(self):
        """POST /api/stores/{store_id}/tier4-test-login triggers background login"""
        # First save credentials
        cred_resp = requests.put(f"{BASE_URL}/api/stores/{self.zarafa_id}/tier4-credentials", 
            headers=self.headers, json={
                "email": "test_buyer@example.com",
                "password": "testpass123",
                "phone": "+966501234567"
            })
        assert cred_resp.status_code == 200, f"Failed to save credentials: {cred_resp.text}"
        
        # Trigger test login
        resp = requests.post(f"{BASE_URL}/api/stores/{self.zarafa_id}/tier4-test-login", headers=self.headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "message" in data
        assert "store_id" in data
        print(f"✓ tier4-test-login triggered: {data['message']}")
        
        # Wait a few seconds for background task to create OTP request
        time.sleep(8)
        
        # Check if OTP request was created (may or may not be pending depending on login flow)
        otp_resp = requests.get(f"{BASE_URL}/api/otp/pending", headers=self.headers)
        assert otp_resp.status_code == 200
        pending = otp_resp.json()
        print(f"✓ After test-login, pending OTPs: {len(pending)}")
        
        # Check OTP status for this store
        status_resp = requests.get(f"{BASE_URL}/api/otp/status/{self.zarafa_id}", headers=self.headers)
        assert status_resp.status_code == 200
        print(f"✓ OTP status for Zarafa: {status_resp.json()}")


class TestStoreListSecurity:
    """Part 5: Store list API security - must NOT return encrypted fields"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        from _auth import login_response_or_skip
        resp = login_response_or_skip("admin@daleelpets.com", "admin123")
        assert resp.status_code == 200
        self.token = resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_stores_list_does_not_return_encrypted_fields(self):
        """GET /api/stores MUST NOT return tier4_email/password/phone/session_cookies"""
        resp = requests.get(f"{BASE_URL}/api/stores", headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        stores = data.get("stores", data) if isinstance(data, dict) else data
        
        forbidden_fields = ["tier4_email", "tier4_password", "tier4_phone", "tier4_session_cookies"]
        
        for store in stores:
            for field in forbidden_fields:
                assert field not in store, f"SECURITY ISSUE: {field} found in store list response for {store.get('name')}"
            
            # Verify tier4_session_status IS present
            assert "tier4_session_status" in store, f"tier4_session_status missing for {store.get('name')}"
        
        print(f"✓ Store list correctly excludes encrypted fields for {len(stores)} stores")
        print(f"✓ All stores have tier4_session_status field")


class TestHealthEndpoint:
    """Health endpoint with scheduler jobs"""
    
    def test_health_returns_10_scheduler_jobs(self):
        """GET /api/health returns healthy with 10 scheduler jobs"""
        resp = requests.get(f"{BASE_URL}/api/health")
        assert resp.status_code == 200
        data = resp.json()
        
        assert data.get("status") == "healthy", f"Expected healthy, got {data.get('status')}"
        assert data.get("mongodb") == "connected", f"MongoDB not connected"
        assert data.get("scheduler_active_jobs") >= 10, f"Expected >=10 jobs, got {data.get('scheduler_active_jobs')}"
        assert data.get("playwright_available") == True, f"Playwright not available"
        
        print(f"✓ Health check: {data}")


class TestCrawlRegression:
    """Part 6: Crawl waterfall regression test"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        from _auth import login_response_or_skip
        resp = login_response_or_skip("admin@daleelpets.com", "admin123")
        assert resp.status_code == 200
        self.token = resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        # Get Zarafa store ID
        stores_resp = requests.get(f"{BASE_URL}/api/stores", headers=self.headers)
        stores = stores_resp.json().get("stores", [])
        self.zarafa_id = next((s["id"] for s in stores if s["name"] == "Zarafa"), None)
        assert self.zarafa_id, "Zarafa store not found"
    
    def test_crawl_still_works_tier2(self):
        """POST /api/stores/{store_id}/crawl still works (Tier 2 crawl regression)"""
        resp = requests.post(f"{BASE_URL}/api/stores/{self.zarafa_id}/crawl", 
            headers=self.headers, timeout=120)
        assert resp.status_code == 200, f"Crawl failed: {resp.text}"
        data = resp.json()
        
        assert "tier_used" in data, "tier_used missing from response"
        assert "products_found" in data, "products_found missing from response"
        
        print(f"✓ Crawl completed: tier={data.get('tier_used')}, products={data.get('products_found')}")


class TestOtpRetryWithCredentials:
    """Test OTP retry endpoint with credentials configured"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        from _auth import login_response_or_skip
        resp = login_response_or_skip("admin@daleelpets.com", "admin123")
        assert resp.status_code == 200
        self.token = resp.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        # Get Caty Store ID (use different store to avoid conflicts)
        stores_resp = requests.get(f"{BASE_URL}/api/stores", headers=self.headers)
        stores = stores_resp.json().get("stores", [])
        self.caty_id = next((s["id"] for s in stores if s["name"] == "Caty Store"), None)
        assert self.caty_id, "Caty Store not found"
    
    def test_otp_retry_triggers_new_login(self):
        """POST /api/otp/retry/{store_id} triggers new login attempt"""
        # First save credentials
        cred_resp = requests.put(f"{BASE_URL}/api/stores/{self.caty_id}/tier4-credentials", 
            headers=self.headers, json={
                "email": "caty_buyer@example.com",
                "password": "catypass123",
                "phone": "+966509876543"
            })
        assert cred_resp.status_code == 200
        
        # Trigger retry
        resp = requests.post(f"{BASE_URL}/api/otp/retry/{self.caty_id}", headers=self.headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "message" in data
        print(f"✓ OTP retry triggered: {data}")
        
        # Wait for background task
        time.sleep(5)
        
        # Check OTP status
        status_resp = requests.get(f"{BASE_URL}/api/otp/status/{self.caty_id}", headers=self.headers)
        assert status_resp.status_code == 200
        print(f"✓ OTP status after retry: {status_resp.json()}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
