"""iter50 — read-only navigation restoration + truthful error guard API checks.

Modules/features covered:
- live preview auth/access behavior for alerts + release status
- release runtime guard exceptions for alerts/notifications in read-only modes
"""

from __future__ import annotations

import os
import re
import uuid
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from starlette.datastructures import URL
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


def _load_super_admin_password_from_memory() -> str:
    """Read credential from memory file so tests avoid hardcoded secrets."""
    src = Path("/app/memory/test_credentials.md")
    if not src.exists():
        return ""
    txt = src.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"\*\*Password\*\*:\s*(.+)", txt)
    return (match.group(1).strip() if match else "")


# Must be set before importing _auth (helper reads env at import time)
if not os.environ.get("DALEEL_TEST_PASSWORD", "").strip():
    pw = _load_super_admin_password_from_memory()
    if pw:
        os.environ["DALEEL_TEST_PASSWORD"] = pw

from _auth import (  # noqa: E402  (import order is intentional)
    SUPER_EMAIL,
    auth_headers,
    base_url,
    live_mongo_url,
    login_response,
)

import release_runtime  # noqa: E402
import release_control  # noqa: E402
import access_policy  # noqa: E402
from release_database import GuardedDatabase  # noqa: E402


BASE = base_url().rstrip("/")


def _j(resp: requests.Response):
    try:
        return resp.json()
    except Exception:
        return {}


def test_release_endpoint_and_super_admin_session_live():
    """Release endpoint should be readable and super admin token should work."""
    headers = auth_headers()
    release = requests.get(f"{BASE}/api/release", headers=headers, timeout=30)
    assert release.status_code == 200, release.text[:300]
    body = _j(release)
    assert isinstance(body, dict)
    assert "mode" in body
    assert "capabilities" in body and isinstance(body["capabilities"], dict)

    me = requests.get(f"{BASE}/api/auth/me", headers=headers, timeout=30)
    assert me.status_code == 200, me.text[:300]
    me_body = _j(me)
    assert me_body.get("email", "").lower() == SUPER_EMAIL.lower()
    assert me_body.get("role") == "super_admin"


def test_alert_get_endpoints_allowed_for_super_admin_live():
    """Read-only exception: GET /alerts and /alerts/feed remain readable."""
    headers = auth_headers()
    r1 = requests.get(f"{BASE}/api/alerts", headers=headers, timeout=45)
    r2 = requests.get(f"{BASE}/api/alerts/feed", headers=headers, params={"days": 30}, timeout=45)

    assert r1.status_code == 200, r1.text[:300]
    assert r2.status_code == 200, r2.text[:300]
    assert isinstance(_j(r1), list)
    assert isinstance(_j(r2), list)


def test_alert_and_notification_mutations_blocked_in_live_release():
    """Outbound notifications / alert mutations must stay blocked by release guard."""
    headers = auth_headers()

    checks = [
        ("POST", "/api/alerts/check", None),
        ("POST", "/api/alerts", {"product_sku": "TEST_NO_WRITE", "alert_type": "price_drop", "threshold": 5, "channel": "in_app"}),
        ("PUT", "/api/alerts/nonexistent/toggle", None),
        ("DELETE", "/api/alerts/nonexistent", None),
        ("GET", "/api/notifications", None),
        ("POST", "/api/notifications", {}),
        ("GET", "/api/alerts/unknown-prefix", None),
    ]

    for method, path, payload in checks:
        resp = requests.request(method, f"{BASE}{path}", headers=headers, json=payload, timeout=45)
        assert resp.status_code in {401, 403, 404, 405, 422, 423}, f"{method} {path} -> {resp.status_code} {resp.text[:200]}"
        if resp.status_code == 423:
            detail = _j(resp).get("detail") or {}
            assert detail.get("code") == "release_write_blocked"


def test_unauthenticated_alerts_read_returns_401_live():
    r = requests.get(f"{BASE}/api/alerts", timeout=30)
    assert r.status_code == 401


def test_restricted_user_forbidden_on_alerts_live():
    """Normal user (my_products-only) should not access alerts page family."""
    login = login_response(os.environ["DALEEL_NORMAL_EMAIL"], os.environ["DALEEL_NORMAL_PASSWORD"], BASE)
    assert login.status_code == 200, "Existing restricted-user login failed"
    token = _j(login).get("token") or _j(login).get("access_token")
    assert token, "Existing restricted-user login did not return a token"

    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE}/api/alerts", headers=headers, timeout=30)
    assert r.status_code == 403, r.text[:300]


def test_access_policy_role_matrix_for_alerts_unit():
    """JWT-fixture-equivalent role matrix: allow alerts page users, deny unauthorized users."""
    role_allow_alerts = {"role": "user", "allowed_pages": ["alerts"]}
    role_unauthorized = {"role": "user", "allowed_pages": ["my_products"]}
    role_super_admin = {"role": "super_admin", "allowed_pages": []}

    # Allowed alerts reader/writer by page policy (release runtime may still block mutations).
    access_policy.enforce(role_allow_alerts, "/api/alerts", "GET")
    access_policy.enforce(role_allow_alerts, "/api/alerts/feed", "GET")
    access_policy.enforce(role_allow_alerts, "/api/alerts/check", "POST")

    # Super admin always allowed.
    access_policy.enforce(role_super_admin, "/api/alerts", "GET")

    # Unauthorized role denied.
    with pytest.raises(Exception):
        access_policy.enforce(role_unauthorized, "/api/alerts", "GET")


@pytest.fixture(scope="module")
def isolated_release_db():
    """Disposable loopback DB to prove release guard behavior without production writes."""
    from test_p0_my_products_baseline import _loopback_mongo_url
    mongo_url = _loopback_mongo_url()
    client = AsyncIOMotorClient(mongo_url)
    db_name = f"iter50_release_guard_{uuid.uuid4().hex}"
    raw = client[db_name]
    guarded = GuardedDatabase(raw)
    yield guarded
    try:
        MongoClient(mongo_url).drop_database(db_name)
    finally:
        client.close()


def test_release_runtime_alert_exceptions_and_denies_no_writes(isolated_release_db):
    """Exact GET exceptions for alerts/feed; deny notification + mutation paths; no data writes."""
    async def _run():
        before_alerts = await isolated_release_db.alerts.count_documents({})
        before_events = await isolated_release_db.alert_events.count_documents({})

        async def authz(path: str, method: str):
            req = SimpleNamespace(url=URL(f"http://test{path}"), method=method)
            return await release_runtime.authorize_request(isolated_release_db, req, "fixture-user")

        # Explicit read exceptions
        await authz("/api/alerts", "GET")
        await authz("/api/alerts/feed", "GET")

        # Notification family remains blocked
        with pytest.raises(release_control.ReleaseBlocked) as blocked_notifications:
            await authz("/api/notifications", "GET")
        assert blocked_notifications.value.detail.get("reason") == "outbound_notifications_unavailable"

        # Unknown /api/alerts* path should still be blocked by release guard
        with pytest.raises(release_control.ReleaseBlocked) as blocked_alert_unknown:
            await authz("/api/alerts/unknown-prefix", "GET")
        assert blocked_alert_unknown.value.detail.get("reason") == "outbound_notifications_unavailable"

        # Mutations denied in observer/frozen path
        with pytest.raises(release_control.ReleaseBlocked):
            await authz("/api/alerts/check", "POST")

        after_alerts = await isolated_release_db.alerts.count_documents({})
        after_events = await isolated_release_db.alert_events.count_documents({})
        assert after_alerts == before_alerts
        assert after_events == before_events

    asyncio.run(_run())
