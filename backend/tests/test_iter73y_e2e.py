"""
Iteration 73y E2E test — bounded seller-snapshot query + perf-probe + freshness + regression.
Runs against the external preview URL through REACT_APP_BACKEND_URL.
"""
import os
import time
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

SUPER_EMAIL = "a.disi@taqueen.sa"
SUPER_PASSWORD = "Ahmaddc90@"

PROBE_SKU = "IT73Y-PROBE-052742024363"


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def super_token():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import login_token
    return login_token(SUPER_EMAIL, SUPER_PASSWORD)


@pytest.fixture(scope="session")
def super_headers(super_token):
    return {"Authorization": f"Bearer {super_token}"}


@pytest.fixture(scope="session")
def normal_user_headers(super_headers):
    """Create a normal user via super-admin endpoint, return their bearer headers."""
    email = "test_iter73y_normal@example.com"
    password = "NormalUser#123"
    # Try to create — ignore 400/409 if already present
    requests.post(
        f"{BASE_URL}/api/admin/users",
        headers=super_headers,
        json={
            "email": email,
            "password": password,
            "name": "Iter73y Normal",
            "role": "user",
            "allowed_pages": ["my_products"],
        },
        timeout=20,
    )
    # Login (shared cached response — login is rate limited to 5/min)
    from _auth import login_response
    r = login_response(email, password)
    if r is None or r.status_code != 200:
        pytest.skip(f"could not login normal user: {getattr(r, 'status_code', 'no-response')}")
    tok = r.json().get("token") or r.json().get("access_token")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="session")
def seeded_probe():
    """Seed data via probe script, cleanup after all tests."""
    import subprocess
    # The probe must write to the LIVE database the API reads — a sibling test
    # module may have left DB_NAME pointing at its own throwaway database, and
    # a subprocess inherits os.environ.
    env = dict(os.environ)
    env.pop("DB_NAME", None)
    for line in Path("/app/backend/.env").read_text().splitlines():
        if line.startswith("DB_NAME="):
            env["DB_NAME"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    p = subprocess.run(
        ["python3", "tools_iter73y_e2e_probe.py"],
        cwd="/app/backend", env=env,
        capture_output=True, text=True, timeout=120,
    )
    print("SEED STDOUT:", p.stdout[-2000:])
    print("SEED STDERR:", p.stderr[-1000:])
    assert p.returncode == 0, f"seed failed: {p.stderr}"
    yield PROBE_SKU
    c = subprocess.run(
        ["python3", "tools_iter73y_e2e_probe.py", "clean"],
        cwd="/app/backend", env=env,
        capture_output=True, text=True, timeout=60,
    )
    print("CLEAN:", c.stdout[-500:], c.stderr[-500:])


# ---------- Perf probe ----------
class TestPerfProbe:
    def test_perf_probe_super_admin_200(self, super_headers, seeded_probe):
        r = requests.get(
            f"{BASE_URL}/api/admin/perf-probe",
            params={"sku": seeded_probe},
            headers=super_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:500]}"
        data = r.json()
        assert "timings_ms" in data, data
        assert "seller_snapshots" in data["timings_ms"], data["timings_ms"]
        assert "counts" in data
        assert "indexes" in data
        idx = data["indexes"]
        assert "product_snapshots" in idx
        assert "product_matches" in idx
        assert "plans" in data
        # 4 key classes should have plans, none collscan
        expected_classes = {"sku", "barcode", "variant_skus", "variant_barcodes"}
        found = set(data["plans"].keys())
        assert expected_classes.issubset(found), f"missing classes: {expected_classes - found}"
        for key_class, plan in data["plans"].items():
            assert plan.get("collscan") is False, f"COLLSCAN detected for {key_class}: {plan}"

    def test_perf_probe_forbidden_for_normal_user(self, normal_user_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/perf-probe",
            params={"sku": PROBE_SKU},
            headers=normal_user_headers,
            timeout=15,
        )
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:300]}"


# ---------- Ensure indexes ----------
class TestEnsureIndexes:
    def test_ensure_indexes_idempotent(self, super_headers):
        for i in range(2):
            r = requests.post(
                f"{BASE_URL}/api/admin/ensure-snapshot-indexes",
                headers=super_headers,
                timeout=60,
            )
            assert r.status_code == 200, f"call {i} status {r.status_code}: {r.text[:300]}"
            data = r.json()
            assert data.get("ok") is True, data
            assert data.get("created_or_verified", 0) >= 30, f"only {data.get('created_or_verified')}"
            failed = data.get("failed", {})
            assert failed == {} or failed == [], f"failures: {failed}"
            existing = data.get("existing_indexes", {})
            assert "product_matches" in existing, existing


# ---------- Product /full seller_count ----------
class TestProductFull:
    def test_product_full_returns_three_sellers_fast(self, super_headers, seeded_probe):
        t0 = time.time()
        r = requests.get(
            f"{BASE_URL}/api/products/{seeded_probe}/full",
            params={"days": 30},
            headers=super_headers,
            timeout=15,
        )
        dt = time.time() - t0
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        assert dt < 5.0, f"too slow: {dt:.2f}s"
        data = r.json()
        assert data.get("seller_count") == 3, f"seller_count={data.get('seller_count')} data keys={list(data)}"
        sp = data.get("store_prices") or []
        assert len(sp) == 3, f"store_prices len={len(sp)}"
        assert data.get("price_range"), "missing price_range"
        history = data.get("history") or data.get("price_history") or {}
        # history is either dict keyed by store_id or list; accept both
        if isinstance(history, dict):
            assert len(history) >= 3, f"history keys={list(history)}"
        elif isinstance(history, list):
            store_ids = {h.get("store_id") for h in history}
            assert len(store_ids) >= 3

    def test_product_non_full_also_three_sellers(self, super_headers, seeded_probe):
        r = requests.get(
            f"{BASE_URL}/api/products/{seeded_probe}",
            headers=super_headers,
            timeout=15,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        data = r.json()
        # possible fields
        sc = data.get("seller_count")
        sp = data.get("store_prices") or []
        if sc is not None:
            assert sc == 3, f"seller_count={sc}"
        else:
            assert len(sp) == 3, f"store_prices len={len(sp)}"


# ---------- Data freshness ----------
class TestDataFreshness:
    def test_freshness_fast_200(self, super_headers):
        t0 = time.time()
        r = requests.get(f"{BASE_URL}/api/data-freshness", headers=super_headers, timeout=10)
        dt = time.time() - t0
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        assert dt < 3.0, f"too slow: {dt:.2f}s"
        data = r.json()
        assert "overall" in data, data
        stores = data.get("stores") or data.get("per_store") or []
        assert isinstance(stores, list), type(stores)
        # If any entry, verify shape
        for e in stores:
            for k in ("store_id", "store_name", "bucket", "snapshot_count", "age_days"):
                assert k in e, f"missing {k} in {e}"


# ---------- Regression on adjacent endpoints ----------
REGRESSION_ENDPOINTS = [
    ("/api/products", {"limit": 5}),
    ("/api/my-products", {}),
    ("/api/insights/summary", {"days": 30}),
    ("/api/price-intel/dashboard", {}),
    ("/api/discounts/top-pct", {"days": 30}),
    ("/api/scanner/opportunities", {}),
    ("/api/price-intel/store-ranking", {}),
]


@pytest.mark.parametrize("path,params", REGRESSION_ENDPOINTS)
def test_regression_endpoints_200(super_headers, path, params):
    r = requests.get(f"{BASE_URL}{path}", params=params, headers=super_headers, timeout=20)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:300]}"
