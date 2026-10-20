"""Store views share sealed facts; no category-velocity or monthly extrapolation."""
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
import category_map
import ledger
from evidence_ledger import sales_map, measured_days, sales_source
from price_cohort import exclusion, identity_keys, FIELDS
from snapshot_reads import latest_pipeline, complete_latest
from observation_contract import since_bound

# Unlike cohort observations (annotated from the parent registry), store views
# also consume persisted exclusion flags. Do not lose them in projections.
ELIGIBILITY_FIELDS = {**FIELDS, "data_origin": 1, "superseded_parent": 1, "last_crawl_at": 1}


async def latest(db, store_id=None, since=None, projection=None, days=30):
    # Bounded by crawl date so the aggregation rides the (store_id, crawled_at)
    # index instead of scanning every snapshot ever written; an offer not seen
    # in `days` is not a current listing for any store view. Callers whose
    # output already excludes older evidence pass a tighter explicit `since`.
    cutoff = since if since is not None else datetime.now(timezone.utc) - timedelta(days=days)
    # One store at a time, newest week first: the all-store 30-day read was a
    # single aggregation over ~1.5M snapshots and passed the 10 s operation
    # limit once Hamtaro and CutePets were crawled in full — the Overview
    # price card, gaps, trending and 30-day market share stopped rebuilding
    # (20 Oct 2026). Same result: newest observation per offer in the window.
    store_ids = [store_id] if store_id else await db.stores.distinct("id")
    split = max(since_bound(cutoff), datetime.now(timezone.utc) - timedelta(days=LATEST_RECENT_DAYS))
    rows = []
    for sid in store_ids:
        base = {"observation_version": 2, "is_synthetic": False, "store_id": sid}
        recent = await complete_latest(db, latest_pipeline({**base, "crawled_at": {"$gte": split}}, projection))
        rows.extend(recent)
        if split > since_bound(cutoff):
            seen = {r.get("offer_id") for r in recent}
            older = await complete_latest(db, latest_pipeline(
                {**base, "crawled_at": {"$gte": since_bound(cutoff), "$lt": split}}, projection))
            rows.extend(r for r in older if r.get("offer_id") not in seen)
    return rows


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
    if orders is None and sales_source() == "ledger":
        for r in sales.values():
            for date, v in (r.get("by_day") or {}).items():
                daily[date] = daily.get(date, 0) + v
    elif orders is None:
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
    observations = await latest(db, projection={"store_id": 1, "comparable": 1})
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
    stores = await db.stores.find({"is_active": {"$ne": False}}, {"_id": 0}).to_list(None)
    start, end = ledger.sealed_ksa_window(30)
    sales = await sales_map(db, start, end)
    groups = []
    if sales_source() == "ledger":
        import ledger_sales
        groups = (await ledger_sales.meta(db)).get("groups") or []
    now = datetime.now(timezone.utc)
    rows, all_offers = [], await latest(db, since=now-timedelta(days=7), projection=ELIGIBILITY_FIELDS)
    valid = [s for s in all_offers if exclusion(s, now=now) is None]
    for store in stores:
        sid = store["id"]
        obs = [s for s in valid if s["store_id"] == sid]
        # Coverage ranks use eligible offers. Availability needs all recent
        # observations with known stock, including out-of-stock offers.
        known_stock = [s for s in all_offers if s['store_id'] == sid
                       and exclusion({**s, 'in_stock': True}, now=now) is None
                       and isinstance(s.get('in_stock'), bool)]
        stock_pct = round(100 * sum(s['in_stock'] for s in known_stock) / len(known_stock), 1) if known_stock else None
        signals = [v for (store_key, _), v in sales.items() if store_key == sid]
        orders = await orders_fn(db, start, end) if store.get("is_own_store") else None
        revenue = orders["revenue"] if orders is not None else round(sum(r["revenue"] for r in signals), 2) if signals else None
        n = len(obs)
        # Everything read from the store in the last 7 days — in or out of
        # stock — so "products" is not mistaken for what Daleel collected
        # (the client read Zarafa's 1,318 in-stock offers as 1,318 of ~4,000
        # products ingested, 19 Oct 2026). Parent listings are not offers.
        catalog_n = sum(1 for s in all_offers if s["store_id"] == sid and not s.get("superseded_parent"))
        basis = "orders_exact" if orders is not None else "inventory_proxy" if signals else "unavailable"
        rows.append({"store_id": sid, "name": store["name"], "domain": store.get("domain"), "platform": store.get("platform"),
                     "is_own_store": bool(store.get("is_own_store")), "products": n, "catalog_products": catalog_n,
                     "in_stock_pct": stock_pct,
                     "revenue_30d": revenue, "revenue_status": "ledger" if orders is not None else "computed" if signals else "not_measurable",
                     "revenue_days_measured": None if orders is not None else len(measured_days(sales, sid)), "revenue_days_expected": 30,
                     "revenue_basis": basis, "revenue_tier": "exact" if orders is not None else "estimated" if signals else "unavailable",
                     # Storefronts that draw on one stock: a shared sale is counted once, for the lead.
                     "shared_stock_with": [n for g in groups if sid in g.get("members", ()) for m, n in zip(g["members"], g["names"]) if m != sid],
                     "shared_stock_lead": any(g.get("lead") == sid for g in groups),
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
    from comparison_views import context, summarize_positions
    import statistics
    own, products, cohorts = await context(db, price_fn)
    observations = await latest(db, projection=ELIGIBILITY_FIELDS)
    valid = [s for s in observations if exclusion(s) is None]
    own_keys = set().union(*(identity_keys(p) for p in products)) if products else set()
    unmatched = {key for s in valid for key in identity_keys(s) if key not in own_keys}
    spreads = [c["max"]-c["min"] for c in cohorts.values() if len(c["sellers"]) >= 2]
    since = datetime.now(timezone.utc)-timedelta(days=days)
    # Day-over-day closing-price drops from the daily ledger, one store at a
    # time on its (store_id, ksa_date) index. The snapshot walk this replaces
    # read every observation of the window in one sorted scan: once Hamtaro and
    # CutePets were crawled in full it outran the 15-minute background budget
    # at 30 and 90 days, and the Overview's price card stayed "being prepared"
    # (20 Oct 2026).
    lo = ledger.ksa_day_str(since)
    previous, drops = {}, 0
    for sid in await db.stores.distinct("id"):
        async for row in db.daily_ledger.find({"store_id": sid, "ksa_date": {"$gte": lo}},
                                              {"_id": 0, "sku": 1, "close_price": 1}).sort("ksa_date", 1):
            price = row.get("close_price")
            if price:
                key = (sid, row.get("sku"))
                if key in previous and 0 < price < previous[key]:
                    drops += 1
                previous[key] = price
    return {"total_skus": len(products), "price_drops": drops if previous else None, "product_gaps": len(unmatched) if valid else None,
            "median_spread": round(statistics.median(spreads), 2) if spreads else None,
            "avg_confidence": round(sum(s["confidence_score"] for s in valid)/len(valid), 1) if valid else None,
            "freshness_breakdown": {"total_tracked": len(observations), "this_week": len(valid), "stale": len(observations)-len(valid)},
            "market_position_summary": summarize_positions(own, products, cohorts, price_fn)}


LATEST_RECENT_DAYS = 7
TOP_SELLERS_LIMIT = 300
REVIEWED_CATEGORY_SOURCES = ("reviewed", "store_supplied", "import_file")


async def top_sellers(db, days, store_id=None):
    start, end = ledger.sealed_ksa_window(days)
    signals = await sales_map(db, start, end)
    observations = {s["offer_id"]: s for s in await latest(db, projection={
        "name_ar": 1, "name_en": 1, "store_name": 1, "source_tier": 1, "confidence_score": 1, "price": 1})}
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
    # 16 Oct 2026 — enough rows for per-store and per-category tabs (was the
    # top 20 only), with the reviewed catalogue category, image and barcode.
    result = sorted(result, key=lambda r: -r["qty_sold_est"])[:TOP_SELLERS_LIMIT]
    # A ledger fact keyed by SKU (no offer id resolved) is not in the latest
    # offers map: its store and product names come from the catalogue
    # (165 of 300 rows had no store name, 16 Oct 2026).
    names = {s["id"]: s.get("name") async for s in db.stores.find({}, {"_id": 0, "id": 1, "name": 1})}
    fields = {"_id": 0, "offer_id": 1, "store_id": 1, "sku": 1, "category": 1, "category_source": 1,
              "image_url": 1, "barcode": 1, "name_ar": 1, "name_en": 1, "product_url": 1}
    by_offer, by_sku = {}, {}
    async for m in db.products.find({"offer_id": {"$in": [r["offer_id"] for r in result if r["offer_id"]]}}, fields):
        by_offer[(m.get("store_id"), m.get("offer_id"))] = m
    loose = [r for r in result if (r["store_id"], r["offer_id"]) not in by_offer]
    if loose:
        async for m in db.products.find({"store_id": {"$in": list({r["store_id"] for r in loose})},
                                         "sku": {"$in": list({r["sku"] for r in loose})}}, fields):
            by_sku[(m.get("store_id"), m.get("sku"))] = m
    for r in result:
        m = by_offer.get((r["store_id"], r["offer_id"])) or by_sku.get((r["store_id"], r["sku"])) or {}
        if r["name_ar"] == r["sku"]:
            r.update(name_ar=m.get("name_ar") or m.get("name_en") or r["sku"], name_en=r["name_en"] or m.get("name_en"))
        if r["name_ar"] == r["sku"]:
            # A retired SKU (Mowkly re-keyed its catalogue in Oct 2026): the
            # name from its last snapshot that carried one.
            snap = await db.product_snapshots.find_one(
                {"store_id": r["store_id"], "sku": r["sku"], "name_ar": {"$nin": [None, ""]}},
                {"_id": 0, "name_ar": 1, "name_en": 1, "product_url": 1}, sort=[("crawled_at", -1)])
            if snap:
                r.update(name_ar=snap["name_ar"], name_en=r["name_en"] or snap.get("name_en"))
                m = {**m, "product_url": m.get("product_url") or snap.get("product_url")}
        r.update(store_name=r["store_name"] or names.get(r["store_id"]),
                 category=m.get("category") if m.get("category_source") in REVIEWED_CATEGORY_SOURCES else None,
                 image_url=m.get("image_url"), barcode=m.get("barcode"), product_url=m.get("product_url"))
        r.update(category_map.facets(r["category"], r["name_ar"], r["name_en"]))
    return result
