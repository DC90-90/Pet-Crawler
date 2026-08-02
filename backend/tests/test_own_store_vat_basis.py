"""iter44/46 — own-store price basis: two-tier storefront + Merchant fallback.

The storefront genuinely lists only part of the catalogue (confirmed in
production: 1,184 of 2,590, stop_reason "no_next"), so it cannot price what it
does not carry. The basis is therefore decided per product:

  on the storefront            -> its inc-VAT shelf price   storefront_inc_vat
  not on it, is_taxable True   -> merchant price x 1.15     merchant_computed_inc_vat
  not on it, is_taxable False  -> merchant price unchanged  merchant_non_taxable
  not on it, is_taxable None   -> merchant price unchanged  merchant_unknown_tax

Unknown tax is deliberately NOT grossed up — inflating a real price on a guess
is worse than leaving a known value — but it IS tagged so the gap is countable.
Stock/sales always come from the Merchant API.

Ground truth: SKU 052742059518 — storefront 170 inc-VAT, merchant 147.83
ex-VAT, 147.83 x 1.15 = 170.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_vat_basis")
import server  # noqa: E402
import crawlers  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}
STORE = {"id": "own", "name": "Pets Houses", "domain": "pets-houses.com",
         "platform": "zid", "is_own_store": True}


def _m(sku, barcode, price, zid_id, sale_price=None, is_taxable="omit", qty=5, sold=1):
    row = {"sku": sku, "barcode": barcode, "name_ar": sku, "name_en": sku,
           "price": price, "sale_price": sale_price, "qty_available": qty,
           "in_stock": True, "sold_count": sold, "img_url": "", "product_url": "",
           "_zid_id": zid_id}
    if is_taxable != "omit":
        row["is_taxable"] = is_taxable
    return row


# Merchant API rows — ex-VAT prices, authoritative stock/sales
MERCHANT = [
    _m("052742059518", "052742059518", 147.83, 1, is_taxable=True, qty=7, sold=42),  # on storefront
    _m("SALE1", "B-SALE", 173.91, 2, sale_price=173.91, is_taxable=True, qty=3),      # on storefront, on sale
    _m("MERCH-SKU", "9999999999999", 86.96, 3, is_taxable=True, qty=1),               # storefront by barcode
    _m("ONLY-MERCH", "B-ONLY", 50.00, 4, is_taxable=True, qty=4),                     # NOT on storefront, taxable
    _m("NT-1", "B-NT", 40.00, 5, is_taxable=False, qty=2),                            # NOT on storefront, exempt
    _m("UNK-1", "B-UNK", 30.00, 6, qty=6),                                            # NOT on storefront, unknown
]
# Storefront rows — inc-VAT; no reliable stock/sales fields
STOREFRONT = [
    {"id": 1, "sku": "052742059518", "barcode": "052742059518", "price": 170, "effective_price": 170, "is_taxable": True},
    {"id": 2, "sku": "SALE1", "barcode": "B-SALE", "price": 200, "effective_price": 170, "is_taxable": True},
    {"id": 3, "sku": "SF-DIFFERENT", "barcode": "9999999999999", "price": 100, "effective_price": 100, "is_taxable": True},
]


def _stub(merchant=MERCHANT, sf=STOREFRONT, sf_ok=True):
    orig = (crawlers._fetch_zid_api_catalog, crawlers.fetch_own_storefront_catalog_raw,
            server.fetch_own_storefront_catalog_raw, server._fetch_zid_api_catalog)

    async def _mf(db, store):
        return [dict(r) for r in merchant], "ok"

    async def _sf(store, max_pages=200):
        return [dict(r) for r in sf], {"ok": sf_ok, "endpoint": "/api/v1/products",
                                       "rows": len(sf), "pages": 1,
                                       "stop_reason": "no_next", "truncated": False}
    crawlers._fetch_zid_api_catalog = _mf
    crawlers.fetch_own_storefront_catalog_raw = _sf
    server.fetch_own_storefront_catalog_raw = _sf
    server._fetch_zid_api_catalog = _mf
    return orig


def _unstub(orig):
    (crawlers._fetch_zid_api_catalog, crawlers.fetch_own_storefront_catalog_raw,
     server.fetch_own_storefront_catalog_raw, server._fetch_zid_api_catalog) = orig


async def _prep(db):
    for c in ("stores", "my_products", "product_snapshots", "crawl_logs", "matching_jobs"):
        await db[c].delete_many({})
    await db.stores.insert_one(dict(STORE))
    # what production holds TODAY: ex-VAT from the merchant path
    await db.my_products.insert_many([
        {"sku": r["sku"], "barcode": r["barcode"], "price": r["price"],
         "sale_price": r.get("sale_price"), "sync_source": "zid_api",
         "last_synced_at": "2026-07-25T00:00:00+00:00"}
        for r in MERCHANT
    ])


# ── the resolver, in isolation ───────────────────────────────────────────────
def test_resolve_own_price_covers_all_four_bases():
    R = crawlers.resolve_own_price
    assert crawlers.KSA_VAT_RATE == 0.15
    # iter73d — resolver now returns a 4-tuple (price, sale, original, basis).
    # The `original_price` element is the LIST/regular price grossed to the
    # SAME basis as `price`, so downstream writers never need to reconstruct
    # a strikethrough after the fact.
    #
    # 1. on the storefront, list==shelf, not on sale
    assert R((170.0, 170.0)) == (170.0, None, 170.0, "storefront_inc_vat")
    # ...on sale → shelf under list, both effective fields carry shelf,
    # original carries list.
    assert R((170.0, 200.0)) == (170.0, 170.0, 200.0, "storefront_inc_vat")
    # 2. not on storefront + explicit taxable → ×1.15 across all three
    assert R(None, merchant_price=147.83, is_taxable=True) == (
        170.0, None, 170.0, "merchant_computed_inc_vat")
    # discounted merchant row grosses up price+sale, list defaults to `price`
    # when not provided (backwards-compatible caller). merchant_price here is
    # already the effective price (see _fetch_zid_api_catalog line 2097).
    assert R(None, merchant_price=100, merchant_sale_price=80, is_taxable=True) == (
        115.0, 92.0, 115.0, "merchant_computed_inc_vat")
    # when the caller DOES pass a distinct list price, it flows through
    assert R(None, merchant_price=80, merchant_sale_price=80,
             merchant_list_price=100, is_taxable=True) == (
        92.0, 92.0, 115.0, "merchant_computed_inc_vat")
    # 3. explicitly non-taxable → unchanged
    assert R(None, merchant_price=40, is_taxable=False) == (
        40.0, None, 40.0, "merchant_non_taxable")
    # 4. iter73d — is_taxable=None NOW grosses up (Saudi default) instead of
    # leaving the row at ex-VAT. Tag switches so the auto-inflation is
    # countable at the VAT-audit surface.
    assert R(None, merchant_price=30, is_taxable=None) == (
        34.5, None, 34.5, "merchant_assumed_inc_vat")


def test_is_taxable_is_a_tristate():
    T = crawlers._zid_is_taxable
    assert T({"is_taxable": True}) is True
    assert T({"is_taxable": False}) is False
    assert T({}) is None                       # absent
    assert T({"is_taxable": None}) is None      # null
    assert T({"is_taxable": "yes"}) is None     # non-bool is NOT truthy-coerced
    assert T({"taxable": True}) is True         # alternate key


# ── Step 2: the sync ─────────────────────────────────────────────────────────
def test_sync_applies_two_tier_basis():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _prep(db)
        server.db = db
        orig = _stub()
        try:
            res = await crawlers.sync_own_store_prices(db, store=dict(STORE))
        finally:
            _unstub(orig)
        rows = {p["sku"]: p async for p in db.my_products.find({}, {"_id": 0})}

        # 1. on the storefront -> inc-VAT shelf price, merchant stock retained
        hills = rows["052742059518"]
        assert hills["price"] == 170 and hills["price_basis"] == "storefront_inc_vat"
        assert hills["quantity"] == 7 and hills["in_stock"] is True

        # on sale: both fields inc-VAT so `sale_price or price` == shelf
        sale = rows["SALE1"]
        assert sale["price"] == 170 and sale["sale_price"] == 170
        assert (sale.get("sale_price") or sale["price"]) == 170

        # matched to the storefront by barcode
        assert rows["MERCH-SKU"]["price"] == 100

        # 2. NOT on the storefront + taxable -> iter73i: storefront ran
        # authoritatively, so this row's merchant sale is a phantom the
        # shopper can't see. Anchor on the merchant LIST price (falls back
        # to merchant `price` since _m() doesn't set list_price) × 1.15,
        # and tag the new hidden basis so ops can audit the phantom-sale drop.
        only = rows["ONLY-MERCH"]
        assert only["price"] == round(50.00 * 1.15, 2) == 57.5
        assert only["price_basis"] == "merchant_hidden_from_storefront_inc_vat"
        assert only["quantity"] == 4                     # stock still from merchant

        # 3. non-taxable + not on storefront -> iter73i: same anchor-on-list
        # policy, but flat (no VAT). Different tag so the audit surface can
        # count both branches.
        assert rows["NT-1"]["price"] == 40.00
        assert rows["NT-1"]["price_basis"] == "merchant_hidden_non_taxable"

        # 4. iter73d + iter73i — unknown tax NOW auto-grosses (Saudi default)
        # AND rides the hidden-from-storefront branch when the storefront is
        # authoritative but doesn't carry this SKU.
        assert rows["UNK-1"]["price"] == round(30.00 * 1.15, 2) == 34.5
        assert rows["UNK-1"]["price_basis"] == "merchant_hidden_from_storefront_inc_vat"

        assert res["price_basis_counts"] == {
            "storefront_inc_vat": 3,
            "merchant_computed_inc_vat": 0,
            "merchant_non_taxable": 0,
            "merchant_assumed_inc_vat": 0,
            "merchant_hidden_from_storefront_inc_vat": 2,   # ONLY-MERCH + UNK-1
            "merchant_hidden_non_taxable": 1,               # NT-1
        }
    asyncio.run(main())


def test_sync_survives_storefront_outage_via_taxable_fallback():
    """A storefront outage no longer means storing ex-VAT: taxable products are
    computed inc-VAT, and the untaxable/unknown ones stay flat and tagged."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _prep(db)
        server.db = db
        orig = _stub(sf=[], sf_ok=False)
        try:
            res = await crawlers.sync_own_store_prices(db, store=dict(STORE))
        finally:
            _unstub(orig)
        rows = {p["sku"]: p async for p in db.my_products.find({}, {"_id": 0})}
        assert rows["052742059518"]["price"] == 170.0        # 147.83 x 1.15
        assert rows["052742059518"]["price_basis"] == "merchant_computed_inc_vat"
        assert rows["052742059518"]["quantity"] == 7          # stock still synced
        assert rows["NT-1"]["price"] == 40.00                 # exempt stays flat
        # iter73d — unknown tax NOW auto-grosses (Saudi default policy).
        assert rows["UNK-1"]["price"] == 34.5                 # 30 × 1.15
        assert res["price_basis_counts"]["merchant_computed_inc_vat"] == 4
        assert res["price_basis_counts"]["merchant_non_taxable"] == 1
        assert res["price_basis_counts"]["merchant_assumed_inc_vat"] == 1
    asyncio.run(main())


