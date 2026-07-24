"""iter27 live-preview validation: endpoint availability, cache envelope, latency.

Runs against the public preview URL as the frontend would.
"""
import os
import time
import pytest
import requests

BASE_URL = "https://price-intel-dev.preview.emergentagent.com"
EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"
TIMEOUT_S = 30.0
LATENCY_BUDGET_S = 2.0


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": EMAIL, "password": PASSWORD}, timeout=TIMEOUT_S)
    assert r.status_code == 200, r.text
    j = r.json()
    return j.get("token") or j.get("access_token")


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


def _timed_get(client, path):
    t0 = time.perf_counter()
    r = client.get(f"{BASE_URL}{path}", timeout=TIMEOUT_S)
    return r, time.perf_counter() - t0


# ---- /api/insights/summary ------------------------------------------------
@pytest.mark.parametrize("days", [7, 14, 30, 90])
def test_insights_summary_cache_envelope(client, days):
    r, dt = _timed_get(client, f"/api/insights/summary?days={days}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "cache" in body, f"missing cache envelope: keys={list(body.keys())}"
    c = body["cache"]
    assert c["source"] == "cache", c
    assert "computed_at" in c and "age_seconds" in c and "stale" in c
    assert dt < LATENCY_BUDGET_S, f"days={days} took {dt:.2f}s"


def test_insights_summary_days_45_uncacheable(client):
    r, dt = _timed_get(client, "/api/insights/summary?days=45")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("cache", {}).get("source") == "live_uncacheable", body.get("cache")


# ---- Other insights list endpoints ---------------------------------------
INSIGHTS_LIST = [
    "/api/insights/leaderboard",
    "/api/insights/top-sellers",
    "/api/insights/trending",
    "/api/insights/gaps",
    "/api/insights/price-wars",
    "/api/insights/restock-opportunities",
    "/api/insights/sales",
]

@pytest.mark.parametrize("path", INSIGHTS_LIST)
@pytest.mark.parametrize("days", [7, 14, 30, 90])
def test_insights_list_endpoints_latency(client, path, days):
    r, dt = _timed_get(client, f"{path}?days={days}")
    assert r.status_code == 200, f"{path}?days={days} -> {r.status_code} {r.text[:200]}"
    assert dt < LATENCY_BUDGET_S, f"{path}?days={days} took {dt:.2f}s"


def test_top_sellers_with_store_id_bypasses_cache(client):
    # Get a real store_id
    r = client.get(f"{BASE_URL}/api/stores", timeout=TIMEOUT_S)
    assert r.status_code == 200
    stores = r.json()
    if isinstance(stores, dict):
        stores = stores.get("stores") or stores.get("data") or []
    assert stores, "no stores returned"
    sid = stores[0].get("id") or stores[0].get("_id")
    r2, dt = _timed_get(client, f"/api/insights/top-sellers?days=30&store_id={sid}")
    assert r2.status_code == 200, r2.text
    # Latency may be higher since it bypasses cache — allow 8s
    assert dt < 8.0, f"top-sellers?store_id={sid} took {dt:.2f}s"


# ---- /api/price-intel/dashboard -----------------------------------------
def test_price_intel_dashboard_cache_envelope(client):
    r, dt = _timed_get(client, "/api/price-intel/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "cache" in body, f"missing cache envelope: keys={list(body.keys())}"
    c = body["cache"]
    assert "computed_at" in c and "source" in c
    for key in ("action_required", "my_advantages", "full_table", "unverified",
                "summary", "confidence_distribution"):
        assert key in body, f"missing key: {key}"
    assert dt < LATENCY_BUDGET_S, f"price-intel/dashboard took {dt:.2f}s"


# ---- /api/my-products iter25 preservation -------------------------------
def test_my_products_iter25_envelope_preserved(client):
    r, dt = _timed_get(client, "/api/my-products?days=30")
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("cache", "kpis", "products", "total", "categories"):
        assert key in body, f"missing key: {key} (have {list(body.keys())})"
    assert dt < 5.0, f"my-products took {dt:.2f}s"
