"""iter79 — Zid partner-app OAuth.

The Orders API has answered 401 since iter75 because Zid needs TWO values from
the SAME installation and we only ever had one:

    Authorization: Bearer  <token response's `authorization`>
    X-Manager-Token:       <token response's `access_token`>

These tests pin exactly that mapping (getting it backwards is the single most
likely way to reintroduce the 401), the one-time state on the callback, that
tokens are encrypted at rest and never returned to a client, and that a missing
or expired authorisation degrades to a reported state instead of an exception.
No network: the token endpoint is stubbed.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["DB_NAME"] = "test_iter79_zid_oauth"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_iter79_zid_oauth"
os.environ.setdefault("ENCRYPTION_KEY", "0" * 43 + "=")
import pytest  # noqa: E402
import zid_oauth  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
BASE = "https://daleel.example.com"


def _db():
    asyncio.set_event_loop(_LOOP)   # motor captures the CURRENT loop at construction
    return AsyncIOMotorClient(MONGO)[_TEST_DB]


# A loop this module OWNS — see the note in test_iter79_market_share.py.
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ZID_CLIENT_ID", "7107")
    monkeypatch.setenv("ZID_CLIENT_SECRET", "shhh")
    monkeypatch.setenv("ZID_OAUTH_SCOPES", "orders.read")
    monkeypatch.delenv("ZID_REDIRECT_URI", raising=False)
    yield


@pytest.fixture
def db():
    d = _db()
    _run(d.zid_oauth.delete_many({}))
    _run(d.zid_oauth_states.delete_many({}))
    _run(d.own_store_orders.delete_many({}))
    return d


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _stub_token(monkeypatch, payload, capture=None):
    async def _post(form):
        if capture is not None:
            capture.append(form)
        return payload, None
    monkeypatch.setattr(zid_oauth, "_post_token", _post)


def test_authorize_url_carries_client_scope_and_exact_redirect(db):
    res = _run(zid_oauth.start_authorization(db, base_url=BASE))
    assert res["ok"]
    assert res["redirect_uri"] == f"{BASE}/api/zid/oauth/callback"
    for part in ("client_id=7107", "response_type=code", "scope=orders.read",
                 "redirect_uri=https%3A%2F%2Fdaleel.example.com%2Fapi%2Fzid%2Foauth%2Fcallback"):
        assert part in res["authorize_url"]
    assert res["authorize_url"].startswith("https://oauth.zid.sa/oauth/authorize?")


def test_env_redirect_uri_overrides_the_request_origin(db, monkeypatch):
    monkeypatch.setenv("ZID_REDIRECT_URI", "https://prod.example.com/api/zid/oauth/callback")
    res = _run(zid_oauth.start_authorization(db, base_url=BASE))
    assert res["redirect_uri"] == "https://prod.example.com/api/zid/oauth/callback"


def test_missing_client_credentials_is_reported_not_raised(db, monkeypatch):
    monkeypatch.setenv("ZID_CLIENT_ID", "")
    res = _run(zid_oauth.start_authorization(db, base_url=BASE))
    assert res["ok"] is False and res["reason"] == "not_configured"


def test_token_exchange_maps_authorization_to_bearer_and_access_token_to_manager(db, monkeypatch):
    sent = []
    _stub_token(monkeypatch, {"authorization": "PARTNER-JWT", "access_token": "STORE-MGR",
                              "refresh_token": "R1", "expires_in": 31536000}, sent)
    st = _run(zid_oauth.start_authorization(db, base_url=BASE))
    out = _run(zid_oauth.complete_authorization(db, "CODE", st["state"], base_url=BASE))
    assert out["ok"] is True
    assert sent[0]["grant_type"] == "authorization_code"
    assert sent[0]["redirect_uri"] == st["redirect_uri"]
    assert sent[0]["client_secret"] == "shhh"

    creds = _run(zid_oauth.credentials(db))
    assert creds == {"authorization": "PARTNER-JWT", "access_token": "STORE-MGR"}


def test_tokens_are_encrypted_at_rest(db, monkeypatch):
    _stub_token(monkeypatch, {"authorization": "PARTNER-JWT", "access_token": "STORE-MGR",
                              "refresh_token": "R1", "expires_in": 100000})
    st = _run(zid_oauth.start_authorization(db, base_url=BASE))
    _run(zid_oauth.complete_authorization(db, "CODE", st["state"], base_url=BASE))
    doc = _run(db.zid_oauth.find_one({"_id": "own"}))
    for f in ("authorization", "access_token", "refresh_token"):
        assert doc[f] and "PARTNER-JWT" not in doc[f] and "STORE-MGR" not in doc[f]


def test_status_never_leaks_a_token(db, monkeypatch):
    _stub_token(monkeypatch, {"authorization": "PARTNER-JWT", "access_token": "STORE-MGR",
                              "refresh_token": "R1", "expires_in": 100000})
    st = _run(zid_oauth.start_authorization(db, base_url=BASE))
    _run(zid_oauth.complete_authorization(db, "CODE", st["state"], base_url=BASE))
    s = _run(zid_oauth.status(db))
    blob = repr(s)
    assert "PARTNER-JWT" not in blob and "STORE-MGR" not in blob and "R1" not in blob
    assert s["connected"] is True and s["has_refresh_token"] is True


def test_a_state_cannot_be_replayed(db, monkeypatch):
    _stub_token(monkeypatch, {"authorization": "A", "access_token": "B", "expires_in": 10})
    st = _run(zid_oauth.start_authorization(db, base_url=BASE))
    assert _run(zid_oauth.complete_authorization(db, "C1", st["state"]))["ok"] is True
    again = _run(zid_oauth.complete_authorization(db, "C2", st["state"]))
    assert again["ok"] is False and again["reason"] == "state_reused"


def test_an_unknown_state_is_refused(db):
    out = _run(zid_oauth.complete_authorization(db, "CODE", "not-ours"))
    assert out["ok"] is False and out["reason"] == "unknown_state"


def test_an_expired_state_is_refused(db, monkeypatch):
    st = _run(zid_oauth.start_authorization(db, base_url=BASE))
    _run(db.zid_oauth_states.update_one(
        {"state": st["state"]},
        {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(hours=2)}}))
    out = _run(zid_oauth.complete_authorization(db, "CODE", st["state"]))
    assert out["ok"] is False and out["reason"] == "state_expired"


def test_an_incomplete_token_response_is_not_stored(db, monkeypatch):
    _stub_token(monkeypatch, {"access_token": "only-the-manager-token", "expires_in": 10})
    st = _run(zid_oauth.start_authorization(db, base_url=BASE))
    out = _run(zid_oauth.complete_authorization(db, "CODE", st["state"]))
    assert out["ok"] is False and out["reason"] == "incomplete_response"
    assert _run(db.zid_oauth.find_one({"_id": "own"})) is None


def test_a_data_enveloped_response_is_still_read():
    a, t, r, e = zid_oauth._extract_tokens(
        {"data": {"authorization": "A", "access_token": "T", "refresh_token": "R",
                  "expires_in": "500"}})
    assert (a, t, r, e) == ("A", "T", "R", 500)


def test_credentials_refresh_when_close_to_expiry(db, monkeypatch):
    _stub_token(monkeypatch, {"authorization": "OLD-A", "access_token": "OLD-T",
                              "refresh_token": "R1", "expires_in": 10})
    st = _run(zid_oauth.start_authorization(db, base_url=BASE))
    _run(zid_oauth.complete_authorization(db, "CODE", st["state"]))
    _stub_token(monkeypatch, {"authorization": "NEW-A", "access_token": "NEW-T",
                              "refresh_token": "R2", "expires_in": 31536000})
    creds = _run(zid_oauth.credentials(db))
    assert creds == {"authorization": "NEW-A", "access_token": "NEW-T"}
    s = _run(zid_oauth.status(db))
    assert s["status"] == "authorized"


def test_a_failed_refresh_is_recorded_and_does_not_raise(db, monkeypatch):
    _stub_token(monkeypatch, {"authorization": "A", "access_token": "T",
                              "refresh_token": "R1", "expires_in": 10})
    st = _run(zid_oauth.start_authorization(db, base_url=BASE))
    _run(zid_oauth.complete_authorization(db, "CODE", st["state"]))

    async def _fail(form):
        return None, {"status": 400, "body": "invalid_grant"}
    monkeypatch.setattr(zid_oauth, "_post_token", _fail)
    creds = _run(zid_oauth.credentials(db))
    assert creds == {"authorization": "A", "access_token": "T"}   # old pair still returned
    doc = _run(db.zid_oauth.find_one({"_id": "own"}))
    assert doc["status"] == "refresh_failed"


def test_no_authorisation_yet_reports_the_action_required(db):
    s = _run(zid_oauth.status(db))
    assert s["connected"] is False
    assert "callback URL" in s["action_required"]
    assert _run(zid_oauth.credentials(db)) is None


def test_orders_sync_sends_both_headers_from_the_same_installation(db, monkeypatch):
    import zid_orders
    monkeypatch.setenv("ZID_API_TOKEN", "STORE-ACCESS-TOKEN")
    monkeypatch.setenv("ZID_STORE_ID", "92252")

    async def _creds(_db):
        return {"authorization": "PARTNER-JWT", "access_token": "STORE-MGR"}
    monkeypatch.setattr(zid_orders.zid_oauth, "credentials", _creds)

    seen = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"orders": []}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            seen.update(headers or {})
            return _Resp()

    monkeypatch.setattr(zid_orders.httpx, "AsyncClient", _Client)
    out = _run(zid_orders.sync_own_store_orders(db))
    assert out["status"] == "ok" and out["auth_source"] == "partner_oauth"
    assert seen["Authorization"] == "Bearer PARTNER-JWT"
    assert seen["X-Manager-Token"] == "STORE-MGR"
    assert seen["Access-Token"] == "STORE-ACCESS-TOKEN"


def test_a_401_reports_that_authorisation_is_needed(db, monkeypatch):
    import zid_orders
    monkeypatch.setenv("ZID_API_TOKEN", "STORE-ACCESS-TOKEN")
    monkeypatch.setenv("ZID_STORE_ID", "92252")

    async def _none(_db):
        return None
    monkeypatch.setattr(zid_orders.zid_oauth, "credentials", _none)
    monkeypatch.delenv("ZID_OAUTH_TOKEN", raising=False)

    class _Resp:
        status_code = 401
        text = "Unauthenticated"

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None, headers=None):
            return _Resp()

    monkeypatch.setattr(zid_orders.httpx, "AsyncClient", _Client)
    out = _run(zid_orders.sync_own_store_orders(db))
    assert out["status"] == "auth_failed"
    assert out["needs"] == "zid_partner_oauth"
    assert out["auth_source"] == "store_token_only"
    assert "Connect" in out["hint"]


def test_endpoints_registered_and_callback_is_public():
    import server
    paths = {r.path for r in server.app.routes}
    for p in ("/api/admin/zid/oauth/status", "/api/admin/zid/oauth/start",
              "/api/zid/oauth/callback", "/api/admin/zid/oauth/disconnect",
              "/api/admin/zid/orders/sync"):
        assert p in paths, p
    # the callback must NOT be behind the super-admin dependency: Zid redirects
    # a browser to it with no Authorization header
    cb = next(r for r in server.app.routes if getattr(r, "path", "") == "/api/zid/oauth/callback")
    assert not [d for d in getattr(cb, "dependant", None).dependencies
                if "super_admin" in str(d.call)]
