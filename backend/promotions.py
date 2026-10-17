"""Promotions calendar (17 Oct 2026): when each store runs sales, how deep and
how long, from the sealed daily ledger (one closing row per product per day,
with its on_sale flag and discount).

daily      per store and day: products read, products on sale, share on sale,
           average discount of the products on sale
campaigns  runs of days where a store's share on sale stood clearly above its
           own usual level (median): CAMPAIGN_RATIO x the median and at least
           CAMPAIGN_MIN_POINTS percentage points above it, merged across gaps
           of one day; with start, end, peak and average depth
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

CAMPAIGN_RATIO = 1.5
CAMPAIGN_MIN_POINTS = 5.0
MIN_PRODUCTS_READ = 50          # a day with fewer readings (partial crawl) is not a signal


def detect_campaigns(days):
    """days: [{"date", "share_pct", "on_sale", "avg_discount_pct"}] for one store, sorted."""
    usable = [d for d in days if d["read"] >= MIN_PRODUCTS_READ]
    if len(usable) < 7:
        return [], None
    base = median(d["share_pct"] for d in usable)
    threshold = max(base * CAMPAIGN_RATIO, base + CAMPAIGN_MIN_POINTS)
    hot = [d for d in usable if d["share_pct"] >= threshold]
    campaigns, cur = [], None
    for d in hot:
        day = datetime.fromisoformat(d["date"])
        if cur and (day - datetime.fromisoformat(cur["end"])).days <= 2:
            cur["end"] = d["date"]
            cur["days"].append(d)
        else:
            cur = {"start": d["date"], "end": d["date"], "days": [d]}
            campaigns.append(cur)
    out = []
    for c in campaigns:
        ds = c.pop("days")
        out.append({**c, "length_days": (datetime.fromisoformat(c["end"]) - datetime.fromisoformat(c["start"])).days + 1,
                    "peak_on_sale": max(d["on_sale"] for d in ds), "peak_share_pct": max(d["share_pct"] for d in ds),
                    "avg_discount_pct": round(sum(d["avg_discount_pct"] or 0 for d in ds) / len(ds), 1)})
    return out, round(base, 1)


async def calendar(db, days=90):
    now = datetime.now(timezone.utc)
    lo = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    names = {s["id"]: s.get("name") async for s in db.stores.find({}, {"_id": 0, "id": 1, "name": 1})}
    per = defaultdict(list)
    async for r in db.daily_ledger.aggregate([
            {"$match": {"ksa_date": {"$gte": lo}, "sealed_at": {"$ne": None}}},
            {"$group": {"_id": {"s": "$store_id", "d": "$ksa_date"}, "read": {"$sum": 1},
                        "on_sale": {"$sum": {"$cond": [{"$eq": ["$on_sale", True]}, 1, 0]}},
                        "disc": {"$avg": {"$cond": [{"$eq": ["$on_sale", True]}, "$discount_pct", None]}}}}],
            allowDiskUse=True):
        per[r["_id"]["s"]].append({"date": r["_id"]["d"], "read": r["read"], "on_sale": r["on_sale"],
                                   "share_pct": round(r["on_sale"] / r["read"] * 100, 1) if r["read"] else 0.0,
                                   "avg_discount_pct": round(r["disc"], 1) if r["disc"] is not None else None})
    stores = []
    for sid, rows in per.items():
        rows.sort(key=lambda d: d["date"])
        campaigns, base = detect_campaigns(rows)
        usable = [d for d in rows if d["read"] >= MIN_PRODUCTS_READ]
        stores.append({"store_id": sid, "name": names.get(sid, sid), "daily": rows, "campaigns": campaigns,
                       "usual_share_pct": base,
                       "avg_share_pct": round(sum(d["share_pct"] for d in usable) / len(usable), 1) if usable else None,
                       "avg_discount_pct": (round(sum(d["avg_discount_pct"] for d in usable if d["avg_discount_pct"]) /
                                                  max(1, sum(1 for d in usable if d["avg_discount_pct"])), 1) if usable else None)})
    stores.sort(key=lambda s: -(s["avg_share_pct"] or 0))
    return {"from": lo, "days": days, "stores": stores, "computed_at": now.isoformat()}
