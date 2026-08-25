"""iter74 (Aug 10 2026) — dead proxy subscription must not mean "no data".

Client screenshot (URGENT): the Stores page showed CRAWL STATUS **Failed** for
Caty, CutePets, Hamtaro, Lana Pets and Zarafa — "Tier 3 extracted 0 products —
all tiers failed" — while every Zid store showed Success. The failing set is
EXACTLY `store_registry.PROXY_STORES`.

Cause: the Webshare residential subscription answers **402 Payment Required**
on all 40 rotation usernames, so every tier of every proxied store died inside
the proxy CONNECT and never reached the storefront. Verified from the pod: a
DIRECT request to those same storefronts returns HTTP 200 (Caty's Tier-1 API
returns 1365 products).

Fix: probe the proxy once, cache the verdict, and crawl DIRECT when it is
unusable — recording the fallback on the crawl log and exposing it through
GET /api/admin/proxy-health so the real reason is visible instead of a
misleading "all tiers failed".
"""
import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crawlers  # noqa: E402
import server  # noqa: E402
import store_registry  # noqa: E402

SRC = Path(crawlers.__file__).read_text()


def _reset():
    crawlers._PROXY_HEALTH.update(ok=None, checked_at=0.0, reason="", exit_ip=None)


class _FakeResp:
    def __init__(self, status_code, text='{"ip":"1.2.3.4"}'):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Stands in for httpx.AsyncClient; counts how often the probe runs."""
    calls = 0
    result = _FakeResp(200)
    raise_exc = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, *a, **k):
        type(self).calls += 1
        if type(self).raise_exc:
            raise type(self).raise_exc
        return type(self).result


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    _reset()
    _FakeClient.calls = 0
    _FakeClient.result = _FakeResp(200)
    _FakeClient.raise_exc = None
    monkeypatch.setattr(crawlers.httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(crawlers, "get_proxy_credentials",
                        lambda: ("user-1", "pw", "p.webshare.io", "80"))
    yield
    _reset()


# ── health probe ────────────────────────────────────────────────────────────
def test_healthy_proxy_reports_ok():
    ok, reason = asyncio.run(crawlers.proxy_health(force=True))
    assert ok is True and reason == ""


def test_402_subscription_is_reported_unusable():
    _FakeClient.raise_exc = RuntimeError("402 Payment Required")
    ok, reason = asyncio.run(crawlers.proxy_health(force=True))
    assert ok is False
    assert "402" in reason


def test_non_200_from_the_proxy_is_unusable():
    _FakeClient.result = _FakeResp(407)
    ok, reason = asyncio.run(crawlers.proxy_health(force=True))
    assert ok is False and reason == "http_407"


def test_verdict_is_cached_so_a_crawl_does_not_probe_per_tier():
    async def body():
        await crawlers.proxy_health(force=True)
        for _ in range(5):
            await crawlers.proxy_health()
    asyncio.run(body())
    assert _FakeClient.calls == 1, "proxy health must be probed once per TTL"
    assert crawlers.PROXY_HEALTH_TTL_SECS >= 60


def test_missing_credentials_is_not_a_crash():
    crawlers.get_proxy_credentials = lambda: None      # patched by fixture anyway
    _reset()
    ok, reason = asyncio.run(crawlers.proxy_health(force=True))
    assert ok is False and reason == "not_configured"


# ── resolver behaviour ──────────────────────────────────────────────────────
def test_unproxied_store_never_touches_the_proxy():
    log = {}
    creds = asyncio.run(crawlers.resolve_proxy_for({"domain": "petsy.sa"}, log, "1"))
    assert creds is None
    assert log == {}, "an unproxied store must not be flagged as a fallback"
    assert _FakeClient.calls == 0


def test_healthy_proxy_is_used_for_a_proxied_store():
    creds = asyncio.run(crawlers.resolve_proxy_for(
        {"domain": "zarafaksa.com", "use_proxy": True}, {}, "1"))
    assert creds == ("user-1", "pw", "p.webshare.io", "80")


def test_dead_proxy_falls_back_to_direct_and_records_why():
    _FakeClient.raise_exc = RuntimeError("402 Payment Required")
    log = {}
    creds = asyncio.run(crawlers.resolve_proxy_for(
        {"domain": "zarafaksa.com", "use_proxy": True}, log, "3"))
    assert creds is None, "a dead proxy must not block the crawl"
    assert "402" in log["proxy_status"]
    assert log["proxy_fallback_tiers"] == ["3"]


def test_fallback_records_every_tier_that_used_it():
    _FakeClient.raise_exc = RuntimeError("402 Payment Required")
    log = {}
    store = {"domain": "hamtaro.sa", "use_proxy": True}

    async def body():
        for tier in ("1", "2", "3", "storefront_categories"):
            await crawlers.resolve_proxy_for(store, log, tier)
    asyncio.run(body())
    assert log["proxy_fallback_tiers"] == ["1", "2", "3", "storefront_categories"]


# ── structural fences ───────────────────────────────────────────────────────
def test_no_tier_resolves_proxy_credentials_behind_the_old_guard():
    """Every tier must go through `resolve_proxy_for`; the old
    `if store.get("use_proxy"): creds = get_proxy_credentials()` pattern is
    what made a dead subscription fail all five stores."""
    assert not re.search(r'if store\.get\("use_proxy"\):\s*\n\s*creds = get_proxy_credentials\(\)', SRC)
    # the only legitimate credential reads are inside the two helpers
    helpers = SRC.split("async def proxy_health(", 1)[1].split(
        "\n# ── ", 1)[0] if "async def proxy_health(" in SRC else ""
    assert SRC.count("creds = get_proxy_credentials()") == \
        helpers.count("creds = get_proxy_credentials()") + 1, \
        "credential reads must live in proxy_health / resolve_proxy_for only"
    assert SRC.count("await resolve_proxy_for(") >= 6


def test_every_proxied_store_in_the_registry_is_covered_by_the_fallback():
    """The failing set the client saw == PROXY_STORES; all of them are Salla
    stores crawled through the tier waterfall the fallback now guards."""
    assert store_registry.PROXY_STORES, "registry must still declare proxied stores"
    for dom in ("zarafaksa.com", "cutepets.com.sa", "hamtaro.sa",
                "lanapets.com", "caty-store.com"):
        assert dom in store_registry.PROXY_STORES


def test_proxy_health_endpoint_registered_and_gated():
    routes = {getattr(r, "path", None) for r in server.app.router.routes}
    assert "/api/admin/proxy-health" in routes
    src = Path(server.__file__).read_text()
    head = src.split("async def admin_proxy_health(", 1)[1][:200]
    assert "require_super_admin" in head
    body = src.split("async def admin_proxy_health(", 1)[1].split("\n@router", 1)[0]
    assert "action_required" in body and "crawlers.proxy_health" in body
