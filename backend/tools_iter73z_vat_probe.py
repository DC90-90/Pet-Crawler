"""iter73z — temporary probe: a my_products row whose basis is storefront-truth.

Reproduces the client's SKU 3182550702362 shape (563.50 SAR inc-VAT, tagged
`storefront_inc_vat`) so the My Products read path can be checked live: it must
render 563.5, never 648.02 (= 563.5 x 1.15).
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

SKU = "IT73Z-PROBE-3182550702362"


async def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


async def seed():
    db = await _db()
    await clean(db)
    now = datetime.now(timezone.utc)
    await db.products.insert_one({
        "_it73z": True, "sku": SKU, "barcode": "3182550702362",
        "name_ar": "بروب", "name_en": "iter73z probe", "category": "cat_food",
        "brand": "Royal Canin",
    })
    await db.my_products.insert_one({
        "_it73z": True, "sku": SKU, "barcode": "3182550702362",
        "name_ar": "بروب", "name_en": "iter73z probe",
        "price": 563.5, "sale_price": None, "original_price": 563.5,
        "price_basis": "storefront_inc_vat", "quantity": 15, "in_stock": True,
        "last_synced_at": now,
    })
    print(f"seeded my_products row {SKU} price=563.5 basis=storefront_inc_vat")


async def clean(db=None):
    if db is None:
        db = await _db()
    a = await db.my_products.delete_many({"_it73z": True})
    b = await db.products.delete_many({"_it73z": True})
    print(f"cleaned my_products={a.deleted_count} products={b.deleted_count}")


if __name__ == "__main__":
    asyncio.run(clean() if sys.argv[1:] == ["clean"] else seed())
