"""iter79 — Market Share.

ONE question, answered without inventing anything: of the sales Daleel can
actually MEASURE inside its tracked market, how much is ours?

What "measurable" means here, in order of strength:

  1. `orders_exact`      — my own store's Zid orders ledger. Real invoices.
  2. `sold_counter_diff` — a store publishes a CUMULATIVE units-sold counter
                           (Salla's "تم بيعه أكثر من N مرة", Zid's sold_count).
                           Only valid uncapped changes are observation proxies,
                           not verified transaction evidence.
  3. `stock_depletion`   — a store publishes stock levels; a drop between two
                           crawls is an inventory movement proxy. Adjustments,
                           transfers and restocks can overstate or understate sales.
  4. `measured_zero`     — the store DOES publish a signal, was crawled at
                           least twice in the window, and this product's
                           counter/stock never moved. This does not prove zero sales.
  5. `unavailable`       — the store publishes neither signal, or was crawled
                           fewer than twice. NOT zero. The number is withheld
                           and the reason is carried on the row.

Nothing in this module extrapolates. The ±50% Salla category-velocity model
(`salla_revenue_estimate`) is deliberately NOT used: a ±50% numerator over a
partial denominator is not a share, and the client asked for no fabricated
figures. Store-level estimates stay where they already live (the Market
Strength ranking), clearly labelled.

Denominator honesty: every row carries `sellers_total` vs `sellers_with_sales`.
A share computed over 2 of 5 sellers is a share of what we can see, and the row
says so — it is never presented as a share of the whole market.
"""

import logging
from datetime import datetime, timedelta, timezone

from core.utils import barcode_keys, canonical_barcode, get_stock_signal
from ledger import ksa_day_str
from evidence_ledger import sales_map
from price_cohort import FIELDS, build_cohorts, identity_agrees
from stock_evidence import own_stock
from price_cohort import exclusion
from pack_guard import (
    slug_descriptor, stated_weight_grams, slug_pack_reject, cluster_outliers,
)

logger = logging.getLogger("market_share")

# Sales-source labels (also the UI's source chips)
SRC_ORDERS = "orders_exact"
SRC_COUNTER = "sold_counter_diff"
SRC_STOCK = "stock_depletion"
SRC_ZERO = "measured_zero"
SRC_NONE = "unavailable"

ACTUAL_SOURCES = {SRC_ORDERS}
APPROX_SOURCES = {SRC_COUNTER, SRC_STOCK, SRC_ZERO}

REASON_NO_SIGNAL = "store_publishes_no_sales_signal"
REASON_ONE_CRAWL = "fewer_than_two_crawls_in_window"
REASON_NO_SELLER_DATA = "no_seller_in_this_market_has_sales_data"
REASON_NOT_CRAWLED = "store_not_crawled_in_window"

# Match strength per identity key class — the strongest key that linked a
# competitor listing to one of our products.
MATCH_STRENGTH = {
    "barcode": 99,          # GTIN on both sides (or numeric SKU used as GTIN)
    "sku": 95,              # identical SKU string
    "variant_barcode": 90,  # our GTIN inside the seller's variant array
    "variant_sku": 88,
    "product_match": 85,    # matcher row (non-barcode method)
}

FRESH_DAYS = 7              # a price older than this weakens row confidence
MISSING_ROWS_CAP = 800
SELLERS_PER_ROW_CAP = 25

# Two listings whose prices differ by this much are probably not the same trade
# item (a pouch sharing a bag's barcode, a single sharing a carton's SKU). We do
# NOT drop them — the client asked never to exclude a seller silently — the row
# is marked LOW confidence with the ratio stated, so the number is visible and
# so is the doubt.
PRICE_SPREAD_SUSPECT = 3.0


def _day(dt):
    return ksa_day_str(dt)


def _aware(v):
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


def _pct(part, whole):
    if part is None or not whole or whole <= 0:
        return None
    return round(part / whole * 100, 2)


def _delta_pct(now_v, prev_v):
    if now_v is None or prev_v in (None, 0):
        return None
    return round((now_v - prev_v) / prev_v * 100, 1)


async def _read_sales(db, start, end, sealed=True):
    return await sales_map(db, start, end, sealed=sealed)


async def _retired_read_sales(db, start, end):
    """Windowed units/revenue per (store_id, sku) from the sealed daily rollups,
    keeping WHICH method produced the figure so the row can label its source.

    Method exclusivity mirrors the estimator every other surface uses: if the
    pair had any positive counter step in the window, the counter wins and stock
    depletion is ignored for that pair.
    """
    match = {"date": {"$gte": _day(start), "$lte": _day(end - timedelta(seconds=1))}}
    acc = {}
    cursor = db.sku_sales_daily.find(
        match, {"_id": 0, "store_id": 1, "sku": 1, "units_sold": 1, "rev_sold": 1,
                "units_qty": 1, "rev_qty": 1}).batch_size(2000)
    async for r in cursor:
        key = (r.get("store_id"), r.get("sku"))
        if None in key:
            continue
        a = acc.setdefault(key, [0, 0.0, 0, 0.0])
        a[0] += r.get("units_sold") or 0
        a[1] += r.get("rev_sold") or 0.0
        a[2] += r.get("units_qty") or 0
        a[3] += r.get("rev_qty") or 0.0
    out = {}
    for key, a in acc.items():
        if a[0] > 0:
            out[key] = {"units": a[0], "revenue": round(a[1], 2), "source": SRC_COUNTER}
        elif a[2] > 0:
            out[key] = {"units": a[2], "revenue": round(a[3], 2), "source": SRC_STOCK}
    return out


