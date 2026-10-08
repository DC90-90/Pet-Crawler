"""Isolated auth/permission/CORS checks for finding F13.

Runs only against a disposable loopback Mongo database via FastAPI TestClient.
No preview session mutation, no production DB reads.
"""

import asyncio
import importlib
import os
import uuid
import secrets
from urllib.parse import urlparse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient


def _read_backend_env(key: str):
    env = Path("/app/backend/.env")
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


@pytest.fixture(scope="module")
def isolated_env():
    mongo_url = os.environ.get("MONGO_URL") or _read_backend_env("MONGO_URL")
    if not mongo_url:
        pytest.skip("MONGO_URL not available for isolated auth suite")
    host = urlparse(mongo_url).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        pytest.skip("isolated auth suite requires loopback MongoDB")

    db_name = f"test_findings_auth_isolated_{uuid.uuid4().hex[:10]}"
    old = dict(os.environ)
    os.environ["DB_NAME"] = db_name
    os.environ["JWT_SECRET"] = f"jwt-{uuid.uuid4().hex}"
    from cryptography.fernet import Fernet
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ["CORS_ORIGINS"] = "https://allowed.example.test"
    os.environ["SUPER_ADMIN_EMAIL"] = "isolated-super@example.test"
    os.environ["SUPER_ADMIN_PASSWORD"] = secrets.token_urlsafe(32)
    try:
        yield {"mongo_url": mongo_url, "db_name": db_name}
    finally:
        os.environ.clear()
        os.environ.update(old)


@pytest.fixture(scope="module")
def isolated_app(isolated_env):
    server = importlib.import_module("server")
    server = importlib.reload(server)

    async_client = AsyncIOMotorClient(isolated_env["mongo_url"])
    test_db = async_client[isolated_env["db_name"]]
    server.db = test_db

    # Patch startup/shutdown hooks so background boot/providers do not run.
    original_startup = list(server.app.router.on_startup)
    original_shutdown = list(server.app.router.on_shutdown)
    server.app.router.on_startup = []
    server.app.router.on_shutdown = []

    with TestClient(server.app) as tc:
        yield {"server": server, "client": tc, "db": test_db}

    server.app.router.on_startup = original_startup
    server.app.router.on_shutdown = original_shutdown
    sync_client = MongoClient(isolated_env["mongo_url"])
    sync_client.drop_database(isolated_env["db_name"])
    sync_client.close()
    async_client.close()


@pytest.fixture(scope="module")
def page_reader(isolated_app):
    server = isolated_app["server"]
    db_name = os.environ["DB_NAME"]
    mongo_url = os.environ.get("MONGO_URL") or _read_backend_env("MONGO_URL")
    email = f"reader-{uuid.uuid4().hex[:8]}@example.test"
    password = f"Reader#{uuid.uuid4().hex[:10]}"
    sync_client = MongoClient(mongo_url)
    sync_client[db_name].users.insert_one(
        {
            "email": email,
            "password_hash": server.hash_pw(password),
            "name": "Reader",
            "role": "user",
            "allowed_pages": ["my_products"],
        }
    )
    sync_client.close()
    return {"email": email, "password": password}


# modules/features: registration policy + cookie flags + bcrypt + page-gated access + logout revocation
def test_registration_disabled_by_default_isolated(isolated_app):
    c = isolated_app["client"]
    payload = {
        "email": f"reg-{uuid.uuid4().hex[:8]}@example.test",
        "password": "Abc123!!",
        "name": "Auth Test",
    }
    r = c.post("/api/auth/register", json=payload)
    assert r.status_code == 403


def test_login_sets_http_only_cookie_isolated(isolated_app, page_reader):
    c = isolated_app["client"]
    r = c.post("/api/auth/login", json=page_reader)
    assert r.status_code == 200
    set_cookie = (r.headers.get("set-cookie") or "").lower()
    assert "daleel_token=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=none" in set_cookie
    assert "secure" in set_cookie


def test_password_hash_uses_bcrypt_2b_prefix_isolated(isolated_app, page_reader):
    db_name = os.environ["DB_NAME"]
    mongo_url = os.environ.get("MONGO_URL") or _read_backend_env("MONGO_URL")
    sync_client = MongoClient(mongo_url)
    doc = sync_client[db_name].users.find_one({"email": page_reader["email"]}, {"password_hash": 1})
    sync_client.close()
    ph = (doc or {}).get("password_hash", "")
    assert str(ph).startswith("$2b$")


