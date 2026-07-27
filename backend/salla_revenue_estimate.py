"""iter55 — estimated revenue for Salla stores (Option B: category-average velocity).

Salla's storefront exposes no cumulative sold-counter, so the live ranking marks
every Salla store `not_measurable`. This module estimates their revenue from the
velocity we DO observe on Zid stores, and is deliberately kept separate from the
measured figure: the output field is `revenue_est`, never `revenue_30d`.

Method
------
1. From measurable stores, build an observation per PRICED product:
       velocity = units_sold_in_window / window_days     (units per product-day)
   Products with no detected sales contribute velocity 0. This matters more than
   anything else here: averaging only the movers would inflate the rate by the
   share of the catalogue that never sells, which in pet retail is most of it.

2. Pool those observations three ways, most specific first:
       per-SKU      mean velocity of that exact SKU across measurable stores
       per-category mean velocity of every product in the category
       global       mean velocity of every observation

3. revenue_est(store) = SUM over its priced products of
       velocity(sku -> category -> global) * price * window_days

MEAN, not median, is used on purpose. We are estimating a SUM, and the mean is
the unbiased estimator of a total; the median of a catalogue where most products
never sell is simply 0.

What this cannot do
-------------------
The estimate is driven by CATALOGUE SIZE and PRICE, not by demand. Two stores
with the same assortment score the same however different their actual traffic
is. Treat the output as an order-of-magnitude indicator, which is why the
back-test below reports per-store error rather than a single headline accuracy.
"""

import statistics

# a category pool below this many observations is not trusted; the estimate
# falls back to the global pool instead
MIN_CATEGORY_SAMPLE = 30

# back-test verdict bands, on absolute percentage error
TRUSTWORTHY_PCT = 30.0
WEAK_PCT = 100.0

# ── fixed confidence band ───────────────────────────────────────────────────
# ONE honest wide band for every Salla store. Deliberately NOT derived from
# matched coverage.
#
# A coverage-derived band tightens as more of a store's catalogue matches a Zid
# product, which sounds like a virtue — but it implies a precision the evidence
# does not support. The leave-one-out back-test measured ~+/-48% median absolute
# error, and that error is dominated by TRAFFIC differences between stores, not
# by how many products we matched. Matching more products does not make one
# store's shoppers behave like another's. Showing a store at "+/-33%" because its
# coverage is high would therefore be a precision claim the method cannot back.
#
# These figures inform pricing decisions, so a number that looks more accurate
# than it is carries real downside. The band is fixed at the back-tested error,
# rounded to a blunt +/-50% so nobody reads a false decimal-point of rigour into
# it.
#
# Coverage is still computed and returned as a DIAGNOSTIC (the admin preview
# reports it) — it just does not move the band.
FIXED_BAND_PCT = 50.0


def estimate_with_band(products, pools, days):
    """estimate_store_revenue plus the fixed band.

    Returns (revenue_est, band_pct, coverage, detail). `coverage` is diagnostic
    only; band_pct is FIXED_BAND_PCT for every store, always.
    """
    est, detail = estimate_store_revenue(products, pools, days)
    priced = detail["priced_products"]
    coverage = (detail["per_sku"] / priced) if priced else 0.0
    return est, FIXED_BAND_PCT, round(coverage, 4), detail


def build_velocity_pools(observations, days, exclude_store=None):
    """observations: iterable of {"store_id", "sku", "category", "units"}.

    EVERY priced product of a measurable store must appear, with units=0 when it
    had no detected sales — see the module docstring.

    exclude_store implements leave-one-out for the back-test: a store must never
    contribute to the pool used to estimate itself, or the test is run on its own
    training data and reports an error far better than the method achieves.
    """
    if days <= 0:
        raise ValueError("days must be positive")
    by_sku, by_cat, allv = {}, {}, []
    for o in observations:
        if exclude_store is not None and o.get("store_id") == exclude_store:
            continue
        v = (o.get("units") or 0) / days
        by_sku.setdefault(o.get("sku"), []).append(v)
        by_cat.setdefault(o.get("category") or "", []).append(v)
        allv.append(v)

    def _mean(xs):
        return sum(xs) / len(xs) if xs else None

    return {
        "per_sku": {k: _mean(v) for k, v in by_sku.items()},
        "per_category": {k: _mean(v) for k, v in by_cat.items()
                         if len(v) >= MIN_CATEGORY_SAMPLE},
        "global": _mean(allv),
        "category_sample_sizes": {k: len(v) for k, v in by_cat.items()},
        "observations": len(allv),
    }