# ── Step 3: the backfill ─────────────────────────────────────────────────────
def test_backfill_reports_bases_and_applies_them():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _prep(db)
        server.db = db
        orig = _stub()
        try:
            dry = await server.own_store_vat_backfill(dry_run=True, sample=10, user=SUPER)
            assert dry["dry_run"] is True
            assert dry["would_update"] == 6, dry["would_update"]
            assert dry["no_live_source"] == 0
            assert dry["price_basis_counts"] == {
                "storefront_inc_vat": 3,
                "merchant_hidden_from_storefront_inc_vat": 2,   # iter73i
                "merchant_hidden_non_taxable": 1,               # iter73i
            }
            assert dry["merchant"]["vat_rate"] == 0.15
            by = {r["sku"]: r for r in dry["sample"]}
            assert by["052742059518"]["after_price"] == 170
            assert abs(by["052742059518"]["ratio"] - 1.15) <= 0.005
            assert by["ONLY-MERCH"]["after_price"] == 57.5
            assert by["ONLY-MERCH"]["after_basis"] == "merchant_hidden_from_storefront_inc_vat"
            assert by["NT-1"]["after_price"] == 40.00
            # dry run wrote nothing
            assert (await db.my_products.find_one({"sku": "052742059518"}))["price"] == 147.83

            real = await server.own_store_vat_backfill(dry_run=False, sample=10, user=SUPER)
            assert real["updated"] == 6
            again = await server.own_store_vat_backfill(dry_run=True, sample=10, user=SUPER)
            assert again["would_update"] == 0 and again["already_on_target_basis"] == 6
        finally:
            _unstub(orig)

        rows = {p["sku"]: p async for p in db.my_products.find({}, {"_id": 0})}
        assert rows["052742059518"]["price"] == 170
        assert rows["ONLY-MERCH"]["price"] == 57.5
        # iter73i — storefront ran authoritatively during the backfill (see the
        # 502-guard fetch above), so hidden-SKU rows carry the new bases.
        assert rows["NT-1"]["price"] == 40.00 and rows["NT-1"]["price_basis"] == "merchant_hidden_non_taxable"
        assert rows["UNK-1"]["price"] == 34.5 and rows["UNK-1"]["price_basis"] == "merchant_hidden_from_storefront_inc_vat"
    asyncio.run(main())


