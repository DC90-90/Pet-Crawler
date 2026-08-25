"""iter64 — the detail supplement runs after ANY Salla crawl, and says so.

Production, Zarafa, 2026-07-31: the 19:09 crawl SUCCEEDED via Tier 2 (3000
products) — the supplement never ran because iter63 wired it only inside
crawl_salla_storefront_categories. The 19:05 Tier 2.5 attempt captured 0 (Salla
blocked the storefront path at 16:58) — so the supplement's only host path was
itself dead. Net: a successful crawl day in which no barcode could possibly be
filled, and NOTHING in the logs to say so.

Two properties fixed here, tested in that order:

1. Coverage — _maybe_salla_detail_supplement is invoked from every tier's
   persistence point (1, 2, 2.5, 3), before process_crawled_products, so a
   recovered barcode still persists through the unchanged iter61 path.
2. Observability — EVERY Salla crawl log carries exactly one
   detail_barcode_supplement entry: status "ran" with counts (non-200s bucketed
   per status code), or "skipped" with a machine-readable reason
   (no_products | degraded_crawl | no_missing_barcodes | no_store_identifier |
   exception:<msg>).

Plus the politeness guard: a crawl that produced < SALLA_DETAIL_MIN_PRODUCTS
products is a store already defending itself — do not pile detail requests on.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["DB_NAME"] = "test_salla_supp_tiers"
import pytest  # noqa: E402
import crawlers  # noqa: E402
import fetch_policy  # noqa: E402


@pytest.fixture(autouse=True)
def _fetch_policy_sandbox(monkeypatch):
    """iter76 — requests now flow through fetch_policy.polite_get.

    Two things must be neutralised for these to stay hermetic unit tests:
    the real backoff ceiling (8s per retry) and the curl_cffi impersonation
    fallback, which would fire a genuine outbound request at the storefront.
    """
    monkeypatch.setattr(fetch_policy, "MAX_DELAY", 1.0)
    monkeypatch.setattr(fetch_policy, "_curl_requests", None)
    fetch_policy.reset_hosts()
    yield
    fetch_policy.reset_hosts()

HILLS = "052742059518"
SALLA_STORE = {"id": "zarafa", "name": "Zarafa", "domain": "zarafaksa.com",
               "platform": "salla", "salla_store_identifier": "745123999"}
ZID_STORE = {"id": "aleef", "name": "Aleef", "domain": "aleef.com", "platform": "zid"}


def _listing(n, with_barcode=False, start=0):
    return [{"id": start + i, "sku": f"SL-{start + i}", "name": f"P{start + i}",
             "price": {"amount": 10.0 + i},
             **({"gtin": f"{2000000000000 + i}"} if with_barcode else {})}
            for i in range(n)]


def _detail_for(item):
    return {"id": item["id"], "skus": [
        {"price": item["price"], "stock_quantity": 3,
         "barcode": f"{3000000000000 + item['id']}"}]}


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}
        self.content = b"x" * 50
        self.headers = {}                 # httpx-shaped: polite_get reads Retry-After

    def json(self):
        return self._body


class _FakeClient:
    def __init__(self, detail_by_id=None, status=200):
        self.detail_by_id = detail_by_id or {}
        self.status = status
        self.calls = []
        self.closed = False

    # iter75 — production requests now flow through fetch_policy.polite_get,
    # which passes params/headers like httpx does. The fake must accept them.
    async def get(self, url, params=None, headers=None):
        self.calls.append(url)
        if self.status != 200:
            return _Resp(status=self.status)
        parts = url.rstrip("/").split("/")
        pid = parts[-2] if parts[-1] == "details" else parts[-1]
        d = self.detail_by_id.get(pid)
        return _Resp(body={"data": d}) if d else _Resp(status=404)

    async def aclose(self):
        self.closed = True


class _Coll:
    def __init__(self, doc=None):
        self.doc = doc
        self.updates = []

    async def find_one(self, *a, **k):
        return self.doc

    async def update_one(self, q, u):
        self.updates.append((q, u))


class _DB:
    def __init__(self, store_doc=None):
        self.stores = _Coll(store_doc)


def _log():
    return {"endpoints_tried": []}


def _supp_entries(log):
    return [e for e in log["endpoints_tried"]
            if e["endpoint"] == "detail_barcode_supplement"]


def _run(coro):
    return asyncio.run(coro)


def _patched_client(client):
    """Route the wrapper's own-client construction to the fake."""
    class _Ctx:
        def __enter__(self):
            self.orig = crawlers.httpx.AsyncClient
            crawlers.httpx.AsyncClient = lambda **kw: client
            return client

        def __exit__(self, *a):
            crawlers.httpx.AsyncClient = self.orig
    return _Ctx()


