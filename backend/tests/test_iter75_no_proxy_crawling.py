"""iter75 (Aug 10 2026) — crawling without a paid proxy, and the own-store
"Failed" badge that was never a failure.

Client: "I don't want to rely on Webshare any more, get the data crawled
correctly by any means. Also fix my own store Pets Houses failing against
api.zid.sa."

Two findings behind those two asks:

1. **The proxy was load-bearing.** Webshare answered 402 on every rotation
   username and all five proxied Salla stores went dark (iter74 added a direct
   fallback). Direct works — but the proxy had been hiding rate limits: ONE
   CutePets crawl logged **277 × HTTP 429** because the barcode supplement
   fired one request per product with no pacing and no backoff, and Caty's
   supplement route answers **404 for every product** (625 useless requests
   per crawl). Fixed by `fetch_policy.polite_get` (per-host adaptive pacing,
   backoff honouring Retry-After, rotating UA, curl_cffi TLS impersonation as
   the last resort) plus a consecutive-failure circuit breaker on both
   supplement stages. `PROXY_ENABLED` now defaults to false, so no store
   routes through Webshare at all.

2. **"Pets Houses — Failed" was a falsy-zero bug.** The own-store sync marks
   `tier_used = 0` to mean "the AUTHENTICATED Zid merchant API won", the best
   possible source. `_finalize_crawl_log` wrote
   `"success" if crawl_log["tier_used"] else "failed"` — and `0` is falsy — so
   every successful 2233-product sync from api.zid.sa was reported as FAILED,
   with `https://api.zid.sa/v1/products/` shown in the tier column. Exactly
   what the client screenshotted. (The Zid ORDERS endpoint really does 401 —
   that needs partner OAuth credentials, tracked separately.)
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import crawlers  # noqa: E402
import fetch_policy  # noqa: E402
import store_registry  # noqa: E402

CRAWLERS_SRC = Path(crawlers.__file__).read_text()


@pytest.fixture(autouse=True)
def _clean_hosts(monkeypatch):
    # Real backoff sleeps up to 8s per retry; the tests assert the SHAPE of the
    # policy, not the wall-clock, so shrink the ceiling for the suite.
    monkeypatch.setattr(fetch_policy, "MAX_DELAY", 1.5)
    fetch_policy.reset_hosts()
    yield
    fetch_policy.reset_hosts()


class _Resp:
    def __init__(self, status_code, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload if payload is not None else {"data": []}
        self.content = b"x" * 10
        self.text = "{}"

    def json(self):
        return self._payload


class _Client:
    """Scripted async client; records the headers of every attempt."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers or {}})
        item = self._responses.pop(0) if self._responses else _Resp(200)
        if isinstance(item, Exception):
            raise item
        return item


# ── no more Webshare ────────────────────────────────────────────────────────
def test_proxy_is_disabled_by_default():
    assert store_registry.PROXY_ENABLED is False
    assert store_registry.PROXY_STORES == set(), \
        "no store may route through the paid proxy unless PROXY_ENABLED is set"
    # the capability list is retained so the flag can be flipped back on
    assert "zarafaksa.com" in store_registry.PROXY_CAPABLE_STORES


def test_registry_flips_existing_proxy_flags_off():
    src = Path(store_registry.__file__).read_text()
    assert '{"domain": {"$nin": list(PROXY_STORES)}, "use_proxy": True}' in src, \
        "stores that used to be proxied must be actively switched off"


# ── pacing + backoff ────────────────────────────────────────────────────────
def test_successful_requests_are_spaced_not_hammered():
    client = _Client([_Resp(200), _Resp(200), _Resp(200)])

    async def body():
        t0 = time.monotonic()
        for _ in range(3):
            await fetch_policy.polite_get(client, "https://shop.example/api")
        return time.monotonic() - t0
    elapsed = asyncio.run(body())
    assert elapsed >= fetch_policy.BASE_DELAY, "requests to one host must be paced"
    assert len(client.calls) == 3


def test_429_is_retried_with_a_widening_delay():
    client = _Client([_Resp(429), _Resp(429), _Resp(200)])

    async def body():
        return await fetch_policy.polite_get(client, "https://shop.example/api")
    resp = asyncio.run(body())
    assert resp.status_code == 200
    assert len(client.calls) == 3
    diag = fetch_policy.host_diagnostics()["shop.example"]
    assert diag["throttled"] == 2
    assert diag["delay_secs"] > fetch_policy.BASE_DELAY, \
        "a throttling host must earn more space between requests"


