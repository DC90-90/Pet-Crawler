"""iter44 Step-1 — own-store VAT-basis audit endpoint (read-only).

The endpoint itself needs live network (Zid Merchant API + our storefront), so
here both fetchers are stubbed with a controlled catalogue that contains every
shape the real audit must classify:

  A, B  taxable, storefront = merchant x 1.15   -> vat_15 bucket
  F     non-taxable, storefront == merchant     -> parity bucket
  G     on sale: price 200 / effective 170      -> divergence + non-1.15 ratio
  C     merchant-only, no barcode in storefront  -> truly absent
  D     merchant-only BUT barcode present in SF  -> recoverable by barcode
  E     storefront-only

Asserts the four Step-1 answers and that the endpoint writes nothing.
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
os.environ["DB_NAME"] = "test_price_audit"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_price_audit"
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}

MERCHANT = [
    {"sku": "A", "barcode": "111", "price": 147.83},
    {"sku": "B", "barcode": "222", "price": 86.96},
    {"sku": "F", "barcode": "333", "price": 60.00},
    {"sku": "G", "barcode": "444", "price": 173.91},
    {"sku": "C", "barcode": "555", "price": 50.00},
    {"sku": "D", "barcode": "1234567890123", "price": 25.00},
]
STOREFRONT = [
    {"sku": "A", "barcode": "111", "price": 170, "effective_price": 170, "is_taxable": True},
    {"sku": "B", "barcode": "222", "price": 100, "effective_price": 100, "is_taxable": True},
    {"sku": "F", "barcode": "333", "price": 60, "effective_price": 60, "is_taxable": False},
    # on sale: shelf price is effective_price (170), list price is 200
    {"sku": "G", "barcode": "444", "price": 200, "effective_price": 170, "is_taxable": True},
    {"sku": "E", "barcode": "1234567890123", "price": 33, "effective_price": 33, "is_taxable": True},
]


def _stub(monkey_merchant=MERCHANT, monkey_sf=STOREFRONT):
    orig = (server._fetch_zid_api_catalog, server.fetch_own_storefront_catalog_raw)

    async def _m(db, store):
        return list(monkey_merchant), "ok"

    async def _s(store):
        return list(monkey_sf), {"ok": True, "endpoint": "/api/v1/products", "rows": len(monkey_sf)}

    server._fetch_zid_api_catalog = _m
    server.fetch_own_storefront_catalog_raw = _s
    return orig


async def _prep(db):
    for c in ("stores", "my_products"):
        await db[c].delete_many({})
    await db.stores.insert_one({"id": "own", "name": "Pets Houses", "domain": "pets-houses.com",
                                "platform": "zid", "is_own_store": True})
    # what is stored TODAY (ex-VAT, from the merchant path) — the audit echoes it
    await db.my_products.insert_many([
        {"sku": "A", "price": 147.83, "sync_source": "zid_api"},
        {"sku": "B", "price": 86.96, "sync_source": "zid_api"},
    ])


def test_audit_answers_all_four_step1_questions():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _prep(db)
        server.db = db
        orig = _stub()
        try:
            out = await server.own_store_price_audit(sample=20, user=SUPER)
        finally:
            server._fetch_zid_api_catalog, server.fetch_own_storefront_catalog_raw = orig

        # ── Q1 coverage, both directions ──
        q1 = out["q1_coverage"]
        assert q1["in_both"] == 4, q1                     # A, B, F, G
        assert q1["merchant_only"] == 2, q1               # C, D
        assert q1["merchant_only_recoverable_by_barcode"] == 1, q1   # D via barcode
        assert q1["merchant_only_truly_absent"] == 1, q1             # C
        assert q1["storefront_only"] == 1, q1             # E
        assert set(q1["merchant_only_sample"]) == {"C", "D"}

        # ── Q2 ratio distribution ──
        q2 = out["q2_ratio_distribution"]
        assert q2["vat_15"] == 2, q2                      # A, B
        assert q2["parity"] == 1, q2                      # F (non-taxable)
        assert q2["other"] == 1, q2                       # G (on sale)
        assert q2["unusable"] == 0, q2
        by_sku = {r["sku"]: r for r in out["q2_sample"]}
        assert by_sku["A"]["ratio"] == round(170 / 147.83, 4)
        assert abs(by_sku["A"]["ratio"] - 1.15) <= 0.005
        assert by_sku["A"]["shelf_price"] == 170 and by_sku["A"]["is_taxable"] is True
        assert by_sku["A"]["stored_now"] == 147.83 and by_sku["A"]["stored_sync_source"] == "zid_api"
        assert by_sku["F"]["is_taxable"] is False and abs(by_sku["F"]["ratio"] - 1.0) <= 0.005
        # the non-1.15 row is surfaced for inspection rather than hidden
        assert [r["sku"] for r in out["q2_other_samples"]] == ["G"]

        # ── Q3 price vs effective_price ──
        q3 = out["q3_price_vs_effective"]
        assert q3["diverging_count"] == 1, q3
        assert q3["samples"][0]["sku"] == "G"
        assert q3["samples"][0]["lower_field"] == "effective_price"
        assert q3["samples"][0]["shelf_price"] == 170          # sale price wins

        # ── Q4 completeness ──
        q4 = out["q4_completeness"]
        assert q4["storefront_rows"] == 5 and q4["storefront_distinct_skus"] == 5
        assert q4["storefront_rows_with_usable_price"] == 5
        assert q4["storefront_priced_pct"] == 100.0
        assert q4["merchant_rows"] == 6 and q4["merchant_status"] == "ok"
        assert q4["storefront_fetch"]["ok"] is True

        # ── read-only: nothing written ──
        assert await db.my_products.count_documents({}) == 2
        assert (await db.my_products.find_one({"sku": "A"}))["price"] == 147.83
    asyncio.run(main())


def test_audit_flags_partial_storefront_and_requires_super_admin():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _prep(db)
        server.db = db
        # a storefront row with no usable price must lower the priced_pct so a
        # partial/blocked fetch can't silently pass Step 1
        partial = STOREFRONT + [{"sku": "H", "barcode": "999", "price": 0, "effective_price": 0}]
        orig = _stub(monkey_sf=partial)
        try:
            out = await server.own_store_price_audit(sample=5, user=SUPER)
            assert out["q4_completeness"]["storefront_rows"] == 6
            assert out["q4_completeness"]["storefront_rows_with_usable_price"] == 5
            assert out["q4_completeness"]["storefront_priced_pct"] < 100.0
            assert len(out["q2_sample"]) <= 5                    # sample cap respected
            try:
                await server.own_store_price_audit(sample=5, user={"role": "viewer", "email": "v@v"})
                raise AssertionError("viewer must be rejected")
            except HTTPException as e:
                assert e.status_code == 403
        finally:
            server._fetch_zid_api_catalog, server.fetch_own_storefront_catalog_raw = orig
    asyncio.run(main())


if __name__ == "__main__":
    test_audit_answers_all_four_step1_questions()
    test_audit_flags_partial_storefront_and_requires_super_admin()
    print("PASS: iter44 Step-1 audit")
