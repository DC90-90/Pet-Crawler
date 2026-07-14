"""Auth: login, lockout, refresh, CSRF, change-password."""
import pytest

from tests.conftest import csrf_headers, login, make_user

pytestmark = pytest.mark.asyncio

EMAIL = "owner@example.com"
PW = "Sup3rSecret!"


async def test_login_success_and_me(app_client, mock_db):
    await make_user(mock_db, EMAIL, PW)
    resp = await app_client.post("/api/auth/login", json={"email": EMAIL, "password": PW})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == EMAIL
    assert body["user"]["role"] == "owner"
    assert "csrfToken" in body
    assert app_client.cookies.get("access_token")
    assert app_client.cookies.get("csrf_token")

    me = await app_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == EMAIL


async def test_login_wrong_password_generic(app_client, mock_db):
    await make_user(mock_db, EMAIL, PW)
    resp = await app_client.post("/api/auth/login", json={"email": EMAIL, "password": "nope"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


async def test_account_lockout_after_5_failures(app_client, mock_db):
    await make_user(mock_db, EMAIL, PW)
    for _ in range(5):
        r = await app_client.post("/api/auth/login", json={"email": EMAIL, "password": "bad"})
        assert r.status_code == 401
    # Correct password should now be rejected due to lockout
    r = await app_client.post("/api/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code == 401


async def test_refresh_rotates(app_client, mock_db):
    await make_user(mock_db, EMAIL, PW)
    await login(app_client, EMAIL, PW)
    old_refresh = app_client.cookies.get("refresh_token")
    resp = await app_client.post("/api/auth/refresh")
    assert resp.status_code == 200
    new_refresh = app_client.cookies.get("refresh_token")
    assert new_refresh and new_refresh != old_refresh


async def test_logout_revokes(app_client, mock_db):
    await make_user(mock_db, EMAIL, PW)
    await login(app_client, EMAIL, PW)
    resp = await app_client.post("/api/auth/logout")
    assert resp.status_code == 200
    me = await app_client.get("/api/auth/me")
    assert me.status_code == 401


async def test_csrf_required_for_mutation(app_client, mock_db):
    await make_user(mock_db, EMAIL, PW)
    await login(app_client, EMAIL, PW)
    # No CSRF header → 403
    resp = await app_client.post("/api/admin/tours", json={"slug": "x", "name": {"en": "X"}})
    assert resp.status_code == 403
    # With CSRF header → allowed
    resp = await app_client.post(
        "/api/admin/tours", json={"slug": "x", "name": {"en": "X"}}, headers=csrf_headers(app_client)
    )
    assert resp.status_code == 201


async def test_dev_owner_bootstrap_enables_login(app_client, mock_db):
    from app.core.config import settings
    from app.seed.run import ensure_dev_owner

    await ensure_dev_owner()
    owner = await mock_db.users.find_one({"email": settings.admin_seed_email.lower()})
    assert owner is not None
    assert owner["role"] == "owner"
    assert owner["forcePasswordChange"] is False  # dev bootstrap logs straight in

    resp = await app_client.post(
        "/api/auth/login",
        json={"email": settings.admin_seed_email, "password": settings.admin_seed_password},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "owner"


async def test_change_password(app_client, mock_db):
    await make_user(mock_db, EMAIL, PW)
    await login(app_client, EMAIL, PW)
    resp = await app_client.post(
        "/api/auth/change-password",
        json={"old_password": PW, "new_password": "N3wpassword!"},
        headers=csrf_headers(app_client),
    )
    assert resp.status_code == 200