def estimate_store_revenue(products, pools, days):
    """products: iterable of {"sku", "price", "category"} for ONE store.

    Returns (revenue_est, detail). detail counts which pool priced each product,
    so a figure resting entirely on the global fallback is visibly weaker than
    one resting on per-SKU velocity.
    """
    total = 0.0
    src = {"per_sku": 0, "per_category": 0, "global": 0, "unpriced": 0, "no_velocity": 0}
    for p in products:
        price = p.get("price")
        if not (isinstance(price, (int, float)) and price > 0):
            src["unpriced"] += 1
            continue
        v = pools["per_sku"].get(p.get("sku"))
        bucket = "per_sku"
        if v is None:
            v = pools["per_category"].get(p.get("category") or "")
            bucket = "per_category"
        if v is None:
            v = pools["global"]
            bucket = "global"
        if v is None:
            src["no_velocity"] += 1
            continue
        src[bucket] += 1
        total += v * price * days
    priced = src["per_sku"] + src["per_category"] + src["global"]
    # confidence: how much of the figure rests on the specific pools rather than
    # the blunt global one
    if priced == 0:
        conf = "none"
    else:
        specific = (src["per_sku"] + src["per_category"]) / priced
        conf = "high" if specific >= 0.8 else "medium" if specific >= 0.5 else "low"
    return round(total, 2), {**src, "priced_products": priced, "confidence": conf}


def back_test(observations, products_by_store, actual_by_store, days):
    """Leave-one-out back-test over the stores whose revenue we actually measure.

    For each measurable store: rebuild the pools with that store EXCLUDED,
    estimate it, and compare against its measured revenue.
    """
    results = []
    for sid, actual in sorted(actual_by_store.items()):
        prods = products_by_store.get(sid) or []
        if not prods or not (actual and actual > 0):
            results.append({"store_id": sid, "actual": actual, "estimate": None,
                            "error_pct": None, "skipped": "no_products_or_no_actual"})
            continue
        pools = build_velocity_pools(observations, days, exclude_store=sid)
        est, detail = estimate_store_revenue(prods, pools, days)
        err = round((est - actual) / actual * 100, 1)
        results.append({
            "store_id": sid, "actual": round(actual, 2), "estimate": est,
            "error_pct": err, "abs_error_pct": abs(err),
            "ratio": round(est / actual, 3),
            "confidence": detail["confidence"], "velocity_source": detail,
        })
    scored = [r for r in results if r.get("abs_error_pct") is not None]
    errs = [r["abs_error_pct"] for r in scored]
    summary = {
        "stores_tested": len(scored),
        "mean_abs_error_pct": round(statistics.mean(errs), 1) if errs else None,
        "median_abs_error_pct": round(statistics.median(errs), 1) if errs else None,
        "worst_abs_error_pct": round(max(errs), 1) if errs else None,
        "within_30pct": sum(1 for e in errs if e <= TRUSTWORTHY_PCT),
        "leave_one_out": True,
    }
    summary["verdict"] = _verdict(summary["median_abs_error_pct"], len(scored))
    return {"per_store": results, "summary": summary}


def _verdict(median_abs_err, n):
    if not n:
        return "inconclusive — no measurable store had both products and revenue"
    if n < 3:
        return (f"inconclusive — only {n} measurable store(s); a leave-one-out test "
                "needs at least 3 to say anything about the method")
    if median_abs_err is None:
        return "inconclusive"
    if median_abs_err <= TRUSTWORTHY_PCT:
        return (f"trustworthy enough to display with an estimate label "
                f"(median abs error {median_abs_err}% <= {TRUSTWORTHY_PCT}%)")
    if median_abs_err <= WEAK_PCT:
        return (f"WEAK — median abs error {median_abs_err}% exceeds the {TRUSTWORTHY_PCT}% bar. "
                "Usable only as a coarse size band, not as a revenue figure")
    return (f"TOO WEAK TO SHOW — median abs error {median_abs_err}%. The estimate is off by "
            "more than the quantity being estimated; showing it would mislead")
