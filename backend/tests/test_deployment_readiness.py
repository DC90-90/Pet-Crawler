"""
Daleel Pets — Deployment Readiness Tests
Tests for: Health endpoint, Rate limiting, Security headers, Auth flow
"""
import pytest
import requests
import os
import time

# IMPORTANT: Use localhost:8001 for rate limiting tests (Kubernetes ingress masks IPs)
BASE_URL_LOCAL = "http://localhost:8001"
BASE_URL_EXTERNAL = os.environ.get('REACT_APP_BACKEND_URL', 'https://saudi-pets-monitor.preview.emergentagent.com').rstrip('/')

# Test credentials — from environment or clearly labeled test-only defaults
ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@daleelpets.com")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "admin123")


class TestHealthEndpoint:
    """Test GET /api/health endpoint - NO authentication required"""
    
    def test_health_endpoint_accessible_without_auth(self):
        """Health endpoint should be accessible without authentication"""
        response = requests.get(f"{BASE_URL_EXTERNAL}/api/health", timeout=10)
        assert response.status_code == 200, f"Health endpoint returned {response.status_code}"
        print(f"✓ Health endpoint accessible without auth: {response.status_code}")
    
    def test_health_endpoint_returns_all_required_fields(self):
        """Health endpoint should return all 6 required fields"""
        response = requests.get(f"{BASE_URL_EXTERNAL}/api/health", timeout=10)
        assert response.status_code == 200
        
        data = response.json()
        required_fields = [
            "status",
            "mongodb",
            "scheduler_active_jobs",
            "playwright_available",
            "last_successful_crawl",
            "uptime_seconds"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
            print(f"✓ Field '{field}' present: {data[field]}")
        
        # Validate field types
        assert data["status"] in ["healthy", "degraded"], f"Invalid status: {data['status']}"
        assert data["mongodb"] in ["connected", "disconnected"], f"Invalid mongodb status: {data['mongodb']}"
        assert isinstance(data["scheduler_active_jobs"], int), "scheduler_active_jobs should be int"
        assert isinstance(data["playwright_available"], bool), "playwright_available should be bool"
        assert isinstance(data["uptime_seconds"], (int, float)), "uptime_seconds should be numeric"
        
        print(f"✓ All 6 required fields present with valid types")
        print(f"  Health response: {data}")


class TestSecurityHeaders:
    """Test HTTP security headers on all API responses"""
    
    def test_security_headers_on_health_endpoint(self):
        """Security headers should be present on /api/health"""
        response = requests.get(f"{BASE_URL_EXTERNAL}/api/health", timeout=10)
        
        # Check required security headers
        headers_to_check = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
        }
        
        for header, expected_value in headers_to_check.items():
            actual_value = response.headers.get(header)
            assert actual_value == expected_value, f"Header {header}: expected '{expected_value}', got '{actual_value}'"
            print(f"✓ {header}: {actual_value}")
        
        # CSP header should be present (value can vary)
        csp = response.headers.get("Content-Security-Policy")
        assert csp is not None, "Content-Security-Policy header missing"
        print(f"✓ Content-Security-Policy: {csp[:50]}...")
    
    def test_security_headers_on_login_endpoint(self):
        """Security headers should be present on /api/auth/login"""
        response = requests.post(
            f"{BASE_URL_EXTERNAL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=10
        )
        
        # Check required security headers
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert response.headers.get("Content-Security-Policy") is not None
        
        print(f"✓ All security headers present on login endpoint")


