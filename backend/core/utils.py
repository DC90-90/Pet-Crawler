"""Shared helpers and constants for Daleel.

Extracted from server.py during the Feb 2026 refactor. These are pure helpers
that do not depend on FastAPI or the Mongo client, so they can be safely
imported from any route module.
"""
import re
import statistics


# Placeholder qty values stores use for "untracked / unlimited" inventory.
# Treated as noise — never derive sales from these.
PLACEHOLDER_QTY_VALUES = {99, 100, 999, 1000, 9999, 10000, 99999, 100000}

# >10 units sold per single crawl interval per SKU is almost certainly a data error.
MAX_QTY_DELTA_PER_INTERVAL = 10

# Absolute upper bound: at most 30 units/day per SKU.
MAX_DAILY_SALES_PER_SKU = 30


def get_stock_signal(qty, in_stock=None):
    """Return a stock label.

    Many Salla/Zid stores set quantity=0 for products with `unlimited_quantity=true`
    or untracked inventory while still being available for purchase. Use the explicit
    `in_stock` flag (when present) as the source of truth and only fall back to qty.
    """
    if in_stock is False:
        return "OOS"
    if in_stock is True and (qty is None or qty == 0):
        return "AVAIL"  # In-stock but quantity not tracked
    if qty is None or qty == 0:
        return "OOS"
    if qty < 10:
        return "LOW"
    if qty <= 30:
        return "MEDIUM"
    return "HIGH"


def _coerce_num(v, default=0.0):
    """Defensively coerce a value that may be None / int / float / str
    with currency symbols or commas to float."""
    if v is None or v == "":
        return float(default)
    if isinstance(v, bool):
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = re.sub(r"[^0-9.\-]", "", str(v))
        if s in ("", "-", ".", "-."):
            return float(default)
        return float(s)
    except (ValueError, TypeError):
        return float(default)


def _coerce_int(v, default=0):
    try:
        return int(_coerce_num(v, default))
    except (ValueError, TypeError):
        return int(default)


def _estimate_sales_from_snapshots(snaps, days):
    """Estimate sales for a SKU at a single store from a chronological snapshot list.

    Strategy:
      1. PREFER `sold_count` diff (Salla `sales_count` / Zid `sold_count`) — cumulative
         sales counter, most reliable.
      2. FALL BACK to qty depletion with sanity filters (drop placeholder values,
         cap deltas).

    Returns: (units_sold, revenue, used_method).
    """
    if not snaps or len(snaps) < 2:
        return 0, 0.0, "insufficient_data"

    # ── Method 1: sold_count cumulative diff (most reliable) ──
    sold_counts = [s.get("sold_count", 0) or 0 for s in snaps]
    if max(sold_counts) > 0 and sold_counts[0] >= 0:
        first_sc = next((sc for sc in sold_counts if sc > 0), 0)
        last_sc = sold_counts[-1] if sold_counts[-1] >= first_sc else max(sold_counts)
        units_from_counter = max(0, last_sc - first_sc)
        if units_from_counter > 0:
            avg_price = sum((s.get("price") or 0) for s in snaps) / max(1, len(snaps))
            units_capped = min(units_from_counter, MAX_DAILY_SALES_PER_SKU * max(1, days))
            return units_capped, round(units_capped * avg_price, 2), "sold_count_diff"

    # ── Method 2: NET qty depletion with strict signal requirements ──
    valid_qtys = [
        s.get("qty_available", 0) or 0
        for s in snaps
        if (s.get("qty_available", 0) or 0) not in PLACEHOLDER_QTY_VALUES
        and (s.get("qty_available", 0) or 0) <= 200
    ]
    if len(valid_qtys) < 3:
        return 0, 0.0, "insufficient_signal"

    first_qty = valid_qtys[0]
    last_qty = valid_qtys[-1]
    net_drop = first_qty - last_qty

    if net_drop < 3:
        return 0, 0.0, "insufficient_signal"

    # If a big restock spike happened, only count post-restock depletion
    for i in range(1, len(valid_qtys)):
        if valid_qtys[i] > valid_qtys[i - 1] + 5:
            net_drop = valid_qtys[i] - last_qty
            if net_drop < 3:
                return 0, 0.0, "insufficient_signal"
            break

    units = min(net_drop, MAX_DAILY_SALES_PER_SKU * max(1, days))
    avg_price = sum((s.get("price") or 0) for s in snaps) / max(1, len(snaps))
    revenue = round(units * avg_price, 2)
    return units, round(revenue, 2), "qty_net_depletion"


def compute_product_metrics(snapshots_by_store, days):
    """Given {store_id: [snapshots sorted by crawled_at asc]}, compute market metrics."""
    all_latest_prices = []
    total_sold = 0
    total_revenue = 0.0
    latest_qty = 0
    any_in_stock = False
    confidences = []
    latest_tier = 1

    for store_id, snaps in snapshots_by_store.items():
        if not snaps:
            continue
        latest = snaps[-1]
        all_latest_prices.append(latest["price"])
        confidences.append(latest["confidence_score"])
        latest_tier = latest["source_tier"]
        latest_qty = max(latest_qty, latest.get("qty_available", 0))
        if latest.get("in_stock") is True:
            any_in_stock = True

        units, revenue, _ = _estimate_sales_from_snapshots(snaps, days)
        total_sold += units
        total_revenue += revenue

    if not all_latest_prices:
        return None

    min_p = min(all_latest_prices)
    max_p = max(all_latest_prices)
    med_p = statistics.median(all_latest_prices)
    avg_p = statistics.mean(all_latest_prices)
    avg_conf = round(statistics.mean(confidences)) if confidences else 0

    return {
        "price": round(avg_p, 2),
        "min_price": round(min_p, 2),
        "max_price": round(max_p, 2),
        "median_price": round(med_p, 2),
        "vs_lowest_pct": round(((avg_p - min_p) / min_p) * 100, 1) if min_p > 0 else 0,
        "vs_median_pct": round(((avg_p - med_p) / med_p) * 100, 1) if med_p > 0 else 0,
        "qty_sold_est": total_sold,
        "revenue_est": round(total_revenue, 2),
        "num_sellers": len(all_latest_prices),
        "latest_qty": latest_qty,
        "stock_signal": get_stock_signal(latest_qty, in_stock=any_in_stock if any_in_stock else None),
        "confidence_score": avg_conf,
        "source_tier": latest_tier,
    }
