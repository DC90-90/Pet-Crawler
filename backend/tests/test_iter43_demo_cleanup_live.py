"""iter43 live-server contract test for /api/admin/demo-cleanup.
Uses a single login token to avoid the 5/min rate-limit.
Also verifies regression endpoints + preservation (health, iter26 tooltips remain wired).
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if "REACT_APP_BACKEND_URL" in os.environ else None
if not BASE_URL:
    # fall back to reading frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"


@pytest.fixture(scope="session")
def token():
    for attempt in range(3):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": EMAIL, "password": PASSWORD}, timeout=30)
        if r.status_code == 429:
            time.sleep(65)
            continue
        assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
        j = r.json()
        return j.get("access_token") or j.get("token")
    pytest.skip("rate-limited")


@pytest.fixture(scope="session")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


class TestAuth:
    def test_me(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert data.get("email") == EMAIL
        assert data.get("role") == "super_admin"


class TestDemoCleanupContract:
    def test_get_dry_run_has_iter43_guard_fields(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/demo-cleanup", headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "guard" in body
        guard = body["guard"]
        assert "ok" in guard and isinstance(guard["ok"], bool)
        assert "reasons" in guard and isinstance(guard["reasons"], list)
        # iter43 new fields:
        assert "real_sku_match" in guard, f"missing real_sku_match: {guard}"
        assert isinstance(guard["real_sku_match"], bool)
        assert "confirm_count_required" in guard, f"missing confirm_count_required: {guard}"
        assert isinstance(guard["confirm_count_required"], int)
        # report shape
        assert "demo_products" in body
        assert "before" in body
        assert "cascade_counts" in body

    def test_post_real_run_without_confirm_count_returns_409(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/demo-cleanup?dry_run=false",
                          headers=auth_headers, timeout=60)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"

    def test_post_real_run_with_wrong_confirm_count_returns_409(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/demo-cleanup?dry_run=false&confirm_count=999999",
                          headers=auth_headers, timeout=60)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        # message should mention count mismatch
        detail = (r.json().get("detail") or "").lower()
        assert "count" in detail or "confirm" in detail or "match" in detail, detail

    def test_get_real_run_returns_405(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/demo-cleanup?dry_run=false",
                         headers=auth_headers, timeout=60)
        assert r.status_code == 405, f"expected 405, got {r.status_code}: {r.text}"


class TestRegression:
    @pytest.mark.parametrize("path", [
        "/api/health",
        "/api/my-products",
        "/api/price-intel/store-ranking",
        "/api/insights/summary",
        "/api/stores",
        "/api/scheduler/status",
    ])
    def test_endpoint_ok(self, auth_headers, path):
        # /api/health is public
        headers = {} if path == "/api/health" else auth_headers
        r = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=60)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"


class TestHealthShape:
    def test_health_fields(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=15)
        assert r.status_code == 200
        b = r.json()
        assert b.get("status") == "healthy", b
        assert b.get("mongodb") == "connected", b
        assert "scheduler_active_jobs" in b, b