def test_page_reader_allowed_read_and_blocked_mutations_isolated(isolated_app, page_reader):
    c = isolated_app["client"]
    login = c.post("/api/auth/login", json=page_reader)
    token = login.json()["token"]
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    read_ok = c.get("/api/my-products", headers=h)
    assert read_ok.status_code == 200

    admin = c.get("/api/admin/users", headers=h)
    assert admin.status_code in (401, 403)

    mutate_store = c.post("/api/stores", headers=h, json={"name": "x"})
    assert mutate_store.status_code in (401, 403, 422)


def test_logout_revokes_current_token_isolated(isolated_app, page_reader):
    c = isolated_app["client"]
    login = c.post("/api/auth/login", json=page_reader)
    token = login.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    me_before = c.get("/api/auth/me", headers=h)
    assert me_before.status_code == 200
    out = c.post("/api/auth/logout", headers=h)
    assert out.status_code == 200
    me_after = c.get("/api/auth/me", headers=h)
    assert me_after.status_code == 401


# modules/features: CORS explicit-origin credentials + preflight allow/deny + untrusted cookie origin rejection + brute-force lockout
def test_cors_allows_credentials_for_explicit_allowed_origin(isolated_app):
    c = isolated_app["client"]
    headers = {
        "Origin": "https://allowed.example.test",
        "Access-Control-Request-Method": "POST",
    }
    r = c.options("/api/auth/login", headers=headers)
    assert r.headers.get("access-control-allow-origin") == "https://allowed.example.test"
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_cors_denies_preflight_for_untrusted_origin(isolated_app):
    c = isolated_app["client"]
    headers = {
        "Origin": "https://evil.example.test",
        "Access-Control-Request-Method": "POST",
    }
    r = c.options("/api/auth/login", headers=headers)
    assert r.status_code in (400, 403)
    assert r.headers.get("access-control-allow-origin") != "https://evil.example.test"


def test_untrusted_origin_with_cookie_cannot_mutate_auth_route(isolated_app):
    c = isolated_app["client"]
    r = c.post(
        "/api/auth/login",
        headers={"Origin": "https://evil.example.test"},
        cookies={"daleel_token": "bogus"},
        json={"email": "x@example.test", "password": "bad"},
    )
    assert r.status_code == 403
    assert "not permitted" in (r.text or "").lower()


def test_bruteforce_lockout_after_five_failed_logins(isolated_app):
    c = isolated_app["client"]
    statuses = []
    payload = {"email": f"ghost-{uuid.uuid4().hex[:8]}@example.test", "password": "wrong"}
    for _ in range(6):
        r = c.post("/api/auth/login", json=payload)
        statuses.append(r.status_code)
    assert 401 in statuses[:5]
    assert statuses[-1] == 429


def test_seed_super_admin_preserves_rotated_password_without_authorization(isolated_app):
    server = isolated_app["server"]
    db_name = os.environ["DB_NAME"]
    mongo_url = os.environ.get("MONGO_URL") or _read_backend_env("MONGO_URL")
    sync_client = MongoClient(mongo_url)
    users = sync_client[db_name].users
    admin_email = os.environ["SUPER_ADMIN_EMAIL"]

    users.delete_many({"email": admin_email})
    retained_password = secrets.token_urlsafe(32)
    retained_hash = server.hash_pw(retained_password)
    users.insert_one(
        {
            "email": admin_email,
            "password_hash": retained_hash,
            "name": "Legacy Super",
            "role": "superadmin",
        }
    )

    isolated_app["client"].portal.call(server.seed_super_admin)

    row = users.find_one({"email": admin_email}, {"password_hash": 1, "role": 1})
    sync_client.close()
    assert row and row.get("role") in {"super_admin", "superadmin"}
    # Current F13 contract: startup must never undo an explicit owner's reset.
    # Changing an env seed value is not authorization to rotate live credentials.
    assert row["password_hash"] == retained_hash
    assert server.check_pw(retained_password, row["password_hash"])
    assert not server.check_pw(os.environ["SUPER_ADMIN_PASSWORD"], row["password_hash"])
