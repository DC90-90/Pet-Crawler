"""Store views share sealed facts; no category-velocity or monthly extrapolation."""
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
import ledger
from evidence_ledger import sales_map
from price_cohort import exclusion, identity_keys


async def latest(db, store_id=None):
    query = {"observation_version": 2, "is_synthetic": False}
    if store_id:
        query["store_id"] = store_id
    return await db.product_snapshots.aggregate([
        {"$match": query}, {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": "$offer_id", "row": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$row"}}, {"$project": {"_id": 0}},
    ], allowDiskUse=True).to_list(200000)


async def profile(db, store_id, orders_fn):
    store = await db.stores.find_one({"id": store_id, "is_active": {"$ne": False}}, {"_id": 0})
    if not store:
        raise HTTPException(404, "Store not found")
    for secret_field in ('tier4_email', 'tier4_password', 'tier4_phone', 'tier4_session_cookies'):
        store.pop(secret_field, None)
    start, end = ledger.sealed_ksa_window(30)
    sales = {oid: v for (sid, oid), v in (await sales_map(db, start, end)).items() if sid == store_id}
    observations = await latest(db, store_id)
    by_offer = {s["offer_id"]: s for s in observations}
    orders = await orders_fn(db, start, end) if store.get("is_own_store") else None
    value = orders["revenue"] if orders is not None else round(sum(r["revenue"] for r in sales.values()), 2) if sales else None
    units = orders["units"] if orders is not None else sum(r["units"] for r in sales.values()) if sales else None
    basis = "orders_exact" if orders is not None else "inventory_proxy" if sales else "unavailable"
    top = [{"sku": r["sku"], "offer_id": oid, "name_ar": by_offer.get(oid, {}).get("name_ar"),
            "name_en": by_offer.get(oid, {}).get("name_en"), "units_sold": r["units"], "basis": "inventory_proxy"}
           for oid, r in sorted(sales.items(), key=lambda pair: -pair[1]["units"]) if r["units"] > 0][:10]
    catalog = [s for s in observations if s.get("comparable")]
    daily = {}
    sealed_days = {r["ksa_date"]: r["sealed_at"] async for r in db.daily_ledger_store.find(
        {"store_id": store_id, "ksa_date": {"$gte": ledger.ksa_day_str(start), "$lt": ledger.ksa_day_str(end)}, "sealed_at": {"$ne": None}}, {"_id": 0})}
    if orders is None:
        async for fact in db.sales_facts_v2.find({"store_id": store_id, "date": {"$in": list(sealed_days)}, "units": {"$ne": None}, "algorithm_version": 2}, {"_id": 0}):
            if fact["created_at"].replace(tzinfo=timezone.utc) <= sealed_days[fact["date"]].replace(tzinfo=timezone.utc):
                daily[fact["date"]] = daily.get(fact["date"], 0) + (fact.get("revenue") or 0)
    else:
        async for order in db.own_store_orders.find({"created_at": {"$gte": start, "$lt": end}, "excluded": False, "financials_complete": True, "currency": "SAR"}, {"_id": 0, "created_at": 1, "total": 1}):
            date = ledger.ksa_day_str(order["created_at"])
            daily[date] = daily.get(date, 0) + order["total"]
    weeks = {}
    for date, v in daily.items():
        week = datetime.fromisoformat(date).strftime("%Y-W%W")
        weeks[week] = weeks.get(week, 0) + v
    return {"store": store, "kpis": {
        "catalog_size": len(catalog), "active_skus": sum(exclusion(s) is None for s in catalog),
        "est_monthly_revenue": value, "est_daily_revenue": None, "est_daily_sales": None,
        "observed_units": units, "revenue_status": "computed" if value is not None else "sales_data_unavailable",
        "revenue_basis": basis, "revenue_band_pct": None, "revenue_range_low": None, "revenue_range_high": None,
        "data_span_days": 30, "avg_discount_rate": None, "last_crawled": store.get("last_successful_crawl_at"),
        "window_start": start, "window_end": end, "catalog_verified": bool(catalog)},
        "revenue_trend_weekly": [{"week": k, "revenue": round(v, 2), "basis": basis} for k, v in sorted(weeks.items())],
        "revenue_trend_daily": [{"date": k, "revenue": round(v, 2), "basis": basis} for k, v in sorted(daily.items())], "top_products": top,
        "category_distribution": [], "new_arrivals": [],
        "recently_oos": [{**s, "last_qty": s.get("qty_available")} for s in catalog if s.get("in_stock") is False][:10]}


async def leaderboard(db, days):
    start, end = ledger.sealed_ksa_window(days)
    signals = await sales_map(db, start, end)
    observations = await latest(db)
    rows = []
    async for store in db.stores.find({"is_active": {"$ne": False}, "is_own_store": {"$ne": True}}, {"_id": 0}):
        values = [r for (sid, _), r in signals.items() if sid == store["id"]]
        rows.append({"store": store["name"], "store_id": store["id"],
                     "revenue_est": round(sum(r["revenue"] for r in values), 2) if values else None,
                     "units_sold": sum(r["units"] for r in values) if values else None,
                     "products": sum(s["store_id"] == store["id"] and s.get("comparable") is True for s in observations),
                     "revenue_status": "computed" if values else "sales_data_unavailable", "revenue_basis": "inventory_proxy",
                     "window_start": start, "window_end": end})
    return sorted(rows, key=lambda r: -(r["revenue_est"] or 0))