# ── (a)/(b) the supplement fires regardless of which tier produced the items ─
# The wrapper is tier-agnostic — what the requirement really pins is that it
# runs and fills from a Tier 1-shaped success (direct API, no Playwright, no
# captured identifier) and from a Tier 2-shaped success (identifier absent,
# cached one used). The per-tier call sites are pinned separately below by
# source inspection, since exercising real tier crawls would need Playwright.

def test_fires_after_tier1_style_success_using_cached_identifier():
    async def main():
        items = _listing(60)                      # >= politeness floor, all missing
        client = _FakeClient({str(i): _detail_for(items[i]) for i in range(60)})
        log = _log()
        with _patched_client(client):
            await crawlers._maybe_salla_detail_supplement(
                _DB(), SALLA_STORE, items, log)   # no identifier passed — Tier 1/2 shape
        entries = _supp_entries(log)
        assert len(entries) == 1 and entries[0]["status"] == "ran"
        assert entries[0]["products"] == 60
        assert all(it.get("gtin") for it in items)
        assert client.closed is True              # wrapper owns + closes its client
    asyncio.run(main())


def test_fires_after_tier2_style_success_and_persists_through_iter61_path():
    async def main():
        items = _listing(55)
        items[0] = {"id": 0, "sku": "SL-0", "name": "Hills GI Biome",
                    "price": {"amount": 162.5, "currency": "SAR"},
                    "quantity": "5", "status": "sale"}
        client = _FakeClient({"0": {"id": 0, "skus": [
            {"price": {"amount": 162.5}, "stock_quantity": 2, "barcode": HILLS}]},
            **{str(i): _detail_for(items[i]) for i in range(1, 55)}})
        log = _log()
        with _patched_client(client):
            await crawlers._maybe_salla_detail_supplement(_DB(), SALLA_STORE, items, log)
        assert items[0]["gtin"] == HILLS

        class _Rec:
            def __init__(self): self.inserted = []
            async def find_one(self, *a, **k): return None
            async def insert_one(self, d): self.inserted.append(d)

        class _RecDB:
            def __init__(self): self.products, self.product_snapshots = _Rec(), _Rec()
        db = _RecDB()
        now = crawlers.datetime.now(crawlers.timezone.utc)
        await crawlers.process_crawled_products(db, SALLA_STORE, items[:1], now, tier=2, confidence=88)
        assert db.products.inserted[0]["barcode"] == HILLS
        assert db.product_snapshots.inserted[0]["barcode"] == HILLS
    asyncio.run(main())


def test_every_tier_call_site_exists_and_precedes_persistence():
    """Pin the wiring itself: each of the four tier functions calls the wrapper,
    and on every success path the call comes BEFORE process_crawled_products —
    the supplement mutates raw items, so after persistence it would be a no-op."""
    import inspect
    for fn in (crawlers.crawl_salla_tier1, crawlers.crawl_tier2_xhr,
               crawlers.crawl_tier3_html, crawlers.crawl_salla_storefront_categories):
        src = inspect.getsource(fn)
        assert "_maybe_salla_detail_supplement" in src, fn.__name__
        if "process_crawled_products" in src:
            assert (src.index("_maybe_salla_detail_supplement")
                    < src.index("process_crawled_products")), fn.__name__


# ── (c) identifier is OPTIONAL since iter65 ─────────────────────────────────

