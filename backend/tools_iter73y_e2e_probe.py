"""iter73y — temporary E2E probe: seed one product's snapshots, hit the live
product-detail endpoint, then clean up. Run with the backend already up.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

SKU = "IT73Y-PROBE-052742024363"
BARCODE = "052742024363"


async def seed():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc)
    await cleanup(db)
    await db.products.insert_one({
        "sku": SKU, "barcode": BARCODE, "name_ar": "بروب", "name_en": "iter73y probe",
        "category": "cat", "brand": "Probe", "_it73y": True,
    })
    stores = await db.stores.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(5)
    rows = []
    for i, st in enumerate(stores[:3]):
        for d in range(0, 20):
            rows.append({
                "_it73y": True, "store_id": st["id"], "store_name": st["name"],
                "sku": SKU if i == 0 else f"S-probe-{i}",
                "barcode": BARCODE if i == 1 else "",
                "variant_skus": [BARCODE] if i == 2 else [],
                "variant_barcodes": [BARCODE, "052742024370"] if i == 2 else [],
                "price": 100.0 + i * 10 + d, "original_price": 130.0,
                "discount_pct": 0, "qty_available": 20 - d, "in_stock": True,
                "source_tier": 1, "confidence_score": 95,
                "product_url": f"https://example.com/{i}",
                "crawled_at": now - timedelta(days=d),
            })
    await db.product_snapshots.insert_many(rows)
    print(f"seeded {len(rows)} snapshots across {min(3, len(stores))} stores for {SKU}")


async def cleanup(db=None):
    if db is None:
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    r1 = await db.product_snapshots.delete_many({"_it73y": True})
    r2 = await db.products.delete_many({"_it73y": True})
    print(f"cleaned snapshots={r1.deleted_count} products={r2.deleted_count}")


if __name__ == "__main__":
    asyncio.run(cleanup() if sys.argv[1:] == ["clean"] else seed())
