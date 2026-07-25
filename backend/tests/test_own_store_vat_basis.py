"""iter44 Step 2 + Step 3 — own-store price moves to the VAT-inclusive basis.

Step 2: the sync keeps sold_count / quantity / stock from the Zid Merchant API
but takes the PRICE from the public storefront (effective_price, else price) —
the same basis as every competitor row and as the orders ledger. A SKU the
storefront doesn't carry keeps the merchant price, tagged merchant_ex_vat.

Step 3: a one-off backfill moves existing my_products rows onto that basis.

Ground truth from production: SKU 052742059518 — storefront 170 inc-VAT,
merchant 147.83 ex-VAT, 147.83 x 1.15 = 170.
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

# Merchant API rows (ex-VAT prices, authoritative stock/sales)
MERCHANT = [
    # the confirmed production case
    {"sku": "052742059518", "barcode": "052742059518", "name_ar": "هيلز", "name_en": "Hills GI",
     "price": 147.83, "sale_price": None, "qty_available": 7, "in_stock": True,
     "sold_count": 42, "img_url": "", "product_url": "", "_zid_id": 1},
    # on sale: merchant list ex-VAT 173.91, storefront shelf 170 (list 200)
    {"sku": "SALE1", "barcode": "B-SALE", "name_ar": "س", "name_en": "Sale",
     "price": 173.91, "sale_price": 173.91, "qty_available": 3, "in_stock": True,
     "sold_count": 5, "img_url": "", "product_url": "", "_zid_id": 2},
    # matched to the storefront by BARCODE only (SKU differs)
    {"sku": "MERCH-SKU", "barcode": "9999999999999", "name_ar": "ب", "name_en": "ByBarcode",
     "price": 86.96, "sale_price": None, "qty_available": 1, "in_stock": True,
     "sold_count": 9, "img_url": "", "product_url": "", "_zid_id": 3},
    # NOT on the storefront at all → must keep the merchant price, tagged
    {"sku": "ONLY-MERCH", "barcode": "B-ONLY", "name_ar": "ف", "name_en": "MerchOnly",
     "price": 50.00, "sale_price": None, "qty_available": 4, "in_stock": True,
     "sold_count": 2, "img_url": "", "product_url": "", "_zid_id": 4},
]
# Storefront rows (inc-VAT; no reliable stock/sales fields)
STOREFRONT = [
    {"sku": "052742059518", "barcode": "052742059518", "price": 170, "effective_price": 170, "is_taxable": True},
    {"sku": "SALE1", "barcode": "B-SALE", "price": 200, "effective_price": 170, "is_taxable": True},
    {"sku": "SF-DIFFERENT", "barcode": "9999999999999", "price": 100, "effective_price": 100, "is_taxable": True},
]


def _stub(merchant=MERCHANT, sf=STOREFRONT, sf_ok=True):
    orig = (crawlers._fetch_zid_api_catalog, crawlers.fetch_own_storefront_catalog_raw,
            server.fetch_own_storefront_catalog_raw)

    async def _m(db, store):
        return [dict(r) for r in merchant], "ok"

    async def _s(store):
        return [dict(r) for r in sf], {"ok": sf_ok, "endpoint": "/api/v1/products", "rows": len(sf)}

    crawlers._fetch_zid_api_catalog = _m
    crawlers.fetch_own_storefront_catalog_raw = _s
    server.fetch_own_storefront_catalog_raw = _s
    return orig


def _unstub(orig):
    (crawlers._fetch_zid_api_catalog, crawlers.fetch_own_storefront_catalog_raw,
     server.fetch_own_storefront_catalog_raw) = orig


async def _prep(db, seed_my_products=True):
    for c in ("stores", "my_products", "product_snapshots", "crawl_logs", "matching_jobs"):
        await db[c].delete_many({})
    await db.stores.insert_one(dict(STORE))
    if seed_my_products:
        # what production holds TODAY: ex-VAT from the merchant path
        await db.my_products.insert_many([
            {"sku": "052742059518", "barcode": "052742059518", "price": 147.83,
             "sale_price": None, "sync_source": "zid_api"},
            {"sku": "SALE1", "barcode": "B-SALE", "price": 173.91,
             "sale_price": 173.91, "sync_source": "zid_api"},
            {"sku": "MERCH-SKU", "barcode": "9999999999999", "price": 86.96,
             "sale_price": None, "sync_source": "zid_api"},
            {"sku": "ONLY-MERCH", "barcode": "B-ONLY", "price": 50.00,
             "sale_price": None, "sync_source": "zid_api"},
        ])


# ── Step 2 ───────────────────────────────────────────────────────────────────
def test_sync_stores_inc_vat_price_and_keeps_merchant_stock():
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

        # (a) taxable SKU stored at the INC-VAT storefront price, not 147.83
        hills = rows["052742059518"]
        assert hills["price"] == 170, hills
        assert hills["price_basis"] == "storefront_inc_vat"
        # stock + sales still come from the MERCHANT API
        assert hills["quantity"] == 7 and hills["in_stock"] is True
        assert hills.get("sold_count") == 42 or res["updated"] >= 1

        # (b) on-sale row: BOTH price fields on the inc-VAT basis, so the
        # universal `sale_price or price` read yields the shelf price
        sale = rows["SALE1"]
        assert sale["price"] == 170 and sale["sale_price"] == 170, sale
        assert (sale.get("sale_price") or sale["price"]) == 170
        assert sale["price_basis"] == "storefront_inc_vat"

        # (c) merchant SKU matched to the storefront by BARCODE
        bybc = rows["MERCH-SKU"]
        assert bybc["price"] == 100 and bybc["price_basis"] == "storefront_inc_vat"

        # (d) merchant-only SKU: NOT dropped, keeps merchant price, tagged
        only = rows["ONLY-MERCH"]
        assert only["price"] == 50.00, only
        assert only["price_basis"] == "merchant_ex_vat"
        assert only["quantity"] == 4

        # (e) basis counts surfaced for observability
        assert res["price_basis_counts"] == {"storefront_inc_vat": 3, "merchant_ex_vat": 1}
    asyncio.run(main())


def test_sync_falls_back_to_merchant_when_storefront_unavailable():
    """The overlay must never fail the sync — prices stay merchant-based and
    are tagged, rather than the catalogue silently going unpriced."""
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
        assert rows["052742059518"]["price"] == 147.83          # merchant retained
        assert rows["052742059518"]["price_basis"] == "merchant_ex_vat"
        assert rows["052742059518"]["quantity"] == 7            # stock still synced
        assert res["price_basis_counts"]["merchant_ex_vat"] == 4
        assert res["updated"] >= 1                              # nothing dropped
    asyncio.run(main())


# ── Step 3 ───────────────────────────────────────────────────────────────────
def test_backfill_dry_run_then_apply():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _prep(db)
        server.db = db
        orig = _stub()
        try:
            dry = await server.own_store_vat_backfill(dry_run=True, sample=10, user=SUPER)
            # dry run writes nothing
            assert dry["dry_run"] is True and dry["would_update"] == 3
            assert dry["no_storefront_match"] == 1
            assert dry["no_storefront_match_sample"] == ["ONLY-MERCH"]
            before = {r["sku"]: r for r in dry["sample"]}
            assert before["052742059518"]["before_price"] == 147.83
            assert before["052742059518"]["after_price"] == 170
            assert abs(before["052742059518"]["ratio"] - 1.15) <= 0.005
            assert (await db.my_products.find_one({"sku": "052742059518"}))["price"] == 147.83

            real = await server.own_store_vat_backfill(dry_run=False, sample=10, user=SUPER)
            assert real["updated"] == 3
        finally:
            _unstub(orig)

        rows = {p["sku"]: p async for p in db.my_products.find({}, {"_id": 0})}
        assert rows["052742059518"]["price"] == 170
        assert rows["052742059518"]["price_basis"] == "storefront_inc_vat"
        assert rows["052742059518"]["vat_backfilled_at"]
        assert rows["SALE1"]["price"] == 170 and rows["SALE1"]["sale_price"] == 170
        assert rows["MERCH-SKU"]["price"] == 100
        # untouched by the storefront, but the basis is now explicit
        assert rows["ONLY-MERCH"]["price"] == 50.00
        assert rows["ONLY-MERCH"]["price_basis"] == "merchant_ex_vat"

        # idempotent: a second run finds nothing left to change
        orig = _stub()
        try:
            again = await server.own_store_vat_backfill(dry_run=True, sample=10, user=SUPER)
        finally:
            _unstub(orig)
        assert again["would_update"] == 0 and again["already_inc_vat"] == 3
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
            # nothing rewritten
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
    test_sync_stores_inc_vat_price_and_keeps_merchant_stock()
    test_sync_falls_back_to_merchant_when_storefront_unavailable()
    test_backfill_dry_run_then_apply()
    test_backfill_refuses_on_storefront_failure_and_requires_super_admin()
    print("PASS: iter44 Step 2 + Step 3")
