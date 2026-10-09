"""Catalog and drill-down adapters with consistent offer and evidence semantics."""
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
import ledger
from comparison_views import context, position
from core.utils import get_stock_signal
from evidence_ledger import sales_map
from observation_contract import gtin
from stock_evidence import own_stock


def verified_barcode(product):
    return str(product.get("barcode")) if gtin(product.get("barcode")) else str(product.get("sku")) if gtin(product.get("sku")) else None


async def dataset(db, days, on_date, date_from, date_to, category, animal_type, search, own_only, price_fn, orders_fn):
    own, catalog, cohorts = await context(db, price_fn)
    if on_date:
        start, end = ledger.ksa_midnight_utc(on_date), ledger.ksa_midnight_utc(on_date)+timedelta(days=1)
    elif date_from or date_to:
        end = ledger.ksa_midnight_utc(date_to)+timedelta(days=1) if date_to else datetime.now(timezone.utc)
        start = ledger.ksa_midnight_utc(date_from) if date_from else end-timedelta(days=days)
    else:
        start, end = ledger.sealed_ksa_window(days)
    orders = await orders_fn(db, start, end)
    sales = await sales_map(db, start, end)
    rows = []
    parent_skus = {str(p.get("listing_id") or p.get("zid_id")): p.get("sku") for p in catalog if p.get("known_variant_parent")}
    for mp in catalog:
        sku = mp.get("sku")
        if not sku or sku not in cohorts:
            continue
        c, price = cohorts[sku], price_fn(mp)
        stock = own_stock(mp)
        if category not in (None, "", "all") and category not in (mp.get("category"), mp.get("subcategory")):
            continue
        if animal_type not in (None, "", "all") and animal_type != mp.get("animal_type"):
            continue
        parent_sku = parent_skus.get(str(mp.get("listing_id") or mp.get("zid_id")))
        searchable = " ".join([*(str(mp.get(k) or "") for k in ("sku", "barcode", "name_ar", "name_en")), parent_sku or ""]).casefold()
        if search and search.casefold() not in searchable:
            continue
        evidence = orders["by_sku"].get(sku, {"units": 0, "revenue": 0}) if orders is not None else sales.get((own.get("id"), mp.get("offer_id") or sku))
        units, value = (evidence.get("units"), evidence.get("revenue")) if evidence else (None, None)
        row = {**mp, "sku": sku, "parent_sku": parent_sku, "price": price or None, "market_price": c["avg"], "is_my_product": True,
               "barcode": verified_barcode(mp),
               "category_candidate": mp.get("category"), "category": mp.get("category") if mp.get("category_source") in ("reviewed", "store_supplied", "import_file") else None,
               **stock, "my_quantity": stock["quantity"], "my_units_sold": units, "my_revenue_est": value,
               "qty_sold_est": units, "revenue_est": value, "my_stock_signal": get_stock_signal(stock["quantity"], stock["in_stock"]),
               "my_stock_status": "not_listed" if mp.get("present_on_store") is False else "own_catalog",
               "num_competitors": len({s["store_id"] for s in c["sellers"]+c["excluded"]}), "num_priced_competitors": len(c["sellers"]),
               "num_sellers": len(c["sellers"]), "competitor_min_price": c["min"], "competitor_max_price": c["max"],
               "vs_my_price_pct": round((c["min"]-price)/price*100, 1) if c["min"] and price else None,
               "market_share_pct": None, "has_market_share": False, "market_share_unavailable_reason": "unreconciled_sales_denominator",
               "my_share_is_estimate": True, "cohort_id": c["cohort_id"], "price_policy": c["policy_version"],
               "excluded_sellers": c["excluded"], "source_observed_at": c["observed_at"],
               "market_position": position(own, mp, price, c), "source_tier": 0, "confidence_score": 99 if price else 0,
               "sales_basis": "orders_exact" if orders is not None else "inventory_proxy" if evidence else "unavailable"}
        rows.append(row)
    measurable = [r for r in rows if r["my_units_sold"] is not None]
    matched = sum(r["num_priced_competitors"] > 0 for r in rows)
    value = round(sum(r["my_revenue_est"] or 0 for r in measurable), 2) if measurable else None
    return {"rows": rows, "total": len(rows), "categories": sorted({r["category"] for r in rows if r.get("category")}),
            "kpis": {"total_products": len(rows), "matched_products": matched, "market_coverage_pct": round(matched/len(rows)*100, 1) if rows else 0,
                     "total_units_sold": sum(r["my_units_sold"] for r in measurable) if measurable else None,
                     "my_revenue": orders["revenue"] if orders is not None else value, "total_revenue": value,
                     "my_orders_count": orders["orders_count"] if orders is not None else None,
                     "my_revenue_source": "zid_orders" if orders is not None else "inventory_proxy" if measurable else "unavailable",
                     "market_revenue": None, "avg_market_share": None, "share_sample_size": 0,
                     "sales_evidence_products": len(measurable), "sales_window": {"from": start, "to": end}}}


