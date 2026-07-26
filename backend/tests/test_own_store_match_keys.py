"""iter47 — own-store match keys (A-D). Own-store matching path only.

Production symptom: Hill's GI Biome 1.5kg is LIVE on pets-houses.com but the
VAT backfill classified it `no_live_source`, because the two sides key it
differently:

    my_products sku/barcode  052742059518   (UPC-A, leading zero kept)
    storefront  ean          52742059518    (leading zero dropped)

Neither the literal key nor the iter45 suffix-stripping bridges those. The fix:

  A. both sides also emit the canonical GTIN-14 form (zero-padded to 14), which
     is identical for the pair -> "00052742059518".
  B. SKU<->EAN cross-matching in BOTH directions, GTIN-aware via A.
  C. product_page_url -> storefront row id, using the existing by_id index.
  D. the backfill dry-run reports no_live_source BEFORE and AFTER these keys.

Guard rails asserted here: short numeric SKUs (e.g. "15") gain no new keys, and
two genuinely different EANs never collide.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_match_keys")
import crawlers  # noqa: E402
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}
L = crawlers.storefront_price_lookup


# ── A/B — the production pair ────────────────────────────────────────────────
def test_upc_leading_zero_pair_matches_via_gtin14():
    """052742059518 (my_products) <-> 52742059518 (storefront) — the exact pair
    that was misclassified as no_live_source."""
    # a shared canonical key exists in both directions
    assert "00052742059518" in crawlers.barcode_keys("052742059518")
    assert "00052742059518" in crawlers.barcode_keys("52742059518")

    # storefront carries the zero-dropped EAN; my_products carries the UPC-A
    sf = [{"id": 900, "sku": "HILL-GI-15", "barcode": "52742059518",
           "price": 170, "effective_price": 170}]
    idx = crawlers._storefront_price_index(sf)
    hit, method = L(idx, sku="052742059518", barcode="052742059518")
    assert hit == (170.0, 170.0), (hit, method)
    assert method == "barcode_gtin14", method

    # ...and the reverse: my_products zero-dropped, storefront zero-kept
    sf_rev = [{"id": 901, "sku": "X", "barcode": "052742059518",
               "price": 170, "effective_price": 170}]
    hit, method = L(crawlers._storefront_price_index(sf_rev),
                    sku="?", barcode="52742059518")
    assert hit == (170.0, 170.0) and method == "barcode_gtin14", method

    # B — cross-field, both ways: our SKU is their EAN, and our EAN is their SKU
    hit, method = L(idx, sku="052742059518")                  # no barcode at all
    assert hit == (170.0, 170.0) and method == "sku_as_barcode_gtin14", method
    sf_sku = [{"id": 902, "sku": "52742059518", "price": 80, "effective_price": 80}]
    hit, method = L(crawlers._storefront_price_index(sf_sku),
                    sku="INTERNAL-1", barcode="52742059518")
    assert hit == (80.0, 80.0) and method == "barcode_as_sku", method

    # the previous key set genuinely could not do this — that is the whole point
    assert L(idx, sku="052742059518", barcode="052742059518",
             canonical=False) == (None, None)


# ── C — product URL bridges to the storefront row id ─────────────────────────
def test_product_url_bridges_to_storefront_id():
    assert crawlers.product_url_id("/products/15") == "15"
    assert crawlers.product_url_id("https://pets-houses.com/products/15") == "15"
    assert crawlers.product_url_id("https://pets-houses.com/products/15?v=2#buy") == "15"
    assert crawlers.product_url_id("https://x.sa/p15") == "15"
    assert crawlers.product_url_id("https://pets-houses.com/about") is None
    assert crawlers.product_url_id(None) is None

    sf = [{"id": 15, "sku": "SF-ONLY", "barcode": "4001234567890",
           "price": 57.5, "effective_price": 57.5}]
    idx = crawlers._storefront_price_index(sf)
    # nothing about this row's sku or barcode matches — only the URL does
    hit, method = L(idx, sku="LEGACY-SKU", barcode="",
                    product_url="https://pets-houses.com/products/15")
    assert hit == (57.5, 57.5) and method == "product_url_id", method
    # ...and the URL must NOT override a real SKU match
    hit, method = L(idx, sku="SF-ONLY", product_url="https://pets-houses.com/products/999")
    assert method == "sku"
    # a URL pointing at a row that isn't in the catalogue stays unmatched
    assert L(idx, sku="?", product_url="https://pets-houses.com/products/999") == (None, None)
    # legacy mode ignores the URL entirely
    assert L(idx, sku="LEGACY-SKU", product_url="https://pets-houses.com/products/15",
             canonical=False) == (None, None)


# ── guard rails ──────────────────────────────────────────────────────────────
def test_short_skus_are_untouched_and_distinct_eans_stay_distinct():
    # short numeric values are not barcodes: no lead match, no canonical form
    for short in ("15", "7", "1234567", "0"):
        assert crawlers.barcode_keys(short) == [short], short
    # 15+ digits are not GTINs either — never truncated into a false match
    assert crawlers.barcode_keys("123456789012345") == ["123456789012345"]
    assert crawlers.barcode_keys("") == [] and crawlers.barcode_keys(None) == []

    # a product whose SKU is literally "15" must not be dragged onto a row
    # merely because some barcode zero-pads near it
    sf = [{"id": 15, "sku": "REAL-15", "barcode": "0000000000015",
           "price": 10, "effective_price": 10}]
    idx = crawlers._storefront_price_index(sf)
    assert L(idx, sku="15") == (None, None)
    assert L(idx, sku="?", barcode="15") == (None, None)

    # distinct EANs stay distinct — canonicalisation must not merge them
    a, b = "4001234567890", "4001234567891"
    assert not (set(crawlers.barcode_keys(a)) & set(crawlers.barcode_keys(b)))
    sf2 = [{"id": 1, "sku": "A", "barcode": a, "price": 10, "effective_price": 10},
           {"id": 2, "sku": "B", "barcode": b, "price": 20, "effective_price": 20}]
    idx2 = crawlers._storefront_price_index(sf2)
    assert L(idx2, sku="?", barcode=a)[0] == (10.0, 10.0)
    assert L(idx2, sku="?", barcode=b)[0] == (20.0, 20.0)
    # a third, absent EAN of the same length resolves to nothing
    assert L(idx2, sku="?", barcode="4009999999999") == (None, None)

    # zero-padding is not transitive across different digit counts: 12345678 and
    # 123456780 are different codes and must not share a canonical key
    assert not (set(crawlers.barcode_keys("12345678")) & set(crawlers.barcode_keys("123456780")))
    # ...but the SAME code with and without leading zeros does share one
    assert set(crawlers.barcode_keys("0012345678")) & set(crawlers.barcode_keys("12345678"))


# ── D — before/after on the backfill dry-run ─────────────────────────────────
def test_backfill_dry_run_reports_no_live_source_before_and_after():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        for c in ("stores", "my_products"):
            await db[c].delete_many({})
        await db.stores.insert_one({"id": "own", "name": "PH", "domain": "pets-houses.com",
                                    "platform": "zid", "is_own_store": True})
        # storefront: zero-dropped EANs + one row reachable only by its URL id
        sf = [{"id": 5000 + i, "sku": f"S-{i}", "barcode": f"{52742059000 + i}",
               "price": round((100 + i) * 1.15, 2), "effective_price": round((100 + i) * 1.15, 2)}
              for i in range(100)]
        sf.append({"id": 15, "sku": "SF-15", "barcode": "",
                   "price": 57.5, "effective_price": 57.5})

        mine = []
        for i in range(40):                       # matched before AND after (sku)
            mine.append({"sku": f"S-{i}", "barcode": f"{52742059000 + i}", "price": 100 + i,
                         "sync_source": "zid_api"})
        for i in range(40, 90):                   # A — recovered by GTIN-14 only
            mine.append({"sku": f"INT-{i}", "barcode": f"0{52742059000 + i}",
                         "price": 100 + i, "sync_source": "zid_api"})
        mine.append({"sku": "LEGACY-15", "barcode": "", "price": 50,   # C — URL only
                     "sync_source": "zid_api",
                     "product_page_url": "https://pets-houses.com/products/15"})
        for i in range(10):                       # genuinely gone
            mine.append({"sku": f"GONE-{i}", "barcode": f"{7000000000000 + i}", "price": 10,
                         "sync_source": "zid_api"})
        await db.my_products.insert_many(mine)
        server.db = db

        async def _fake_fetch(store, max_pages=200):
            return sf, {"ok": True, "endpoint": "/api/v1/products", "rows": len(sf),
                        "pages": 5, "stop_reason": "pages_count_reached", "truncated": False}

        async def _no_merchant(db, store):
            return [], "missing_token"

        orig = (server.fetch_own_storefront_catalog_raw, server._fetch_zid_api_catalog)
        server.fetch_own_storefront_catalog_raw = _fake_fetch
        server._fetch_zid_api_catalog = _no_merchant
        try:
            rep = await server.own_store_vat_backfill(dry_run=True, sample=10, user=SUPER)
        finally:
            server.fetch_own_storefront_catalog_raw, server._fetch_zid_api_catalog = orig

        assert rep["my_products_total"] == 101
        # BEFORE: 50 GTIN-only rows + 1 URL-only row + 10 dead = 61 unmatched
        assert rep["no_live_source_before_iter47_keys"] == 61, rep
        # AFTER: only the 10 genuinely-dead rows remain
        assert rep["no_live_source"] == 10, rep
        rec = rep["recovered_by_iter47_keys"]
        assert rec["count"] == 51, rec
        assert rec["by_method"] == {"barcode_gtin14": 50, "product_url_id": 1}, rec
        assert rep["match_methods"]["sku"] == 40
        # every recovered row is now priced on the inc-VAT storefront basis
        assert rep["price_basis_counts"]["storefront_inc_vat"] == 91
        assert rep["would_update"] == 91, rep["would_update"]
        # dry run wrote nothing
        assert (await db.my_products.find_one({"sku": "S-0"}))["price"] == 100
    asyncio.run(main())


if __name__ == "__main__":
    test_upc_leading_zero_pair_matches_via_gtin14()
    test_product_url_bridges_to_storefront_id()
    test_short_skus_are_untouched_and_distinct_eans_stay_distinct()
    test_backfill_dry_run_reports_no_live_source_before_and_after()
    print("PASS: iter47 own-store match keys")