class TestAuthFlow:
    """Test authentication still works after middleware additions"""
    
    def test_login_with_valid_credentials(self):
        """Login should work with valid credentials"""
        response = requests.post(
            f"{BASE_URL_EXTERNAL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=10
        )
        
        assert response.status_code == 200, f"Login failed: {response.status_code} - {response.text}"
        
        data = response.json()
        assert "token" in data, "Token missing from login response"
        assert "user" in data, "User missing from login response"
        assert data["user"]["email"] == ADMIN_EMAIL
        
        # Check httpOnly cookie is set
        cookies = response.cookies
        assert "daleel_token" in cookies or response.headers.get("Set-Cookie"), "httpOnly cookie not set"
        
        print(f"✓ Login successful for {ADMIN_EMAIL}")
        print(f"  Token: {data['token'][:20]}...")
        print(f"  User: {data['user']}")
        
        return data["token"]
    
    def test_login_with_invalid_credentials(self):
        """Login should fail with invalid credentials"""
        response = requests.post(
            f"{BASE_URL_EXTERNAL}/api/auth/login",
            json={"email": "wrong@example.com", "password": "wrongpassword"},
            timeout=10
        )
        
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print(f"✓ Invalid credentials correctly rejected with 401")
    
    def test_protected_endpoint_with_token(self):
        """Protected endpoints should work with valid token"""
        # First login
        login_response = requests.post(
            f"{BASE_URL_EXTERNAL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=10
        )
        token = login_response.json()["token"]
        
        # Access protected endpoint
        response = requests.get(
            f"{BASE_URL_EXTERNAL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        
        assert response.status_code == 200, f"Protected endpoint failed: {response.status_code}"
        data = response.json()
        assert data["email"] == ADMIN_EMAIL
        print(f"✓ Protected endpoint accessible with valid token")


class TestRateLimiting:
    """
    Test rate limiting on auth endpoints (5/min/IP)
    IMPORTANT: Must use localhost:8001 - Kubernetes ingress masks client IPs
    """
    
    def test_login_rate_limiting(self):
        """
        POST /api/auth/login should allow 5 requests, then return 429 on 6th
        Using localhost:8001 to bypass Kubernetes ingress IP masking
        """
        print("\n--- Testing Rate Limiting on /api/auth/login ---")
        print("Using localhost:8001 (bypasses K8s ingress IP masking)")
        
        # Use a unique email to avoid interfering with other tests
        test_email = f"ratelimit_test_{int(time.time())}@example.com"
        
        results = []
        for i in range(7):
            response = requests.post(
                f"{BASE_URL_LOCAL}/api/auth/login",
                json={"email": test_email, "password": "wrongpassword"},
                timeout=10
            )
            results.append(response.status_code)
            print(f"  Request {i+1}: HTTP {response.status_code}")
            
            # Small delay to ensure requests are processed
            time.sleep(0.1)
        
        # First 5 should be 401 (invalid credentials, but not rate limited)
        for i in range(5):
            assert results[i] == 401, f"Request {i+1} should be 401, got {results[i]}"
        
        # 6th and 7th should be 429 (rate limited)
        assert results[5] == 429, f"Request 6 should be 429 (rate limited), got {results[5]}"
        print(f"✓ Rate limiting working: 5 requests allowed, 6th returned 429")
        
        # Verify the error message
        response = requests.post(
            f"{BASE_URL_LOCAL}/api/auth/login",
            json={"email": test_email, "password": "wrongpassword"},
            timeout=10
        )
        if response.status_code == 429:
            data = response.json()
            assert "Too many attempts" in data.get("detail", ""), f"Expected rate limit message, got: {data}"
            print(f"✓ Rate limit message correct: {data.get('detail')}")
    
    def test_register_rate_limiting(self):
        """
        POST /api/auth/register should allow 5 requests, then return 429 on 6th
        Using localhost:8001 to bypass Kubernetes ingress IP masking
        """
        print("\n--- Testing Rate Limiting on /api/auth/register ---")
        print("Using localhost:8001 (bypasses K8s ingress IP masking)")
        
        # Wait a bit to reset rate limit from previous test
        time.sleep(2)
        
        results = []
        for i in range(7):
            # Use unique email each time to avoid "already registered" error
            test_email = f"ratelimit_reg_{int(time.time())}_{i}@example.com"
            response = requests.post(
                f"{BASE_URL_LOCAL}/api/auth/register",
                json={"email": test_email, "password": "testpass123", "name": "Test User"},
                timeout=10
            )
            results.append(response.status_code)
            print(f"  Request {i+1}: HTTP {response.status_code}")
            
            time.sleep(0.1)
        
        # First 5 should be 200 (successful registration)
        for i in range(5):
            assert results[i] == 200, f"Request {i+1} should be 200, got {results[i]}"
        
        # 6th and 7th should be 429 (rate limited)
        assert results[5] == 429, f"Request 6 should be 429 (rate limited), got {results[5]}"
        print(f"✓ Rate limiting working on register: 5 requests allowed, 6th returned 429")


class TestDeployFiles:
    """Test that all required deployment files exist"""
    
    def test_deploy_directory_files(self):
        """All required deployment files should exist"""
        deploy_dir = "/app/deploy"
        required_files = [
            "backend.Dockerfile",
            "frontend.Dockerfile",
            "docker-compose.yml",
            "nginx.conf",
            ".env.example",
            "DEPLOYMENT_GUIDE.md",
            "start.sh",
            "PLATFORM_SUMMARY.md"
        ]
        
        missing_files = []
        for filename in required_files:
            filepath = os.path.join(deploy_dir, filename)
            if os.path.exists(filepath):
                print(f"✓ {filename} exists")
            else:
                missing_files.append(filename)
                print(f"✗ {filename} MISSING")
        
        assert len(missing_files) == 0, f"Missing deployment files: {missing_files}"
        print(f"\n✓ All {len(required_files)} required deployment files present")
    
    def test_start_sh_is_executable(self):
        """start.sh should be executable"""
        start_sh = "/app/deploy/start.sh"
        assert os.path.exists(start_sh), "start.sh not found"
        assert os.access(start_sh, os.X_OK), "start.sh is not executable"
        print(f"✓ start.sh is executable")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