async def _store_signals(db, start, end):
    """Per store: how many days it was crawled in the window and whether it
    publishes a sales signal at all. This is what separates a genuine
    "sold nothing" from "we cannot see this store's sales".

    Days come from `daily_ledger_store` (one row per store per KSA day, written
    by every crawl) and fall back to `metric_daily_rollups`. Signal CAPABILITY
    comes from the ledger's own fields, not from the derived sales rollup — a
    store that publishes a counter must not be reported as signal-less just
    because the rollup has not been rebuilt yet.
    """
    d_from, d_to = _day(start), _day(end - timedelta(seconds=1))
    days_by_store = {}
    async for r in db.daily_ledger_store.find(
            {"ksa_date": {"$gte": d_from, "$lte": d_to}},
            {"_id": 0, "store_id": 1, "ksa_date": 1}):
        days_by_store.setdefault(r["store_id"], set()).add(r["ksa_date"])
    async for r in db.metric_daily_rollups.find(
            {"date": {"$gte": d_from, "$lte": d_to}},
            {"_id": 0, "store_id": 1, "date": 1}):
        days_by_store.setdefault(r["store_id"], set()).add(r["date"])

    capability = {}
    async for r in db.daily_ledger.aggregate([
        {"$match": {"ksa_date": {"$gte": d_from, "$lte": d_to}}},
        {"$group": {"_id": "$store_id",
                    "counter": {"$max": "$sold_count_cumulative"},
                    "qty": {"$max": "$qty_available"}}},
    ]):
        capability[r["_id"]] = ("counter" if (r.get("counter") or 0) > 0 else
                                "stock" if (r.get("qty") or 0) > 0 else "none")
    async for r in db.sku_sales_daily.aggregate([
        {"$match": {"date": {"$gte": d_from, "$lte": d_to}}},
        {"$group": {"_id": "$store_id",
                    "counter": {"$sum": {"$cond": [{"$gt": ["$units_sold", 0]}, 1, 0]}},
                    "stock": {"$sum": {"$cond": [{"$gt": ["$units_qty", 0]}, 1, 0]}}}},
    ]):
        if capability.get(r["_id"], "none") == "none":
            capability[r["_id"]] = ("counter" if r["counter"] else
                                    "stock" if r["stock"] else "none")

    out = {}
    for sid in set(days_by_store) | set(capability):
        out[sid] = {"days_observed": len(days_by_store.get(sid, ())),
                    "signal": capability.get(sid, "none")}
    return out


