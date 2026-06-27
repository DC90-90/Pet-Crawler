"""Shared helpers and constants for Daleel.

Extracted from server.py during the Feb 2026 refactor. These are pure helpers
that do not depend on FastAPI or the Mongo client, so they can be safely
imported from any route module.
"""
import re
import time
import statistics
import functools
import inspect


# ── TTL Cache (Feb 2026 perf sprint) ────────────────────────
# Lightweight in-memory cache for read-only aggregation endpoints whose data
# only changes after a crawl run (every 12-24h). A 60s TTL is correct and safe:
# users see fresh data within 60s of any crawl completing, and dashboards
# served from cache return in ~1ms instead of 300-1600ms.
# Not Redis (single-instance backend) — when we scale horizontally, swap this
# helper out without touching the call sites.
_TTL_CACHE: dict = {}


def cache_clear():
    """Manually invalidate the entire TTL cache (called after crawl completion)."""
    _TTL_CACHE.clear()


def ttl_cache(ttl_seconds: int = 60, key_prefix: str = ""):
    """Decorator that caches async function results by argument values.

    The cache key is `(key_prefix, func_name, *args, *sorted(kwargs.items()))`
    EXCLUDING any FastAPI `Depends` injected parameters (e.g. `user`). Endpoint
    handlers should keep `user=Depends(...)` LAST so that filtering is easy.
    """
    def decorator(func):
        sig = inspect.signature(func)
        # Names of parameters we exclude from the cache key (they're per-user
        # injected deps, not real inputs that change the response).
        skip_param_names = {
            name for name, p in sig.parameters.items()
            if name in ("user", "_", "request", "response", "db")
        }

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Build a stable key from positional + kwargs, dropping ignored params
            bound = sig.bind_partial(*args, **kwargs)
            key_parts = [key_prefix or func.__name__]
            for name, value in bound.arguments.items():
                if name in skip_param_names:
                    continue
                key_parts.append(f"{name}={value!r}")
            cache_key = "|".join(key_parts)
            now = time.time()
            entry = _TTL_CACHE.get(cache_key)
            if entry is not None and entry[0] > now:
                return entry[1]
            result = await func(*args, **kwargs)
            _TTL_CACHE[cache_key] = (now + ttl_seconds, result)
            return result
        return wrapper
    return decorator


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

    # ── Method 2: positive-delta SUM with restock filtering ──
    # Monotonic by construction: each additional snapshot can only ADD a non-negative
    # delta to the total. Prior implementation used `net_drop = first_qty − last_qty`,
    # which made 90D windows occasionally report LESS than their 7D sub-windows when
    # the SKU was restocked between them.
    valid_qtys = [
        s.get("qty_available", 0) or 0
        for s in snaps
        if (s.get("qty_available", 0) or 0) not in PLACEHOLDER_QTY_VALUES
        and (s.get("qty_available", 0) or 0) <= 200
    ]
    if len(valid_qtys) < 2:
        return 0, 0.0, "insufficient_signal"

    # Sum positive (downward) deltas only; treat upward jumps > 5 as restocks
    # (they contribute 0 to sales).
    total_drop = 0
    RESTOCK_SPIKE = 5  # an UPWARD jump > 5 within one sample is a restock, not a sale
    for i in range(1, len(valid_qtys)):
        delta = valid_qtys[i - 1] - valid_qtys[i]
        if delta > 0:
            total_drop += delta
        elif delta < -RESTOCK_SPIKE:
            # explicit no-op: the previous step is the restock event itself.
            # Sales captured before it are already in total_drop.
            pass

    if total_drop < 1:
        return 0, 0.0, "no_depletion"

    units = min(total_drop, MAX_DAILY_SALES_PER_SKU * max(1, days))
    avg_price = sum((s.get("price") or 0) for s in snaps) / max(1, len(snaps))
    revenue = round(units * avg_price, 2)
    return units, round(revenue, 2), "qty_positive_delta_sum"


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