def test_runs_without_any_store_identifier_via_the_store_domain_route():
    """iter65 — the primary /details route needs no store-identifier, so a
    missing identifier no longer skips the supplement (iter64 skipped with
    no_store_identifier here)."""
    async def main():
        store = {k: v for k, v in SALLA_STORE.items() if k != "salla_store_identifier"}
        items = _listing(60)
        client = _FakeClient({str(i): _detail_for(items[i]) for i in range(60)})
        log = _log()
        with _patched_client(client):
            await crawlers._maybe_salla_detail_supplement(
                _DB(store_doc={}), store, items, log)
        e = _supp_entries(log)[0]
        assert e["status"] == "ran" and e["products"] == 60
        # every fetch went to the store domain — no identifier, no fallback host
        assert all(c.startswith("https://zarafaksa.com/en/api/v1/products/") for c in client.calls)
        assert all(c.endswith("/details") for c in client.calls)
    asyncio.run(main())


# ── (d) politeness guard ────────────────────────────────────────────────────

def test_skipped_on_degraded_crawl():
    async def main():
        log = _log()
        await crawlers._maybe_salla_detail_supplement(
            _DB(), SALLA_STORE, _listing(crawlers.SALLA_DETAIL_MIN_PRODUCTS - 1), log)
        e = _supp_entries(log)[0]
        assert e["status"] == "skipped" and e["error"] == "degraded_crawl"

        # the Zarafa 19:05 shape: zero products
        log2 = _log()
        await crawlers._maybe_salla_detail_supplement(_DB(), SALLA_STORE, [], log2)
        assert _supp_entries(log2)[0]["error"] == "no_products"
    asyncio.run(main())


def test_skipped_when_nothing_is_missing():
    async def main():
        log = _log()
        await crawlers._maybe_salla_detail_supplement(
            _DB(), SALLA_STORE, _listing(60, with_barcode=True), log)
        e = _supp_entries(log)[0]
        assert e["status"] == "skipped" and e["error"] == "no_missing_barcodes"
    asyncio.run(main())


def test_non_salla_platforms_get_no_entry_at_all():
    async def main():
        log = _log()
        await crawlers._maybe_salla_detail_supplement(_DB(), ZID_STORE, _listing(60), log)
        assert _supp_entries(log) == []
    asyncio.run(main())


# ── (e) failed_403 counting ─────────────────────────────────────────────────

def test_403_responses_are_counted_per_status_code_in_the_summary():
    async def main():
        items = _listing(60)
        client = _FakeClient(status=403)          # Salla defending the detail path
        orig_dom = crawlers._salla_dom_barcode_supplement

        async def _no_dom(_store, still, cap=None, dom_reader=None):
            return 0, len(still[:crawlers.SALLA_DOM_BARCODE_CAP]), len(still[:crawlers.SALLA_DOM_BARCODE_CAP])
        crawlers._salla_dom_barcode_supplement = _no_dom
        try:
            log = _log()
            with _patched_client(client):
                await crawlers._maybe_salla_detail_supplement(_DB(), SALLA_STORE, items, log)
        finally:
            crawlers._salla_dom_barcode_supplement = orig_dom
        e = _supp_entries(log)[0]
        assert e["status"] == "ran" and e["products"] == 0
        # the per-status bucket is what makes a defended route diagnosable
        assert "failed_403=" in e["error"], e["error"]
        assert "filled=0" in e["error"], e["error"]
        # iter75 — the stage no longer grinds through all 60 products: a host
        # that 403s every request pushes us to the maximum backoff and the
        # stage stops there, recording WHY. (Pre-iter75 this read failed=60.)
        assert "failed_aborted_host_saturated=" in e["error"], e["error"]
        # iter65 — stage 2 was still attempted on what stage 1 could not fill
        assert "dom_attempted=60" in e["error"] and "dom_failed=60" in e["error"]
    asyncio.run(main())


def test_wrapper_exception_becomes_a_skipped_entry_not_a_crash():
    async def main():
        class _BoomDB:
            class stores:
                @staticmethod
                async def find_one(*a, **k):
                    raise RuntimeError("db down")
        store = {k: v for k, v in SALLA_STORE.items() if k != "salla_store_identifier"}
        log = _log()
        await crawlers._maybe_salla_detail_supplement(_BoomDB(), store, _listing(60), log)
        e = _supp_entries(log)[0]
        assert e["status"] == "skipped" and e["error"].startswith("exception:")
    asyncio.run(main())


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception:
            bad += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
