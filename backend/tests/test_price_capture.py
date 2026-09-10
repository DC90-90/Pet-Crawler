"""iter35 — effective/sale/original price capture in _normalize_raw_product.

Root cause of the production price bug (confirmed case: Lana Pets Brit Care 7kg
showing 279 instead of the live 237.02): Salla defines sales PER VARIANT —
skus[].price is the variant's CURRENT price and skus[].regular_price the
pre-sale price — while the old normalizer read root-level fields only, AND took
the barcode from a variant but the price from the root. These tests pin the new
semantics for every platform shape, plus a FerretDB integration proving
sale_price/discount_pct land on the snapshot.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_price_capture"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_price_capture"
from crawlers import _normalize_raw_product, _price_amount, process_crawled_products  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")


def _amt(x):
    return {"amount": x, "currency": "SAR"}


def test_price_amount_coercion():
    assert _price_amount({"amount": 237.02}) == 237.02
    assert _price_amount({"amount": None}) == 0.0
    assert _price_amount({"title": None}) == 0.0     # promotion-shaped dict
    assert _price_amount(142.44) == 142.44
    assert _price_amount("79.5") == 79.5
    assert _price_amount(None) == 0.0
    assert _price_amount("") == 0.0
    assert _price_amount("abc") == 0.0


def test_salla_variant_level_sale_the_lana_case():
    """The confirmed production case: root shows the regular 279 with no root
    sale; the matched-barcode variant carries the live sale 237.02."""
    raw = {
        "id": 111, "sku": "", "name": "Brit Care Grain-Free Hair Care",
        "price": _amt(279), "sale_price": _amt(0), "regular_price": _amt(279),
        "quantity": "4", "status": "sale",
        "skus": [
            {"barcode": "8595602540860", "price": _amt(45), "sale_price": _amt(45), "regular_price": _amt(0)},
            # NOT first in the list — selection must follow the matched barcode
        ],
    }
    # make the 7kg variant the FIRST EAN-carrying entry to mirror matching
    raw["skus"].insert(0, {"barcode": "8595602540877", "price": _amt(237.02),
                           "sale_price": _amt(237.02), "regular_price": _amt(279)})
    n = _normalize_raw_product(raw, "LanaPets")
    assert n["barcode"] == "8595602540877"
    assert n["price"] == 237.02          # effective — was 279 before the fix
    assert n["original_price"] == 279
    assert n["sale_price"] == 237.02


def test_salla_root_on_sale_price_already_effective():
    # Salla convention on single-variant items: price is ALREADY discounted,
    # regular_price holds the pre-sale price, sale_price mirrors price.
    raw = {"id": 1, "sku": "X1", "name": "P", "price": _amt(237.02),
           "sale_price": _amt(237.02), "regular_price": _amt(279), "quantity": "9"}
    n = _normalize_raw_product(raw, "S")
    assert n["price"] == 237.02 and n["original_price"] == 279 and n["sale_price"] == 237.02


def test_salla_no_sale():
    raw = {"id": 2, "sku": "X2", "name": "P", "price": _amt(100),
           "sale_price": _amt(0), "regular_price": _amt(100), "quantity": "5"}
    n = _normalize_raw_product(raw, "S")
    assert n["price"] == 100 and n["original_price"] == 100 and n["sale_price"] is None


def test_salla_variant_mirror_prices_no_regular():
    # Real Salla shape from the API reference: variant price 79 / sale 79 /
    # regular 0 → no discount signal, price 79.
    raw = {"id": 3, "sku": "", "name": "P", "price": _amt(100), "sale_price": _amt(0),
           "skus": [{"barcode": "45344432343", "price": _amt(79),
                     "sale_price": _amt(79), "regular_price": _amt(0)}]}
    n = _normalize_raw_product(raw, "S")
    assert n["barcode"] == "45344432343"
    assert n["price"] == 79 and n["original_price"] == 79 and n["sale_price"] is None


def test_zid_number_prices_on_sale():
    raw = {"id": 4, "sku": "Z1", "name": {"en": "P"}, "price": 279.0,
           "sale_price": 237.02, "barcode": "3182550702973", "quantity": 3}
    n = _normalize_raw_product(raw, "Z")
    assert n["price"] == 237.02 and n["original_price"] == 279.0 and n["sale_price"] == 237.02


def test_zid_null_sale_price():
    raw = {"id": 5, "sku": "Z2", "name": {"en": "P"}, "price": 142.44,
           "sale_price": None, "quantity": None, "is_infinite": True}
    n = _normalize_raw_product(raw, "Z")
    assert n["price"] == 142.44 and n["original_price"] == 142.44 and n["sale_price"] is None


def test_promotion_null_does_not_crash():
    # Salla sometimes returns promotion: null — the old code raised
    # AttributeError ((raw.get("promotion", {}) returned None).get(...)).
    raw = {"id": 6, "sku": "X6", "name": "P", "price": _amt(50), "promotion": None}
    n = _normalize_raw_product(raw, "S")
    assert n["price"] == 50 and n["sale_price"] is None


def test_promotion_price_fallback():
    raw = {"id": 7, "sku": "X7", "name": "P", "price": 60.0,
           "promotion": {"price": 45.0}}
    n = _normalize_raw_product(raw, "S")
    assert n["price"] == 45.0 and n["original_price"] == 60.0 and n["sale_price"] == 45.0


def test_mowkly_special_price_fallback():
    raw = {"id": 8, "sku": "M1", "name": "P", "price": 80.0, "special_price": 64.0}
    n = _normalize_raw_product(raw, "Mowkly")
    assert n["price"] == 64.0 and n["original_price"] == 80.0 and n["sale_price"] == 64.0


def test_bogus_regular_below_price_makes_no_fake_discount():
    raw = {"id": 9, "sku": "X9", "name": "P", "price": _amt(100),
           "regular_price": _amt(50)}
    n = _normalize_raw_product(raw, "S")
    assert n["price"] == 100 and n["original_price"] == 100 and n["sale_price"] is None


def test_variant_without_price_falls_back_to_root():
    # A variant carrying the barcode but no usable price must not zero the item.
    raw = {"id": 10, "sku": "", "name": "P", "price": _amt(120), "sale_price": _amt(96),
           "skus": [{"barcode": "12345678", "price": _amt(0)}]}
    n = _normalize_raw_product(raw, "S")
    assert n["barcode"] == "12345678"
    assert n["price"] == 96 and n["original_price"] == 120 and n["sale_price"] == 96


def test_snapshot_carries_sale_price_and_discount():
    """Integration on real Mongo: process_crawled_products persists the new
    sale_price field and a REAL discount_pct for a Salla variant-level sale."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        for c in ("product_snapshots", "products"):
            await db[c].delete_many({})
        store = {"id": "lana-pets-001", "name": "LanaPets", "domain": "lanapets.com"}
        raw = {
            "id": 111, "sku": "BRIT-7KG", "name": "Brit Care 7kg",
            "price": _amt(279), "sale_price": _amt(0), "regular_price": _amt(279),
            "quantity": "4", "status": "sale",
            "skus": [{"barcode": "8595602540877", "price": _amt(237.02),
                      "sale_price": _amt(237.02), "regular_price": _amt(279)}],
        }
        await process_crawled_products(db, store, [raw], datetime.now(timezone.utc))
        snap = await db.product_snapshots.find_one({"store_id": "lana-pets-001"}, {"_id": 0})
        assert snap["price"] == 237.02, snap
        assert snap["original_price"] == 279
        assert snap["sale_price"] == 237.02
        assert snap["discount_pct"] == 15          # round((1-237.02/279)*100)
    asyncio.run(main())


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("PASS: iter35 price capture semantics")
