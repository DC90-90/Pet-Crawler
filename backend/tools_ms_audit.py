"""One-off read-only audit of the data sources a Market Share tab would need."""
import asyncio, os, json
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


async def main():
    cl = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cl[os.environ["DB_NAME"]]
    out = {}
    out["collections"] = sorted(await db.list_collection_names())
    stores = await db.stores.find({}, {"_id": 0, "store_id": 1, "name": 1, "platform": 1,
                                       "is_own_store": 1, "is_active": 1,
                                       "last_crawl_status": 1, "product_count": 1}).to_list(100)
    out["stores"] = stores
    counts = {}
    for c in ["product_snapshots", "my_products", "products", "product_matches",
              "sku_sales_daily", "sku_store_coverage", "metric_daily_rollups",
              "daily_ledger", "daily_ledger_store", "own_orders", "orders",
              "zid_orders", "archive_files", "crawl_logs"]:
        if c in out["collections"]:
            counts[c] = await db[c].estimated_document_count()
    out["counts"] = counts

    now = datetime.now(timezone.utc)
    since30 = now - timedelta(days=30)

    # sales rollups per store, 30d
    out["sku_sales_daily_30d"] = await db.sku_sales_daily.aggregate([
        {"$match": {"date": {"$gte": since30.strftime("%Y-%m-%d")}}},
        {"$group": {"_id": "$store_id", "rows": {"$sum": 1},
                    "units_sold": {"$sum": "$units_sold"}, "units_qty": {"$sum": "$units_qty"},
                    "rev_sold": {"$sum": "$rev_sold"}, "rev_qty": {"$sum": "$rev_qty"},
                    "skus": {"$addToSet": "$sku"}}},
        {"$project": {"rows": 1, "units_sold": 1, "units_qty": 1, "rev_sold": 1,
                      "rev_qty": 1, "n_skus": {"$size": "$skus"}}},
    ]).to_list(100)

    # sold_count presence (Salla badge / Zid counter) per store in 30d snapshots
    out["sold_count_30d"] = await db.product_snapshots.aggregate([
        {"$match": {"crawled_at": {"$gte": since30}}},
        {"$group": {"_id": "$store_id", "snaps": {"$sum": 1},
                    "with_sold_pos": {"$sum": {"$cond": [{"$gt": ["$sold_count", 0]}, 1, 0]}},
                    "with_sold_field": {"$sum": {"$cond": [{"$ne": ["$sold_count", None]}, 1, 0]}},
                    "with_barcode": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$barcode", ""]}}, 0]}, 1, 0]}},
                    "with_qty": {"$sum": {"$cond": [{"$gt": ["$qty_available", 0]}, 1, 0]}},
                    "distinct_days": {"$addToSet": {"$dateToString": {"date": "$crawled_at", "format": "%Y-%m-%d"}}}}},
        {"$project": {"snaps": 1, "with_sold_pos": 1, "with_sold_field": 1,
                      "with_barcode": 1, "with_qty": 1, "n_days": {"$size": "$distinct_days"}}},
    ]).to_list(100)

    # brand / category coverage
    out["products_brand_cov"] = await db.products.aggregate([
        {"$group": {"_id": None, "n": {"$sum": 1},
                    "with_brand": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$brand", ""]}}, 0]}, 1, 0]}},
                    "with_cat": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$category", ""]}}, 0]}, 1, 0]}}}},
    ]).to_list(5)
    out["my_products_brand_cov"] = await db.my_products.aggregate([
        {"$group": {"_id": None, "n": {"$sum": 1},
                    "with_brand": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$brand", ""]}}, 0]}, 1, 0]}},
                    "with_cat": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$category", ""]}}, 0]}, 1, 0]}},
                    "with_barcode": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$barcode", ""]}}, 0]}, 1, 0]}}}},
    ]).to_list(5)

    # snapshot doc shape
    s = await db.product_snapshots.find_one({}, {"_id": 0})
    out["snapshot_sample_keys"] = sorted((s or {}).keys())
    mp = await db.my_products.find_one({}, {"_id": 0})
    out["my_product_sample_keys"] = sorted((mp or {}).keys())
    pm = await db.product_matches.find_one({}, {"_id": 0})
    out["product_match_sample"] = {k: str(v)[:60] for k, v in (pm or {}).items()}
    p = await db.products.find_one({}, {"_id": 0})
    out["products_sample_keys"] = sorted((p or {}).keys())

    # ledger
    if "daily_ledger" in out["collections"]:
        l = await db.daily_ledger.find_one({}, {"_id": 0})
        out["daily_ledger_sample"] = {k: str(v)[:40] for k, v in (l or {}).items()}
        out["daily_ledger_30d"] = await db.daily_ledger.aggregate([
            {"$match": {"ksa_date": {"$gte": since30.strftime("%Y-%m-%d")}}},
            {"$group": {"_id": "$store_id", "rows": {"$sum": 1},
                        "sold_delta": {"$sum": "$sold_delta"}}},
        ]).to_list(100)

    # own store orders collection detection
    for c in out["collections"]:
        if "order" in c:
            d = await db[c].find_one({}, {"_id": 0})
            out.setdefault("order_collections", {})[c] = {
                "count": await db[c].estimated_document_count(),
                "sample_keys": sorted((d or {}).keys()),
            }

    print(json.dumps(out, indent=1, default=str))
    cl.close()


asyncio.run(main())
