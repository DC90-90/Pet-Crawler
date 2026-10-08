"""Presentation adapters over the same current-price cohort."""
from datetime import datetime, timezone
from price_cohort import build_cohorts, POLICY_VERSION
from core.utils import compute_market_position
from observation_contract import gtin


async def context(db, own_price_fn):
    own = await db.stores.find_one({"is_own_store": True}, {"_id": 0}) or {}
    products = await db.my_products.find({}, {"_id": 0}).to_list(50000)
    cohorts = await build_cohorts(db, products, own.get("id"), own_price_fn)
    return own, products, cohorts


def position(own, product, price, cohort):
    if not price:
        return None
    return compute_market_position(cohort["sellers"] + [{"store_id": own.get("id"), "store_name": own.get("name"), "price": price}], own.get("id"))


async def intel(db, own_price_fn):
    own, products, cohorts = await context(db, own_price_fn)
    full, actions, advantages = [], [], []
    for mp in products:
        sku = mp.get("sku")
        if sku not in cohorts:
            continue
        c, price = cohorts[sku], own_price_fn(mp)
        sellers = c["sellers"]
        low = sellers[0] if sellers else {}
        gap = round((price-low["price"])/low["price"]*100, 1) if low and price else None
        barcode = mp.get("barcode") if gtin(mp.get("barcode")) else sku if gtin(sku) else None
        row = dict(my_sku=sku, my_barcode=barcode, my_name_ar=mp.get("name_ar"), my_name_en=mp.get("name_en"),
                   my_price=price or None, my_qty=mp.get("quantity"), sellers=len(sellers), image_url=mp.get("image_url"),
                   cheapest_competitor=low.get("store_name", ""), cheapest_price=low.get("price"), diff_pct=gap,
                   price_status="live" if low else "unavailable", confidence=99 if low else 0, match_method="verified_offer",
                   flags=[], market_position=position(own, mp, price, c), cohort_id=c["cohort_id"],
                   excluded_sellers=c["excluded"], policy_version=POLICY_VERSION)
        full.append(row)
        if gap is not None and gap > 5 and mp.get("in_stock") is True and mp.get("present_on_store") is not False:
            actions.append({**row, "severity": "red" if gap > 15 else "yellow", "reason": f"Price gap {gap}%"})
        if gap is not None and gap <= 0:
            advantages.append({**row, "advantage": "cheapest", "saving_sar": round(low["price"]-price, 2)})
    return dict(action_required=sorted(actions, key=lambda r: -r["diff_pct"]), my_advantages=advantages,
                full_table=full, unverified=[], confidence_distribution={}, policy_version=POLICY_VERSION,
                summary=dict(total_products=len(products), matched_products=sum(bool(cohorts[p["sku"]]["sellers"]) for p in products if p.get("sku")),
                             unverified_products=0, overpriced_red=sum(r["severity"]=="red" for r in actions),
                             overpriced_yellow=sum(r["severity"]=="yellow" for r in actions), cheapest_count=len(advantages),
                             oos_opportunities=0, rows_without_live_price=sum(r["price_status"]!="live" for r in full)))


async def position_summary(db, price_fn):
    own, products, cohorts = await context(db, price_fn)
    ranked = [position(own, p, price_fn(p), cohorts[p["sku"]]) for p in products if p.get("sku") in cohorts]
    ranked = [r for r in ranked if r]
    return {"ranked_products": len(ranked), "total_my_products": len(products),
            "cheapest_count": sum(r["is_cheapest"] for r in ranked),
            "most_expensive_count": sum(r["is_most_expensive"] for r in ranked),
            "below_median_count": sum(r["below_median"] for r in ranked),
            "above_median_count": sum(r["above_median"] for r in ranked),
            "at_median_count": sum(not r["above_median"] and not r["below_median"] for r in ranked),
            "avg_percentile": round(sum(r["percentile"] for r in ranked)/len(ranked), 1) if ranked else None,
            "price_policy": POLICY_VERSION}


