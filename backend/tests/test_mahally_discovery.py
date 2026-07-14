"""Tests for the Jul 2026 Mahally discovery-pool expansion.

Covers the three-source walker (store pages → browse root → pet subcategory
tree): pattern fallback for store routes, broken-pagination handling
(?page=2 → 500), non-pet nav-link filtering, cross-source dedup, the 1,000
cap, the page budget, and a full dry-run of enrich_barcodes_from_mahally over
a fixture universe proving the three guards are untouched and nothing writes.

No network — mahally._get is monkeypatched with a canned site map.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import mahally
from mahally import (
    discover_pet_products,
    enrich_barcodes_from_mahally,
    extract_browse_links,
)


def _product_page(store_id, pid, name_ar, barcode, store_domain="zarafaksa.com", store_username="zarafaksa"):
    """Minimal product detail page in the RSC-escaped shape the parser expects."""
    barcode_json = "null" if barcode is None else f'\\"{barcode}\\"'
    return f'''
<html><head>
<script type="application/ld+json">
{{"@context":"https://schema.org","@graph":[{{"@type":"Product","name":"{name_ar}","x":1}}]}}
</script></head><body>
<script>self.__next_f.push([1, "...\\"store\\":{{\\"id\\":{store_id},\\"name\\":\\"متجر\\",\\"username\\":\\"{store_username}\\",\\"domain\\":\\"https://{store_domain}\\"}},\\"skus\\":[{{\\"id\\":1,\\"product_id\\":{pid},\\"barcode\\":{barcode_json},\\"sku\\":\\"S{pid}\\",\\"mpn\\":null,\\"gtin\\":null,\\"updated_at\\":\\"2026-07-13 10:00:00\\"}}]"])</script>
</body></html>'''


def _index_page(pairs, browse_links=()):
    links = "".join(f'<a href="/ar/products/{s}/{p}/?queryID=x">x</a>' for s, p in pairs)
    cats = "".join(f'<a href="{l}">cat</a>' for l in browse_links)
    return f"<html><body>{links}{cats}</body></html>"


PET_ROOT = "/ar/browse/الحيوانات-الأليفة-و-مستلزماتها/"


def _make_site():
    """Canned site map: {path_or_url: html | None(=non-200)}."""
    site = {
        # Store pages: zarafaksa resolves on pattern 1; petsy-1 only on
        # pattern 2 (route fallback); tsahyel-1 resolves nowhere.
        "/ar/stores/zarafaksa/": _index_page([(10, 101), (10, 102)]),
        "/ar/stores/zarafaksa/?page=2": _index_page([(10, 103)]),
        "/ar/stores/zarafaksa/?page=3": _index_page([(10, 103)]),  # no new → stop
        "/ar/stores/petsy-1/": None,
        "/ar/store/petsy-1/": _index_page([(20, 201)]),
        "/ar/stores/tsahyel-1/": None,
        "/ar/store/tsahyel-1/": None,
        "/ar/tsahyel-1/": None,
        "/ar/stores/zarafaksa.com/": None,
        "/ar/stores/petsy-1.com/": None,
        "/ar/stores/tsahyel-1.com/": None,
        "/ar/store/tsahyel-1.com/": None,
        "/ar/tsahyel-1.com/": None,
        # Browse root: 2 products (one duplicating the zarafaksa store page),
        # one pet subcategory, one NON-pet nav link that must be ignored.
        PET_ROOT: _index_page(
            [(10, 101), (30, 301)],
            browse_links=["/ar/browse/طعام-قطط/", "/ar/browse/الالكترونيات/"],
        ),
        f"{PET_ROOT}?page=2": None,  # Mahally's real 500 behavior
        # Pet subcategory: has products, real pagination, and a depth-2 child.
        "/ar/browse/طعام-قطط/": _index_page([(30, 302)], browse_links=["/ar/browse/طعام-قطط-جاف/"]),
        "/ar/browse/طعام-قطط/?page=2": _index_page([(30, 303)]),
        "/ar/browse/طعام-قطط/?page=3": None,
        # Depth-2 child (walked) with a depth-3 child (NOT walked).
        "/ar/browse/طعام-قطط-جاف/": _index_page([(30, 304)], browse_links=["/ar/browse/طعام-قطط-جاف-كبار/"]),
        "/ar/browse/طعام-قطط-جاف/?page=2": None,
        # Product detail pages
        "/ar/products/10/101/": _product_page(10, 101, "رويال كانين طعام قطط 2 كجم", "1000000000101"),
        "/ar/products/10/102/": _product_page(10, 102, "ويسكاس تونا 85g", "1000000000102"),
        "/ar/products/10/103/": _product_page(10, 103, "سنبد بلا باركود", None),
        "/ar/products/20/201/": _product_page(20, 201, "شراب غير مطابق تماما", "1000000000201", "petsy-1.com", "petsy-1"),
        "/ar/products/30/301/": _product_page(30, 301, "رويال كانين طعام قطط 4 كجم", "1000000000301"),
        "/ar/products/30/302/": _product_page(30, 302, "فارمينا طعام كلاب 12kg", "1000000000302"),
        "/ar/products/30/303/": _product_page(30, 303, "هيلز طعام قطط 1.5kg", "1000000000303"),
        "/ar/products/30/304/": _product_page(30, 304, "بورينا وان قطط معقمة 3kg", "1000000000304"),
    }
    return site


def _patch_get(monkeypatch, site, log=None):
    async def fake_get(client, path_or_url):
        path = path_or_url.replace(mahally.MAHALLY_BASE, "")
        if log is not None:
            log.append(path)
        return site.get(path)
    monkeypatch.setattr(mahally, "_get", fake_get)


# ── Browse-link extraction ──────────────────────────────────

def test_extract_browse_links_filters_non_pet_slugs():
    html = _index_page([], browse_links=["/ar/browse/طعام-قطط/", "/ar/browse/الالكترونيات/", "/ar/browse/dog-toys/"])
    assert extract_browse_links(html) == ["/ar/browse/طعام-قطط/", "/ar/browse/dog-toys/"]


# ── Discovery walker ────────────────────────────────────────

def test_discovery_three_sources_dedup_and_attribution(monkeypatch):
    log = []
    _patch_get(monkeypatch, _make_site(), log)
    pairs, stats = asyncio.run(discover_pet_products(None, max_products=1000))
    # 8 unique products: 4 via stores (101,102,103,201), 301 via root, 302-304 via subcats
    assert len(pairs) == 8
    assert (10, 101) in pairs and (30, 304) in pairs
    # (10,101) appears on BOTH the zarafaksa store page and the browse root —
    # store source wins because store pages are walked first.
    assert stats["by_source"]["store:zarafaksa.com"] == 3
    assert stats["by_source"]["store:petsy-1.com"] == 1
    assert stats["by_source"]["browse_root"] == 1   # only (30,301) is new there
    assert stats["by_source"]["subcategory:d1"] == 2
    assert stats["by_source"]["subcategory:d2"] == 1
    # Route resolution: petsy-1 fell back to pattern 2; tsahyel unresolved.
    assert stats["store_routes_resolved"]["zarafaksa.com"] == "/ar/stores/zarafaksa/"
    assert stats["store_routes_resolved"]["petsy-1.com"] == "/ar/store/petsy-1/"
    assert stats["store_routes_resolved"]["tsahyel-1.com"] == ""
    # Non-pet nav link never fetched; depth-3 child never fetched.
    assert "/ar/browse/الالكترونيات/" not in log
    assert "/ar/browse/طعام-قطط-جاف-كبار/" not in log


def test_discovery_survives_broken_pagination(monkeypatch):
    log = []
    _patch_get(monkeypatch, _make_site(), log)
    pairs, _ = asyncio.run(discover_pet_products(None, max_products=1000))
    # Root ?page=2 500s (None) — walk continued to subcategories anyway,
    # and subcategory real pagination (?page=2 with NEW products) was used.
    assert (30, 303) in pairs
    assert f"{PET_ROOT}?page=2" in log


def test_discovery_cap_enforced(monkeypatch):
    _patch_get(monkeypatch, _make_site())
    pairs, _ = asyncio.run(discover_pet_products(None, max_products=3))
    assert len(pairs) == 3


def test_discovery_hard_ceiling_is_1000(monkeypatch):
    # A pathological caller asking for 50,000 still gets the 1,000 ceiling.
    big_site = {"/ar/stores/zarafaksa/": _index_page([(1, i) for i in range(1, 2000)])}
    _patch_get(monkeypatch, big_site)
    pairs, _ = asyncio.run(discover_pet_products(None, max_products=50000))
    assert len(pairs) == 1000


def test_discovery_page_budget(monkeypatch):
    _patch_get(monkeypatch, _make_site())
    monkeypatch.setattr(mahally, "MAX_DISCOVERY_PAGES", 2)
    pairs, stats = asyncio.run(discover_pet_products(None, max_products=1000))
    assert stats["pages_fetched"] <= 2


# ── End-to-end dry-run over the fixture universe ────────────

class _Cursor:
    def __init__(self, rows): self._rows = rows
    async def to_list(self, n): return self._rows[:n]


class _Products:
    def __init__(self, rows): self.rows = rows
    def find(self, query, projection=None): return _Cursor(self.rows)
    async def find_one(self, query, projection=None): return None  # no barcode conflicts
    async def update_one(self, *a, **k): raise AssertionError("dry-run must never write")


class _FakeDB:
    def __init__(self, rows): self.products = _Products(rows)


MY_ROWS = [
    # Exact-ish match to Mahally (10,101): same brand + same size → enrich.
    # Mahally serves the same Salla merchant record, so real names are
    # near-identical; the word-order difference keeps token_set_ratio honest.
    {"sku": "RC-2KG", "name_ar": "طعام قطط رويال كانين 2 كجم", "name_en": "", "brand": "رويال كانين"},
    # Same brand but 4kg — the size guard must steer it to the 4 كجم twin only
    {"sku": "RC-4KG", "name_ar": "طعام قطط رويال كانين 4 كجم", "name_en": "", "brand": "رويال كانين"},
    # Brand column empty → guard must reject even at ratio 100
    {"sku": "WH-85G", "name_ar": "ويسكاس تونا 85 جرام", "name_en": "", "brand": ""},
    # No plausible Mahally counterpart
    {"sku": "ZZZ-1", "name_ar": "لعبة فأر قماشية للقطط", "name_en": "", "brand": "بت زون"},
]


def test_enrich_dry_run_end_to_end(monkeypatch):
    _patch_get(monkeypatch, _make_site())
    db = _FakeDB(MY_ROWS)
    report = asyncio.run(enrich_barcodes_from_mahally(db, max_products=1000, dry_run=True))
    assert report["dry_run"] is True
    assert report["written"] == 0
    assert report["mahally_products_discovered"] == 8
    assert report["mahally_products_with_barcode"] == 7  # (10,103) has null barcode
    by_sku = {m["my_sku"]: m for m in report["sample_matches"]}
    # Size guard steers each Royal Canin row to its size twin, never crossed
    assert by_sku["RC-2KG"]["mahally_barcode"] == "1000000000101"
    assert by_sku["RC-4KG"]["mahally_barcode"] == "1000000000301"
    # Empty-brand row rejected despite near-identical name
    assert "WH-85G" not in by_sku
    assert report["would_enrich"] == 2
    for m in report["sample_matches"]:
        assert m["score"] >= 92
    # Discovery stats surfaced in the report
    assert report["discovery"]["by_source"]["store:zarafaksa.com"] == 3
