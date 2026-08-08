"""iter73s — Route Salla stores through Tier 2.5/3 for revenue (Aug 8 2026).

Client confirmed Zarafa (a Salla store, 4,177 products) really sells >1M
SAR/month. Yet the Store Profile page rendered 162.5 SAR (post-iter73q
alignment). Root cause: `sku_sales_daily` for Salla stores captures well
under 1% of real sales — Salla only publishes bucketed "sold X times"
badges on a handful of bestsellers, and those buckets rarely tick over
during a crawl window. The measurement exists but is unrepresentative.

Fix (iter73s):

* `_store_ranking_compute` — for Salla stores, suppress Tier 1
  (`revenue_by_store`) so the cascade in `_ranking_revenue_value` falls
  through to Tier 2.5 (MEASURED ~ badge diff) or Tier 3 (±50% ESTIMATE).
  Zid stores unaffected — their Merchant API sold_count is authoritative.

* `store_profile` — for Salla stores, do the SAME cascade inline: badge
  diff → category-velocity estimate → sales_data_unavailable. Emits new
  fields `revenue_basis`, `revenue_band_pct`, `revenue_range_low/high`
  so the FE can render an "ESTIMATE ±50%" chip next to the KPI.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


# ── _store_ranking_compute suppresses Tier 1 for Salla ──────────────────────
def test_iter73s_ranking_suppresses_tier1_for_salla_only():
    src = (BACKEND / "server.py").read_text()
    # Locate the competitor branch of the row assembly.
    a = src.index('async def _store_ranking_compute(db):')
    b = src.index('# ── iter62: rank on REVENUE', a)
    body = src[a:b]
    assert 'iter73s' in body, "iter73s marker missing from ranking row-assembly"
    # The Salla suppression must live inside the `else:` (non-own-store) branch.
    assert 'platform_low = (meta.get("platform") or "").lower()' in body, \
        "must read platform once per row"
    assert 'if platform_low == "salla":\n                rev = 0.0' in body, \
        "for Salla stores, Tier 1 (revenue_by_store) must be suppressed to 0.0"
    assert 'else:\n                rev = round(revenue_by_store.get(sid, 0.0), 2)' in body, \
        "Zid stores must keep the Tier 1 path unchanged"


def test_iter73s_ranking_cascade_preserved():
    """After Tier 1 is suppressed, the cascade in `_ranking_revenue_value`
    (Tier 2.5 → Tier 3) MUST still exist so Salla stores get a value from
    the fallback tiers."""
    src = (BACKEND / "server.py").read_text()
    a = src.index('def _ranking_revenue_value(row):')
    b = src.index('async def _store_ranking_compute(db):', a)
    body = src[a:b]
    assert 'return float(ap_rev), "measured_approx"' in body, \
        "Tier 2.5 branch must still be present"
    assert 'return float(est_rev), "estimated"' in body, \
        "Tier 3 branch must still be present"
    # Regression fence: order of tiers preserved (exact → approx → est).
    assert body.index('"exact"') < body.index('"measured_approx"') < body.index('"estimated"')


# ── store_profile inline cascade ────────────────────────────────────────────
def _store_profile_body():
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def store_profile(store_id: str")
    b = src.index("    return {", a)
    return src[a:b]


def test_iter73s_store_profile_detects_salla_platform():
    body = _store_profile_body()
    assert '_is_salla = (store.get("platform") or "").lower() == "salla"' in body, \
        "store profile must branch on platform=='salla' to trigger the cascade"


def test_iter73s_store_profile_resets_tier1_for_salla():
    body = _store_profile_body()
    a = body.index("iter73s")
    b = body.index("est_monthly_revenue = round(", a)
    salla_block = body[a:b]
    assert "if _is_salla:" in salla_block
    assert "total_rev = 0.0" in salla_block, \
        "the profile must discard the sparse Tier 1 measurement before running the cascade"
    assert "total_sold = 0" in salla_block
    assert "_sales_by_sku_units = {}" in salla_block


def test_iter73s_store_profile_runs_badge_diff_first():
    body = _store_profile_body()
    a = body.index("Tier 2.5: MEASURED ~ from Salla sold-badge diff")
    b = body.index("Tier 3: ", a)
    tier25 = body[a:b]
    assert "salla_diff_series(" in tier25
    assert "salla_store_revenue_from_velocity(" in tier25
    # Must read product_snapshots scoped to THIS store with sold_count_cumulative present.
    assert '"store_id": store_id' in tier25
    assert '"crawled_at": {"$gte": since_90d}' in tier25
    assert '"sold_count_cumulative": {"$exists": True}' in tier25


def test_iter73s_store_profile_falls_through_to_estimate():
    body = _store_profile_body()
    a = body.index("Tier 3: ")
    b = body.index("est_monthly_revenue = round(", a)
    tier3 = body[a:b]
    assert "salla_build_velocity_pools(" in tier3
    assert "salla_estimate_with_band(" in tier3
    # Pool builder uses the same 30d ranking window (per iter73l docs).
    assert "_RANKING_WINDOW_DAYS" in tier3
    # Catalog widened to 365d (iter73l) so stale-but-known Salla stores still
    # get an estimate — matches the ranking's estimator input.
    assert "timedelta(days=365)" in tier3


def test_iter73s_store_profile_zid_stores_untouched():
    """Regression fence: Zid stores must keep the Tier 1 path — no Salla
    routing branch executes for them."""
    body = _store_profile_body()
    # The Salla branch is guarded by `if _is_salla:` — its scope must NOT
    # override the aggregates on non-Salla paths (i.e., no fall-through
    # `else` that resets total_rev for other platforms).
    a = body.index("if _is_salla:")
    b = body.index("est_monthly_revenue = round(", a)
    salla_block = body[a:b]
    # No stray `else:` at the top level that would run for Zid.
    stripped = "\n".join(line for line in salla_block.splitlines() if line and not line.startswith("    #"))
    # Confirm the total_rev reset only appears inside the `if _is_salla:` scope.
    assert stripped.count("total_rev = 0.0") == 1


def test_iter73s_store_profile_response_carries_estimate_fields():
    src = (BACKEND / "server.py").read_text()
    # Response block for store_profile.
    a = src.index("async def store_profile(store_id: str")
    b = src.index("# ── Export", a)
    body = src[a:b]
    assert '"revenue_basis": revenue_basis' in body, \
        "response must include the tier basis so FE knows what chip to render"
    assert '"revenue_band_pct": revenue_band_pct' in body, \
        "response must include the ±% band for the ESTIMATE chip"
    assert '"revenue_range_low": revenue_range_low' in body
    assert '"revenue_range_high": revenue_range_high' in body


def test_iter73s_revenue_status_carries_tier_for_measured_revenue():
    """When total_rev > 0, revenue_status now carries the tier name so
    frontends can distinguish 'measured Zid' from 'estimate for Salla'."""
    body = _store_profile_body()
    a = body.index("if total_rev > 0:")
    b = body.index("elif not _has_signal:", a)
    branch = body[a:b]
    assert "revenue_status = revenue_basis" in branch, \
        "revenue_status must reflect the tier when we have a positive value"


# ── Math: cascade yields a realistic number for a large Salla store ────────
def test_iter73s_cascade_math_zarafa_style_case():
    """A store with 4,000 SKUs at an average priced-shelf of 100 SAR and
    an observed velocity of 0.001 units/product-day (typical of Zid
    competitors) produces an estimate on the order of 12,000 SAR/month
    per 100 products — orders of magnitude bigger than the 162.5 SAR
    Tier 1 returned. The test pins the arithmetic so a future formula
    tweak can't silently regress."""
    from salla_revenue_estimate import estimate_store_revenue
    velocity_per_product_day = 0.001    # 1 sale per 1000 product-days
    catalog_size = 4000
    priced_avg = 100.0
    days = 30
    # `estimate_store_revenue` expects `pools` produced by
    # `build_velocity_pools` — per_sku/per_category are MEAN velocities
    # (scalars), not lists. Global is a single mean too.
    pools = {
        "per_sku": {},
        "per_category": {"pet_food": velocity_per_product_day},
        "global": velocity_per_product_day,
    }
    products = [{"sku": f"S{i}", "price": priced_avg, "category": "pet_food"}
                for i in range(catalog_size)]
    est, _detail = estimate_store_revenue(products, pools, days)
    # Sanity: 4000 * 100 * 0.001 * 30 = 12,000 SAR/month
    assert 10_000 < est < 20_000, f"expected 12K SAR for this synthetic case, got {est}"
    # Compared to what Tier 1 returned for Zarafa (162.5 SAR), the cascade
    # produces an order-of-magnitude bigger figure — the whole point of
    # the fix. `est=12,000` in this synthetic case is already ~74× larger
    # than Tier 1's 162.5.
    assert est > 50 * 162.5


def test_iter73s_marker_present_on_both_surfaces():
    src = (BACKEND / "server.py").read_text()
    assert src.count("iter73s") >= 3, \
        "iter73s marker required on ranking + profile + at least one comment for future audit"