def test_retry_after_header_is_honoured():
    client = _Client([_Resp(429, headers={"Retry-After": "1"}), _Resp(200)])

    async def body():
        t0 = time.monotonic()
        r = await fetch_policy.polite_get(client, "https://slow.example/api")
        return r, time.monotonic() - t0
    resp, elapsed = asyncio.run(body())
    assert resp.status_code == 200
    assert elapsed >= 1.0, "Retry-After must be obeyed, not guessed"


def test_404_is_an_answer_not_a_retry():
    client = _Client([_Resp(404), _Resp(200)])
    resp = asyncio.run(fetch_policy.polite_get(client, "https://shop.example/x"))
    assert resp.status_code == 404
    assert len(client.calls) == 1, "404 must not burn retries"


def test_every_request_looks_like_a_browser_and_rotates_identity():
    client = _Client([_Resp(429), _Resp(429), _Resp(200)])
    asyncio.run(fetch_policy.polite_get(client, "https://shop.example/api"))
    uas = [c["headers"].get("User-Agent") for c in client.calls]
    assert all(ua and "Mozilla/5.0" in ua for ua in uas)
    assert all("ar-SA" in c["headers"].get("Accept-Language", "") for c in client.calls)


def test_exceptions_never_escape_and_return_none():
    client = _Client([RuntimeError("boom"), RuntimeError("boom"), RuntimeError("boom")])
    resp = asyncio.run(fetch_policy.polite_get(client, "https://dead.example/api"))
    assert resp is None


def test_caller_supplied_headers_survive():
    client = _Client([_Resp(200)])
    asyncio.run(fetch_policy.polite_get(
        client, "https://shop.example/api", headers={"store-identifier": "abc"}))
    assert client.calls[0]["headers"]["store-identifier"] == "abc"


def test_impersonation_fallback_is_available():
    """curl_cffi gives us a real Chrome TLS fingerprint — the only bot-block
    answer left once the residential proxy is gone."""
    assert fetch_policy.impersonation_available() is True
    assert 403 in fetch_policy.IMPERSONATE_STATUSES
    assert 429 in fetch_policy.RETRY_STATUSES


# ── the crawler uses the policy everywhere ──────────────────────────────────
def test_no_raw_client_get_left_in_the_storefront_crawl_paths():
    """Every storefront request must be paced. (The authenticated Zid merchant
    API is first-party and deliberately exempt.)"""
    def _fn(name, end="\nasync def "):
        return CRAWLERS_SRC.split(f"async def {name}(", 1)[1].split(end, 1)[0]

    for fn_name in ("_try_single_endpoint", "_paginate_endpoint",
                    "_salla_detail_barcode_supplement"):
        body = _fn(fn_name)
        assert "await polite_get(" in body, f"{fn_name} must use polite_get"
        for forbidden in ("await http.get(", "await client.get("):
            assert forbidden not in body, \
                f"{forbidden} in {fn_name} bypasses pacing/backoff"
    cats = _fn("crawl_salla_storefront_categories")
    assert "await polite_get(client, url)" in cats
    assert CRAWLERS_SRC.count("await polite_get(") >= 5


# ── supplement circuit breakers ─────────────────────────────────────────────
def test_host_saturation_is_detectable():
    """A host that has pushed us to MAX_DELAY will not yield more data —
    per-product stages must be able to see that and stop."""
    client = _Client([_Resp(429) for _ in range(30)])

    async def body():
        for _ in range(6):
            await fetch_policy.polite_get(client, "https://angry.example/api")
    asyncio.run(body())
    assert fetch_policy.host_saturated("https://angry.example/api") is True
    assert fetch_policy.host_saturated("https://calm.example/api") is False


def test_stage1_supplement_stops_when_the_host_saturates():
    """hamtaro.sa 429s its details route even through TLS impersonation: the
    limit is per IP. Grinding costs ~24s per product and returns nothing."""
    items = [{"id": i, "price": 10, "sku": f"S{i}"} for i in range(200)]
    client = _Client([_Resp(429) for _ in range(2000)])
    filled, missing, failed, nbytes, by_status = asyncio.run(
        crawlers._salla_detail_barcode_supplement(
            client, items, store_domain="hamtaro.sa"))
    assert filled == 0
    assert "aborted_host_saturated" in by_status
    assert failed < fetch_policy.SUPPLEMENT_ABORT_AFTER, \
        "saturation must cut the stage sooner than the plain failure breaker"


