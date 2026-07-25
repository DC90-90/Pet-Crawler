"""Iteration 45 regression: gating for new admin endpoints + reused-token regression sweep.

Rate-limit safe: logs in ONCE and reuses the token everywhere.
Skips 200-body checks on the two heavy admin endpoints (audit / vat-backfill dry run)
because they commonly 502/504 through the ingress due to ~60-90s live external fetch.
Only their gating (401/403) is asserted.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or pytest.skip(
    "REACT_APP_BACKEND_URL missing", allow_module_level=True
)
SUPER_EMAIL = "a.disi@taqueen.sa"
SUPER_PASS = "Ahmaddc90@"


@pytest.fixture(scope="session")
def super_token():
    """Log in ONCE per session; on 429, wait 60s and retry once."""
    url = f"{BASE_URL}/api/auth/login"
    payload = {"email": SUPER_EMAIL, "password": SUPER_PASS}
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code == 429:
        time.sleep(60)
        r = requests.post(url, json=payload, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="session")
def auth_headers(super_token):
    return {"Authorization": f"Bearer {super_token}"}


# ---------- Auth basics ----------

def test_auth_me(auth_headers):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=20)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("email") == SUPER_EMAIL
    assert body.get("role") in ("super_admin", "superadmin", "admin"), body


# ---------- Admin gating (the CRITICAL part) ----------

def test_own_store_price_audit_requires_auth():
    r = requests.get(f"{BASE_URL}/api/admin/own-store-price-audit", timeout=20)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text[:200]}"


def test_own_store_vat_backfill_requires_auth():
    r = requests.post(
        f"{BASE_URL}/api/admin/own-store-vat-backfill",
        params={"dry_run": "true"},
        timeout=20,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code} {r.text[:200]}"


def test_own_store_price_audit_invalid_token():
    r = requests.get(
        f"{BASE_URL}/api/admin/own-store-price-audit",
        headers={"Authorization": "Bearer notavalidtoken.xxx.yyy"},
        timeout=20,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


def test_own_store_vat_backfill_invalid_token():
    r = requests.post(
        f"{BASE_URL}/api/admin/own-store-vat-backfill",
        params={"dry_run": "true"},
        headers={"Authorization": "Bearer notavalidtoken.xxx.yyy"},
        timeout=20,
    )
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


# ---------- Preservation: hardened /api/health ----------

def test_health_hardened():
    t0 = time.time()
    r = requests.get(f"{BASE_URL}/api/health", timeout=15)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body.get("status") == "healthy", body
    assert body.get("mongodb") == "connected", body
    assert "scheduler_active_jobs" in body, body
    assert elapsed < 10, f"health too slow: {elapsed:.1f}s"


# ---------- Regression sweep with reused token ----------

REGRESSION_ENDPOINTS = [
    ("GET", "/api/my-products", None),
    ("GET", "/api/my-products", {"days": 7}),
    ("GET", "/api/my-products", {"days": 30}),
    ("GET", "/api/my-products", {"days": 90}),
    ("GET", "/api/price-intel/store-ranking", None),
    ("GET", "/api/price-intel/dashboard", None),
    ("GET", "/api/insights/summary", None),
    ("GET", "/api/insights/leaderboard", None),
    ("GET", "/api/insights/top-sellers", None),
    ("GET", "/api/discounts/top-pct", None),
    ("GET", "/api/scanner/opportunities", None),
    ("GET", "/api/stores", None),
    ("GET", "/api/scheduler/status", None),
]


@pytest.mark.parametrize("method,path,params", REGRESSION_ENDPOINTS)
def test_regression_endpoint(method, path, params, auth_headers):
    url = f"{BASE_URL}{path}"
    r = requests.request(method, url, headers=auth_headers, params=params, timeout=60)
    assert r.status_code == 200, f"{path} params={params} -> {r.status_code}: {r.text[:300]}"
    # Must be valid JSON
    try:
        body = r.json()
    except Exception as e:
        pytest.fail(f"{path} did not return JSON: {e}; body={r.text[:200]}")
    assert body is not None