def test_backfill_flags_stale_rows_and_never_prices_them():
    """Rows in NEITHER live source are left untouched and reported by age and
    sync_source, so pruning can be considered instead of VAT-inflating them."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _prep(db)
        await db.my_products.insert_many([
            {"sku": "GHOST-1", "barcode": "B-G1", "price": 11.0, "sync_source": "crawler_ingest",
             "last_synced_at": "2025-01-01T00:00:00+00:00"},
            {"sku": "GHOST-2", "barcode": "B-G2", "price": 12.0, "sync_source": "zid_api",
             "last_synced_at": "2026-07-20T00:00:00+00:00"},
            {"sku": "GHOST-3", "barcode": "B-G3", "price": 13.0},      # never synced
        ])
        server.db = db
        orig = _stub()
        try:
            dry = await server.own_store_vat_backfill(dry_run=True, sample=10, user=SUPER)
        finally:
            _unstub(orig)
        assert dry["no_live_source"] == 3
        assert set(dry["no_live_source_sample"]) == {"GHOST-1", "GHOST-2", "GHOST-3"}
        sb = dry["stale_breakdown"]
        assert sb["by_sync_source"] == {"crawler_ingest": 1, "zid_api": 1, "(none)": 1}
        assert sb["by_age"][">90d"] == 1 and sb["by_age"]["never_synced"] == 1
        assert len(sb["samples"]) == 3
        # untouched — no price written for a product no source carries
        assert (await db.my_products.find_one({"sku": "GHOST-1"}))["price"] == 11.0
    asyncio.run(main())


def test_backfill_refuses_on_storefront_failure_and_requires_super_admin():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _prep(db)
        server.db = db
        orig = _stub(sf=[], sf_ok=False)
        try:
            try:
                await server.own_store_vat_backfill(dry_run=False, user=SUPER)
                raise AssertionError("must refuse when the storefront fetch fails")
            except HTTPException as e:
                assert e.status_code == 502
            assert (await db.my_products.find_one({"sku": "052742059518"}))["price"] == 147.83
        finally:
            _unstub(orig)
        orig = _stub()
        try:
            try:
                await server.own_store_vat_backfill(dry_run=True, user={"role": "viewer", "email": "v@v"})
                raise AssertionError("viewer must be rejected")
            except HTTPException as e:
                assert e.status_code == 403
        finally:
            _unstub(orig)
    asyncio.run(main())


if __name__ == "__main__":
    test_resolve_own_price_covers_all_four_bases()
    test_is_taxable_is_a_tristate()
    test_sync_applies_two_tier_basis()
    test_sync_survives_storefront_outage_via_taxable_fallback()
    test_backfill_reports_bases_and_applies_them()
    test_backfill_flags_stale_rows_and_never_prices_them()
    test_backfill_refuses_on_storefront_failure_and_requires_super_admin()
    print("PASS: iter46 two-tier VAT basis")
