"""iter63 — Salla Tier 2.5 detail supplement: recover barcodes the listing omits.

Live evidence (Zarafa, Hills GI Biome p1694697895 @ 162.5 SAR): the Tier 2.5
LISTING payload (api.salla.dev/store/v1/products?source=categories) carries no
per-variant skus[] barcodes — the static page's JSON-LD "sku" is a different
number ("5274204208"), and the true barcode 052742059518 only arrives from the
product-DETAIL XHR. So iter61's persistence had nothing to persist for these
stores and the matcher's Level 1 stayed blind to them.

The supplement re-fetches the detail for ONLY the products whose listing gave
no barcode, capped per crawl (SALLA_DETAIL_SUPPLEMENT_CAP) so remaining gaps
fill over successive daily crawls, and injects the recovered value where the
normalizer's existing root scan finds it — persistence then flows through the
exact iter61 path. The listing's price fields are never touched: the barcode
must describe the LISTED item, which is why selection is price-match first.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_salla_detail_supp")
import crawlers  # noqa: E402
from core.utils import canonical_barcode  # noqa: E402

HILLS = "052742059518"
HILLS_3KG = "052742059525"


def _detail(variants, **root):
    return {"id": 1694697895, "name": "Hills GI Biome", "skus": variants, **root}


def _v(price, barcode=None, gtin=None, mpn=None, stock=0):
    v = {"price": {"amount": price, "currency": "SAR"}, "stock_quantity": stock}
    if barcode is not None:
        v["barcode"] = barcode
    if gtin is not None:
        v["gtin"] = gtin
    if mpn is not None:
        v["mpn"] = mpn
    return v


# ── variant selection ───────────────────────────────────────────────────────

def test_variant_matching_listed_price_wins():
    """The Zarafa case: two variants (1.5 Kg @162.5, 3 Kg), listed at 162.5 —
    the barcode must come from the 1.5 Kg variant, not the first row."""
    d = _detail([_v(310.0, barcode=HILLS_3KG, stock=4),
                 _v(162.5, barcode=HILLS, stock=2)])
    assert crawlers._select_salla_variant_barcode(d, listed_price=162.5) == HILLS


def test_no_price_match_falls_back_to_first_in_stock_variant():
    d = _detail([_v(99.0, barcode="1111111111116", stock=0),
                 _v(120.0, barcode="2222222222222", stock=7)])
    assert crawlers._select_salla_variant_barcode(d, listed_price=162.5) == "2222222222222"


def test_all_oos_falls_back_to_first_variant():
    d = _detail([_v(99.0, barcode="1111111111116", stock=0),
                 _v(120.0, barcode="2222222222222", stock=0)])
    assert crawlers._select_salla_variant_barcode(d, listed_price=55.0) == "1111111111116"


def test_gtin_and_mpn_are_read_when_barcode_is_absent():
    d = _detail([_v(162.5, gtin=HILLS, stock=1)])
    assert crawlers._select_salla_variant_barcode(d, listed_price=162.5) == HILLS
    d2 = _detail([_v(162.5, mpn=HILLS, stock=1)])
    assert crawlers._select_salla_variant_barcode(d2, listed_price=162.5) == HILLS


def test_chosen_variant_without_identifiers_falls_back_to_root_not_sibling():
    """A sibling variant's GTIN must NOT be attached to the listed price — that
    is precisely the pack-size collision the iter51-53 guards exist for."""
    d = _detail([_v(162.5, stock=2),                       # chosen; no identifiers
                 _v(310.0, barcode=HILLS_3KG, stock=4)],   # sibling — must not leak
                gtin="4444444444440")
    assert crawlers._select_salla_variant_barcode(d, listed_price=162.5) == "4444444444440"
    d_no_root = _detail([_v(162.5, stock=2), _v(310.0, barcode=HILLS_3KG, stock=4)])
    assert crawlers._select_salla_variant_barcode(d_no_root, listed_price=162.5) == ""


def test_canonicalisation_gate_and_suffix_handling():
    # junk values are rejected by the canonical_barcode gate
    d = _detail([_v(162.5, barcode="abc01", gtin="123", stock=1)])
    assert crawlers._select_salla_variant_barcode(d, listed_price=162.5) == ""
    # a suffixed variant value persists as its digits-only GTIN-14 canonical
    # form (the normalizer's root scan requires a full-digit match)
    d2 = _detail([_v(162.5, barcode="9003579308936carton", stock=1)])
    got = crawlers._select_salla_variant_barcode(d2, listed_price=162.5)
    assert got == "09003579308936"
    assert canonical_barcode(got) == canonical_barcode("9003579308936")


def test_variantless_detail_reads_root_fields():
    d = {"id": 9, "name": "X", "gtin": HILLS}
    assert crawlers._select_salla_variant_barcode(d, listed_price=10.0) == HILLS
    assert crawlers._select_salla_variant_barcode({}, listed_price=10.0) == ""
    assert crawlers._select_salla_variant_barcode(None, listed_price=10.0) == ""


# ── who needs the supplement ────────────────────────────────────────────────

def test_missing_detection_mirrors_the_normalizer():
    assert crawlers._salla_raw_barcode({"id": 1, "sku": "SL-1"}) == ""
    assert crawlers._salla_raw_barcode({"id": 2, "gtin": HILLS}) == HILLS
    assert crawlers._salla_raw_barcode(
        {"id": 3, "skus": [{"barcode": HILLS}]}) == HILLS
    # iter73u — a numeric root-level `sku` is a valid barcode candidate; Zarafa
    # and other Salla merchants routinely store the EAN in the sku field
    # (e.g. "052742024363"). The supplement's skip-check must mirror the
    # normalizer's new fallback so we don't re-fetch products we already have
    # a barcode for.
    assert crawlers._salla_raw_barcode({"id": 4, "sku": "5274204208"}) == "5274204208"
    # Non-numeric SKUs (merchant-internal strings) are still ignored — the
    # _NUMERIC_BARCODE_RE gate keeps them out.
    assert crawlers._salla_raw_barcode({"id": 5, "sku": "HL-CAT-3KG"}) == ""


# ── the supplement pass itself ──────────────────────────────────────────────

class _Resp:
    def __init__(self, status=200, body=None, content=b"{}"):
        self.status_code = status
        self._body = body or {}
        self.content = content

    def json(self):
        return self._body


class _FakeClient:
    """Answers detail URLs from a dict; records every URL it was asked for."""

    def __init__(self, by_id):
        self.by_id = by_id
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        parts = url.rstrip("/").split("/")
        pid = parts[-2] if parts[-1] == "details" else parts[-1]
        entry = self.by_id.get(pid)
        if entry == "boom":
            raise RuntimeError("connection reset")
        if entry is None:
            return _Resp(status=404)
        return _Resp(body={"data": entry}, content=b"x" * 100)


def _run(coro):
    return asyncio.run(coro)


def test_supplement_fills_only_missing_and_injects_gtin():
    listing = [
        {"id": 1694697895, "sku": "SL-88213", "name": "Hills GI Biome",
         "price": {"amount": 162.5}},                       # missing — Zarafa case
        {"id": 2, "sku": "SL-2", "gtin": "3182550702263",
         "price": {"amount": 129.0}},                       # already has one
    ]
    client = _FakeClient({"1694697895": _detail(
        [_v(310.0, barcode=HILLS_3KG, stock=4), _v(162.5, barcode=HILLS, stock=2)])})
    filled, missing, failed, nbytes, by_status = _run(
        crawlers._salla_detail_barcode_supplement(
            client, listing, store_domain="zarafaksa.com"))
    assert (filled, missing, failed) == (1, 1, 0)
    assert by_status == {}
    assert nbytes == 100
    assert listing[0]["gtin"] == HILLS                      # injected
    assert listing[1]["gtin"] == "3182550702263"            # untouched
    assert len(client.calls) == 1                           # no fetch for item 2
    # iter65 — the working route: store domain, /details suffix
    assert client.calls[0] == "https://zarafaksa.com/en/api/v1/products/1694697895/details"
    # price fields untouched — the supplement must never reprice the listing
    assert listing[0]["price"] == {"amount": 162.5}


def test_cap_bounds_the_fetches_per_crawl():
    listing = [{"id": i, "sku": f"S{i}", "price": {"amount": 10.0}} for i in range(10)]
    client = _FakeClient({str(i): _detail([_v(10.0, barcode=f"{1000000000000 + i}")])
                          for i in range(10)})
    filled, missing, failed, _b, _by = _run(
        crawlers._salla_detail_barcode_supplement(
            client, listing, store_domain="zarafaksa.com", cap=3))
    assert missing == 10 and len(client.calls) == 3 and filled == 3
    assert sum(1 for it in listing if it.get("gtin")) == 3   # the rest wait for tomorrow


def test_supplement_is_fail_soft_per_product():
    listing = [{"id": 1, "sku": "A", "price": {"amount": 5.0}},   # detail raises
               {"id": 2, "sku": "B", "price": {"amount": 6.0}},   # detail 404s
               {"id": 3, "sku": "C", "price": {"amount": 7.0}}]   # works
    client = _FakeClient({"1": "boom",
                          "3": _detail([_v(7.0, barcode=HILLS)])})
    filled, missing, failed, _b, by_status = _run(
        crawlers._salla_detail_barcode_supplement(
            client, listing, store_domain="zarafaksa.com"))
    assert (filled, missing, failed) == (1, 3, 2)
    # iter64 — the two failures are attributed: one exception, one HTTP 404
    assert by_status == {"exception": 1, 404: 1}
    assert listing[2]["gtin"] == HILLS


# ── end to end: recovered barcode persists through the iter61 path ──────────

class _RecColl:
    def __init__(self):
        self.inserted = []

    async def find_one(self, *a, **k):
        return None

    async def insert_one(self, doc):
        self.inserted.append(doc)


class _RecDB:
    def __init__(self):
        self.products = _RecColl()
        self.product_snapshots = _RecColl()


def test_recovered_barcode_reaches_products_and_snapshots():
    """The whole point: after the supplement, the normal iter61 write path
    persists the barcode to BOTH collections, GTIN-14-compatible with our
    catalogue's leading-zero form."""
    async def main():
        listing = [{"id": 1694697895, "name": "Hills GI Biome Cat", "sku": "SL-88213",
                    "price": {"amount": 162.5, "currency": "SAR"},
                    "quantity": "5", "status": "sale"}]
        client = _FakeClient({"1694697895": _detail(
            [_v(310.0, barcode=HILLS_3KG, stock=4),
             _v(162.5, barcode="52742059518", stock=2)])})   # zero-dropped form
        await crawlers._salla_detail_barcode_supplement(
            client, listing, store_domain="zarafaksa.com")

        db = _RecDB()
        now = crawlers.datetime.now(crawlers.timezone.utc)
        await crawlers.process_crawled_products(
            db, {"id": "zarafa", "name": "Zarafa", "domain": "zarafaksa.com"},
            listing, now, tier=2, confidence=88)
        assert db.products.inserted[0]["barcode"] == "52742059518"
        assert db.product_snapshots.inserted[0]["barcode"] == "52742059518"
        # bridges to our catalogue's 052742059518 via the canonical key
        assert canonical_barcode("52742059518") == canonical_barcode(HILLS)
        # and the listed price survived untouched
        assert db.product_snapshots.inserted[0]["price"] == 162.5
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
