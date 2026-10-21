"""Catalog and drill-down adapters with consistent offer and evidence semantics."""
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
import ledger
from comparison_views import context, position
from core.utils import get_stock_signal
from evidence_ledger import sales_map, measured_days
from observation_contract import gtin
from stock_evidence import own_stock

# The own-store sync compares the merchant catalogue with the public storefront;
# a product the storefront does not show is priced on a merchant_hidden_* basis.
# Its page returns 404 for shoppers (verified 13 Oct 2026: Applaws 2 kg,
# Farmina GI 2 kg, Farmina Quinoa 1.5 kg), so it is not a live offer of ours.
HIDDEN_FROM_STOREFRONT = ("merchant_hidden_from_storefront_inc_vat", "merchant_hidden_non_taxable")


def hidden_on_storefront(mp):
    return str(mp.get("price_basis") or "") in HIDDEN_FROM_STOREFRONT


def identity_check(own_price, cohort):
    """A shared barcode with an own price far from every competitor's usually
    means the wrong barcode on one side or a pack/size mismatch (13 Oct 2026:
    a Royal Canin adult food carrying the Persian 400 g barcode at 17.25 vs
    33-34.5; Caviara piece vs pack at 6.04 vs 11.96). Flagged for review,
    never corrected automatically."""
    prices = sorted(s["price"] for s in (cohort or {}).get("sellers", []) if s.get("price"))
    if not own_price or len(prices) < 2:
        return None
    mid = prices[len(prices) // 2] if len(prices) % 2 else (prices[len(prices) // 2 - 1] + prices[len(prices) // 2]) / 2
    ratio = own_price / mid
    if ratio < 0.6:
        return "own_price_far_below_market"
    if ratio > 1.6:
        return "own_price_far_above_market"
    return None


def verified_barcode(product):
    return str(product.get("barcode")) if gtin(product.get("barcode")) else str(product.get("sku")) if gtin(product.get("sku")) else None


def _oos_fields(cohort):
    oos = out_of_stock_competitors(cohort)
    return {"oos_competitors": len(oos),
            "oos_competitor_min_price": min((r["last_price"] for r in oos), default=None),
            "oos_competitor_max_price": max((r["last_price"] for r in oos), default=None)}


def market_share(mine, competitors):
    """One product's market size and my share, from ledger sales facts.

    mine/competitors: sales evidence ({units, revenue}) or None where a seller
    cannot be measured. The market size is the sum over measured sellers; the
    share is given only when every live seller is measured, so it never leaves
    out a seller whose sales we cannot see (as a share of the measured sellers
    would). A product nobody sold in the window has no share."""
    sellers = [mine, *competitors]
    measured = [e for e in sellers if e is not None]
    units = round(sum(e.get("units") or 0 for e in measured), 2) if measured else None
    revenue = round(sum(e.get("revenue") or 0 for e in measured), 2) if measured else None
    complete = mine is not None and len(measured) == len(sellers)
    reason = (None if complete and revenue else "own_sales_unmeasured" if mine is None
              else "competitor_sales_unmeasured" if not complete else "no_sales_in_window")
    return {"market_units_est": units, "market_revenue_est": revenue,
            "market_my_revenue_est": round(mine.get("revenue") or 0, 2) if mine is not None else None,
            "market_sellers_measured": len(measured), "market_sellers_total": len(sellers),
            "market_size_complete": complete,
            "market_share_pct": round((mine.get("revenue") or 0) / revenue * 100, 1) if reason is None else None,
            "market_unit_share_pct": round((mine.get("units") or 0) / units * 100, 1) if reason is None and units else None,
            "has_market_share": reason is None, "market_share_unavailable_reason": reason}


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
        # A listing whose sizes or flavours are its own rows (each priced and
        # compared) is not an offer: 327 such containers showed in My Products
        # with no price and no comparison (20 Oct 2026). A search still finds
        # it, so its sizes can be looked up by the parent's code.
        if mp.get("superseded_parent") and not search:
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
        share = market_share(sales.get((own.get("id"), mp.get("offer_id") or sku)) if price else None,
                             [sales.get((s["store_id"], s.get("offer_id") or s.get("sku"))) for s in c["sellers"]])
        pos = price_position(price, [s["price"] for s in c["sellers"]]) or {}
        row = {**mp, "sku": sku, "parent_sku": parent_sku, "price": price or None, "market_price": c["avg"], "is_my_product": True,
               "barcode": verified_barcode(mp),
               "category_candidate": mp.get("category"), "category": mp.get("category") if mp.get("category_source") in ("reviewed", "store_supplied", "import_file") else None,
               **stock, "my_quantity": stock["quantity"], "my_units_sold": units, "my_revenue_est": value,
               "qty_sold_est": units, "revenue_est": value, "my_stock_signal": get_stock_signal(stock["quantity"], stock["in_stock"]),
               "my_stock_status": "not_listed" if mp.get("present_on_store") is False else "hidden_on_store" if hidden_on_storefront(mp) else "own_catalog",
               "identity_check": identity_check(price, c),
               "num_competitors": len({s["store_id"] for s in c["sellers"]} | {s["store_id"] for s in current_excluded(c)}), "num_priced_competitors": len(c["sellers"]),
               "num_sellers": len(c["sellers"]), "competitor_min_price": c["min"], "competitor_max_price": c["max"],
               **_oos_fields(c), "competitor_offers": competitor_offers(c),
               "vs_my_price_pct": round((c["min"]-price)/price*100, 1) if c["min"] and price else None,
               "vs_lowest_pct": pos.get("vs_lowest_pct"), "vs_median_pct": pos.get("vs_median_pct"),
               "market_median_price": pos.get("market_median"), "price_rank": pos.get("rank"), "price_rank_of": pos.get("of"),
               "discount_pct": discount_pct(price, mp.get("original_price")) if mp.get("sale_price") else None,
               **share, **({"market_share_unavailable_reason": "own_out_of_stock"}
                           if share["market_share_unavailable_reason"] == "own_sales_unmeasured" and stock["in_stock"] is False else {}),
               "my_share_is_estimate": True, "cohort_id": c["cohort_id"], "price_policy": c["policy_version"],
               "excluded_sellers": c["excluded"], "source_observed_at": c["observed_at"],
               "market_position": position(own, mp, price, c), "source_tier": 0, "confidence_score": 99 if price else 0,
               "sales_basis": "orders_exact" if orders is not None else "inventory_proxy" if evidence else "unavailable"}
        rows.append(row)
    measurable = [r for r in rows if r["my_units_sold"] is not None]
    matched = sum(r["num_priced_competitors"] > 0 for r in rows)
    value = round(sum(r["my_revenue_est"] or 0 for r in measurable), 2) if measurable else None
    shared = [r for r in rows if r["has_market_share"]]
    share_market = round(sum(r["market_revenue_est"] for r in shared), 2) if shared else None
    share_mine = sum(r["market_my_revenue_est"] for r in shared)
    return {"rows": rows, "total": len(rows), "categories": sorted({r["category"] for r in rows if r.get("category")}),
            "_valid_until": min((c["valid_until"] for c in cohorts.values()), default=datetime.now(timezone.utc)+timedelta(seconds=300)),
            "kpis": {"total_products": len(rows), "matched_products": matched, "market_coverage_pct": round(matched/len(rows)*100, 1) if rows else 0,
                     "total_units_sold": sum(r["my_units_sold"] for r in measurable) if measurable else None,
                     "my_revenue": orders["revenue"] if orders is not None else value, "total_revenue": value,
                     "my_orders_count": orders["orders_count"] if orders is not None else None,
                     "my_revenue_source": "zid_orders" if orders is not None else "inventory_proxy" if measurable else "unavailable",
                     # Over products where every seller's sales are measured.
                     "market_revenue": share_market,
                     "avg_market_share": round(share_mine / share_market * 100, 1) if share_market else None,
                     "share_sample_size": len(shared),
                     "sales_evidence_products": len(measurable), "sales_window": {"from": start, "to": end},
                     "sales_days_measured": None if orders is not None else len(measured_days(sales, own.get("id"))),
                     "sales_days_expected": max(1, round((end - start).total_seconds() / 86400))}}


def discount_pct(price, original):
    return round((1 - price / original) * 100, 1) if price and original and original > price else None


def _median(values):
    v = sorted(values)
    return None if not v else v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2


def price_position(price, competitor_prices):
    """Where my price sits among the eligible competitor prices: rank 1 is the
    cheapest (ties share the better rank), gaps are relative to each reference."""
    prices = sorted(p for p in competitor_prices if p)
    if not price or not prices:
        return None
    lowest, avg, med = prices[0], sum(prices) / len(prices), _median(prices)

    def gap(ref):
        return round((price - ref) / ref * 100, 1)
    return {"rank": 1 + sum(p < price for p in prices), "of": len(prices) + 1,
            "vs_lowest_pct": gap(lowest), "vs_avg_pct": gap(avg), "vs_median_pct": gap(med),
            "market_median": round(med, 2), "market_avg": round(avg, 2), "market_lowest": lowest}


def unmeasured_reason(seller, platform):
    """Why a live seller has no measured sales for the period."""
    if seller.get("in_stock") is False or seller.get("qty_available") == 0:
        return "out_of_stock"          # nothing to sell: no stock movement to read
    if platform == "zid" or seller.get("is_own_store"):
        return "no_stock_movement"     # stock is published but did not move between readings
    return "not_published"             # the store shows neither stock levels nor a sold counter


async def seller_sales(db, own, mp, sellers, days):
    """Per-seller sold units and revenue for one product over the last `days`
    sealed KSA days, from the same ledger facts as every revenue figure.

    Each live seller gets units_sold/revenue_est (0 when measured without a
    sale) or None when its sales cannot be measured (the store shows neither
    stock levels nor a sold counter). Market totals cover measured sellers;
    unit/revenue shares are given only when every live seller is measured,
    so a share never leaves out a seller we cannot see."""
    import evidence_ledger
    import ledger_sales
    if evidence_ledger.sales_source() != "ledger":
        return None
    start, end = ledger.sealed_ksa_window(days)
    live = [s for s in sellers if s.get("price_status") == "live" and s.get("price")]
    keys = {s["store_id"]: (s["store_id"], (mp.get("offer_id") or mp.get("sku")) if s.get("is_own_store")
                            else (s.get("offer_id") or s.get("sku"))) for s in live}
    found = await ledger_sales.offer_sales(db, keys.values(), start, end)
    groups = (await ledger_sales.meta(db)).get("groups") or []
    per_day, measured_days = {}, set()
    for s in sellers:
        ev = found.get(keys.get(s["store_id"])) if any(s is x for x in live) else None
        g = ledger_sales.shared_group_of(groups, s["store_id"])
        s.update(units_sold=ev["units"] if ev else None, revenue_est=ev["revenue"] if ev else None,
                 sales_days_measured=ev["days_measured"] if ev else 0, sales_measured=bool(ev),
                 sales_basis=(ev or {}).get("source"),
                 shared_stock_with=[n for sid, n in zip(g["members"], g["names"]) if sid != s["store_id"]] if g else [])
        if ev:
            measured_days.update(ev["days"])
            for d, u in ev["by_day"].items():
                row = per_day.setdefault(d, {"date": d, "units": 0})
                row["units"] += u
                row[s.get("store_name") or s["store_id"]] = round(row.get(s.get("store_name") or s["store_id"], 0) + u, 2)
    measured = [s for s in live if s["sales_measured"]]
    units = round(sum(s["units_sold"] for s in measured), 2)
    revenue = round(sum(s["revenue_est"] for s in measured), 2)
    complete = bool(live) and len(measured) == len(live)
    for s in live:
        s.update(unit_share_pct=round(s["units_sold"] / units * 100, 1) if complete and units and s["sales_measured"] else None,
                 revenue_share_pct=round(s["revenue_est"] / revenue * 100, 1) if complete and revenue and s["sales_measured"] else None)
    velocity = [{**per_day.get(d, {"date": d, "units": 0}), "units": round(per_day.get(d, {}).get("units", 0), 2)}
                for d in sorted(measured_days)]
    mine = next((s for s in live if s.get("is_own_store")), None)
    platforms = {d["id"]: d.get("platform") async for d in db.stores.find(
        {"id": {"$in": [s["store_id"] for s in live]}}, {"_id": 0, "id": 1, "platform": 1})}
    if not measured:
        units = revenue = None                 # nothing measured is not "0 sold"
    return {"units": units, "revenue": revenue, "sellers_live": len(live), "sellers_measured": len(measured),
            "complete": complete, "days": days, "window": {"from": start, "to": end},
            "unmeasured_stores": [s.get("store_name") for s in live if not s["sales_measured"]],
            "unmeasured": [{"store": s.get("store_name"), "reason": unmeasured_reason(s, platforms.get(s["store_id"]))}
                           for s in live if not s["sales_measured"]],
            "my_unit_share_pct": mine.get("unit_share_pct") if mine else None,
            "my_revenue_share_pct": mine.get("revenue_share_pct") if mine else None,
            "velocity": {"velocity": velocity, "total_units": units,
                         "avg_daily": round(units / len(measured_days), 2) if measured_days else None,
                         "stores": [s.get("store_name") or s["store_id"] for s in measured if s["units_sold"]]}}


def current_excluded(cohort):
    """One excluded row per store — its newest reading — and none for a store
    that has a live offer. A store's earlier offers (identity changes, the
    pre-8 Oct crawl) listed each competitor twice: "7 stores not compared"
    for 4 stores (client report, 20 Oct 2026)."""
    live = {r["store_id"] for r in cohort.get("sellers", [])}
    best = {}
    for r in cohort.get("excluded", []):
        sid = r.get("store_id")
        if sid in live:
            continue
        ts = str(r.get("crawled_at") or "")
        if sid not in best or ts > str(best[sid].get("crawled_at") or ""):
            best[sid] = r
    return sorted(best.values(), key=lambda r: (r.get("price") or 0))


def competitor_offers(cohort):
    """Every competitor behind a product's comparison: the live sellers (used:
    their prices set the lowest, the median and any suggested price) and, one
    per store, those left out with the reason. Pricing names the stores its
    suggestion rests on (client request, 21 Oct 2026)."""
    out = [{"store_id": r["store_id"], "store_name": r.get("store_name"), "price": r.get("price"),
            "in_stock": r.get("in_stock"), "url": r.get("product_url"), "seen_at": r.get("crawled_at"),
            "used": True, "reason": None} for r in cohort.get("sellers", [])]
    out += [{"store_id": r["store_id"], "store_name": r.get("store_name"), "price": r.get("price"),
             "in_stock": r.get("in_stock"), "url": r.get("product_url"), "seen_at": r.get("crawled_at"),
             "used": False, "reason": r.get("excluded_reason")} for r in current_excluded(cohort)]
    return out


def out_of_stock_competitors(cohort):
    rows = [r for r in current_excluded(cohort) if r.get("excluded_reason") == "out_of_stock" and r.get("price")]
    return [{"store_id": r["store_id"], "store_name": r.get("store_name"), "last_price": r.get("price"),
             "seen_at": r.get("crawled_at")} for r in rows]


async def detail(db, sku, days, price_fn, competitor_store_ids=None):
    own, products, cohorts = await context(db, price_fn, competitor_store_ids)
    mp = next((p for p in products if p.get("sku") == sku), None)
    if mp is None:
        raise HTTPException(404, "Product not in own catalog; use a store-specific offer")
    c, price = cohorts[sku], price_fn(mp)
    stock = own_stock(mp)
    sellers = []
    for row in c["sellers"] + current_excluded(c):
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
    for s in sellers:
        s.update(discount_pct=discount_pct(s.get("price"), s.get("original_price") if not s.get("is_own_store") else
                                           mp.get("original_price") if mp.get("sale_price") else None))
    market = await seller_sales(db, own, mp, sellers, days)
    history, since = {}, datetime.now(timezone.utc)-timedelta(days=days)
    pairs = [(s["store_id"], s["offer_id"]) for s in c["sellers"] if s.get("offer_id")] + ([(own.get("id"), mp["offer_id"])] if mp.get("offer_id") else [])
    # Each (store_id, offer_id) rides the (store_id, offer_id, crawled_at) index;
    # offer_id alone has no index and scanned a month of snapshots.
    for sid, oid in pairs:
        async for snap in db.product_snapshots.find({"store_id": sid, "offer_id": oid, "crawled_at": {"$gte": since}, "observation_version": 2, "comparable": True},
                                                    {"_id": 0, "store_name": 1, "crawled_at": 1, "price": 1, "qty_available": 1}).sort("crawled_at", 1):
            history.setdefault(snap["store_name"], []).append({"date": snap["crawled_at"].isoformat(), "price": snap["price"], "qty": snap.get("qty_available")})
    return {**mp, **stock, "price": price or None, "sale_price": mp.get("sale_price") if price else None,
            "barcode": verified_barcode(mp), "source_tier": 0 if price else None, "confidence_score": 99 if price else None,
            "historical_price": (mp.get("historical_price") if mp.get("historical_price") is not None else mp.get("price")) if not price else None,
            "price_status": "live" if price else "unavailable",
            "is_my_product": True, "store_prices": sellers, "seller_count": len(c["sellers"]),
            "competitors_total": len({r["store_id"] for r in c["sellers"]} | {r["store_id"] for r in current_excluded(c)}),
            "out_of_stock_competitors": out_of_stock_competitors(c),
            "seller_summary": {"live": len(c["sellers"]), "stale": len(current_excluded(c)), "oos": sum(s.get("in_stock") is False for s in current_excluded(c))},
            "price_range": {"min": c["min"], "max": c["max"], "avg": c["avg"]} if c["min"] else {},
            "total_volume": market["units"] if market else None, "market_sales": market,
            "position": price_position(price, [s["price"] for s in c["sellers"]]),
            "market_position": position(own, mp, price, c), "cohort_id": c["cohort_id"],
            "history": history, "velocity": market["velocity"] if market else {"velocity": [], "avg_daily": None, "total_units": None},
            "policy_version": c["policy_version"]}


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