# ── Market Position helper (Feb 2026) ───────────────────────
# Used by /api/my-products, /api/products/{sku}/full, /api/insights/summary
# to rank a product's price against competitors. Rules:
#   • Only sellers with snapshots crawled in the last 7 days count
#   • Only confidence_score >= 75 (skips Tier-3 HTML noise)
#   • Lowest price = rank 1 (best); ties at the same price share the lower rank
#   • Returns None if fewer than 2 valid sellers OR own price absent
def compute_market_position(seller_prices, my_store_id):
    """
    seller_prices: list of dicts {"store_id", "store_name", "price", "confidence_score", "crawled_at"}
                   (already pre-filtered to "latest snapshot per store" by caller)
    my_store_id:   the user's own store_id

    Returns a dict with rank/range/percentile or None if insufficient data.
    """
    import math
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    def _crawled_ts(v):
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        try:
            d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    valid = []
    for sp in seller_prices or []:
        price = sp.get("price")
        if not (isinstance(price, (int, float)) and price > 0):
            continue
        is_mine = sp.get("store_id") == my_store_id
        # Own price is always authoritative — skip the freshness/confidence check
        # for the user's own store. Their price is what THEY set, not crawled.
        if not is_mine:
            conf = sp.get("confidence_score", 0) or 0
            if conf < 75:
                continue
            ts = _crawled_ts(sp.get("crawled_at"))
            if ts is None or ts < cutoff:
                continue
        valid.append({
            "store_id": sp.get("store_id"),
            "store_name": sp.get("store_name", ""),
            "price": round(float(price), 2),
            "is_mine": is_mine,
        })

    if len(valid) < 2:
        return None

    # Sort ASC by price; ties share the LOWER rank (standard competition ranking).
    sorted_sellers = sorted(valid, key=lambda x: x["price"])
    rank_by_idx = []
    last_price = None
    last_rank = 0
    for i, s in enumerate(sorted_sellers):
        if last_price is None or s["price"] != last_price:
            last_rank = i + 1
            last_price = s["price"]
        rank_by_idx.append(last_rank)

    prices = [s["price"] for s in sorted_sellers]
    min_p = prices[0]
    max_p = prices[-1]
    n = len(prices)
    if n % 2 == 1:
        median_p = prices[n // 2]
    else:
        median_p = round((prices[n // 2 - 1] + prices[n // 2]) / 2, 2)

    my_idx = next((i for i, s in enumerate(sorted_sellers) if s["is_mine"]), None)
    if my_idx is None:
        return None

    my_rank = rank_by_idx[my_idx]
    my_price = sorted_sellers[my_idx]["price"]
    # Percentile (0 = cheapest, 100 = most expensive)
    if n > 1:
        percentile = round(((my_rank - 1) / (n - 1)) * 100, 1)
    else:
        percentile = 0.0

    is_cheapest = my_rank == 1
    is_most_expensive = my_price == max_p
    above_median = my_price > median_p
    below_median = my_price < median_p

    if is_cheapest:
        tag = "cheapest"
    elif is_most_expensive:
        tag = "most_expensive"
    elif above_median:
        tag = "above_median"
    elif below_median:
        tag = "below_median"
    else:
        tag = "median"

    return {
        "rank": my_rank,
        "total_sellers": n,
        "my_price": my_price,
        "min_price": min_p,
        "max_price": max_p,
        "median_price": median_p,
        "percentile": percentile,
        "is_cheapest": is_cheapest,
        "is_most_expensive": is_most_expensive,
        "below_median": below_median,
        "above_median": above_median,
        "tag": tag,
        # Compact array for the visual range bar
        "sellers": [
            {"store_name": s["store_name"], "price": s["price"], "is_mine": s["is_mine"], "rank": rank_by_idx[i]}
            for i, s in enumerate(sorted_sellers)
        ],
    }