async def scanner(db, days, own_price_fn, orders_fn, sales_fn):
    import ledger
    own, products, cohorts = await context(db, own_price_fn)
    start, end = ledger.sealed_ksa_window(days)
    orders = await orders_fn(db, start, end)
    signals = {(r.get("offer_id") or r["sku"], r["store_id"]): r["units"] for r in await sales_fn(db, start, until=end)}
    rows, competitors, positioned, undercut, excluded = [], [], [], [], []
    total_exposure = 0.0
    for mp in products:
        sku = mp.get("sku")
        if sku not in cohorts:
            continue
        c, price = cohorts[sku], own_price_fn(mp)
        excluded.extend({**r, "sku": sku, "reason": r["excluded_reason"], "excluded_price": r.get("price")} for r in c["excluded"])
        if not c["sellers"] or not price or mp.get("in_stock") is not True or mp.get("present_on_store") is False:
            continue
        low, high = c["sellers"][0], c["sellers"][-1]
        gap = round((price-low["price"])/low["price"]*100, 1)
        if gap < 10:
            positioned.append(dict(sku=sku, name_ar=mp.get("name_ar"), price=price, market_avg=c["avg"], store_name=own.get("name")))
            continue
        units = (orders["by_sku"].get(sku, {}).get("units", 0) if orders is not None else signals.get((mp.get("offer_id") or sku, own.get("id"))))
        basis = "orders" if orders is not None else "rollup" if units is not None else "none"
        exposure = round((price-low["price"])*units, 2) if units is not None else None
        total_exposure += exposure or 0
        sellers = sorted([{**r, "qty": r.get("qty_available"), "is_own": False} for r in c["sellers"]] + [dict(store_id=own.get("id"), store_name=own.get("name"), price=price, is_own=True, in_stock=True, qty=mp.get("quantity"))], key=lambda r: r["price"])
        for r in sellers:
            r.update(is_lowest=r["price"]==sellers[0]["price"], is_highest=r["price"]==sellers[-1]["price"])
        rows.append(dict(sku=sku, name_ar=mp.get("name_ar") or sku, name_en=mp.get("name_en"), category=mp.get("category", ""),
                         image_url=mp.get("image_url"), store_name=own.get("name"), store_id=own.get("id"), my_price=price,
                         market_lowest=low["price"], market_highest=high["price"], market_avg=c["avg"], lowest_store_name=low["store_name"],
                         lowest_store_id=low["store_id"], highest_store_name=high["store_name"], gap_pct=gap, units_sold=units,
                         units_basis=basis, market_sold=None, price_gap_exposure=exposure, revenue_uplift=exposure,
                         forecast_revenue_uplift=None, badge="overpriced_risk" if gap>=25 else "overpriced",
                         num_sellers=len(sellers), sellers=sellers, in_stock=True, qty=mp.get("quantity"), cohort_id=c["cohort_id"]))
    rows.sort(key=lambda r: (r["price_gap_exposure"] or 0, r["gap_pct"]), reverse=True)
    summary = dict(total_overpriced=len(rows), overpriced_count=len(rows), total_uplift=round(total_exposure, 2),
                   total_uplift_sar=round(total_exposure, 2), total_price_gap_exposure_sar=round(total_exposure, 2),
                   uplift_is_forecast=False, zero_sales_overpriced=sum(r["units_sold"]==0 for r in rows),
                   unknown_sales_overpriced=sum(r["units_sold"] is None for r in rows), competitors_overpriced=0,
                   excluded_offers=len(excluded), excluded_offer_sample=excluded[:50], policy_version=POLICY_VERSION,
                   sales_window=await ledger.sealed_days_in_window(db, days))
    if not any(r["price_gap_exposure"] is not None for r in rows):
        summary.update(total_uplift=None, total_uplift_sar=None, total_price_gap_exposure_sar=None)
    for name in ("pack_mismatch", "suspected_pack_mismatch", "low_outliers_kept", "slug_pack_mismatch", "low_outliers_excluded", "barcode_unreliable"):
        summary[name] = 0
        summary[name+"_sample"] = []
    summary["pack_mismatch_skipped"] = 0
    return dict(opportunities=rows[:200], competitors_overpriced=competitors, well_positioned=positioned[:50], undercut=undercut, summary=summary)