"""Stock planner (17 Oct 2026): days of stock left, what to reorder, and what
running out cost — for the own store, from its own sealed daily ledger.

Per own product over the last `days` sealed KSA days:
  velocity       units sold per in-stock day (ledger sales, measured days only)
  days_of_cover  current quantity / velocity
  reorder_qty    units to cover lead_days + cover_days at that velocity
  oos_days       sealed days the product closed at zero stock
  lost_units     oos_days x velocity          (estimate, labelled as such)
  competitor_revenue_while_oos
                 what measured competitors sold of the same product on the
                 days it was out at mine (real ledger facts, not an estimate)
"""
from collections import defaultdict
from datetime import timedelta

STATUS_ORDER = {"out": 0, "critical": 1, "low": 2, "ok": 3, "overstock": 4, "no_sales": 5}


def status_of(qty, velocity, days_cover, lead_days):
    if qty is not None and qty <= 0:
        return "out"
    if not velocity:
        return "no_sales"
    if days_cover is not None and days_cover <= lead_days:
        return "critical"
    if days_cover is not None and days_cover <= lead_days * 2:
        return "low"
    if days_cover is not None and days_cover > 120:
        return "overstock"
    return "ok"


def plan_row(qty, units, in_stock_days, oos_days, price, lead_days, cover_days):
    velocity = round(units / in_stock_days, 3) if units and in_stock_days else 0.0
    cover = round(qty / velocity, 1) if velocity and qty is not None and qty > 0 else (0.0 if qty is not None and qty <= 0 else None)
    reorder = max(0, round(velocity * (lead_days + cover_days) - max(qty or 0, 0))) if velocity else 0
    lost_units = round(oos_days * velocity, 1) if velocity else 0.0
    return {"velocity_per_day": velocity, "days_of_cover": cover, "reorder_qty": reorder,
            "oos_days": oos_days, "lost_units_est": lost_units,
            "lost_revenue_est": round(lost_units * price, 2) if price and lost_units else 0.0,
            "status": status_of(qty, velocity, cover, lead_days)}


async def planner(db, price_fn, days=30, lead_days=7, cover_days=30):
    import ledger
    from comparison_views import context
    from evidence_ledger import sales_map
    from stock_evidence import own_stock
    start, end = ledger.sealed_ksa_window(days)
    lo, hi = ledger.ksa_day_str(start), ledger.ksa_day_str(end - timedelta(seconds=1))
    own, products, cohorts = await context(db, price_fn)
    oid = own.get("id")
    sales = await sales_map(db, start, end)
    oos, seen = defaultdict(set), defaultdict(set)
    async for r in db.daily_ledger.find({"store_id": oid, "ksa_date": {"$gte": lo, "$lte": hi}},
                                        {"_id": 0, "sku": 1, "ksa_date": 1, "qty_available": 1, "in_stock": 1}):
        seen[r["sku"]].add(r["ksa_date"])
        if (r.get("qty_available") is not None and r["qty_available"] <= 0) or r.get("in_stock") is False:
            oos[r["sku"]].add(r["ksa_date"])
    rows = []
    for mp in products:
        sku = mp.get("sku")
        if not sku or mp.get("present_on_store") is False:
            continue
        stock = own_stock(mp)
        ev = sales.get((oid, mp.get("offer_id") or sku)) or {}
        out_days = oos.get(sku, set())
        in_days = len(seen.get(sku, set()) - out_days)
        price = price_fn(mp) or None
        row = {"sku": sku, "name_ar": mp.get("name_ar"), "name_en": mp.get("name_en"), "image_url": mp.get("image_url"),
               "barcode": mp.get("barcode"), "category": mp.get("category"), "price": price, "cost": mp.get("cost"),
               "quantity": stock["quantity"], "units_sold": ev.get("units") or 0, "days_tracked": len(seen.get(sku, ())),
               **plan_row(stock["quantity"], ev.get("units") or 0, in_days, len(out_days), price, lead_days, cover_days)}
        # Competitors' measured sales of this product while it was out at mine.
        comp = 0.0
        for s in (cohorts.get(sku) or {}).get("sellers", []):
            by_day = (sales.get((s["store_id"], s.get("offer_id") or s.get("sku"))) or {}).get("by_day") or {}
            comp += sum(v for d, v in by_day.items() if d in out_days)
        row["competitor_revenue_while_oos"] = round(comp, 2)
        row["reorder_value_at_cost"] = round(row["reorder_qty"] * mp["cost"], 2) if mp.get("cost") and row["reorder_qty"] else None
        rows.append(row)
    rows.sort(key=lambda r: (STATUS_ORDER[r["status"]], -(r["lost_revenue_est"] + r["competitor_revenue_while_oos"]), -r["velocity_per_day"]))
    summary = {s: sum(r["status"] == s for r in rows) for s in STATUS_ORDER}
    summary.update(lost_revenue_est=round(sum(r["lost_revenue_est"] for r in rows), 2),
                   competitor_revenue_while_oos=round(sum(r["competitor_revenue_while_oos"] for r in rows), 2),
                   reorder_value_at_cost=round(sum(r["reorder_value_at_cost"] or 0 for r in rows), 2),
                   reorder_products=sum(1 for r in rows if r["reorder_qty"] > 0))
    return {"rows": rows, "summary": summary, "window": {"from": lo, "to": hi, "days": days},
            "lead_days": lead_days, "cover_days": cover_days}
