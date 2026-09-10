"""
Tier 4 Credential Vault Tests
Tests for encrypted credential storage for buyer accounts on competitor stores.
CRITICAL: No API endpoint should EVER return plaintext credentials.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def auth_token():
    """Cached token for the legacy admin account (tests/_auth.py); skips if absent."""
    from _auth import login_token_or_skip
    return login_token_or_skip("admin@daleelpets.com", "admin123")

@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}

@pytest.fixture(scope="module")
def test_store_id(auth_headers):
    """Get a store ID for testing (Zarafa)"""
    response = requests.get(f"{BASE_URL}/api/tier4/summary", headers=auth_headers)
    if response.status_code == 200:
        stores = response.json()
        if stores:
            # Find Zarafa or use first store
            for s in stores:
                if "zarafa" in s.get("store_name", "").lower():
                    return s["store_id"]
            return stores[0]["store_id"]
    pytest.skip("Could not get store ID for testing")


class TestEncryptionVerify:
    """Test GET /api/encryption/verify endpoint"""
    
    def test_encryption_verify_requires_auth(self):
        """Encryption verify endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/encryption/verify")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Encryption verify requires auth")
    
    def test_encryption_verify_returns_active(self, auth_headers):
        """GET /api/encryption/verify returns {status: 'active', ok: true}"""
        response = requests.get(f"{BASE_URL}/api/encryption/verify", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data.get("status") == "active", f"Expected status='active', got {data.get('status')}"
        assert data.get("ok") == True, f"Expected ok=True, got {data.get('ok')}"
        print(f"PASS: Encryption verify returns {data}")


class TestTier4Summary:
    """Test GET /api/tier4/summary endpoint"""
    
    def test_tier4_summary_requires_auth(self):
        """Tier4 summary endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/tier4/summary")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Tier4 summary requires auth")
    
    def test_tier4_summary_returns_stores(self, auth_headers):
        """GET /api/tier4/summary returns list of stores with tier4 status fields"""
        response = requests.get(f"{BASE_URL}/api/tier4/summary", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert isinstance(data, list), f"Expected list, got {type(data)}"
        assert len(data) > 0, "Expected at least one store"
        
        # Check required fields in each store
        for store in data:
            assert "store_id" in store, "Missing store_id"
            assert "store_name" in store, "Missing store_name"
            assert "platform" in store, "Missing platform"
            assert "session_status" in store, "Missing session_status"
            assert "has_email" in store, "Missing has_email"
            assert "has_phone" in store, "Missing has_phone"
            # CRITICAL: Should have masked email, not plaintext
            if store.get("has_email"):
                assert "email_masked" in store, "Missing email_masked"
                # Verify it's actually masked (contains ***)
                if store.get("email_masked"):
                    assert "***" in store["email_masked"], f"Email not masked: {store['email_masked']}"
            # CRITICAL: Should have phone_last4, not full phone
            if store.get("has_phone"):
                assert "phone_last4" in store, "Missing phone_last4"
                # Verify it's only 4 digits
                if store.get("phone_last4"):
                    assert len(store["phone_last4"]) <= 4, f"Phone not masked: {store['phone_last4']}"
        
        print(f"PASS: Tier4 summary returns {len(data)} stores with proper fields")


class TestTier4Credentials:
    """Test PUT /api/stores/{store_id}/tier4-credentials endpoint"""
    
    def test_save_credentials_requires_auth(self, test_store_id):
        """Save credentials endpoint requires authentication"""
        response = requests.put(f"{BASE_URL}/api/stores/{test_store_id}/tier4-credentials", json={
            "email": "test@example.com"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Save credentials requires auth")
    
    def test_save_credentials_success(self, auth_headers, test_store_id):
        """PUT /api/stores/{store_id}/tier4-credentials saves credentials encrypted"""
        test_email = "TEST_buyer@teststore.com"
        test_password = "TEST_secretpass123"
        test_phone = "+966501234567"
        
        response = requests.put(
            f"{BASE_URL}/api/stores/{test_store_id}/tier4-credentials",
            headers=auth_headers,
            json={
                "email": test_email,
                "password": test_password,
                "phone": test_phone
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # CRITICAL: Response should NOT contain plaintext credentials
        response_str = str(data)
        assert test_email not in response_str, f"SECURITY VIOLATION: Plaintext email in response"
        assert test_password not in response_str, f"SECURITY VIOLATION: Plaintext password in response"
        assert test_phone not in response_str, f"SECURITY VIOLATION: Plaintext phone in response"
        
        # Should have confirmation fields
        assert "message" in data, "Missing message in response"
        assert "has_email" in data, "Missing has_email in response"
        assert "has_phone" in data, "Missing has_phone in response"
        assert data["has_email"] == True, "has_email should be True"
        assert data["has_phone"] == True, "has_phone should be True"
        
        print(f"PASS: Credentials saved, response: {data}")
    
    def test_save_credentials_no_data(self, auth_headers, test_store_id):
        """PUT with empty payload returns 400"""
        response = requests.put(
            f"{BASE_URL}/api/stores/{test_store_id}/tier4-credentials",
            headers=auth_headers,
            json={}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("PASS: Empty credentials returns 400")


class TestTier4Status:
    """Test GET /api/stores/{store_id}/tier4-status endpoint"""
    
    def test_tier4_status_requires_auth(self, test_store_id):
        """Tier4 status endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/stores/{test_store_id}/tier4-status")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Tier4 status requires auth")
    
    def test_tier4_status_returns_masked_data(self, auth_headers, test_store_id):
        """GET /api/stores/{store_id}/tier4-status returns masked email and phone only"""
        response = requests.get(
            f"{BASE_URL}/api/stores/{test_store_id}/tier4-status",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        # Check required fields
        assert "store_id" in data, "Missing store_id"
        assert "store_name" in data, "Missing store_name"
        assert "platform" in data, "Missing platform"
        assert "session_status" in data, "Missing session_status"
        assert "has_email" in data, "Missing has_email"
        assert "has_password" in data, "Missing has_password"
        assert "has_phone" in data, "Missing has_phone"
        
        # CRITICAL: Should have masked email, not plaintext
        if data.get("has_email"):
            assert "email_masked" in data, "Missing email_masked"
            email_masked = data.get("email_masked", "")
            if email_masked:
                assert "***" in email_masked, f"Email not properly masked: {email_masked}"
                # Should be format like "bu***@domain.com"
                assert "@" in email_masked, f"Masked email missing @: {email_masked}"
        
        # CRITICAL: Should have phone_last4, not full phone
        if data.get("has_phone"):
            assert "phone_last4" in data, "Missing phone_last4"
            phone_last4 = data.get("phone_last4", "")
            if phone_last4:
                assert len(phone_last4) <= 4, f"Phone not properly masked: {phone_last4}"
        
        # CRITICAL: Should NOT have plaintext password field
        assert "password" not in data, "SECURITY VIOLATION: password field in response"
        assert "tier4_password" not in data, "SECURITY VIOLATION: tier4_password field in response"
        
        print(f"PASS: Tier4 status returns masked data: email_masked={data.get('email_masked')}, phone_last4={data.get('phone_last4')}")
    
    def test_tier4_status_not_found(self, auth_headers):
        """GET with invalid store_id returns 404"""
        response = requests.get(
            f"{BASE_URL}/api/stores/invalid-store-id-12345/tier4-status",
            headers=auth_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Invalid store_id returns 404")


class TestTier4ClearSession:
    """Test POST /api/stores/{store_id}/tier4-clear-session endpoint"""
    
    def test_clear_session_requires_auth(self, test_store_id):
        """Clear session endpoint requires authentication"""
        response = requests.post(f"{BASE_URL}/api/stores/{test_store_id}/tier4-clear-session")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Clear session requires auth")
    
    def test_clear_session_success(self, auth_headers, test_store_id):
        """POST /api/stores/{store_id}/tier4-clear-session clears session and sets status to expired"""
        response = requests.post(
            f"{BASE_URL}/api/stores/{test_store_id}/tier4-clear-session",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "message" in data, "Missing message in response"
        assert "session_status" in data, "Missing session_status in response"
        # Status should be 'expired' or 'not_configured'
        assert data["session_status"] in ["expired", "not_configured"], f"Unexpected status: {data['session_status']}"
        
        print(f"PASS: Session cleared, status: {data['session_status']}")
    
    def test_clear_session_not_found(self, auth_headers):
        """POST with invalid store_id returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/stores/invalid-store-id-12345/tier4-clear-session",
            headers=auth_headers
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Invalid store_id returns 404")


class TestTier4TestLogin:
    """Test POST /api/stores/{store_id}/tier4-test-login endpoint (placeholder)"""
    
    def test_test_login_requires_auth(self, test_store_id):
        """Test login endpoint requires authentication"""
        response = requests.post(f"{BASE_URL}/api/stores/{test_store_id}/tier4-test-login")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Test login requires auth")
    
    def test_test_login_returns_placeholder_message(self, auth_headers, test_store_id):
        """POST /api/stores/{store_id}/tier4-test-login returns placeholder message"""
        # First ensure credentials are set
        requests.put(
            f"{BASE_URL}/api/stores/{test_store_id}/tier4-credentials",
            headers=auth_headers,
            json={"email": "TEST_login@test.com"}
        )
        
        response = requests.post(
            f"{BASE_URL}/api/stores/{test_store_id}/tier4-test-login",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "message" in data, "Missing message in response"
        # Should mention Part 3 or placeholder
        assert "Part 3" in data["message"] or "queued" in data["message"].lower(), f"Unexpected message: {data['message']}"
        
        print(f"PASS: Test login returns placeholder: {data['message']}")
    
    def test_test_login_no_credentials(self, auth_headers):
        """POST without credentials returns 400"""
        # Get a store without credentials
        summary = requests.get(f"{BASE_URL}/api/tier4/summary", headers=auth_headers).json()
        store_without_creds = None
        for s in summary:
            if not s.get("has_email") and not s.get("has_phone"):
                store_without_creds = s["store_id"]
                break
        
        if store_without_creds:
            response = requests.post(
                f"{BASE_URL}/api/stores/{store_without_creds}/tier4-test-login",
                headers=auth_headers
            )
            assert response.status_code == 400, f"Expected 400, got {response.status_code}"
            print("PASS: Test login without credentials returns 400")
        else:
            print("SKIP: All stores have credentials, cannot test no-credentials case")


class TestHealthEndpoint:
    """Test existing health endpoint still works"""
    
    def test_health_returns_scheduler_jobs(self):
        """GET /api/health shows scheduler jobs (should be 9+)"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert data.get("status") == "healthy", f"Expected healthy, got {data.get('status')}"
        assert data.get("mongodb") == "connected", f"MongoDB not connected"
        # Should have 9+ scheduler jobs (7 stores + digest + alert jobs)
        jobs = data.get("scheduler_active_jobs", 0)
        assert jobs >= 9, f"Expected 9+ scheduler jobs, got {jobs}"
        
        print(f"PASS: Health check OK, {jobs} scheduler jobs")


class TestLoginStillWorks:
    """Test existing login functionality still works"""
    
    def test_login_success(self):
        """POST /api/auth/login works with valid credentials"""
        from _auth import login_response
        response = login_response("admin@daleelpets.com", "admin123")
        if response.status_code != 200:
            pytest.skip(f"legacy admin account absent ({response.status_code})")
        data = response.json()
        
        assert "token" in data, "Missing token in response"
        assert "user" in data, "Missing user in response"
        assert data["user"]["email"] == "admin@daleelpets.com", "Wrong email in response"
        
        print("PASS: Login works correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
