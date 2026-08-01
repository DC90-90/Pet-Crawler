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

# Sold-count delta sanity cap (Feb 2026 — P1 data accuracy guard):
# Sold-counters can occasionally jump (manual reset, backfill, partner sync glitch).
# Any single per-snapshot increase above this gets clamped — it's almost certainly
# an admin re-import or a faulty counter, not genuine sales in one crawl interval.
MAX_SOLD_COUNT_DELTA_PER_INTERVAL = 50

# Minimum confidence_score required to participate in dashboard aggregations
# (revenue, sales velocity, leaderboards, market position). Lower-tier
# snapshots (Tier-3 HTML scraping ~75) carry too much noise to drive KPIs.
# Setting the floor at 85 admits Tier-0/1/2 (own store + structured APIs) only.
MIN_AGGREGATION_CONFIDENCE = 85


# ── Barcode canonicalisation (iter47, shared here in iter61) ────────────────
# The same physical product is keyed as UPC-A (12 digits, leading zero) on one
# side and EAN (11 digits, zero dropped) on the other:
#     my_products 052742059518   vs   competitor 52742059518
# Neither literal equality nor suffix-stripping bridges those, so every side
# also gets the canonical GTIN-14 form (zero-padded to 14), which is identical
# for both.
#
# iter61 — this lived in crawlers.py and was therefore reachable only from the
# own-store price-resolution path. The MATCHER did a raw set intersection with
# no normalization at all, so the exact pair iter47 was written to fix still
# failed to link a competitor to our catalogue — costing seller coverage rather
# than price accuracy. One definition, used by both.
_BARCODE_LEAD_RE = re.compile(r"^(\d{8,14})(?=[^\d]|$)")


def barcode_keys(value, canonical=True):
    """Candidate lookup keys for a barcode-ish value (lowercased).

    The 8-digit floor is what keeps short numeric SKUs ("15", "4021") out of the
    key space entirely — they are never barcode candidates, so widening the
    canonical form cannot collide them.

    canonical=False reproduces the pre-iter47 key set, used only to measure how
    many rows the new keys recover.
    """
    raw = str(value or "").strip().lower()
    if not raw:
        return []
    keys = [raw]
    m = _BARCODE_LEAD_RE.match(raw)
    if m:
        lead = m.group(1)
        if lead != raw:
            keys.append(lead)
        if canonical:
            canon = lead.zfill(14)          # GTIN-14 canonical form
            if canon not in keys:
                keys.append(canon)
    return keys


def canonical_barcode(value):
    """The single GTIN-14 form of a barcode-ish value, or None.

    Set membership needs ONE key per value, not a list — two products are the
    same trade item iff their GTIN-14 forms are equal.
    """
    raw = str(value or "").strip().lower()
    m = _BARCODE_LEAD_RE.match(raw)
    return m.group(1).zfill(14) if m else None


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
    # We now sum CLAMPED per-step positive diffs rather than `last - first`.
    # Reason: a single bad data point (sold_count reset, partner-sync backfill)
    # used to inflate the window total by thousands. Per-step clamping caps
    # each interval at MAX_SOLD_COUNT_DELTA_PER_INTERVAL and a total cap of
    # MAX_DAILY_SALES_PER_SKU * days keeps the window-level number sane too.
    sold_counts = [s.get("sold_count", 0) or 0 for s in snaps]
    if max(sold_counts) > 0:
        units_from_counter = 0
        any_positive_step = False
        for i in range(1, len(sold_counts)):
            delta = sold_counts[i] - sold_counts[i - 1]
            if delta <= 0:
                # Counter went down (reset / refurbished history) — ignore.
                continue
            any_positive_step = True
            units_from_counter += min(delta, MAX_SOLD_COUNT_DELTA_PER_INTERVAL)
        if any_positive_step and units_from_counter > 0:
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
#   • Only confidence_score >= MIN_AGGREGATION_CONFIDENCE (skips Tier-3 HTML noise)
#   • Lowest price = rank 1 (best); ties at the same price share the lower rank
#   • Returns None if fewer than 2 valid sellers OR own price absent
def compute_market_position(seller_prices, my_store_id, max_age_days=7,
                            min_confidence=MIN_AGGREGATION_CONFIDENCE):
    """
    seller_prices: list of dicts {"store_id", "store_name", "price", "confidence_score", "crawled_at"}
                   (already pre-filtered to "latest snapshot per store" by caller)
    my_store_id:   the user's own store_id

    max_age_days / min_confidence (iter60): the aggregation defaults above are
    right for list views, where the user cannot see what was filtered out. The
    product detail page CAN — it prints the seller table directly beneath this
    badge — so it passes max_age_days=None, min_confidence=0 to make "Cheapest
    of N" agree with the list. `stale_sellers` / `low_confidence_sellers` in the
    result say how many rows the defaults would have removed.

    Returns a dict with rank/range/percentile or None if insufficient data.
    """
    import math
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)
              if max_age_days is not None else None)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    n_stale = n_lowconf = 0

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
            if conf < min_confidence:
                continue
            ts = _crawled_ts(sp.get("crawled_at"))
            if cutoff is not None and (ts is None or ts < cutoff):
                continue
            if ts is None or ts < stale_cutoff:
                n_stale += 1
            if conf < MIN_AGGREGATION_CONFIDENCE:
                n_lowconf += 1
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
        # iter60 — how much of the ranked set is older than 7 days / below the
        # aggregation confidence floor. Shown, not silently dropped.
        "stale_sellers": n_stale,
        "low_confidence_sellers": n_lowconf,
        # Compact array for the visual range bar
        "sellers": [
            {"store_name": s["store_name"], "price": s["price"], "is_mine": s["is_mine"], "rank": rank_by_idx[i]}
            for i, s in enumerate(sorted_sellers)
        ],
    }
