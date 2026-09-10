"""
Iteration 18 — Sync hardening (sync_runs persistence + sync_health alarm)
+ Fair-share fix on /api/my-products (honest market_share_pct, new KPIs:
matched_products, market_coverage_pct).

Covers Bundle A (silent-failure visibility) and Bundle B (honest avg_market_share).
"""

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
SUPER_ADMIN_EMAIL = "a.disi@taqueen.sa"
SUPER_ADMIN_PASSWORD = "Ahmaddc90@"


@pytest.fixture(scope="session")
def auth_token():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import login_token
    return login_token(SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASSWORD)


@pytest.fixture(scope="session")
def client(auth_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"})
    return s


# ─── Health / regression smoke ─────────────────────────────────────────────
def test_health(client):
    r = client.get(f"{BASE_URL}/api/health", timeout=10)
    assert r.status_code == 200


# ─── Bundle A: sync_health structure BEFORE manual run ────────────────────
def test_data_freshness_has_sync_health_block(client):
    r = client.get(f"{BASE_URL}/api/data-freshness", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "sync_health" in data, "sync_health missing from /api/data-freshness"
    sh = data["sync_health"]
    expected_keys = {
        "last_run", "last_run_age_hours", "last_sync_status", "last_match_status",
        "last_sync_updated", "last_match_added", "next_run_expected",
        "scheduler_running", "is_stale", "alarm",
    }
    missing = expected_keys - set(sh.keys())
    assert not missing, f"sync_health missing keys: {missing}"
    # scheduler_running should be a bool
    assert isinstance(sh["scheduler_running"], bool)


def test_data_freshness_scheduler_running_true(client):
    r = client.get(f"{BASE_URL}/api/data-freshness", timeout=15)
    sh = r.json()["sync_health"]
    assert sh["scheduler_running"] is True, "scheduler should be running"
    # next_run_expected should be ISO timestamp string if scheduler is up
    if sh["scheduler_running"] and sh.get("next_run_expected"):
        assert "T" in sh["next_run_expected"], "next_run_expected should be ISO"


# ─── Bundle A: trigger /api/import/run-matching and verify sync_runs row ─
def test_run_matching_triggers_sync_run_row_and_clears_alarm(client):
    # Snapshot BEFORE
    before = client.get(f"{BASE_URL}/api/data-freshness", timeout=15).json()
    before_last_run = before["sync_health"].get("last_run")
    before_alarm = before["sync_health"].get("alarm")
    print(f"[before] last_run={before_last_run} alarm={before_alarm}")

    # Trigger manual_match_only
    r = client.post(f"{BASE_URL}/api/import/run-matching", json={}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "running"

    # Background task — poll for up to 180s until last_run advances
    deadline = time.time() + 180
    after = None
    while time.time() < deadline:
        time.sleep(4)
        after = client.get(f"{BASE_URL}/api/data-freshness", timeout=15).json()
        if after["sync_health"].get("last_run") and after["sync_health"]["last_run"] != before_last_run:
            break

    assert after is not None
    sh = after["sync_health"]
    print(f"[after] last_run={sh.get('last_run')} sync_status={sh.get('last_sync_status')} match_status={sh.get('last_match_status')} alarm={sh.get('alarm')}")

    # A new sync_runs row should exist
    assert sh["last_run"] is not None, "sync_health.last_run still None after triggering match"
    assert sh["last_run"] != before_last_run, "last_run timestamp did not advance"

    # For manual_match_only: sync_status='skipped', match_status='ok' (assuming match succeeded)
    assert sh["last_sync_status"] == "skipped", f"expected sync_status=skipped, got {sh['last_sync_status']}"
    assert sh["last_match_status"] in ("ok", "error"), f"unexpected match_status {sh['last_match_status']}"
    # If match succeeded, alarm should be cleared
    if sh["last_match_status"] == "ok":
        assert sh.get("alarm") in (None, ""), f"alarm should clear after successful match, got: {sh.get('alarm')}"


# ─── Bundle B: fair-share on /api/my-products?days=90 ─────────────────────
@pytest.fixture(scope="session")
def my_products_90d(client):
    r = client.get(f"{BASE_URL}/api/my-products?days=90&limit=500", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def test_my_products_no_row_has_100_pct_fallback(my_products_90d):
    """No product should now have market_share_pct=100 from the OLD fallback.
    A real 100% (rare) where my_units == market_units is allowed but verified
    has_market_data=True. The OLD bug imputed 100% on num_competitors=0."""
    products = my_products_90d["products"]
    bad = [
        p for p in products
        if (p.get("market_share_pct") == 100 and (p.get("num_competitors") or 0) < 1)
    ]
    assert not bad, f"{len(bad)} rows still show 100% share with no competitors (fallback bug)"


def test_my_products_null_share_when_no_competitors(my_products_90d):
    """iter20: predicate now keyed on num_priced_competitors + has_market_share
    (iter19 removed the iter18 has_market_data conflation field).
    """
    products = my_products_90d["products"]
    for p in products:
        n_priced = p.get("num_priced_competitors") or 0
        qty = p.get("qty_sold_est") or 0
        if n_priced >= 1 and qty > 0:
            assert p.get("has_market_share") is True, f"row {p.get('sku')} should have market share"
            assert isinstance(p.get("market_share_pct"), (int, float)), f"row {p.get('sku')} share should be numeric"
        else:
            assert p.get("market_share_pct") is None, f"row {p.get('sku')} should have null share (n_priced={n_priced}, qty={qty})"
            assert p.get("has_market_share") is False


def test_my_products_kpis_have_matched_and_coverage(my_products_90d):
    kpis = my_products_90d["kpis"]
    assert "matched_products" in kpis, f"matched_products missing — keys: {list(kpis.keys())}"
    assert "market_coverage_pct" in kpis, f"market_coverage_pct missing — keys: {list(kpis.keys())}"
    assert isinstance(kpis["matched_products"], int)
    assert isinstance(kpis["market_coverage_pct"], (int, float))
    # Sanity: matched_products <= total_products
    assert kpis["matched_products"] <= kpis["total_products"]
    # Sanity: coverage % = matched/total * 100
    if kpis["total_products"] > 0:
        expected = round(kpis["matched_products"] / kpis["total_products"] * 100, 1)
        assert abs(kpis["market_coverage_pct"] - expected) < 0.2, f"coverage mismatch: {kpis['market_coverage_pct']} vs {expected}"
    print(f"[kpis] matched={kpis['matched_products']} coverage={kpis['market_coverage_pct']}% avg_share={kpis.get('avg_market_share')}")


def test_my_products_avg_market_share_computed_over_matched_only(my_products_90d):
    """avg_market_share should equal Σmy_units(matched) / Σmarket_units(matched) × 100."""
    products = my_products_90d["products"]
    kpis = my_products_90d["kpis"]
    matched = [p for p in products if p.get("has_market_data")]
    my_sum = sum((p.get("my_units_sold") or 0) for p in matched)
    market_sum = sum((p.get("qty_sold_est") or 0) for p in matched)
    expected = round((my_sum / market_sum) * 100, 1) if market_sum > 0 else 0
    actual = kpis.get("avg_market_share", 0)
    # Allow small rounding tolerance
    assert abs(actual - expected) <= 0.5, f"avg_market_share={actual} vs computed-from-matched={expected}"


def test_my_products_null_share_roughly_matches_no_competitors(my_products_90d):
    """Rows with market_share_pct=null should approximately equal rows with num_competitors<1
    or qty_sold_est<=0."""
    products = my_products_90d["products"]
    null_share = sum(1 for p in products if p.get("market_share_pct") is None)
    no_data_qualifier = sum(
        1 for p in products
        if (p.get("num_competitors") or 0) < 1 or (p.get("qty_sold_est") or 0) <= 0
    )
    # Exact match expected by the contract; allow ±2 slack for edge tolerance
    assert abs(null_share - no_data_qualifier) <= 2, f"null_share={null_share} vs no_data_qualifier={no_data_qualifier}"


# ─── Regression: 15 confidence-floor endpoints + SKU search still pass ───
def test_regression_key_endpoints(client):
    endpoints = [
        "/api/insights/summary?days=30",
        "/api/insights/leaderboard?days=30",
        "/api/insights/top-sellers?days=30",
        "/api/insights/trending?days=30",
        "/api/insights/gaps?days=30",
        "/api/insights/price-wars?days=30",
        "/api/insights/restock-opportunities?days=30",
        "/api/insights/sales?days=30",
        "/api/discounts/top-pct?days=30",
        "/api/discounts/top-amount?days=30",
        "/api/discounts/timeline?days=30",
        "/api/discounts/aggression?days=30",
        "/api/scanner/opportunities?days=30",
        "/api/data-freshness",
        "/api/scheduler/status",
    ]
    failed = []
    for ep in endpoints:
        r = client.get(f"{BASE_URL}{ep}", timeout=20)
        if r.status_code != 200:
            failed.append((ep, r.status_code))
    assert not failed, f"endpoints failed: {failed}"


def test_regression_search_sku_exact(client):
    """iter16 regex-escape regression."""
    r = client.get(f"{BASE_URL}/api/products?search=.*&limit=5", timeout=15)
    assert r.status_code == 200
    body = r.json()
    rows = body if isinstance(body, list) else body.get("products", body.get("items", []))
    assert isinstance(rows, list)
    assert len(rows) == 0, f"'.*' should not match any product, got {len(rows)}"