async def ranking(db, orders_fn):
    stores = await db.stores.find({"is_active": {"$ne": False}}, {"_id": 0}).to_list(10000)
    start, end = ledger.sealed_ksa_window(30)
    sales = await sales_map(db, start, end)
    rows, all_offers = [], await latest(db)
    valid = [s for s in all_offers if exclusion(s) is None]
    for store in stores:
        sid = store["id"]
        obs = [s for s in valid if s["store_id"] == sid]
        # Coverage ranks use eligible offers. Availability needs all recent
        # observations with known stock, including out-of-stock offers.
        known_stock = [s for s in all_offers if s['store_id'] == sid
                       and exclusion({**s, 'in_stock': True}) is None
                       and isinstance(s.get('in_stock'), bool)]
        stock_pct = round(100 * sum(s['in_stock'] for s in known_stock) / len(known_stock), 1) if known_stock else None
        signals = [v for (store_key, _), v in sales.items() if store_key == sid]
        orders = await orders_fn(db, start, end) if store.get("is_own_store") else None
        revenue = orders["revenue"] if orders is not None else round(sum(r["revenue"] for r in signals), 2) if signals else None
        n = len(obs)
        basis = "orders_exact" if orders is not None else "inventory_proxy" if signals else "unavailable"
        rows.append({"store_id": sid, "name": store["name"], "domain": store.get("domain"), "platform": store.get("platform"),
                     "is_own_store": bool(store.get("is_own_store")), "products": n, "in_stock_pct": stock_pct,
                     "revenue_30d": revenue, "revenue_status": "ledger" if orders is not None else "computed" if signals else "not_measurable",
                     "revenue_basis": basis, "revenue_tier": "exact" if orders is not None else "estimated" if signals else "unavailable",
                     "revenue_rank_value": None, "revenue_rank_basis": "none", "sales_status": basis, "sales_sample": len(signals),
                     "overlap": 0, "strength_score": None, "revenue_approx": None, "revenue_est_salla": None,
                     "rank_basis": "verified_offer_coverage", "components": {
                         "breadth": {"score": 0, "products": n}, "price": {"score": 0, "avg_percentile": None, "shared_products": 0},
                         "stock": {"score": stock_pct / 100 if stock_pct is not None else None, "pct": stock_pct},
                         "freshness": {"score": 1 if n else 0, "pct": 100 if n else None}}})
    # Orders and depletion proxies do not share a revenue leaderboard denominator.
    rows.sort(key=lambda r: (-r["products"], r["name"]))
    for row in rows:
        row["rank"] = 1 + sum(other["products"] > row["products"] for other in rows) if row["products"] > 0 else None
    health = await ledger.sealed_days_in_window(db, 30)
    return {"window_days": 30, "weights": {}, "total_stores": len(rows), "own_rank": next((r["rank"] for r in rows if r["is_own_store"]), None),
            "sorted_by": "verified_offer_coverage_desc", "ranked_on_measured": 0, "ranked_on_estimate": 0,
            "no_revenue_value": sum(r["revenue_30d"] is None for r in rows), "stores": rows,
            "revenue_window": {"basis": "sealed_ksa_days", "start_ksa_date": health["start_ksa_date"], "end_ksa_date": health["end_ksa_date"],
                               "expected_days": health["expected"], "sealed_days": health["sealed_days"], "unsealed_days": health["unsealed_days"]}}


async def market_summary(db, days, price_fn):
    from comparison_views import context, position_summary
    import statistics
    _, products, cohorts = await context(db, price_fn)
    observations = await latest(db)
    valid = [s for s in observations if exclusion(s) is None]
    own_keys = set().union(*(identity_keys(p) for p in products)) if products else set()
    unmatched = {key for s in valid for key in identity_keys(s) if key not in own_keys}
    spreads = [c["max"]-c["min"] for c in cohorts.values() if len(c["sellers"]) >= 2]
    since = datetime.now(timezone.utc)-timedelta(days=days)
    previous, drops = {}, 0
    async for row in db.product_snapshots.find({"observation_version": 2, "is_synthetic": False, "comparable": True, "crawled_at": {"$gte": since}}, {"_id": 0, "offer_id": 1, "price": 1}).sort("crawled_at", 1):
        oid, price = row["offer_id"], row.get("price")
        if price is not None:
            if oid in previous and 0 < price < previous[oid]:
                drops += 1
            previous[oid] = price
    return {"total_skus": len(products), "price_drops": drops if previous else None, "product_gaps": len(unmatched) if valid else None,
            "median_spread": round(statistics.median(spreads), 2) if spreads else None,
            "avg_confidence": round(sum(s["confidence_score"] for s in valid)/len(valid), 1) if valid else None,
            "freshness_breakdown": {"total_tracked": len(observations), "this_week": len(valid), "stale": len(observations)-len(valid)},
            "market_position_summary": await position_summary(db, price_fn)}


async def top_sellers(db, days, store_id=None):
    start, end = ledger.sealed_ksa_window(days)
    signals = await sales_map(db, start, end)
    observations = {s["offer_id"]: s for s in await latest(db)}
    active = set(await db.stores.distinct("id", {"is_active": {"$ne": False}}))
    result = []
    for (sid, oid), r in signals.items():
        if sid not in active or (store_id not in (None, "", "all") and sid != store_id) or not r["units"]:
            continue
        s = observations.get(oid, {})
        result.append({"sku": r["sku"], "offer_id": oid, "store_id": sid,
                       "name_ar": s.get("name_ar") or r["sku"], "name_en": s.get("name_en"),
                       "store_name": s.get("store_name"), "category": None,
                       "qty_sold_est": r["units"], "revenue_est": r["revenue"],
                       "source_tier": s.get("source_tier"), "confidence_score": s.get("confidence_score"),
                       "num_sellers": 1, "velocity": r["units"], "basis": "inventory_proxy", "avg_price": s.get("price")})
    return sorted(result, key=lambda r: -r["qty_sold_est"])[:20]
