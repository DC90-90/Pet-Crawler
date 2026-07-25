"""Live production check — /api/insights/summary across all four windows.

Runs ONLY when the DALEEL_TEST_* environment variables are set; skipped
otherwise so the normal suite never needs credentials or network access.
No secrets and no URLs are hardcoded in this file.
"""
import os

import pytest

BASE_URL = os.environ.get("DALEEL_TEST_BASE_URL")
PASSWORD = os.environ.get("DALEEL_TEST_PASSWORD")
EMAIL = os.environ.get("DALEEL_TEST_EMAIL", "a.disi@taqueen.sa")

if not BASE_URL or not PASSWORD:
    pytest.skip("set DALEEL_TEST_* env vars to run live tests", allow_module_level=True)

import httpx  # noqa: E402

WINDOWS = [7, 14, 30, 90]


def _login(client):
    r = client.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    token = r.json().get("access_token") or r.json().get("token")
    assert token, f"no token in login response: {r.text[:200]}"
    return {"Authorization": f"Bearer {token}"}


def test_insights_summary_all_windows_live():
    with httpx.Client(timeout=60.0) as client:
        headers = _login(client)
        for days in WINDOWS:
            r = client.get(f"{BASE_URL}/api/insights/summary", params={"days": days}, headers=headers)
            assert r.status_code == 200, f"days={days}: HTTP {r.status_code} {r.text[:300]}"
            body = r.json()
            # must be the real KPI payload — never the old diagnostic error shape
            assert body.get("error") is not True, f"days={days}: diagnostic error payload {body}"
            for key in ("total_skus", "price_drops", "product_gaps", "median_spread",
                        "avg_confidence", "freshness_breakdown"):
                assert key in body, f"days={days}: missing {key}"
            fb = body["freshness_breakdown"]
            assert fb.get("total_tracked", 0) >= 0
            # cache headers present on standard windows
            assert r.headers.get("x-cache-source") in ("cache", "live_fallback", "live_uncacheable")