async def detail(db, sku, days, price_fn, competitor_store_ids=None):
    own, products, cohorts = await context(db, price_fn, competitor_store_ids)
    mp = next((p for p in products if p.get("sku") == sku), None)
    if mp is None:
        raise HTTPException(404, "Product not in own catalog; use a store-specific offer")
    c, price = cohorts[sku], price_fn(mp)
    stock = own_stock(mp)
    sellers = []
    for row in c["sellers"] + c["excluded"]:
        excluded = row.get("eligible") is False
        sellers.append({**row, "price": row.get("price") if not excluded else None,
                        "historical_price": row.get("price") if excluded else None,
                        "historical_quantity": row.get("qty_available") if excluded else None,
                        "historical_quantity_at": row.get("crawled_at") if excluded else None,
                        "qty_available": None if excluded else row.get("qty_available"),
                        "in_stock": None if excluded and row.get("excluded_reason") != "out_of_stock" else row.get("in_stock"),
                        "price_status": "excluded" if excluded else "live", "is_stale": excluded,
                        "last_crawl_at": row.get("crawled_at"), "days_since_crawl": None,
                        "tier4_status": None, "is_own_store": False,
                        "stock_signal": "UNKNOWN" if excluded and row.get("excluded_reason") != "out_of_stock" else get_stock_signal(row.get("qty_available"), row.get("in_stock"))})
    if price:
        sellers.append({"sku": sku, "store_id": own.get("id"), "store_name": own.get("name"), "price": price,
                        "in_stock": stock["in_stock"], "qty_available": stock["quantity"], "is_own_store": True,
                        "stock_signal": get_stock_signal(stock["quantity"], stock["in_stock"]),
                        "product_url": mp.get("product_url"), "price_status": "live", "confidence_score": 99, "source_tier": 0,
                        "last_crawl_at": mp.get("last_synced_at")})
    history, since = {}, datetime.now(timezone.utc)-timedelta(days=days)
    offer_ids = [s.get("offer_id") for s in c["sellers"] if s.get("offer_id")]
    async for snap in db.product_snapshots.find({"offer_id": {"$in": offer_ids}, "crawled_at": {"$gte": since}, "observation_version": 2, "comparable": True}, {"_id": 0}).sort("crawled_at", 1):
        history.setdefault(snap["store_name"], []).append({"date": snap["crawled_at"].isoformat(), "price": snap["price"], "qty": snap.get("qty_available")})
    return {**mp, **stock, "price": price or None, "sale_price": mp.get("sale_price") if price else None,
            "barcode": verified_barcode(mp), "source_tier": 0 if price else None, "confidence_score": 99 if price else None,
            "historical_price": (mp.get("historical_price") if mp.get("historical_price") is not None else mp.get("price")) if not price else None,
            "price_status": "live" if price else "unavailable",
            "is_my_product": True, "store_prices": sellers, "seller_count": len(c["sellers"]),
            "seller_summary": {"live": len(c["sellers"]), "stale": len(c["excluded"]), "oos": sum(s.get("in_stock") is False for s in c["excluded"])},
            "price_range": {"min": c["min"], "max": c["max"], "avg": c["avg"]} if c["min"] else {},
            "total_volume": None, "market_position": position(own, mp, price, c), "cohort_id": c["cohort_id"],
            "history": history, "velocity": {"velocity": [], "avg_daily": None, "total_units": None}, "policy_version": c["policy_version"]}


async def intel_detail(db, sku, price_fn, competitor_store_ids=None):
    result = await detail(db, sku, 30, price_fn, competitor_store_ids)
    own = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1}) or {}
    competitors = [{**r, "competitor_store_id": r["store_id"], "competitor_store_name": r.get("store_name"),
                    "competitor_sku": r.get("sku"), "competitor_offer_id": r.get("offer_id"),
                    "competitor_price": r.get("price"), "competitor_url": r.get("product_url"),
                    "diff_pct": round((price_fn(result)-r["price"])/r["price"]*100, 1) if price_fn(result) and r.get("price") else None,
                    "confidence": 99 if r.get("price_status") == "live" else None,
                    "match_method": "verified_offer" if r.get("price_status") == "live" else "unverified",
                    "flags": [], "excluded_reason": r.get("excluded_reason")}
                   for r in result["store_prices"] if not r.get("is_own_store")]
    for row in competitors:
        row.update(competitor_name=row.get("name_ar"), competitor_barcode=row.get("barcode"),
                   competitor_in_stock=row.get("in_stock") if row.get("price_status") == "live" or row.get("excluded_reason") == "out_of_stock" else None,
                   last_crawled_at=row.get("crawled_at"),
                   diff_sar=round(price_fn(result)-row["competitor_price"], 2) if price_fn(result) and row.get("competitor_price") else None)
    return {"my_product": {**result, "is_own_store": True}, "competitors": competitors, "own_store_id": own.get("id"), "cohort_id": result["cohort_id"],
            "market_summary": {"lowest_price": result["price_range"].get("min"), "highest_price": result["price_range"].get("max"),
                               "sellers_count": result["seller_count"], "matched_count": len(competitors), "my_price": result["price"]}}