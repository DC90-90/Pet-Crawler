"""iter80 — the suite-wide shared test token.

POST /api/auth/login is rate limited to 5/min per IP (server.py `@limiter.limit`)
and that production limit is NOT relaxed for tests. Before this drop ~25 live-API
modules each logged in from their own fixture, so most of the suite errored during
setup with `429 Too many attempts`. These tests fence the replacement: one login
per (base_url, email) per run, cached, 429-aware, and no module logging in directly.
"""
import json
import re
from pathlib import Path

import pytest

import _auth

TESTS_DIR = Path(__file__).resolve().parent

# Modules allowed to call /api/auth/login directly, with the reason:
#   test_deployment_readiness.py — its subject IS the login endpoint (rate-limit
#     proof + security headers); it deliberately fires 6+ logins at localhost.
#   test_iter27_live.py / test_iter43_demo_cleanup_live.py — opt-in live suites,
#     skipped unless DALEEL_TEST_* env vars are supplied, credentials come from env.
DIRECT_LOGIN_ALLOWLIST = {
    "test_deployment_readiness.py",
    "test_iter27_live.py",
    "test_iter43_demo_cleanup_live.py",
}


class _FakeResp:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Isolate the helper: empty caches, throwaway disk cache, no real sleeping."""
    monkeypatch.setattr(_auth, "_TOKENS", {})
    monkeypatch.setattr(_auth, "_RESPONSES", {})
    monkeypatch.setattr(_auth, "_CACHE_FILE", tmp_path / "tokens.json")
    monkeypatch.setattr(_auth.time, "sleep", lambda *_: None)
    calls = {"post": 0, "get": 0}
    return calls


def test_helper_exposes_the_shared_api():
    for name in ("base_url", "login_response", "login_token", "login_token_or_skip",
                 "auth_headers", "auth_session", "extract_token"):
        assert callable(getattr(_auth, name)), f"_auth.{name} missing"
    assert _auth.SUPER_EMAIL and _auth.SUPER_PASSWORD


def test_base_url_resolves_without_env(monkeypatch):
    monkeypatch.delenv("REACT_APP_BACKEND_URL", raising=False)
    url = _auth.base_url()
    assert url.startswith("http") and not url.endswith("/")


def test_one_login_no_matter_how_many_callers(sandbox, monkeypatch):
    def fake_post(url, **kw):
        sandbox["post"] += 1
        return _FakeResp(200, {"token": "tok-123"})

    monkeypatch.setattr(_auth.requests, "post", fake_post)
    tokens = [_auth.login_token("x@y.z", "pw", url="http://fake") for _ in range(6)]
    assert tokens == ["tok-123"] * 6
    assert sandbox["post"] == 1, f"logged in {sandbox['post']} times, expected 1"


def test_retries_through_429_then_succeeds(sandbox, monkeypatch):
    seq = [_FakeResp(429, {"detail": "Too many attempts. Wait 60 seconds."},
                     {"Retry-After": "1"}),
           _FakeResp(429, {"detail": "Too many attempts. Wait 60 seconds."}),
           _FakeResp(200, {"access_token": "tok-after-429"})]

    def fake_post(url, **kw):
        sandbox["post"] += 1
        return seq[min(sandbox["post"] - 1, len(seq) - 1)]

    monkeypatch.setattr(_auth.requests, "post", fake_post)
    assert _auth.login_token("x@y.z", "pw", url="http://fake") == "tok-after-429"
    assert sandbox["post"] == 3


def test_429_is_never_cached_as_a_terminal_answer(sandbox, monkeypatch):
    """A run that is throttled for the whole window must not poison the cache."""
    monkeypatch.setattr(_auth, "_RETRY_ATTEMPTS", 2)

    def fake_post(url, **kw):
        sandbox["post"] += 1
        return _FakeResp(429, {"detail": "Too many attempts."})

    monkeypatch.setattr(_auth.requests, "post", fake_post)
    r = _auth.login_response("x@y.z", "pw", url="http://fake")
    assert r.status_code == 429
    assert not _auth._RESPONSES, "429 must not be cached"


def test_failed_credentials_cost_exactly_one_attempt(sandbox, monkeypatch):
    """A module with stale credentials cannot burn the limiter budget."""
    def fake_post(url, **kw):
        sandbox["post"] += 1
        return _FakeResp(401, {"detail": "Invalid credentials"})

    monkeypatch.setattr(_auth.requests, "post", fake_post)
    for _ in range(4):
        assert _auth.login_response("ghost@y.z", "pw", url="http://fake").status_code == 401
    assert sandbox["post"] == 1


def test_or_skip_skips_instead_of_failing(sandbox, monkeypatch):
    monkeypatch.setattr(_auth.requests, "post",
                        lambda url, **kw: _FakeResp(401, {"detail": "Invalid credentials"}))
    # pytest.skip raises Skipped, which derives from BaseException
    with pytest.raises(BaseException) as exc:
        _auth.login_token_or_skip("ghost@y.z", "pw", url="http://fake")
    assert type(exc.value).__name__ == "Skipped", type(exc.value).__name__


def test_disk_cache_is_reused_without_a_new_login(sandbox, monkeypatch):
    _auth._CACHE_FILE.write_text(json.dumps(
        {"http://fake|x@y.z": {"token": "tok-on-disk", "at": _auth.time.time()}}))
    monkeypatch.setattr(_auth, "_token_alive", lambda url, tok: True)

    def fake_post(url, **kw):
        sandbox["post"] += 1
        return _FakeResp(200, {"token": "fresh"})

    monkeypatch.setattr(_auth.requests, "post", fake_post)
    assert _auth.login_token("x@y.z", "pw", url="http://fake") == "tok-on-disk"
    assert sandbox["post"] == 0, "disk-cached token should avoid the login entirely"


def test_stale_disk_token_is_replaced(sandbox, monkeypatch):
    _auth._CACHE_FILE.write_text(json.dumps(
        {"http://fake|x@y.z": {"token": "expired", "at": _auth.time.time()}}))
    monkeypatch.setattr(_auth, "_token_alive", lambda url, tok: False)
    monkeypatch.setattr(_auth.requests, "post",
                        lambda url, **kw: _FakeResp(200, {"token": "fresh"}))
    assert _auth.login_token("x@y.z", "pw", url="http://fake") == "fresh"


def test_no_test_module_logs_in_directly():
    """Structural fence — new suites must go through tests/_auth.py."""
    pattern = re.compile(r"(requests|client|s|_session)\.post\(\s*f?\"[^\"]*?/api/auth/login")
    offenders = []
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name in DIRECT_LOGIN_ALLOWLIST:
            continue
        src = path.read_text()
        for m in pattern.finditer(src):
            line = src[:m.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line}")
    assert not offenders, (
        "these modules log in directly instead of using tests/_auth.py "
        f"(login is 5/min rate limited): {offenders}")


def test_conftest_puts_the_helper_on_the_path_and_resolves_the_url():
    src = (TESTS_DIR / "conftest.py").read_text()
    assert "sys.path.insert" in src
    assert "REACT_APP_BACKEND_URL" in src


# ── live: the whole point of the drop ────────────────────────────────────────
def test_live_shared_token_authenticates_many_calls():
    """Many modules' worth of authenticated traffic on ONE login — no 429."""
    url = _auth.base_url()
    headers = _auth.auth_headers()
    statuses = []
    for _ in range(12):
        r = _auth.requests.get(f"{url}/api/auth/me", headers=headers, timeout=20)
        statuses.append(r.status_code)
    assert set(statuses) == {200}, f"expected all 200, got {sorted(set(statuses))}"
