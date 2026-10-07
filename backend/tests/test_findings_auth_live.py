"""Live auth/permission checks for investigation finding F13."""

import os

import pytest
import requests
from pymongo import MongoClient

from _auth import base_url, login_response, auth_headers, live_db_name, live_mongo_url

API = f"{base_url()}/api"
NORMAL_EMAIL = "test_iter73y_normal@example.com"
NORMAL_PASSWORD = "NormalUser#123"


@pytest.fixture(scope="module")
def normal_headers():
    r = login_response(NORMAL_EMAIL, NORMAL_PASSWORD)
    if r is None or r.status_code != 200:
        pytest.skip("normal user credentials unavailable for this environment")
    token = r.json().get("token")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_registration_disabled_by_default():
    payload = {"email": "authtest_disabled@example.com", "password": "Abc123!!", "name": "Auth Test"}
    r = requests.post(f"{API}/auth/register", json=payload, timeout=30)
    assert r.status_code == 403


def test_login_sets_http_only_cookie():
    r = login_response(NORMAL_EMAIL, NORMAL_PASSWORD)
    if r is None or r.status_code != 200:
        pytest.skip("normal user credentials unavailable for this environment")
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "daleel_token=" in set_cookie
    assert "httponly" in set_cookie


def test_password_hash_uses_bcrypt_2b_prefix():
    client = MongoClient(live_mongo_url(), serverSelectionTimeoutMS=5000)
    try:
        doc = client[live_db_name()].users.find_one({"email": NORMAL_EMAIL}, {"password_hash": 1})
    finally:
        client.close()
    if not doc:
        pytest.skip("normal user not found in DB")
    assert str(doc.get("password_hash", "")).startswith("$2b$")


def test_page_reader_can_read_allowed_page_family(normal_headers):
    r = requests.get(f"{API}/my-products", headers=normal_headers, timeout=60)
    assert r.status_code == 200


def test_page_reader_cannot_run_admin_or_mutation_operations(normal_headers):
    admin = requests.get(f"{API}/admin/users", headers=normal_headers, timeout=30)
    assert admin.status_code in (401, 403)

    mutate_store = requests.post(f"{API}/stores", headers=normal_headers, json={"name": "x"}, timeout=30)
    assert mutate_store.status_code in (401, 403, 422)

    trigger_import = requests.post(f"{API}/import/sync-own-store", headers=normal_headers, timeout=30)
    assert trigger_import.status_code in (401, 403)


def test_logout_revokes_current_token(normal_headers):
    s = requests.Session()
    s.headers.update(normal_headers)
    me_before = s.get(f"{API}/auth/me", timeout=30)
    assert me_before.status_code == 200
    out = s.post(f"{API}/auth/logout", timeout=30)
    assert out.status_code == 200
    me_after = s.get(f"{API}/auth/me", timeout=30)
    assert me_after.status_code == 401
