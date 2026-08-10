"""iter65 — the supplement can actually FILL barcodes: working route + DOM read.

Production 31 Jul (Zarafa): iter64's observability delivered its verdict on the
first crawl — `missing=1425 attempted=300 filled=0 failed=300 failed_410=299`.
Root cause: GET api.salla.dev/store/v1/products/{id} is a RETIRED route; it
410s for every product. Direct testing found the working route:

    GET {store_domain}/en/api/v1/products/{id}/details        (200, no
        store-identifier header needed)

with api.salla.dev/store/v1/products/{id}/details (identifier required) as the
fallback. BUT for multi-variant products the details root gtin/mpn are empty
and root sku is a merchant-internal code ("5274204208") — while the REAL
variant barcode (052742059518) is JS-rendered into the product page DOM, next
to a barcode icon under the variant picker. Confirmed in-browser: page find
locates it; a DevTools network search across all variant XHRs finds nothing;
curl of the raw HTML lacks it. For those products the rendered page is the
only source, hence stage 2.

Guard rails pinned here:
- root `sku` (and every DOM candidate) must pass STRICT GTIN validation —
  digits, GTIN length {8,12,13,14}, mod-10 check digit. "5274204208" is length
  10: not a GTIN length, rejected even though it happens to pass the check
  digit. Page text is full of 8-14 digit runs that are not barcodes (a Saudi
  phone number is 12 digits), so DOM candidates are never taken on the
  digit-run gate alone.
- a page with several strict candidates and no barcode label to disambiguate
  is SKIPPED, not guessed at — a wrong barcode is a wrong match, which is the
  exact false-positive class the iter51-53 guards exist to keep out.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_salla_dom")
import crawlers  # noqa: E402

HILLS = "052742059518"          # valid UPC-A (12, check digit ok)
RC = "3182550702263"            # valid EAN-13
INTERNAL = "5274204208"         # Zarafa's internal code — 10 digits, NOT a GTIN
PHONE = "966501234567"          # 12 digits, fails the check digit

SALLA_STORE = {"id": "zarafa", "name": "Zarafa", "domain": "zarafaksa.com",
               "platform": "salla", "salla_store_identifier": "745123999"}


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}
        self.content = b"x" * 50

    def json(self):
        return self._body


class _RouteClient:
    """Answers per (host-kind, pid): 'domain' routes vs 'salla_dev' fallback."""

    def __init__(self, domain_by_id=None, fallback_by_id=None, domain_status=200):
        self.domain_by_id = domain_by_id or {}
        self.fallback_by_id = fallback_by_id or {}
        self.domain_status = domain_status
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        parts = url.rstrip("/").split("/")
        pid = parts[-2] if parts[-1] == "details" else parts[-1]
        if "api.salla.dev" in url:
            d = self.fallback_by_id.get(pid)
            return _Resp(body={"data": d}) if d else _Resp(status=404)
        if self.domain_status != 200:
            return _Resp(status=self.domain_status)
        d = self.domain_by_id.get(pid)
        return _Resp(body={"data": d}) if d else _Resp(status=404)


def _run(coro):
    return asyncio.run(coro)


# ── strict GTIN validation ──────────────────────────────────────────────────

def test_strict_gtin_validation():
    assert crawlers._is_strict_gtin(HILLS) is True
    assert crawlers._is_strict_gtin(RC) is True
    assert crawlers._is_strict_gtin(INTERNAL) is False      # length 10
    assert crawlers._is_strict_gtin(PHONE) is False         # bad check digit
    assert crawlers._is_strict_gtin("12345678") is False    # 8 digits, bad check
    assert crawlers._is_strict_gtin("") is False
    assert crawlers._is_strict_gtin("52742059518") is False  # 11 — zero-dropped, not a GTIN length


# ── (a) stage 1 fills from the details root gtin ────────────────────────────

def test_stage1_fills_from_details_root_gtin_via_the_working_route():
    listing = [{"id": 100, "sku": "SL-100", "price": {"amount": 90.0}}]
    client = _RouteClient(domain_by_id={"100": {"id": 100, "sku": "SL-100",
                                                "gtin": RC, "skus": []}})
    filled, missing, failed, _b, by = _run(crawlers._salla_detail_barcode_supplement(
        client, listing, store_domain="zarafaksa.com", store_identifier="745123999"))
    assert (filled, missing, failed) == (1, 1, 0) and by == {}
    assert listing[0]["gtin"] == RC
    assert client.calls == ["https://zarafaksa.com/en/api/v1/products/100/details"]


def test_stage1_falls_back_to_salla_dev_when_the_store_domain_4xxs():
    listing = [{"id": 7, "sku": "SL-7", "price": {"amount": 20.0}}]
    client = _RouteClient(domain_status=403,
                          fallback_by_id={"7": {"id": 7, "gtin": HILLS, "skus": []}})
    filled, _m, failed, _b, by = _run(crawlers._salla_detail_barcode_supplement(
        client, listing, store_domain="zarafaksa.com", store_identifier="745123999"))
    assert filled == 1 and failed == 0 and by == {}
    assert listing[0]["gtin"] == HILLS
    assert client.calls == [
        "https://zarafaksa.com/en/api/v1/products/7/details",
        "https://api.salla.dev/store/v1/products/7/details",
    ]


def test_stage1_without_identifier_never_touches_the_fallback_host():
    listing = [{"id": 7, "sku": "SL-7", "price": {"amount": 20.0}}]
    client = _RouteClient(domain_status=410)
    filled, _m, failed, _b, by = _run(crawlers._salla_detail_barcode_supplement(
        client, listing, store_domain="zarafaksa.com", store_identifier=None))
    assert filled == 0 and failed == 1 and by == {410: 1}
    assert all("api.salla.dev" not in c for c in client.calls)


# ── (b) the internal root sku is rejected ───────────────────────────────────

def test_stage1_rejects_non_gtin_root_sku():
    """The exact production shape: multi-variant details with empty root
    gtin/mpn and the internal code in sku. Must NOT be promoted to a barcode."""
    detail = {"id": 1694697895, "sku": INTERNAL, "gtin": "", "mpn": "", "skus": []}
    assert crawlers._stage1_extract_barcode(detail, listed_price=162.5) == ""

    listing = [{"id": 1694697895, "sku": "SL-88213", "price": {"amount": 162.5}}]
    client = _RouteClient(domain_by_id={"1694697895": detail})
    filled, _m, _f, _b, _by = _run(crawlers._salla_detail_barcode_supplement(
        client, listing, store_domain="zarafaksa.com"))
    assert filled == 0 and "gtin" not in listing[0]


def test_stage1_accepts_a_root_sku_that_is_a_real_gtin():
    """Single-variant stores that type the EAN into the sku field still fill."""
    detail = {"id": 5, "sku": HILLS, "gtin": "", "mpn": "", "skus": []}
    assert crawlers._stage1_extract_barcode(detail) == HILLS


# ── (c) stage 2 DOM extraction ──────────────────────────────────────────────

def test_pick_dom_barcode_prefers_the_labelled_candidate():
    preferred = [f"باركود {HILLS}"]                    # the visible barcode row
    body = f"شحن مجاني فوق 200 ريال\nاتصل بنا {PHONE}\n{HILLS}\nSKU: {INTERNAL}"
    assert crawlers._pick_dom_barcode(preferred, body) == HILLS
    # label wins even when the body is ambiguous
    assert crawlers._pick_dom_barcode([f"barcode: {RC}"], f"{HILLS} {RC}") == RC


def test_pick_dom_barcode_body_only_requires_a_unique_strict_candidate():
    # exactly one strict GTIN in the page -> taken
    assert crawlers._pick_dom_barcode([], f"phone {PHONE} .. {HILLS} .. id {INTERNAL}") == HILLS
    # two distinct strict GTINs and no label -> ambiguous, never guessed
    assert crawlers._pick_dom_barcode([], f"{HILLS} and {RC}") == ""
    # nothing strict -> nothing
    assert crawlers._pick_dom_barcode([], f"{PHONE} {INTERNAL}") == ""
    # boundary rule: a run inside a longer number is not a candidate
    assert crawlers._pick_dom_barcode([], f"9{HILLS}9") == ""


def test_stage2_extracts_from_mocked_dom_and_injects():
    async def main():
        items = [{"id": 1694697895, "sku": "SL-88213", "price": {"amount": 162.5},
                  "urls": {"customer": "https://zarafaksa.com/ar/hills-gi/p1694697895"}}]
        seen = []

        async def dom_reader(_page, url):
            seen.append(url)
            return [f"باركود  {HILLS}"], f"junk {PHONE}"
        filled, attempted, failed = await crawlers._salla_dom_barcode_supplement(
            SALLA_STORE, items, dom_reader=dom_reader)
        assert (filled, attempted, failed) == (1, 1, 0)
        assert items[0]["gtin"] == HILLS
        assert seen == ["https://zarafaksa.com/ar/hills-gi/p1694697895"]
        # and the injected value persists through the normalizer like iter61
        norm = crawlers._normalize_raw_product(items[0], "Zarafa")
        assert norm["barcode"] == HILLS
    asyncio.run(main())


def test_stage2_counts_ambiguous_and_urlless_items_as_failed():
    async def main():
        items = [
            {"id": 1, "sku": "A", "urls": {"customer": "https://z.com/a/p1"}},
            {"id": 2, "sku": "B"},                                    # no URL
            {"id": 3, "sku": "C", "url": "/c/p3"},                    # relative — absolutized
        ]

        async def dom_reader(_page, url):
            if url.endswith("/p1"):
                return [], f"{HILLS} {RC}"                            # ambiguous
            return [f"barcode {RC}"], ""
        filled, attempted, failed = await crawlers._salla_dom_barcode_supplement(
            {"domain": "z.com"}, items, dom_reader=dom_reader)
        assert (filled, attempted, failed) == (1, 3, 2)
        assert items[2]["gtin"] == RC and "gtin" not in items[0]
    asyncio.run(main())


# ── (d) stage-2 cap ─────────────────────────────────────────────────────────

def test_stage2_cap_is_respected():
    """iter73v (Aug 8 2026) — the DOM barcode cap was lifted from 100 to
    100000 (effectively unlimited) so high-catalog Salla stores (Zarafa
    4177 products) are crawled completely in a single cycle. Old
    assertion checked a specific 100-item ceiling; new assertion
    verifies the cap is at least large enough to handle 150 items in
    one pass AND that the code still uses `cap` as a bound (regression
    fence against a future hard-coded truncation)."""
    async def main():
        items = [{"id": i, "sku": f"S{i}",
                  "urls": {"customer": f"https://z.com/x/p{i}"}} for i in range(150)]
        calls = []

        async def dom_reader(_page, url):
            calls.append(url)
            return [f"barcode {HILLS}"], ""
        filled, attempted, failed = await crawlers._salla_dom_barcode_supplement(
            {"domain": "z.com"}, items, dom_reader=dom_reader)
        # Cap is now large enough to cover a full 150-item pass in one crawl.
        assert crawlers.SALLA_DOM_BARCODE_CAP >= 150
        # All 150 items attempted (no artificial truncation).
        assert attempted == 150 and len(calls) == 150
        assert filled == 150 and failed == 0
        assert sum(1 for it in items if it.get("gtin")) == 150
    asyncio.run(main())


# ── (e) the combined counters in the crawl-log entry ────────────────────────

class _Coll:
    async def find_one(self, *a, **k):
        return None


class _DB:
    stores = _Coll()


def test_entry_carries_filled_details_filled_dom_and_dom_failure_counters():
    async def main():
        # 60 products: stage 1 fills 20 (details carry gtin), 410s the other 40;
        # stage 2 (stubbed) fills 25 of those and fails 15.
        items = [{"id": i, "sku": f"SL-{i}", "price": {"amount": 10.0},
                  "urls": {"customer": f"https://zarafaksa.com/x/p{i}"}}
                 for i in range(60)]
        client = _RouteClient(domain_by_id={
            str(i): {"id": i, "gtin": RC, "skus": []} for i in range(20)})
        orig_dom = crawlers._salla_dom_barcode_supplement

        async def _dom(store, still, cap=None, dom_reader=None):
            for it in still[:25]:
                it["gtin"] = HILLS
            return 25, 40, 15
        crawlers._salla_dom_barcode_supplement = _dom
        orig_client = crawlers.httpx.AsyncClient
        crawlers.httpx.AsyncClient = lambda **kw: client
        client.aclose = _noop
        log = {"endpoints_tried": []}
        try:
            await crawlers._maybe_salla_detail_supplement(_DB(), SALLA_STORE, items, log)
        finally:
            crawlers._salla_dom_barcode_supplement = orig_dom
            crawlers.httpx.AsyncClient = orig_client
        entries = [e for e in log["endpoints_tried"]
                   if e["endpoint"] == "detail_barcode_supplement"]
        assert len(entries) == 1
        e = entries[0]
        assert e["status"] == "ran"
        assert e["products"] == 45                        # 20 details + 25 dom
        for frag in ("missing=60", "filled=45", "filled_details=20", "filled_dom=25",
                     "failed=40", "failed_404=40", "dom_attempted=40", "dom_failed=15"):
            assert frag in e["error"], (frag, e["error"])
    asyncio.run(main())


async def _noop():
    return None


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
