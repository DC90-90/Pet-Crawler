"""Live production check — /api/admin/demo-cleanup contract (READ-ONLY).

This suite never performs a real deletion: it exercises the dry run and the
refusal paths only. Runs ONLY when the DALEEL_TEST_* environment variables are
set; skipped otherwise. No secrets and no URLs are hardcoded in this file.
"""
import os

import pytest

BASE_URL = os.environ.get("DALEEL_TEST_BASE_URL")
PASSWORD = os.environ.get("DALEEL_TEST_PASSWORD")
EMAIL = os.environ.get("DALEEL_TEST_EMAIL", "a.disi@taqueen.sa")

if not BASE_URL or not PASSWORD:
    pytest.skip("set DALEEL_TEST_* env vars to run live tests", allow_module_level=True)

import httpx  # noqa: E402


def _login(client):
    r = client.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    token = r.json().get("access_token") or r.json().get("token")
    assert token, f"no token in login response: {r.text[:200]}"
    return {"Authorization": f"Bearer {token}"}


def test_demo_cleanup_dry_run_get_live():
    with httpx.Client(timeout=60.0) as client:
        headers = _login(client)
        r = client.get(f"{BASE_URL}/api/admin/demo-cleanup", params={"dry_run": "true"}, headers=headers)
        assert r.status_code == 200, f"HTTP {r.status_code} {r.text[:300]}"
        body = r.json()
        assert body["dry_run"] is True
        assert "guard" in body and "cascade_counts" in body and "before" in body
        guard = body["guard"]
        assert "real_sku_match" in guard and "confirm_count_required" in guard
        assert guard["confirm_count_required"] == body["demo_products"]
        # the cascade must audit every referencing collection
        for coll in ("product_snapshots", "product_matches", "match_blacklist",
                     "sku_store_coverage", "sku_sales_daily", "my_products",
                     "alerts", "alert_events", "products"):
            assert coll in body["cascade_counts"], coll


def test_demo_cleanup_get_never_deletes_live():
    with httpx.Client(timeout=60.0) as client:
        headers = _login(client)
        r = client.get(f"{BASE_URL}/api/admin/demo-cleanup", params={"dry_run": "false"}, headers=headers)
        assert r.status_code == 405, f"GET dry_run=false must be rejected, got {r.status_code}"


def test_demo_cleanup_confirm_count_mismatch_refused_live():
    # deliberately impossible confirm_count → the real run must refuse with 409
    # and delete nothing (this is the ONLY POST this live suite ever sends)
    with httpx.Client(timeout=60.0) as client:
        headers = _login(client)
        before = client.get(f"{BASE_URL}/api/admin/demo-cleanup", params={"dry_run": "true"}, headers=headers).json()
        r = client.post(
            f"{BASE_URL}/api/admin/demo-cleanup",
            params={"dry_run": "false", "confirm_count": 999999},
            headers=headers,
        )
        assert r.status_code == 409, f"mismatched confirm_count must refuse, got {r.status_code} {r.text[:200]}"
        after = client.get(f"{BASE_URL}/api/admin/demo-cleanup", params={"dry_run": "true"}, headers=headers).json()
        assert after["demo_products"] == before["demo_products"], "refused run must not delete anything"
