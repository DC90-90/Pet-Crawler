"""Shared, rate-limit-safe auth for the live-API test suites.

POST /api/auth/login is rate limited to 5 requests/minute per IP and that
production limit is deliberately NOT relaxed for tests. Instead every suite
authenticates through here: ONE real login per (base_url, email) per run,
cached in memory and on disk (validated against /api/auth/me before reuse),
with a 429-aware retry. Failed logins are cached too, so a module carrying
stale credentials can no longer burn the limiter budget for the whole suite.
"""
import json
import os
import threading
import time
from pathlib import Path

import pytest
import requests

SUPER_EMAIL = "a.disi@taqueen.sa"
SUPER_PASSWORD = "Ahmaddc90@"

_CACHE_FILE = Path(os.environ.get("DALEEL_TEST_TOKEN_CACHE", "/tmp/daleel_test_tokens.json"))
_CACHE_MAX_AGE = 6 * 3600          # server tokens live 24h — refresh well before expiry
_RETRY_ATTEMPTS = 6
_RETRY_SLEEP = 12                  # 6 x 12s comfortably outlasts the 60s limiter window

_LOCK = threading.Lock()
_TOKENS = {}
_RESPONSES = {}


def base_url():
    """Preview/prod base URL: env first, then frontend/.env, then localhost."""
    val = os.environ.get("REACT_APP_BACKEND_URL", "").strip().rstrip("/")
    if val:
        return val
    dotenv = Path(__file__).resolve().parents[2] / "frontend" / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                val = line.split("=", 1)[1].strip().rstrip("/")
                if val:
                    os.environ["REACT_APP_BACKEND_URL"] = val
                    return val
    return "http://localhost:8001"


def extract_token(resp):
    try:
        body = resp.json()
    except Exception:
        return None
    return body.get("token") or body.get("access_token")


def _disk_read():
    try:
        return json.loads(_CACHE_FILE.read_text())
    except Exception:
        return {}


def _disk_write(store):
    try:
        _CACHE_FILE.write_text(json.dumps(store))
    except Exception:
        pass


def _token_alive(url, token):
    try:
        r = requests.get(f"{url}/api/auth/me",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15)
        return r.status_code == 200
    except Exception:
        return False


def login_response(email=SUPER_EMAIL, password=SUPER_PASSWORD, url=None):
    """One real login attempt per (url, email) per run, retried through 429."""
    url = (url or base_url()).rstrip("/")
    key = f"{url}|{email}"
    with _LOCK:
        cached = _RESPONSES.get(key)
    if cached is not None:
        return cached

    resp = None
    for attempt in range(_RETRY_ATTEMPTS):
        resp = requests.post(f"{url}/api/auth/login",
                             json={"email": email, "password": password}, timeout=30)
        if resp.status_code != 429:
            break
        wait = _RETRY_SLEEP
        try:
            wait = max(wait, int(resp.headers.get("Retry-After", 0)))
        except (TypeError, ValueError):
            pass
        time.sleep(wait)

    if resp is not None and resp.status_code != 429:
        with _LOCK:
            _RESPONSES[key] = resp
    return resp


def login_token(email=SUPER_EMAIL, password=SUPER_PASSWORD, url=None):
    """Cached bearer token. Logs in at most once per (url, email) per run."""
    url = (url or base_url()).rstrip("/")
    key = f"{url}|{email}"

    with _LOCK:
        token = _TOKENS.get(key)
    if token:
        return token

    entry = _disk_read().get(key) or {}
    token = entry.get("token")
    if token and (time.time() - float(entry.get("at", 0))) < _CACHE_MAX_AGE and _token_alive(url, token):
        with _LOCK:
            _TOKENS[key] = token
        return token

    resp = login_response(email, password, url)
    assert resp is not None, f"login request to {url} produced no response"
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text[:300]}"
    token = extract_token(resp)
    assert token, f"no token in login response: {resp.text[:300]}"

    with _LOCK:
        _TOKENS[key] = token
        store = _disk_read()
        store[key] = {"token": token, "at": time.time()}
        _disk_write(store)
    return token


def login_token_or_skip(email, password, url=None):
    """For legacy suites bound to accounts that may not exist in this DB."""
    resp = login_response(email, password, url)
    if resp is None or resp.status_code != 200:
        code = getattr(resp, "status_code", "no-response")
        pytest.skip(f"account {email} cannot authenticate ({code}) — suite not applicable")
    token = extract_token(resp)
    if not token:
        pytest.skip(f"account {email} returned no token")
    return token


def live_db_name():
    """The database the RUNNING backend uses.

    Sibling suites hard-assign DB_NAME to their own throwaway database at import
    time, and python-dotenv does NOT override an existing env var — so a live-API
    suite that also inspects Mongo directly has to read backend/.env itself or it
    silently queries another suite's (empty) database.
    """
    env = Path("/app/backend/.env")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("DB_NAME="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    return os.environ["DB_NAME"]


def live_mongo_url():
    env = Path("/app/backend/.env")
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("MONGO_URL="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    return os.environ["MONGO_URL"]


def login_response_or_skip(email, password, url=None):
    """Same as login_response, but skips the suite when the account cannot log in."""
    resp = login_response(email, password, url)
    if resp is None or resp.status_code != 200:
        code = getattr(resp, "status_code", "no-response")
        pytest.skip(f"account {email} cannot authenticate ({code}) — suite not applicable")
    return resp


def auth_headers(email=SUPER_EMAIL, password=SUPER_PASSWORD, url=None, json_content=False):
    h = {"Authorization": f"Bearer {login_token(email, password, url)}"}
    if json_content:
        h["Content-Type"] = "application/json"
    return h


def auth_session(email=SUPER_EMAIL, password=SUPER_PASSWORD, url=None, json_content=True):
    s = requests.Session()
    s.headers.update(auth_headers(email, password, url, json_content=json_content))
    return s
