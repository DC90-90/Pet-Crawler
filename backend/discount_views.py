"""Current discounts belong to specific verified offers, not global SKUs."""
from datetime import datetime, timezone, timedelta
from price_cohort import exclusion, FIELDS
from store_views import latest
import category_map

# A current discount is a current price: every tracked store is crawled daily.
# Reading 30 days of latest offers took >10 s on production, past the
# connection's 10 s operation limit, and the Discounts page failed (15 Oct 2026).
CURRENT_DAYS = 7
META_BATCH = 1000
PROJECTION = {**FIELDS, "original_price": 1, "sale_price": 1, "discount_pct": 1, "image_url": 1}


async def top(db, days, store_id=None, category=None, limit=30, by_amount=False):
    active = await db.stores.distinct("id", {"is_active": {"$ne": False}})
    limit = max(1, min(int(limit), 500))
    candidates = []
    # One compact read per store: a single all-store latest-per-offer read
    # sorted whole snapshot documents for >10 s, past the connection's
    # operation limit (15 Oct 2026). Per store it is ~0.1-0.3 s on the
    # (store_id, crawled_at) index, with a projection.
    for sid in ([store_id] if store_id else active):
        if sid not in active:
            continue
        for s in await latest(db, sid, days=CURRENT_DAYS, projection=PROJECTION):
            price, original = s.get("price"), s.get("original_price")
            if exclusion(s) is None and price and original and original > price:
                candidates.append(s)

    # Catalogue metadata in batches, not one query per offer.
    meta = {}
    offer_ids = [s["offer_id"] for s in candidates]
    for i in range(0, len(offer_ids), META_BATCH):
        async for m in db.products.find({"offer_id": {"$in": offer_ids[i:i + META_BATCH]}},
                                        {"_id": 0, "offer_id": 1, "store_id": 1, "category": 1,
                                         "category_source": 1, "image_url": 1}):
            meta[(m.get("offer_id"), m.get("store_id"))] = m

    rows = []
    for s in candidates:
        metadata = meta.get((s["offer_id"], s["store_id"]), {})
        cat = metadata.get("category") if metadata.get("category_source") in ("reviewed", "store_supplied", "import_file") else None
        if category not in (None, "", "all") and cat != category:
            continue
        price, original = s["price"], s["original_price"]
        rows.append({**s, "category": cat, "image_url": metadata.get("image_url"),
                     "discount_pct": round((1-price/original)*100, 1), "discount_amount_sar": round(original-price, 2),
                     "sale_price": price, "effective_price": price, "ongoing": True,
                     "duration_is_lower_bound": True, "data_origin": "verified_offer",
                     **category_map.facets(cat, s.get("name_ar"), s.get("name_en"))})
    rows.sort(key=lambda r: r["discount_amount_sar"] if by_amount else r["discount_pct"], reverse=True)
    rows = rows[:limit]

    # How long each shown discount has run: only for the rows returned.
    since = datetime.now(timezone.utc)-timedelta(days=int(days))
    for r in rows:
        first, count = r["crawled_at"], 0
        async for h in db.product_snapshots.find(
                # store_id first: rides the (store_id, offer_id, crawled_at) index.
                {"store_id": r["store_id"], "offer_id": r["offer_id"], "crawled_at": {"$gte": since}, "observation_version": 2},
                {"_id": 0, "comparable": 1, "price": 1, "original_price": 1, "crawled_at": 1}).sort("crawled_at", -1):
            if not h.get("comparable") or not h.get("price") or not h.get("original_price") or h["original_price"] <= h["price"]:
                break
            first, count = h["crawled_at"], count+1
        duration = max(0, (datetime.now(timezone.utc)-first.replace(tzinfo=timezone.utc)).days)
        r.update(days_on_discount=duration, duration_days=duration, started_at=first.isoformat(), snapshots_in_run=count)
    return rows
