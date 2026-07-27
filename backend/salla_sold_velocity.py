"""iter59 — real sold-velocity for Salla stores, by diffing the storefront badge.

Salla publishes a CUMULATIVE units-sold counter (`sold_quantity`, the number
behind "تم بيعه أكثر من N مرة"). The crawler parsed it and discarded it before
writing snapshots, so those stores were reported "not measurable" and had to be
served by the ±50% category-velocity estimate.

With the counter persisted, velocity is a diff between consecutive crawls —
exactly how Zid stock depletion already works — which makes Salla revenue
MEASURED rather than estimated.

Why it is "measured (approx.)" and not simply "measured"
--------------------------------------------------------
The badge is BUCKETED. Salla rounds it for display and caps it above a ceiling,
so a diff is a real observation of real sales but not an exact unit count. It
therefore gets its own tier, distinct from both the exact Zid figure and the
±50% estimate. Overstating it as exact would be the same mistake as showing a
coverage-tightened band on the estimate.

Guards
------
counter reset   a new value BELOW the previous one means the merchant reset or
                republished the product. The step is skipped, never added as a
                negative — one reset would otherwise wipe out a store's window.
capped reading  a "1000+" value stops moving while sales continue. Diffing it
                reports 0 for the store's best sellers, i.e. silently
                under-counts exactly where it matters most. Capped readings are
                excluded and counted, so the coverage number stays honest.
single reading  a cumulative counter needs TWO points. One crawl is a baseline
                and yields no velocity — the estimate stays in place until the
                second crawl lands.
"""

# a single step larger than this is treated as a republish/backfill artefact
# rather than real sales, mirroring MAX_QTY_DELTA_PER_INTERVAL on the Zid path
MAX_SOLD_STEP = 5000


def diff_series(readings, max_step=MAX_SOLD_STEP):
    """Units sold across a series of cumulative readings for ONE (sku, store).

    readings: iterable of {"value", "capped", "at"} — `at` orders them.
    Returns a dict; `units` is None when nothing diffable exists, which the
    caller must treat as "no data", NOT as zero sales.
    """
    rows = sorted(
        (r for r in readings if r.get("at") is not None and r.get("value") is not None),
        key=lambda r: r["at"])
    usable = [r for r in rows if not r.get("capped")]
    out = {
        "units": None, "steps": 0, "readings": len(rows),
        "usable_readings": len(usable), "capped_readings": len(rows) - len(usable),
        "resets": 0, "clamped_steps": 0, "status": "no_data",
        "first_at": None, "last_at": None,
    }
    if not usable:
        out["status"] = "all_capped" if rows else "no_data"
        return out
    out["first_at"], out["last_at"] = usable[0]["at"], usable[-1]["at"]
    if len(usable) < 2:
        out["status"] = "baseline_only"      # one point: cannot diff yet
        return out

    units = 0
    for prev, curr in zip(usable, usable[1:]):
        delta = (curr["value"] or 0) - (prev["value"] or 0)
        if delta < 0:
            out["resets"] += 1               # merchant reset — skip, never negative
            continue
        if delta > max_step:
            out["clamped_steps"] += 1
            delta = max_step
        if delta > 0:
            out["steps"] += 1
        units += delta
    out["units"] = units
    out["status"] = "measured_approx"
    return out


def store_revenue_from_velocity(products):
    """Sum velocity x price across a store's products.

    products: iterable of {"sku", "units", "price", "status"}. Only rows with a
    real diff contribute; everything else is counted so the caller can report
    what share of the catalogue the figure actually rests on.
    """
    revenue = 0.0
    measured = baseline = capped = nodata = 0
    for p in products:
        st = p.get("status")
        if st == "measured_approx" and p.get("units") is not None:
            price = p.get("price")
            if isinstance(price, (int, float)) and price > 0:
                revenue += (p["units"] or 0) * price
                measured += 1
                continue
            nodata += 1
        elif st == "baseline_only":
            baseline += 1
        elif st == "all_capped":
            capped += 1
        else:
            nodata += 1
    total = measured + baseline + capped + nodata
    return {
        "revenue": round(revenue, 2),
        "products_measured": measured,
        "products_baseline_only": baseline,
        "products_capped": capped,
        "products_no_data": nodata,
        "products_total": total,
        "coverage_pct": round(100 * measured / total, 1) if total else 0.0,
        # a figure resting on a sliver of the catalogue is not a store total
        "usable": measured > 0,
    }
