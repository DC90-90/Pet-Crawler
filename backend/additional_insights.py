"""Secondary tabs must not bypass verified offer identity or null semantics."""
from datetime import datetime, timezone, timedelta
from comparison_views import context
from price_cohort import identity_keys, exclusion
from store_views import latest
from evidence_ledger import sales_map
import ledger


async def prices(db, price_fn, mode):
    own, products, cohorts = await context(db, price_fn)
    result = []
    for p in products:
        c = cohorts.get(p.get("sku"))
        if not c:
            continue
        base = {"sku": p["sku"], "name_ar": p.get("name_ar"), "name_en": p.get("name_en"), "cohort_id": c["cohort_id"]}
        if mode == "wars" and len(c["sellers"]) >= 2 and c["max"] > c["min"]:
            result.append({**base, "spread_sar": round(c["max"]-c["min"], 2), "spread_pct": round((c["max"]-c["min"])/c["min"]*100, 1),
                           "prices": [{"store": r["store_name"], "price": r["price"]} for r in c["sellers"]]})
        elif mode == "restock" and c["sellers"]:
            oos = [r for r in c["excluded"] if r.get("excluded_reason") == "out_of_stock"]
            if oos:
                result.append({**base, "oos_stores": [r["store_name"] for r in oos], "oos_count": len(oos),
                               "in_stock_stores": [{"store": r["store_name"], "qty": r.get("qty_available")} for r in c["sellers"]]})
    return result


async def gaps(db):
    own = await db.my_products.find({}, {"_id": 0, "sku": 1, "barcode": 1}).to_list(50000)
    keys = set().union(*(identity_keys(p) for p in own)) if own else set()
    grouped = {}
    active = set(await db.stores.distinct("id", {"is_active": {"$ne": False}, "is_own_store": {"$ne": True}}))
    for row in await latest(db):
        codes = identity_keys(row)
        if row["store_id"] not in active or exclusion(row) or not codes or codes & keys:
            continue
        key = sorted(codes)[0]
        g = grouped.setdefault(key, {"sku": row["sku"], "name_ar": row.get("name_ar"), "name_en": row.get("name_en"), "stores": set()})
        g["stores"].add(row["store_id"])
    return [{"sku": g["sku"], "name_ar": g["name_ar"], "name_en": g["name_en"], "category": None,
             "num_stores": len(g["stores"]), "missing_count": None, "opportunity_score": None, "basis": "not_in_saved_catalog"} for g in grouped.values()]


async def categories(db, days):
    start, end = ledger.sealed_ksa_window(days)
    signals = await sales_map(db, start, end)
    observations = {s["offer_id"]: s for s in await latest(db)}
    metadata = {p["offer_id"]: p async for p in db.products.find({"offer_id": {"$exists": True}}, {"_id": 0, "offer_id": 1, "category": 1, "category_source": 1})}
    out = {}
    for (sid, oid), value in signals.items():
        if not value["units"]:
            continue
        p, s = metadata.get(oid, {}), observations.get(oid, {})
        category = p.get("category") if p.get("category_source") in ("reviewed", "store_supplied", "import_file") else "Unclassified"
        g = out.setdefault(category, {"category": category, "total_sales": 0, "top_products": [], "basis": "inventory_proxy"})
        g["total_sales"] += value["units"]
        g["top_products"].append({"sku": value["sku"], "name_ar": s.get("name_ar"), "name_en": s.get("name_en"), "units_sold": value["units"]})
    for row in out.values():
        row["top_products"] = sorted(row["top_products"], key=lambda p: -p["units_sold"])[:5]
    return sorted(out.values(), key=lambda r: -r["total_sales"])