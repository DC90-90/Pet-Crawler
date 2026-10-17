"""Data-trust views (17 Oct 2026): what Daleel can see in each store, and the
product matches that need a human decision.

coverage(): per tracked store — catalogue size, images, the last crawl and
the last 7 days of crawl outcomes, freshness of its newest observation, and
how many of the last 30 sealed days its sales were measured.

matches_to_review(): own products whose price is far from every seller of the
same barcode (identity_check) or whose sellers' prices differ more than
SPREAD_RATIO times — usually a wrong barcode or a pack-size mismatch. Each
comes with the competitor offers so the owner can confirm or reject one.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

SPREAD_RATIO = 2.0
OK_CRAWL = ("complete", "done")


async def coverage(db):
    import ledger_sales
    now = datetime.now(timezone.utc)
    stores = await db.stores.find({}, {"_id": 0, "id": 1, "name": 1, "domain": 1, "platform": 1, "is_active": 1,
                                       "is_own_store": 1}).to_list(200)
    counts = {r["_id"]: r async for r in db.products.aggregate([
        {"$group": {"_id": "$store_id", "products": {"$sum": 1},
                    "with_image": {"$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": [
                        {"$cond": [{"$eq": [{"$type": "$image_url"}, "string"]}, "$image_url", ""]}, ""]}}, 8]}, 1, 0]}}}}])}
    attempts = defaultdict(list)
    async for a in db.crawl_attempts.find({"started_at": {"$gte": now - timedelta(days=7)},
                                           "status": {"$ne": "deferred"}},
                                          {"_id": 0, "store_id": 1, "started_at": 1, "status": 1, "products_found": 1,
                                           "snapshots_created": 1, "trigger": 1}).sort("started_at", -1):
        attempts[a["store_id"]].append(a)
    meta = await ledger_sales.meta(db)
    measured = {}
    if meta.get("build"):
        lo = (now - timedelta(days=31)).strftime("%Y-%m-%d")
        async for r in db.ledger_sales_daily.aggregate([
                {"$match": {"build": meta["build"], "date": {"$gte": lo}}},
                {"$group": {"_id": "$store_id", "days": {"$addToSet": "$date"}}}]):
            measured[r["_id"]] = len(r["days"])
    rows = []
    for s in stores:
        c = counts.get(s["id"], {})
        tries = attempts.get(s["id"], [])
        last = tries[0] if tries else None
        ok = [t for t in tries if t.get("status") in OK_CRAWL]
        rows.append({
            "store_id": s["id"], "name": s.get("name"), "domain": s.get("domain"), "platform": s.get("platform"),
            "active": s.get("is_active") is not False, "own": bool(s.get("is_own_store")),
            "products": c.get("products", 0),
            "image_pct": round(c.get("with_image", 0) / c["products"] * 100) if c.get("products") else None,
            "last_crawl": last and {"at": last["started_at"], "status": last.get("status"),
                                    "found": last.get("products_found"), "saved": last.get("snapshots_created")},
            "crawls_7d": {"total": len(tries), "complete": len(ok),
                          "partial": sum(t.get("status") == "partial" for t in tries),
                          "cut_off": sum(t.get("status") in ("cut_off_by_restart", "running") and t is not last for t in tries),
                          "failed": sum(t.get("status") in ("failed", "timed_out", "empty") for t in tries)},
            "sales_measured_days_30": measured.get(s["id"], 0),
            "sales_method": ("stock levels" if s.get("platform") == "zid" else
                             "public sold counter" if measured.get(s["id"]) else "not published by the store"),
        })
    rows.sort(key=lambda r: (not r["own"], not r["active"], r["name"] or ""))
    return {"stores": rows, "ledger_build": meta.get("build"), "computed_at": now.isoformat()}


async def matches_to_review(db, price_fn):
    from comparison_views import context
    from catalog_views import identity_check
    own, products, cohorts = await context(db, price_fn)
    rows = []
    for mp in products:
        sku, price = mp.get("sku"), price_fn(mp)
        c = cohorts.get(sku) or {}
        sellers = c.get("sellers") or []
        if not sku or not price or not sellers:
            continue
        flag = identity_check(price, c)
        prices = [s["price"] for s in sellers if s.get("price")]
        spread = max(prices) / min(prices) if len(prices) >= 2 and min(prices) > 0 else 1.0
        if not flag and spread < SPREAD_RATIO:
            continue
        rows.append({"sku": sku, "name_ar": mp.get("name_ar"), "name_en": mp.get("name_en"), "barcode": mp.get("barcode"),
                     "image_url": mp.get("image_url"), "my_price": price,
                     "reason": flag or "sellers_prices_differ_" + f"{spread:.1f}x",
                     "offers": [{"store_id": s["store_id"], "store_name": s.get("store_name"), "price": s.get("price"),
                                 "name": s.get("name_ar") or s.get("name_en"), "sku": s.get("sku"),
                                 "offer_id": s.get("offer_id"), "url": s.get("product_url"),
                                 "ratio_to_mine": round(s["price"] / price, 2) if s.get("price") else None}
                                for s in sellers]})
    rows.sort(key=lambda r: -max(abs((o["ratio_to_mine"] or 1) - 1) for o in r["offers"]))
    return {"rows": rows, "total": len(rows)}
