"""iter45 — own-store storefront pagination + heterogeneous match keys.

Production symptom: the VAT backfill dry-run saw only 1,184 storefront products
against 2,590 in my_products, so no_storefront_match was 1,404 (~half the
catalogue).

Root cause: the SHARED _paginate_endpoint stops on `len(page) < 20` — a "short
page means last page" heuristic. Any page the storefront returns short (filtered
/ trimmed / uneven page) ends the walk early. That helper is also used by the
COMPETITOR crawl, so the own-store fetch now has its own paginator driven by the
response's explicit pagination metadata.

Second cause: match keys. my_products holds Zid internal ids ("Z.123456") and
barcode variants ("9003579308936carton"), neither of which matched a storefront
row keyed by plain sku/barcode.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_sf_pagination"
import crawlers  # noqa: E402
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}
PAGE_SIZE = 24
TOTAL = 2590                      # production catalogue size
PAGES = (TOTAL + PAGE_SIZE - 1) // PAGE_SIZE      # 108


def _product(i):
    return {"id": 1000 + i, "sku": f"SKU-{i}", "barcode": f"{9003579300000 + i}",
            "price": 100 + i, "effective_price": 100 + i, "is_taxable": True}


class _Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status
        self.headers = {}                 # httpx-shaped: polite_get reads Retry-After

    def json(self):
        return self._body


class _FakeHttp:
    """Storefront that paginates with explicit metadata and — critically —
    returns a SHORT page in the middle of the catalogue (the exact shape that
    tripped the old `len(more) < 20` heuristic)."""
    def __init__(self, total=TOTAL, short_page=50, meta="pages_count"):
        self.total, self.short_page, self.meta = total, short_page, meta
        self.pages_requested = []
        # consistent page map: the short page carries fewer items but NO item is
        # skipped, so the catalogue still sums to `total`
        self.pages, i = [], 0
        while i < total:
            size = 7 if len(self.pages) + 1 == short_page else PAGE_SIZE
            self.pages.append([_product(j) for j in range(i, min(i + size, total))])
            i += size

    # iter76 — the shared paginator goes through fetch_policy.polite_get, which
    # sends browser-shaped headers. Without this kwarg every page raised a
    # TypeError inside polite_get and the walk stopped after page 1.
    async def get(self, url, params=None, headers=None, timeout=None):
        page = int((params or {}).get("page", 1))
        self.pages_requested.append(page)
        items = self.pages[page - 1] if 1 <= page <= len(self.pages) else []
        body = {"data": items}
        if self.meta == "pages_count":
            body["pages_count"] = len(self.pages)
        elif self.meta == "next":
            body["pagination"] = {"next": None if page >= len(self.pages) else f"?page={page+1}"}
        elif self.meta == "results":
            body["pagination"] = {"results": self.total}
        return _Resp(body)


def _ep():
    return {"url": "https://pets-houses.com/api/v1/products", "params": {"page": 1},
            "tag": "/api/v1/products", "pagination": "page"}


def test_shared_paginator_truncates_on_short_page_regression():
    """Documents the defect: the SHARED helper stops at the short page. It is
    intentionally left unchanged because the competitor crawl depends on it."""
    async def main():
        http = _FakeHttp()
        first = (await http.get(_ep()["url"], params={"page": 1})).json()["data"]
        rows = await crawlers._paginate_endpoint(http, _ep(), first)
        assert len(rows) < TOTAL                 # truncated, as in production
        assert len(rows) == (50 - 1) * PAGE_SIZE + 7   # stopped exactly at the short page
    asyncio.run(main())


def test_own_paginator_walks_the_full_catalogue():
    async def main():
        for meta in ("pages_count", "next", "results"):
            http = _FakeHttp(meta=meta)
            first = (await http.get(_ep()["url"], params={"page": 1})).json()["data"]
            rows, pages, stop = await crawlers._paginate_own_storefront(http, _ep(), first)
            # the short page must NOT end the walk
            assert len(rows) == TOTAL, (meta, len(rows), stop)
            assert pages >= len(http.pages) - 1, (meta, pages)
            assert stop in ("pages_count_reached", "no_next", "results_total_reached",
                            "empty_page", "exhausted"), (meta, stop)
    asyncio.run(main())


def test_own_paginator_bounds_and_dedupes():
    async def main():
        # page cap honoured and reported
        http = _FakeHttp()
        first = (await http.get(_ep()["url"], params={"page": 1})).json()["data"]
        rows, pages, stop = await crawlers._paginate_own_storefront(http, _ep(), first, max_pages=5)
        assert stop == "max_pages" and pages == 5 and len(rows) < TOTAL

        # a storefront that echoes page 1 forever must not loop
        class _Stuck(_FakeHttp):
            async def get(self, url, params=None, timeout=None):
                return _Resp({"data": [_product(i) for i in range(PAGE_SIZE)]})
        stuck = _Stuck()
        first = (await stuck.get("u", params={"page": 1})).json()["data"]
        rows, pages, stop = await crawlers._paginate_own_storefront(stuck, _ep(), first)
        assert stop == "duplicate_page" and len(rows) == PAGE_SIZE

        # a mid-walk HTTP error stops cleanly with what was collected
        class _Breaks(_FakeHttp):
            async def get(self, url, params=None, timeout=None):
                page = int((params or {}).get("page", 1))
                if page == 4:
                    return _Resp({}, status=500)
                return await super().get(url, params=params, timeout=timeout)
        br = _Breaks()
        first = (await br.get("u", params={"page": 1})).json()["data"]
        rows, pages, stop = await crawlers._paginate_own_storefront(br, _ep(), first)
        assert stop == "http_500" and len(rows) == 3 * PAGE_SIZE
    asyncio.run(main())


# ── match keys ───────────────────────────────────────────────────────────────
SF_ROWS = [
    {"id": 123456, "sku": "MERCH-1", "barcode": "9003579308936", "price": 170, "effective_price": 170},
    {"id": 777, "sku": "MERCH-2", "barcode": "4001234567890carton", "price": 90, "effective_price": 90},
]


def test_match_keys_handle_zid_ids_and_carton_suffixes():
    idx = crawlers._storefront_price_index(SF_ROWS)
    L = crawlers.storefront_price_lookup
    # plain sku
    assert L(idx, sku="MERCH-1")[1] == "sku"
    # exact barcode
    assert L(idx, sku="?", barcode="9003579308936")[1] == "barcode"
    # my_products carries the carton variant, storefront carries the clean EAN
    hit, method = L(idx, sku="?", barcode="9003579308936carton")
    assert hit[0] == 170 and method == "barcode_normalized"
    # ...and the reverse: storefront carries the suffix, my_products is clean.
    # The index holds BOTH forms, so this matches on the literal key.
    hit, method = L(idx, sku="?", barcode="4001234567890")
    assert hit[0] == 90 and method == "barcode"
    # Zid internal id as the SKU
    hit, method = L(idx, sku="Z.123456")
    assert hit[0] == 170 and method == "zid_internal_id"
    # numeric SKU that is really a barcode
    hit, method = L(idx, sku="9003579308936")
    assert hit[0] == 170 and method == "sku_as_barcode"
    # genuinely absent
    assert L(idx, sku="NOPE", barcode="0000000000000") == (None, None)
    # a 15-digit string must NOT be truncated into a false 14-digit match
    assert crawlers.barcode_keys("123456789012345") == ["123456789012345"]


def test_backfill_dry_run_with_full_catalogue_and_mixed_keys():
    """End-to-end: full pagination + the new keys, on a catalogue shaped like
    production (clean SKUs, Z. ids, carton barcodes, and true absentees)."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        for c in ("stores", "my_products"):
            await db[c].delete_many({})
        await db.stores.insert_one({"id": "own", "name": "PH", "domain": "pets-houses.com",
                                    "platform": "zid", "is_own_store": True})
        # storefront: 1000 products, inc-VAT
        sf = [{"id": 5000 + i, "sku": f"S-{i}", "barcode": f"{9003579300000 + i}",
               "price": round((100 + i) * 1.15, 2), "effective_price": round((100 + i) * 1.15, 2)}
              for i in range(1000)]
        # my_products: ex-VAT, keyed four different ways + 50 genuine absentees
        mine = []
        for i in range(0, 400):                       # by SKU
            mine.append({"sku": f"S-{i}", "barcode": f"{9003579300000 + i}", "price": 100 + i,
                         "sync_source": "zid_api"})
        for i in range(400, 700):                     # by Zid internal id
            mine.append({"sku": f"Z.{5000 + i}", "barcode": "", "price": 100 + i,
                         "sync_source": "zid_api"})
        for i in range(700, 1000):                    # by carton-suffixed barcode
            mine.append({"sku": f"INT-{i}", "barcode": f"{9003579300000 + i}carton",
                         "price": 100 + i, "sync_source": "zid_api"})
        for i in range(50):                           # genuinely not on the storefront
            mine.append({"sku": f"GONE-{i}", "barcode": f"{7000000000000 + i}", "price": 10,
                         "sync_source": "zid_api"})
        await db.my_products.insert_many(mine)
        server.db = db

        async def _fake_fetch(store, max_pages=200):
            return sf, {"ok": True, "endpoint": "/api/v1/products", "rows": len(sf),
                        "pages": 42, "stop_reason": "pages_count_reached", "truncated": False}
        async def _no_merchant(db, store):
            return [], "missing_token"
        orig = (server.fetch_own_storefront_catalog_raw, server._fetch_zid_api_catalog)
        server.fetch_own_storefront_catalog_raw = _fake_fetch
        server._fetch_zid_api_catalog = _no_merchant
        try:
            rep = await server.own_store_vat_backfill(dry_run=True, sample=10, user=SUPER)
        finally:
            server.fetch_own_storefront_catalog_raw, server._fetch_zid_api_catalog = orig

        assert rep["my_products_total"] == 1050
        assert rep["would_update"] == 1000, rep["would_update"]
        # no storefront row AND no merchant row -> no live source
        assert rep["no_live_source"] == 50, rep["no_live_source"]
        # every key shape resolved, and we can see WHICH
        assert rep["match_methods"]["sku"] == 400
        assert rep["match_methods"]["zid_internal_id"] == 300
        assert rep["match_methods"]["barcode_normalized"] == 300
        assert rep["storefront"]["truncated"] is False
        # ratios land on 1.15
        for r in rep["sample"]:
            assert abs(r["ratio"] - 1.15) <= 0.01, r
        # dry run wrote nothing
        assert (await db.my_products.find_one({"sku": "S-0"}))["price"] == 100
    asyncio.run(main())


if __name__ == "__main__":
    test_shared_paginator_truncates_on_short_page_regression()
    test_own_paginator_walks_the_full_catalogue()
    test_own_paginator_bounds_and_dedupes()
    test_match_keys_handle_zid_ids_and_carton_suffixes()
    test_backfill_dry_run_with_full_catalogue_and_mixed_keys()
    print("PASS: iter45 storefront pagination + match keys")