async def _latest_snapshots(db, since, min_confidence):
    active = await db.stores.distinct("id", {"is_active": {"$ne": False}})
    return await db.product_snapshots.aggregate([
        {"$match": {"store_id": {"$in": active}, "crawled_at": {"$gte": since}, "offer_id": {"$type": "string"}}},
        {"$sort": {"crawled_at": -1}}, {"$group": {"_id": "$offer_id", "row": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$row"}}, {"$project": FIELDS},
    ], allowDiskUse=True).to_list(200000)


async def _retired_latest_snapshots(db, since, min_confidence):
    """Latest accepted snapshot per (sku, store) in the window — the price,
    stock and slug every row is built from. Lean projection (no variant arrays:
    those are fetched separately and only for our own keys)."""
    pipeline = [
        {"$match": {"crawled_at": {"$gte": since},
                    "confidence_score": {"$gte": min_confidence}}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {
            "_id": {"sku": "$sku", "store_id": "$store_id"},
            "sku": {"$first": "$sku"},
            "store_id": {"$first": "$store_id"},
            "store_name": {"$first": "$store_name"},
            "price": {"$first": "$price"},
            "sale_price": {"$first": "$sale_price"},
            "discount_pct": {"$first": "$discount_pct"},
            "barcode": {"$first": "$barcode"},
            "qty_available": {"$first": "$qty_available"},
            "in_stock": {"$first": "$in_stock"},
            "product_url": {"$first": "$product_url"},
            "confidence_score": {"$first": "$confidence_score"},
            "crawled_at": {"$first": "$crawled_at"},
        }},
    ]
    return await db.product_snapshots.aggregate(pipeline, allowDiskUse=True).to_list(200000)


async def _variant_links(db, own_keys, since):
    return {}  # Discovery-only arrays may never supply a parent's price or units.


async def _retired_variant_links(db, own_keys, since):
    """(store_id, sku) → (own_key, key_class) for competitors whose VARIANT
    arrays carry one of our GTINs/SKUs. Indexed multikey lookups (iter73x), so
    this stays a bounded query instead of dragging variant arrays through the
    main pass."""
    links = {}
    keys = list(own_keys)
    if not keys:
        return links
    for field, klass in (("variant_barcodes", "variant_barcode"),
                         ("variant_skus", "variant_sku")):
        for chunk_start in range(0, len(keys), 5000):
            chunk = keys[chunk_start:chunk_start + 5000]
            async for r in db.product_snapshots.aggregate([
                {"$match": {field: {"$in": chunk}, "crawled_at": {"$gte": since}}},
                {"$group": {"_id": {"store_id": "$store_id", "sku": "$sku"},
                            "hits": {"$first": f"${field}"}}},
            ], allowDiskUse=True):
                pair = (r["_id"]["store_id"], r["_id"]["sku"])
                if pair in links:
                    continue
                hit = next((h for h in (r.get("hits") or []) if h in own_keys), None)
                if hit:
                    links[pair] = (hit, klass)
    return links


def _resolve_units(pair, sales, store_signals, is_own, own_units):
    """units/revenue/source/reason for one (store, sku) pair."""
    if is_own and own_units is not None:
        return (own_units.get("units", 0), own_units.get("revenue", 0.0),
                SRC_ORDERS, None)
    row = sales.get(pair)
    if row:
        return row["units"], row["revenue"], row["source"], None
    sg = store_signals.get(pair[0]) or {}
    if not sg.get("days_observed"):
        return None, None, SRC_NONE, REASON_NOT_CRAWLED
    if sg.get("days_observed", 0) < 2:
        return None, None, SRC_NONE, REASON_ONE_CRAWL
    # Store-wide capability is not evidence that this product was observed twice.
    return None, None, SRC_NONE, REASON_NO_SIGNAL


def _row_confidence(sellers, my_source, fresh_days=FRESH_DAYS, now=None):
    """High / Medium / Low / Unavailable + the reason, from match strength,
    denominator coverage and price freshness."""
    now = now or datetime.now(timezone.utc)
    with_sales = [s for s in sellers if s["units"] is not None]
    if not with_sales:
        return "unavailable", REASON_NO_SELLER_DATA
    coverage = len(with_sales) / len(sellers)
    strengths = [s.get("match_strength") or 0 for s in sellers if not s.get("is_own")]
    weakest = min(strengths) if strengths else 99
    ages = []
    for s in sellers:
        ca = _aware(s.get("last_crawl_at"))
        if isinstance(ca, datetime):
            ages.append((now - ca).days)
    oldest = max(ages) if ages else None
    if (all(s.get("units_source") == SRC_ORDERS for s in sellers) and coverage >= 0.999 and weakest >= 95
            and (oldest is None or oldest <= fresh_days)):
        return "high", None
    if coverage >= 0.5 and weakest >= 88:
        return "medium", (f"sales data for {len(with_sales)} of {len(sellers)} sellers"
                          if coverage < 0.999 else
                          ("my own units are measured, not invoiced"
                           if my_source not in ACTUAL_SOURCES else
                           f"prices up to {oldest}d old"))
    return "low", (f"sales data for {len(with_sales)} of {len(sellers)} sellers"
                   if coverage < 0.5 else f"weakest identity match {weakest}%")


def _apply_pack_guard(my_name, sellers, own_price):
    """Drop sellers that are demonstrably a DIFFERENT pack size, and price
    outliers the rest of the market contradicts. Reuses the iter78 guard so the
    Market Share tab cannot disagree with the Scanner."""
    my_weight = stated_weight_grams(my_name)
    excluded = []
    kept = []
    for s in sellers:
        if s.get("is_own"):
            kept.append(s)
            continue
        slug = slug_descriptor(s.get("product_url") or "")
        reject, reason = slug_pack_reject(my_name or "", my_weight, slug)
        if reject:
            s["excluded_reason"] = reason
            s["excluded_detail"] = slug[:120]
            excluded.append(s)
        else:
            kept.append(s)
    priced = [(s["store_id"], s["price"]) for s in kept
              if not s.get("is_own") and (s.get("price") or 0) > 0]
    if len(priced) >= 2:
        outliers = cluster_outliers(priced, own_price=own_price)
        if outliers:
            still = []
            for s in kept:
                info = outliers.get(s["store_id"]) if not s.get("is_own") else None
                if info:
                    s["excluded_reason"] = "price_outlier_vs_cluster"
                    s["excluded_detail"] = (
                        f"{info['ratio']}x below the {info['cluster_median']} SAR "
                        f"{info['references']} other sellers agree on")
                    excluded.append(s)
                else:
                    still.append(s)
            kept = still
    return kept, excluded


def _price_spread(sellers):
    """(ratio, warning) across every kept seller including us."""
    prices = [s["price"] for s in sellers if (s.get("price") or 0) > 0]
    if len(prices) < 2 or min(prices) <= 0:
        return None, None
    ratio = round(max(prices) / min(prices), 2)
    if ratio < PRICE_SPREAD_SUSPECT:
        return ratio, None
    return ratio, (f"seller prices differ by {ratio}× ({min(prices)} to {max(prices)}) — "
                   "one of these listings may be a different pack size")


def _price_stats(sellers):
    prices = [s["price"] for s in sellers if not s.get("is_own") and (s.get("price") or 0) > 0]
    if not prices:
        return {"min": None, "max": None, "avg": None, "n": 0}
    return {"min": round(min(prices), 2), "max": round(max(prices), 2),
            "avg": round(sum(prices) / len(prices), 2), "n": len(prices)}


def aggregate_groups(my_rows, missing_rows, key):
    """Brand / category rollup over a SET of product rows.

    Shared by the dataset build and by the filtered endpoints, so a filtered
    Brands/Categories table is computed exactly the way the unfiltered one is.
    """
    bucket = {}

    def _acc(name, row, mine_flag):
        b = bucket.setdefault(name, {
            "units": 0, "revenue": 0.0, "my_units": 0, "my_revenue": 0.0,
            "products": 0, "my_products": 0, "measured_products": 0,
            "top_products": [], "stores": {}, "prev_units": 0, "prev_revenue": 0.0,
            "missing_products": 0, "missing_value": 0.0,
            "my_observed": 0, "units_observed": 0, "bases": set(),
            "share_my_units": 0, "share_units": 0, "share_my_revenue": 0.0,
            "share_revenue": 0.0, "share_products": 0,
        })
        b["products"] += 1
        if mine_flag:
            b["my_products"] += 1
        if row.get("market_revenue") is not None:
            b["measured_products"] += 1
            b['bases'].add(row.get('market_value_basis', 'unknown'))
            b["units"] += row.get("market_units") or 0
            b["revenue"] += row.get("market_revenue") or 0
            b["prev_units"] += (row.get("trend") or {}).get("prev_units") or 0
            b["prev_revenue"] += (row.get("trend") or {}).get("prev_revenue") or 0
            b["top_products"].append({"sku": row["sku"], "name": row["name"],
                                      "units": row.get("market_units") or 0,
                                      "revenue": row.get("market_revenue") or 0,
                                      "in_catalog": mine_flag})
        if mine_flag:
            b["my_units"] += row.get("my_units") or 0
            b["my_revenue"] += row.get("my_revenue") or 0
            b['my_observed'] += row.get('my_units') is not None
            if row.get('share_comparable') and all(row.get(k) is not None for k in ('my_units', 'my_revenue', 'market_units', 'market_revenue')):
                b['share_products'] += 1
                b['share_my_units'] += row['my_units']
                b['share_units'] += row['market_units']
                b['share_my_revenue'] += row['my_revenue']
                b['share_revenue'] += row['market_revenue']
        else:
            b["missing_products"] += 1
            b["missing_value"] += row.get("market_revenue") or 0
        for s in row.get("sellers", []):
            if s.get("is_own"):
                continue
            st = b["stores"].setdefault(s["store_name"], {"units": 0, "revenue": 0.0})
            st["units"] += s.get("units") or 0
            st["revenue"] += s.get("revenue") or 0

    for row in my_rows or []:
        if row.get(key):
            _acc(row[key], row, True)
    for row in missing_rows or []:
        if row.get(key):
            _acc(row[key], row, False)

    total_rev = sum(v["revenue"] for v in bucket.values())
    total_units = sum(v["units"] for v in bucket.values())
    bases = set().union(*(v['bases'] for v in bucket.values())) if bucket else set()
    common_basis = len(bases) == 1 and 'unknown' not in bases
    out = []
    for name, v in bucket.items():
        out.append({
            key: name,
            "units": v["units"] if v['measured_products'] else None,
            "revenue": round(v["revenue"], 2) if v['measured_products'] and len(v['bases']) == 1 else None,
            "revenue_share_pct": _pct(v["revenue"], total_rev) if v['measured_products'] and common_basis else None,
            "unit_share_pct": _pct(v["units"], total_units) if v['measured_products'] and common_basis else None,
            "my_units": v["my_units"] if v['my_observed'] else None,
            "my_revenue": round(v["my_revenue"], 2) if v['my_observed'] else None,
            "my_revenue_share_pct": _pct(v['share_my_revenue'], v['share_revenue']) if v['share_products'] else None,
            "my_unit_share_pct": _pct(v['share_my_units'], v['share_units']) if v['share_products'] else None,
            "share_products": v['share_products'],
            "products": v["products"], "my_products_count": v["my_products"],
            "measured_products": v["measured_products"],
            "missing_products": v["missing_products"],
            "missing_opportunity_value": round(v["missing_value"], 2),
            "top_products": sorted(v["top_products"], key=lambda p: -p["revenue"])[:5],
            "top_stores": sorted([{"store_name": k, "units": s["units"],
                                   "revenue": round(s["revenue"], 2)}
                                  for k, s in v["stores"].items()],
                                 key=lambda s: -s["revenue"])[:5],
            "trend": {"units_pct": _delta_pct(v["units"], v["prev_units"]),
                      "revenue_pct": _delta_pct(v["revenue"], v["prev_revenue"]),
                      "basis": "previous equal-length window"},
            "confidence": ("unavailable" if v["measured_products"] == 0 else
                           "medium" if v["measured_products"] >= max(3, 0.3 * v["products"])
                           else "low"),
            "coverage": f"{v['measured_products']} of {v['products']} products have measurable sales",
        })
    return sorted(out, key=lambda r: -(r["revenue"] or 0))


def quality_summary(my_rows, orders_connected):
    return {
        "own_orders_ledger_connected": bool(orders_connected),
        "my_products_with_brand": sum(1 for r in my_rows if r["brand"]),
        "my_products_brand_derived": sum(1 for r in my_rows if r["brand_source"] == "derived_from_name"),
        "my_products_with_category": sum(1 for r in my_rows if r["category"]),
        "rows_high_confidence": sum(1 for r in my_rows if r["confidence"] == "high"),
        "rows_medium_confidence": sum(1 for r in my_rows if r["confidence"] == "medium"),
        "rows_low_confidence": sum(1 for r in my_rows if r["confidence"] == "low"),
        "rows_unavailable": sum(1 for r in my_rows if r["confidence"] == "unavailable"),
        "rows_flagged_price_spread": sum(1 for r in my_rows if r["price_spread_warning"]),
        "sellers_excluded_pack_mismatch": sum(len(r["excluded_sellers"]) for r in my_rows),
    }


def summarize(my_rows, missing_rows, store_rows, *, catalog_total, orders_connected,
              missing_total=None, brands=0, categories=0):
    """The KPI block. Called once for the whole window and again, unchanged, for
    any filtered subset — so a filtered headline is the same arithmetic."""
    measured_rows = [r for r in my_rows if r["market_revenue"] is not None]
    contested = [r for r in measured_rows if r["contested"]]
    sole = [r for r in measured_rows if r["sole_seller"]]
    contested = [r for r in contested if r.get("my_revenue") is not None and r.get("share_comparable")]
    my_measured = [r for r in contested if r["my_revenue"] is not None]
    total_my_rev = round(sum(r["my_revenue"] or 0 for r in my_measured), 2)
    total_mkt_rev = round(sum(r["market_revenue"] or 0 for r in contested), 2)
    total_my_units = sum(r["my_units"] or 0 for r in my_measured)
    total_mkt_units = sum(r["market_units"] or 0 for r in contested)
    own_units_source = (SRC_ORDERS if orders_connected else
                        (SRC_COUNTER if any(r["my_units_source"] == SRC_COUNTER for r in my_rows)
                         else SRC_STOCK if any(r["my_units_source"] == SRC_STOCK for r in my_rows)
                         else SRC_NONE))
    return {
        "tracked_stores": len(store_rows),
        "stores_with_sales_data": sum(1 for s in store_rows if s["sales_data_available"]),
        "my_catalog_products": catalog_total,
        "products_with_tracked_competitor": sum(1 for r in my_rows if r["competitor_count"] > 0),
        "products_with_measurable_market": len(measured_rows),
        "products_contested": len(contested),
        "products_sole_seller": len(sole),
        "sole_seller_revenue": round(sum(r["my_revenue"] or 0 for r in sole), 2),
        "share_basis": ("products where at least one OTHER tracked seller's sales are "
                        "measurable — products only we sell are reported separately"),
        "my_units": total_my_units if my_measured else None,
        "my_revenue": total_my_rev if my_measured else None,
        "market_units": total_mkt_units if my_measured else None,
        "market_revenue": total_mkt_rev if my_measured else None,
        "my_unit_share_pct": _pct(total_my_units, total_mkt_units) if my_measured else None,
        "my_revenue_share_pct": _pct(total_my_rev, total_mkt_rev) if my_measured else None,
        "my_units_source": own_units_source,
        "missing_products_total": (missing_total if missing_total is not None
                                   else len(missing_rows)),
        "missing_opportunity_value": round(sum(m["market_revenue"] or 0 for m in missing_rows), 2),
        "brands_resolved": brands,
        "categories_tracked": categories,
    }


async def build_dataset(db, days, own_store_id, *, own_price_fn, brand_fn,
                        category_fn, orders_by_sku, min_confidence,
                        window_start, window_end, sealed=True, now=None, competitor_store_ids=None):
    """The whole Market Share dataset for ONE window. Endpoints slice, filter
    and paginate this; it is computed once and page-cached."""
    now = now or datetime.now(timezone.utc)
    span = max(1, (window_end - window_start).days)
    prev_end, prev_start = window_start, window_start - timedelta(days=span)
    snap_since = now - timedelta(days=days)

    stores = {s["id"]: s for s in await db.stores.find(
        {"is_active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1, "platform": 1, "is_own_store": 1,
             "is_active": 1, "last_crawl_at": 1, "last_crawl_status": 1}).to_list(200)}
    if competitor_store_ids is not None:
        stores = {sid: s for sid, s in stores.items() if sid == own_store_id or sid in competitor_store_ids}

    sales = await _read_sales(db, window_start, window_end, sealed=sealed)
    prev_sales = await _read_sales(db, prev_start, prev_end, sealed=sealed)
    signals = await _store_signals(db, window_start, window_end)
    snaps = [s for s in await _latest_snapshots(db, snap_since, min_confidence) if s.get("store_id") in stores]

    my_rows = await db.my_products.find(
        {}, {"_id": 0, "sku": 1, "name_ar": 1, "name_en": 1, "price": 1,
             "sale_price": 1, "original_price": 1, "price_basis": 1,
             "quantity": 1, "in_stock": 1, "brand": 1, "category": 1,
             "barcode": 1, "brand_source": 1, "category_source": 1,
             "last_synced_at": 1, "present_on_store": 1, "currency": 1, "offer_id": 1,
             "known_variant_parent": 1, "quarantine_active": 1, "price_unavailable_reason": 1,
             "historical_quantity": 1, "historical_quantity_at": 1, "quantity_observed_at": 1}).to_list(50000)
    my_by_sku = {r["sku"]: r for r in my_rows if r.get("sku")}
    cohorts = await build_cohorts(db, my_rows, own_store_id, own_price_fn, now=now, competitor_store_ids=competitor_store_ids)
    cohort_links = {}
    cohort_exclusions = {}
    for own_sku, cohort in cohorts.items():
        for offer in cohort["excluded"]:
            cohort_exclusions[(own_sku, offer["store_id"], offer.get("offer_id"))] = offer["excluded_reason"]
        for offer in cohort['sellers'] + cohort['excluded']:
            cohort_links.setdefault((offer['store_id'], offer.get('offer_id')), set()).add(own_sku)

    # ── identity: every key that resolves to one of OUR products ────────────
    own_key_index = {}          # normalized key -> (my_sku, key_class)
    for sku, r in my_by_sku.items():
        for k in barcode_keys(sku):
            own_key_index.setdefault(k, (sku, "barcode" if len(k) >= 8 and k.isdigit() else "sku"))
        own_key_index.setdefault(str(sku).strip().lower(), (sku, "sku"))
        for k in barcode_keys(r.get("barcode")):
            own_key_index.setdefault(k, (sku, "barcode"))

    alias = {}                  # (store_id, competitor_sku) -> (my_sku, strength, method)
    async for m in db.product_matches.find(
            {"identity_version": 2}, {"_id": 0, "my_sku": 1, "competitor_sku": 1, "competitor_store_id": 1,
                 "confidence": 1, "match_method": 1}):
        if not (m.get("my_sku") in my_by_sku and m.get("competitor_sku")
                and m.get("competitor_store_id")):
            continue
        alias[(m["competitor_store_id"], m["competitor_sku"])] = (
            m["my_sku"], int(m.get("confidence") or 85), m.get("match_method") or "product_match")

    variant_links = await _variant_links(db, set(own_key_index.keys()), snap_since)

    # catalog names / brand / category for every SKU we may render
    catalog = {}
    async for p in db.products.find(
            {}, {"_id": 0, "sku": 1, "offer_id": 1, "name_ar": 1, "name_en": 1, "brand": 1,
                 "category": 1, "brand_source": 1, "category_source": 1, "barcode": 1}).batch_size(2000):
        if p.get("offer_id"):
            catalog[p["offer_id"]] = p

    # ── group every (sku, store) observation under a canonical product ──────
    mine = {}                   # my_sku -> {"sellers": [...]}
    others = {}                 # canonical key -> {"sellers": [...], "names": set}
    for s in snaps:
        sid, sku = s.get("store_id"), s.get("sku")
        if not sid or not sku:
            continue
        is_own = sid == own_store_id
        my_sku, klass, strength = None, None, None
        if is_own and sku in my_by_sku:
            my_sku, klass, strength = sku, "own", 100
        if my_sku is None:
            al = alias.get((sid, sku))
            if al:
                my_sku, strength = al[0], al[1]
                klass = "barcode" if al[2] == "barcode" else "product_match"
        if my_sku is None:
            for k in barcode_keys(sku) + barcode_keys(s.get("barcode")):
                hit = own_key_index.get(k)
                if hit:
                    my_sku, klass = hit
                    strength = MATCH_STRENGTH.get(klass, 90)
                    break
        if my_sku is None:
            vl = variant_links.get((sid, sku))
            if vl:
                hit = own_key_index.get(vl[0])
                if hit:
                    my_sku, klass = hit[0], vl[1]
                    strength = MATCH_STRENGTH.get(vl[1], 88)
        if not is_own:
            # Reuse the shared identity decisions, including scoped manual
            # reviews and blacklists. Local-SKU aliases are not authority.
            candidates = cohort_links.get((sid, s.get('offer_id')), set())
            my_sku = next(iter(candidates)) if len(candidates) == 1 else None
            klass, strength = ('verified_offer', 99) if my_sku else (None, None)
        seller = {
            "store_id": sid,
            "store_name": s.get("store_name") or (stores.get(sid) or {}).get("name") or sid,
            "platform": (stores.get(sid) or {}).get("platform"),
            "is_own": is_own,
            "sku_at_store": sku,
            "offer_id": s.get("offer_id"),
            "name_ar": s.get("name_ar"), "name_en": s.get("name_en"),
            "match_source": klass,
            "match_strength": strength,
            "price": round(float(s["price"]), 2) if s.get("price") and exclusion(s, now) is None else None,
            "price_eligible": exclusion(s, now) is None,
            "price_excluded_reason": exclusion(s, now),
            "historical_price": s.get("price") if exclusion(s, now) else None,
            "discount_pct": s.get("discount_pct") or 0,
            "in_stock": s.get("in_stock") if exclusion(s, now) in (None, "out_of_stock") else None,
            "stock_signal": get_stock_signal(s.get("qty_available"), s.get("in_stock")) if exclusion(s, now) in (None, "out_of_stock") else "UNKNOWN",
            "qty_available": s.get("qty_available") if exclusion(s, now) is None else None,
            "historical_quantity": s.get("qty_available") if exclusion(s, now) else None,
            "historical_quantity_at": _aware(s.get("crawled_at")) if exclusion(s, now) else None,
            "product_url": s.get("product_url"),
            "last_crawl_at": _aware(s.get("crawled_at")),
        }
        if my_sku:
            cohort_reason = cohort_exclusions.get((my_sku, sid, s.get("offer_id")))
            if cohort_reason:
                seller.update(price=None, price_eligible=False, price_excluded_reason=cohort_reason,
                              historical_price=s.get("price"))
            mine.setdefault(my_sku, []).append(seller)
        elif not is_own:
            code = canonical_barcode(s.get("barcode")) or canonical_barcode(sku)
            name = f"{s.get('name_ar') or ''} {s.get('name_en') or ''}"
            weight = stated_weight_grams(name)
            ckey = f"gtin:{code}:grams:{weight}" if code else f"offer:{s.get('offer_id') or sid + ':' + sku}"
            g = others.setdefault(ckey, {"sellers": [], "skus": set()})
            g["sellers"].append(seller)
            g["skus"].add(sku)

    own_units_map = orders_by_sku or {}

    # ── section A/B: my products ────────────────────────────────────────────
    my_products = []
    for sku, mp in my_by_sku.items():
        sellers = mine.get(sku, [])
        cat_row = mp
        name_ar = mp.get("name_ar") or cat_row.get("name_ar") or ""
        name_en = mp.get("name_en") or cat_row.get("name_en") or ""
        my_name = f"{name_ar} {name_en}".strip()
        my_price = round(float(own_price_fn(mp) or 0), 2)
        current_stock = own_stock(mp, now=now)

        own_seller = next((s for s in sellers if s.get("is_own")), None)
        if own_seller is None:
            own_seller = {
                "store_id": own_store_id,
                "store_name": (stores.get(own_store_id) or {}).get("name") or "My store",
                "platform": (stores.get(own_store_id) or {}).get("platform"),
                "is_own": True, "sku_at_store": sku, "match_source": "own",
                "match_strength": 100, "price": my_price, "discount_pct": 0,
                "in_stock": bool(mp.get("in_stock")) or (mp.get("quantity") or 0) > 0,
                "stock_signal": get_stock_signal(mp.get("quantity"), mp.get("in_stock")),
                "qty_available": mp.get("quantity"), "product_url": None,
                "last_crawl_at": None,
            }
            sellers = [own_seller] + sellers
        own_seller["price"] = my_price      # catalogue price is the truth for us
        own_seller.update(price=my_price or None, price_eligible=bool(my_price),
                          in_stock=current_stock["in_stock"], qty_available=current_stock["quantity"],
                          stock_signal=get_stock_signal(current_stock["quantity"], current_stock["in_stock"]),
                          historical_quantity=current_stock["historical_quantity"], historical_quantity_at=current_stock["historical_quantity_at"],
                          last_crawl_at=_aware(mp.get("last_synced_at")))

        kept, excluded = _apply_pack_guard(my_name, sellers, my_price)
        own_units = own_units_map.get(sku, {"units": 0, "revenue": 0.0}) if orders_by_sku is not None else None
        for s in kept:
            u, rev, src, reason = _resolve_units(
                (s["store_id"], s.get("offer_id") or s["sku_at_store"]), sales, signals, s["is_own"], own_units)
            s["units"], s["revenue"], s["units_source"], s["unavailable_reason"] = u, rev, src, reason
            if s["is_own"] and mp.get("known_variant_parent"):
                s.update(units=None, revenue=None, units_source=SRC_NONE, unavailable_reason="unresolved_parent_variants")
            pu = prev_sales.get((s["store_id"], s.get("offer_id") or s["sku_at_store"])) or {}
            s["prev_units"], s["prev_revenue"] = pu.get("units"), pu.get("revenue")

        own = next((s for s in kept if s["is_own"]), None)
        comps = [s for s in kept if not s["is_own"]]
        with_sales = [s for s in kept if s["units"] is not None]
        compatible = bool(with_sales) and len({s["units_source"] for s in with_sales}) == 1
        market_units = sum(s["units"] for s in with_sales) if compatible else None
        market_revenue = round(sum(s["revenue"] or 0 for s in with_sales), 2) if compatible else None
        prev_units = sum((s.get("prev_units") or 0) for s in kept)
        prev_revenue = round(sum((s.get("prev_revenue") or 0) for s in kept), 2)

        my_units = (own or {}).get("units")
        my_revenue = (own or {}).get("revenue")
        confidence, conf_reason = _row_confidence(kept, (own or {}).get("units_source"), now=now)
        spread_ratio, spread_warning = _price_spread(kept)
        if spread_warning and confidence in ("high", "medium"):
            confidence, conf_reason = "low", spread_warning
        cohort = cohorts[sku]
        stats = {"min": cohort["min"], "max": cohort["max"], "avg": cohort["avg"]}
        share_comparable = (my_units is not None and len(with_sales) == len(kept) and len(with_sales) >= 2
                            and all(s["units_source"] == SRC_ORDERS for s in with_sales))

        ranked_price = sorted(cohort['sellers'] + ([{'price': my_price, 'is_own': True}] if my_price > 0 else []), key=lambda s: s['price'])
        price_rank = next((i + 1 for i, s in enumerate(ranked_price) if s.get('is_own')), None) if cohort['sellers'] else None
        ranked_units = sorted(with_sales, key=lambda s: -(s["units"] or 0))
        units_rank = (next((i + 1 for i, s in enumerate(ranked_units) if s["is_own"]), None)
                      if share_comparable else None)
        top_comp = max([s for s in with_sales if not s["is_own"]],
                       key=lambda s: (s["units"] or 0, s["revenue"] or 0), default=None)

        for s in kept:
            s["unit_share_pct"] = _pct(s["units"], market_units) if share_comparable else None
            s["revenue_share_pct"] = _pct(s["revenue"], market_revenue) if share_comparable else None

        brand = mp.get("brand") if mp.get("brand_source") in ("reviewed", "store_supplied") else brand_fn(name_ar, name_en, existing=mp.get("brand") or "") or ""
        brand_source = mp.get("brand_source") if mp.get("brand_source") in ("reviewed", "store_supplied") else "derived_from_name" if brand else "unresolved"
        category = mp.get("category") if mp.get("category_source") in ("reviewed", "store_supplied", "import_file") else ""
        category_source = mp.get("category_source") if category else "unclassified"

        my_products.append({
            "canonical_key": canonical_barcode(sku) or f"sku:{sku}",
            "sku": sku,
            "barcode": mp.get("barcode") or (canonical_barcode(sku) and sku) or "",
            "name_ar": name_ar, "name_en": name_en,
            "name": name_en or name_ar or sku,
            "brand": brand, "brand_source": brand_source,
            "category": category, "category_source": category_source,
            "in_catalog": True,
            "my_price": my_price or None,
            "my_units": my_units,
            "my_revenue": my_revenue,
            "my_units_source": (own or {}).get("units_source"),
            "my_unavailable_reason": (own or {}).get("unavailable_reason"),
            "market_units": market_units if with_sales else None,
            "market_revenue": market_revenue if with_sales else None,
            "unit_share_pct": _pct(my_units, market_units) if share_comparable else None,
            "revenue_share_pct": _pct(my_revenue, market_revenue) if share_comparable else None,
            "share_comparable": share_comparable, "cohort_id": cohort["cohort_id"],
            "share_unavailable_reason": None if share_comparable else "incomplete_or_incompatible_sales_evidence",
            "market_value_basis": "shelf_price_proxy" if any(s["units_source"] != SRC_ORDERS for s in with_sales) else "orders_exact",
            "competitor_count": len(comps),
            "sellers_total": len(kept),
            "sellers_with_sales": len(with_sales),
            # A share is only a comparison when someone else's sales are in the
            # denominator. Products where we are the ONLY measurable seller are
            # honestly 100% — and are excluded from the headline KPI, which
            # would otherwise drift toward 100% as the catalogue grows.
            "contested": my_units is not None and any(s["units"] is not None for s in comps),
            "sole_seller": not comps and my_units is not None,
            "top_competitor": ({"store_name": top_comp["store_name"],
                                "units": top_comp["units"],
                                "revenue": top_comp["revenue"]} if top_comp else None),
            "competitor_price_min": stats["min"],
            "competitor_price_max": stats["max"],
            "competitor_price_avg": stats["avg"],
            "price_spread_ratio": spread_ratio,
            "price_spread_warning": spread_warning,
            "price_rank": price_rank, "price_rank_of": len(ranked_price),
            "units_rank": units_rank, "units_rank_of": len(ranked_units),
            "trend": {
                "units_pct": _delta_pct(market_units, prev_units),
                "revenue_pct": _delta_pct(market_revenue, prev_revenue),
                "prev_units": prev_units or None,
                "prev_revenue": prev_revenue or None,
                "basis": "previous equal-length window",
            },
            "confidence": confidence,
            "confidence_reason": conf_reason,
            "unavailable_reason": None if with_sales else REASON_NO_SELLER_DATA,
            "last_crawl_at": max([s["last_crawl_at"] for s in kept
                                  if isinstance(s.get("last_crawl_at"), datetime)], default=None),
            "sellers": sorted(kept, key=lambda s: (s.get("price") or 0)),
            "excluded_sellers": [{
                "store_name": e["store_name"], "price": e["price"],
                "reason": e.get("excluded_reason"), "detail": e.get("excluded_detail"),
            } for e in excluded],
        })

    # ── section C: products competitors sell and we do not ──────────────────
    missing = []
    for ckey, g in others.items():
        sellers = g["sellers"]
        for s in sellers:
            u, rev, src, reason = _resolve_units(
                (s["store_id"], s.get("offer_id") or s["sku_at_store"]), sales, signals, False, None)
            s["units"], s["revenue"], s["units_source"], s["unavailable_reason"] = u, rev, src, reason
            pu = prev_sales.get((s["store_id"], s.get("offer_id") or s["sku_at_store"])) or {}
            s["prev_units"], s["prev_revenue"] = pu.get("units"), pu.get("revenue")
        with_sales = [s for s in sellers if s["units"] is not None]
        compatible = bool(with_sales) and len({s["units_source"] for s in with_sales}) == 1
        market_units = sum(s["units"] for s in with_sales) if compatible else None
        market_revenue = round(sum(s["revenue"] or 0 for s in with_sales), 2) if compatible else None
        prev_units = sum((s.get("prev_units") or 0) for s in sellers)
        prev_revenue = round(sum((s.get("prev_revenue") or 0) for s in sellers), 2)
        stats = _price_stats(sellers)
        sample_sku = sorted(g["skus"])[0]
        cat_row = catalog.get(sellers[0].get("offer_id"), {})
        name_ar, name_en = sellers[0].get("name_ar") or "", sellers[0].get("name_en") or ""
        brand = cat_row.get("brand") if cat_row.get("brand_source") in ("reviewed", "store_supplied") else brand_fn(name_ar, name_en, existing=cat_row.get("brand") or "") or ""
        category = cat_row.get("category") if cat_row.get("category_source") in ("reviewed", "store_supplied", "import_file") else ""
        top = max(with_sales, key=lambda s: (s["units"] or 0, s["revenue"] or 0), default=None)
        spread_ratio, spread_warning = _price_spread(sellers)
        confidence = ("unavailable" if not with_sales else
                      "low" if (spread_warning or len(with_sales) != len(sellers)) else "medium")
        missing.append({
            "canonical_key": ckey,
            "sku": sample_sku,
            "barcode": cat_row.get("barcode") or (ckey if not ckey.startswith("sku:") else ""),
            "name_ar": name_ar, "name_en": name_en,
            "name": name_en or name_ar or sample_sku,
            "brand": brand, "category": category,
            "in_catalog": False,
            "my_unit_share_pct": None, "my_revenue_share_pct": None,
            "competitor_count": len(sellers),
            "competitors": [s["store_name"] for s in sorted(sellers, key=lambda s: s["store_name"])],
            "sellers_with_sales": len(with_sales),
            "market_units": market_units if with_sales else None,
            "market_revenue": market_revenue if with_sales else None,
            "top_competitor": ({"store_name": top["store_name"], "units": top["units"],
                                "revenue": top["revenue"]} if top else None),
            "avg_price": stats["avg"], "min_price": stats["min"], "max_price": stats["max"],
            "price_spread_ratio": spread_ratio,
            "price_spread_warning": spread_warning,
            "trend": {"units_pct": _delta_pct(market_units, prev_units),
                      "revenue_pct": _delta_pct(market_revenue, prev_revenue),
                      "basis": "previous equal-length window"},
            "confidence": confidence,
            "unavailable_reason": None if with_sales else REASON_NO_SELLER_DATA,
            "in_stock_sellers": sum(1 for s in sellers if s["in_stock"]),
            "sellers": sorted(sellers, key=lambda s: (s.get("price") or 0)),
        })

    # opportunity score — a transparent RANKING heuristic over the rows we can
    # measure, never presented as a forecast
    max_rev = max([m["market_revenue"] or 0 for m in missing], default=0)
    max_units = max([m["market_units"] or 0 for m in missing], default=0)
    max_sellers = max([m["competitor_count"] for m in missing], default=0)
    for m in missing:
        rev = (m["market_revenue"] or 0) / max_rev if max_rev else 0
        un = (m["market_units"] or 0) / max_units if max_units else 0
        se = m["competitor_count"] / max_sellers if max_sellers else 0
        m["opportunity_score"] = round(100 * (0.5 * rev + 0.3 * un + 0.2 * se), 1)
        m["opportunity_formula"] = "0.5×shelf-value proxy + 0.3×observed movement + 0.2×sellers; scaled within this comparison scope, not a sales forecast"
        if not m["sellers_with_sales"]:
            m["recommended_action"] = "Watch — no eligible observation intervals in this scope"
        elif m["competitor_count"] >= 3 and (m["market_revenue"] or 0) > 0:
            m["recommended_action"] = (f"Consider stocking — {m['competitor_count']} tracked stores "
                                       f"list it; {m['market_revenue']} SAR shelf-value proxy, not verified sales")
        elif (m["market_revenue"] or 0) > 0:
            m["recommended_action"] = "Investigate — observed movement, few sellers; demand unverified"
        else:
            m["recommended_action"] = "Low priority — carried but no measured movement"
    missing.sort(key=lambda m: -m["opportunity_score"])
    missing_total = len(missing)
    # Pagination belongs to the API, never before grouping or denominators.

    # ── sections D/E: brands and categories ─────────────────────────────────
    brand_rows = aggregate_groups(my_products, missing, "brand")
    category_rows = aggregate_groups(my_products, missing, "category")

    # ── overview KPIs + data quality ────────────────────────────────────────
    store_rows = []
    for sid, st in stores.items():
        sg = signals.get(sid) or {}
        store_rows.append({
            "store_id": sid, "store_name": st.get("name"), "platform": st.get("platform"),
            "is_own": bool(st.get("is_own_store")),
            "days_observed": sg.get("days_observed", 0),
            "sales_signal": sg.get("signal", "none"),
            "last_crawl_at": _aware(st.get("last_crawl_at")),
            "last_crawl_status": st.get("last_crawl_status"),
            "sales_data_available": sg.get("signal") in ("counter", "stock") and sg.get("days_observed", 0) >= 2,
        })
    store_rows.sort(key=lambda s: (not s["is_own"], s["store_name"] or ""))

    return {
        "window": {
            "days": days,
            "date_from": _day(window_start), "date_to": _day(window_end - timedelta(seconds=1)),
            "sealed": sealed, "sales_basis": "immutable_offer_intervals_v2", "algorithm_version": 2,
            "prev_date_from": _day(prev_start), "prev_date_to": _day(prev_end - timedelta(seconds=1)),
            "generated_at": now,
        },
        "kpis": summarize(my_products, missing, store_rows,
                          catalog_total=len(my_by_sku),
                          orders_connected=orders_by_sku is not None,
                          missing_total=missing_total,
                          brands=len(brand_rows), categories=len(category_rows)),
        "stores": store_rows,
        "my_products": my_products,
        "missing_products": missing,
        "missing_products_total": missing_total,
        "brands": brand_rows,
        "categories": category_rows,
        "data_quality": quality_summary(my_products, orders_by_sku is not None),
    }