def test_stage1_supplement_gives_up_after_a_run_of_failures():
    """Caty answers 404 for every product on the details route: 625 requests,
    zero barcodes. It must stop and say why."""
    items = [{"id": i, "price": 10, "sku": f"S{i}"} for i in range(300)]
    client = _Client([_Resp(404) for _ in range(2000)])

    filled, missing, failed, nbytes, by_status = asyncio.run(
        crawlers._salla_detail_barcode_supplement(
            client, items, store_domain="caty-store.com"))
    assert filled == 0
    assert failed == fetch_policy.SUPPLEMENT_ABORT_AFTER
    assert by_status["aborted_after_consecutive"] == fetch_policy.SUPPLEMENT_ABORT_AFTER
    assert len(client.calls) <= fetch_policy.SUPPLEMENT_ABORT_AFTER + 2, \
        "the breaker must cut the request count, not just the bookkeeping"


def test_stage1_breaker_resets_on_success():
    """Intermittent failures must NOT trip the breaker."""
    items = [{"id": i, "price": 10, "sku": f"S{i}"} for i in range(40)]
    good = _Resp(200, payload={"data": {"barcode": "3182550702362", "price": 10}})
    script = []
    for i in range(40):
        script.append(_Resp(404) if i % 2 else good)
    client = _Client(script)
    filled, missing, failed, nbytes, by_status = asyncio.run(
        crawlers._salla_detail_barcode_supplement(
            client, items, store_domain="shop.example"))
    assert "aborted_after_consecutive" not in by_status
    assert failed < fetch_policy.SUPPLEMENT_ABORT_AFTER


def test_dom_stage_gives_up_after_a_run_of_misses():
    items = [{"id": i, "urls": {"customer": f"https://s.example/p{i}"}}
             for i in range(200)]
    reads = {"n": 0}

    async def _reader(page, url):
        reads["n"] += 1
        return [], "no barcode here"

    filled, attempted, failed = asyncio.run(
        crawlers._salla_dom_barcode_supplement(
            {"domain": "s.example"}, items, dom_reader=_reader))
    assert filled == 0
    assert reads["n"] <= fetch_policy.SUPPLEMENT_ABORT_AFTER + 1, \
        "a Playwright navigation costs seconds — stop after a losing streak"


def test_dom_stage_stops_when_items_carry_no_urls():
    items = [{"id": i} for i in range(200)]        # no product URL at all

    async def _reader(page, url):                  # must never be called
        raise AssertionError("no URL should mean no navigation")

    filled, attempted, failed = asyncio.run(
        crawlers._salla_dom_barcode_supplement(
            {"domain": "s.example"}, items, dom_reader=_reader))
    assert filled == 0
    assert failed == fetch_policy.SUPPLEMENT_ABORT_AFTER


# ── the own-store "Failed" badge ────────────────────────────────────────────
class _FakeStores:
    def __init__(self):
        self.set_doc = None

    async def update_one(self, flt, update):
        self.set_doc = update["$set"]


class _FakeLogs:
    async def insert_one(self, doc):
        return None


class _FakeDB:
    def __init__(self):
        self.stores = _FakeStores()
        self.crawl_logs = _FakeLogs()


def test_tier_zero_authenticated_api_is_a_success_not_a_failure():
    """The exact client-reported bug: 2233 products synced from api.zid.sa and
    the Stores page said FAILED, because tier 0 is falsy."""
    db = _FakeDB()
    log = {"tier_used": 0, "error": None, "products_found": 2233,
           "endpoint_used": "https://api.zid.sa/v1/products/"}
    asyncio.run(crawlers._finalize_crawl_log(db, log, "own-store-id"))
    assert db.stores.set_doc["last_crawl_status"] == "success"
    assert db.stores.set_doc["last_crawl_tier"] == 0


def test_a_crawl_that_reached_no_tier_is_still_a_failure():
    db = _FakeDB()
    log = {"tier_used": None, "error": "all tiers failed", "products_found": 0,
           "endpoint_used": None}
    asyncio.run(crawlers._finalize_crawl_log(db, log, "some-store"))
    assert db.stores.set_doc["last_crawl_status"] == "failed"


def test_normal_tiers_still_report_success():
    for tier in (1, 2, 3):
        db = _FakeDB()
        asyncio.run(crawlers._finalize_crawl_log(
            db, {"tier_used": tier, "error": None, "products_found": 10,
                 "endpoint_used": "/api/v1/products"}, "s"))
        assert db.stores.set_doc["last_crawl_status"] == "success"
