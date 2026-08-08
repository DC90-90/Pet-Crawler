"""iter73r — Store Profile: Category Distribution reflects units sold, not
catalog composition (Aug 8 2026).

Client-reported bug: the Category Distribution pie on every store profile
showed the CATALOG composition (unique SKUs per category — 39% cat_food,
26% accessories, etc.) rather than the SALES composition. A store that
STOCKS 39% cat food but SELLS 5% cat food renders the same pie either
way, so the operator can't tell what categories actually drive sales.
Client called this "fabricated numbers".

Fix: aggregate `sku_sales` (units_sold per SKU, MEASURED from the same
sku_sales_daily rollup that feeds the KPI and trend chart) by category
via a single bulk `products.find({sku: $in: [...]})` lookup. When there
are no measured sales, return an empty list — the frontend renders an
honest "No sales data" state instead of the fabricated catalog pie.

Frontend chart contract preserved: `dataKey="count"` still works because
we KEEP the `count` field name but populate it with `units_sold`. A new
`basis: "units_sold"` field disambiguates for the FE label.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def _store_profile_body():
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def store_profile(store_id: str")
    b = src.index("    return {", a)
    return src[a:b]


# ── Code-shape fences ───────────────────────────────────────────────────────
def test_iter73r_marker_present():
    body = _store_profile_body()
    assert "iter73r" in body, "iter73r marker missing on the category-distribution block"


def test_iter73r_no_more_per_sku_lookup_over_latest_snapshots():
    """The buggy path used `for l in latest: products.find_one(sku=...)` —
    per-SKU query over the latest-snapshot list, counting each row as 1
    catalog contribution. That whole pattern is gone."""
    body = _store_profile_body()
    # Locate the category block and inspect ONLY that region.
    a = body.index("# Category distribution")
    b = body.index("# New arrivals", a)
    cat_block = body[a:b]
    assert "for l in latest:" not in cat_block, \
        "catalog-based per-latest-snapshot iteration must be gone from the category block"
    assert "cat_count[p[\"category\"]] = cat_count.get(p[\"category\"], 0) + 1" not in cat_block, \
        "the buggy +1-per-catalog-sku accumulation must be gone"


def test_iter73r_reads_units_from_sku_sales_dict():
    """The new path aggregates from `sku_sales` — a dict populated ABOVE by
    the sku_sales_daily rollup reader (same source as the KPI card, so we
    cannot disagree with the reported monthly revenue)."""
    body = _store_profile_body()
    a = body.index("# Category distribution")
    b = body.index("# New arrivals", a)
    cat_block = body[a:b]
    assert "for sku, units in sku_sales.items():" in cat_block, \
        "the aggregation must iterate `sku_sales.items()` — the measured units per SKU"
    assert "cat_units[_cat] = cat_units.get(_cat, 0) + int(units)" in cat_block, \
        "the accumulator must sum UNITS (not +1) so the pie is unit-weighted"


def test_iter73r_bulk_category_lookup():
    """Regression fence: the fix uses a SINGLE bulk lookup
    (`find({sku: $in: [...]})`), not one query per SKU. On a store with
    thousands of sold SKUs the old N+1 pattern would have been slow AND
    wrong."""
    body = _store_profile_body()
    a = body.index("# Category distribution")
    b = body.index("# New arrivals", a)
    cat_block = body[a:b]
    assert 'find({"sku": {"$in": _sold_skus}}' in cat_block, \
        "must use a single bulk find({sku: $in: [...]}) instead of per-SKU find_one"


def test_iter73r_response_shape_carries_basis_tag():
    """Response entries must carry `basis: "units_sold"` so the frontend
    can label the pie unambiguously (and so a future audit can detect
    any accidental fallback to catalog composition)."""
    body = _store_profile_body()
    a = body.index("# Category distribution")
    b = body.index("# New arrivals", a)
    cat_block = body[a:b]
    assert '"basis": "units_sold"' in cat_block, \
        "each row must carry basis='units_sold' — audit / display contract"
    assert '"count": v' in cat_block, \
        "the `count` dataKey must be preserved for chart backwards-compat"


def test_iter73r_empty_when_no_measured_sales():
    """When `sku_sales` is empty (Salla store with no sold-badge exposure),
    the response MUST be an empty list. NO fallback to catalog-count —
    that is the exact behavior the client called `fabricated`."""
    body = _store_profile_body()
    a = body.index("# Category distribution")
    b = body.index("# New arrivals", a)
    cat_block = body[a:b]
    assert "category_dist = []" in cat_block, \
        "category_dist must be initialised to [] so no-sales stores render empty (not catalog)"
    assert "if sku_sales:" in cat_block, \
        "the aggregation body must be guarded by `if sku_sales:` — no sales → empty"


def test_iter73r_drops_zero_unit_rows():
    """`sku_sales_daily` never writes 0 units, but the dict could contain
    stale zero entries after future merges. Belt-and-suspenders: rows
    with `units <= 0` must be skipped so a zero-unit-sold row can't
    inflate the pie."""
    body = _store_profile_body()
    a = body.index("# Category distribution")
    b = body.index("# New arrivals", a)
    cat_block = body[a:b]
    assert "if units <= 0:" in cat_block


def test_iter73r_drops_uncategorized_rows():
    """A SKU that has sales but no `category` on its products doc must be
    DROPPED (not bucketed under a fabricated "unknown" label — same
    principle as iter73h Top Brands)."""
    body = _store_profile_body()
    a = body.index("# Category distribution")
    b = body.index("# New arrivals", a)
    cat_block = body[a:b]
    assert "if not _cat:" in cat_block, \
        "uncategorized SKUs must be dropped from the pie"
    assert "\"Unknown\"" not in cat_block and "'Unknown'" not in cat_block, \
        "iter73h fence — no `Unknown` bucket in category distribution either"


# ── Math: unit-weighted vs sku-weighted diverge for real workloads ─────────
def test_iter73r_units_weighted_diverges_from_catalog_weighted():
    """Documentation of the exact bug the fix closes. A store stocking
    100 accessory SKUs (each selling 1 unit) and 20 cat_food SKUs (each
    selling 50 units) sells 1000 units of cat_food vs 100 accessory
    units — a ~91%/9% real split — but the CATALOG pie shows 17%
    cat_food / 83% accessories, the exact "fabricated" pattern the
    client screenshotted."""
    # Catalog-weighted (old, buggy)
    accessories_catalog = 100
    cat_food_catalog = 20
    total_catalog = accessories_catalog + cat_food_catalog
    catalog_cat_food_pct = round(cat_food_catalog / total_catalog * 100)
    # Units-weighted (new, correct)
    accessories_units = 100 * 1
    cat_food_units = 20 * 50
    total_units = accessories_units + cat_food_units
    units_cat_food_pct = round(cat_food_units / total_units * 100)
    # The two composition views cannot agree unless every SKU sold the
    # SAME number of units — a corner case that never holds in practice.
    assert catalog_cat_food_pct != units_cat_food_pct
    assert units_cat_food_pct >= 90 and catalog_cat_food_pct <= 20, \
        "the fix inverts the pie's dominant slice for this workload — that's the point"
