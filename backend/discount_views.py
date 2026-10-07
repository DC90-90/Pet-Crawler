"""Current discounts belong to specific verified offers, not global SKUs."""
from datetime import datetime, timezone, timedelta
from price_cohort import exclusion
from store_views import latest


async def top(db, days, store_id=None, category=None, limit=30, by_amount=False):
    active = set(await db.stores.distinct("id", {"is_active": {"$ne": False}}))
    candidates = [s for s in await latest(db, store_id) if s["store_id"] in active and exclusion(s) is None]
    rows = []
    for s in candidates:
        price, original = s.get("price"), s.get("original_price")
        if not price or not original or original <= price:
            continue
        metadata = await db.products.find_one({"offer_id": s["offer_id"], "store_id": s["store_id"]}, {"_id": 0}) or {}
        cat = metadata.get("category") if metadata.get("category_source") in ("reviewed", "store_supplied", "import_file") else None
        if category not in (None, "", "all") and cat != category:
            continue
        since = datetime.now(timezone.utc)-timedelta(days=int(days))
        first, count = s["crawled_at"], 0
        async for h in db.product_snapshots.find({"offer_id": s["offer_id"], "crawled_at": {"$gte": since}, "observation_version": 2}, {"_id": 0}).sort("crawled_at", -1):
            if not h.get("comparable") or not h.get("price") or not h.get("original_price") or h["original_price"] <= h["price"]:
                break
            first, count = h["crawled_at"], count+1
        duration = max(0, (datetime.now(timezone.utc)-first.replace(tzinfo=timezone.utc)).days)
        rows.append({**s, "category": cat, "image_url": metadata.get("image_url"),
                     "discount_pct": round((1-price/original)*100, 1), "discount_amount_sar": round(original-price, 2),
                     "sale_price": price, "effective_price": price, "days_on_discount": duration,
                     "duration_days": duration, "started_at": first.isoformat(), "ongoing": True,
                     "snapshots_in_run": count, "duration_is_lower_bound": True, "data_origin": "verified_offer"})
    rows.sort(key=lambda r: r["discount_amount_sar"] if by_amount else r["discount_pct"], reverse=True)
    return rows[:max(1, min(int(limit), 500))]