"""Probe 2 — match keys, brand/category derivation, seller overlap. Read-only."""
import asyncio, os, json
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


async def main():
    cl = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cl[os.environ["DB_NAME"]]
    out = {}
    own = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1, "name": 1})
    out["own_store"] = own
    own_id = own["id"]

    # product_matches shape (real rows)
    out["matches_sample"] = await db.product_matches.find({}, {"_id": 0}).limit(3).to_list(3)
    out["matches_by_method"] = await db.product_matches.aggregate([
        {"$group": {"_id": {"m": "$match_method", "c": "$confidence"}, "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 15},
    ]).to_list(15)
    out["matches_distinct_my_skus"] = len(await db.product_matches.distinct("my_sku"))

    # my_products sku shape: numeric (EAN-as-SKU) vs alnum
    skus = await db.my_products.distinct("sku")
    numeric = [s for s in skus if s and s.isdigit()]
    out["my_skus"] = {"total": len(skus), "numeric": len(numeric),
                      "numeric_len_hist": {}}
    for s in numeric:
        out["my_skus"]["numeric_len_hist"][len(s)] = out["my_skus"]["numeric_len_hist"].get(len(s), 0) + 1

    # how many my_products SKUs appear in competitor snapshots by exact sku
    comp_skus = set(await db.product_snapshots.distinct("sku", {"store_id": {"$ne": own_id}}))
    out["overlap_exact_sku"] = len([s for s in skus if s in comp_skus])
    comp_barcodes = set(x for x in await db.product_snapshots.distinct(
        "barcode", {"store_id": {"$ne": own_id}}) if x)
    out["overlap_sku_as_barcode"] = len([s for s in numeric if s in comp_barcodes])
    out["overlap_union"] = len([s for s in skus if s in comp_skus or s in comp_barcodes])

    # brand/category derivation: are there products docs for own skus?
    sample = numeric[:200]
    out["products_docs_for_my_skus"] = await db.products.count_documents({"sku": {"$in": sample}})
    out["products_with_cat_for_my_skus"] = await db.products.count_documents(
        {"sku": {"$in": sample}, "category": {"$nin": [None, ""]}})
    out["products_field_coverage"] = await db.products.aggregate([
        {"$group": {"_id": None, "n": {"$sum": 1},
                    "name_en": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$name_en", ""]}}, 0]}, 1, 0]}},
                    "name_ar": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$name_ar", ""]}}, 0]}, 1, 0]}},
                    "brand": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$brand", ""]}}, 0]}, 1, 0]}},
                    "category": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$category", ""]}}, 0]}, 1, 0]}},
                    "barcode": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$barcode", ""]}}, 0]}, 1, 0]}}}},
    ]).to_list(3)
    out["top_categories"] = await db.products.aggregate([
        {"$match": {"category": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$category", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}}, {"$limit": 12},
    ]).to_list(12)
    out["distinct_categories"] = len(await db.products.distinct("category"))
    out["distinct_brands"] = len(await db.products.distinct("brand"))

    # snapshot day coverage overall (can we diff at all?)
    out["snapshot_days"] = await db.product_snapshots.aggregate([
        {"$group": {"_id": {"$dateToString": {"date": "$crawled_at", "format": "%Y-%m-%d"}},
                    "n": {"$sum": 1}, "stores": {"$addToSet": "$store_id"}}},
        {"$project": {"n": 1, "n_stores": {"$size": "$stores"}}},
        {"$sort": {"_id": 1}},
    ]).to_list(60)
    out["ledger_days"] = await db.daily_ledger.aggregate([
        {"$group": {"_id": "$ksa_date", "n": {"$sum": 1},
                    "sold_delta": {"$sum": "$sold_delta"},
                    "with_sold_cum": {"$sum": {"$cond": [{"$gt": ["$sold_count_cumulative", 0]}, 1, 0]}}}},
        {"$sort": {"_id": 1}},
    ]).to_list(60)
    l = await db.daily_ledger.find_one({"store_id": {"$ne": "own"}}, {"_id": 0})
    out["ledger_competitor_sample"] = {k: str(v)[:40] for k, v in (l or {}).items()}
    out["test_store"] = await db.stores.find_one({"name": "Test Store"}, {"_id": 0})
    print(json.dumps(out, indent=1, default=str))
    cl.close()


asyncio.run(main())
