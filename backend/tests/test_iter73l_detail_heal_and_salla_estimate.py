"""iter73l — three client-reported fixes on production (Aug 3 2026):

1. VAT still on the product-detail modal for SKU 8595602540877 (180.17 SAR)
   even though Price Intel already healed. Root cause: `_build_store_prices`
   read `price` / `original_price` directly off `product_snapshots` for the
   own-store row instead of routing through `_effective_own_price`.

2. Salla store "Not measurable" on the Market Strength Ranking (Lana Pets).
   Root cause: the Salla-estimate catalog window was 30 days, so a store
   whose crawl went stale weeks ago had NO rows in `_prods_by_store` and
   was skipped. Widen the catalog window to 365d while keeping the velocity
   POOL window at 30d — catalog is structural, no sales fabrication.

3. Sort by revenue (highest → lowest). Verified already correct at
   server.py L6184-6188; test guards against regression.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from datetime import datetime, timezone

# ── Fix 1: `_build_store_prices` heals the own-store row ────────────────────
def test_build_store_prices_accepts_own_mp_row_kwarg():
    """The signature must accept the `own_mp_row=` kwarg so callers can
    plumb the my_products row for the phantom-sale heal."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("def _build_store_prices(")
    b = src.index("\n    now = now or datetime", a)
    sig = src[a:b]
    assert "own_mp_row=None" in sig, "signature must accept own_mp_row=None"


def test_build_store_prices_uses_effective_own_price_for_own_row():
    """The own-store row inside `_build_store_prices` must route through
    `_effective_own_price` (not read `latest.get('price')` raw)."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("def _build_store_prices(")
    b = src.index("\n\ndef ", a)
    body = src[a:b]
    assert "_effective_own_price(own_mp_row)" in body, \
        "own-store row must route through _effective_own_price"
    assert "if is_own and own_mp_row:" in body, \
        "heal branch must gate on is_own AND own_mp_row (only touches ONE row)"


def test_build_store_prices_recomputes_discount_after_heal():
    """After healing, the phantom sale strikethrough / discount % must be
    dropped OR recomputed against the healed price — never left with the
    stale snapshot values that no longer match `price`."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("def _build_store_prices(")
    b = src.index("\n\ndef ", a)
    body = src[a:b]
    # both branches present: real sale kept, phantom sale dropped
    assert "_orig = _healed" in body and "_disc = 0" in body, \
        "phantom-sale branch must drop the fake discount"
    assert "round((1 - _healed / _orig_mp) * 100)" in body, \
        "real-sale branch must recompute discount % against the healed price"


def test_get_product_endpoint_passes_own_mp_row():
    """`/api/products/{sku}` — the product detail modal endpoint — must
    fetch my_products and pass it to `_build_store_prices` for healing.
    This is the exact endpoint that rendered 180.17 SAR on the client's
    screenshot."""
    src = (BACKEND / "server.py").read_text()
    a = src.index('@router.get("/products/{sku}")\n')
    b = src.index("@router.get", a + 1)
    body = src[a:b]
    assert 'own_mp = await db.my_products.find_one(' in body, \
        "/products/{sku} must fetch the own my_products row"
    assert 'own_mp_row=own_mp' in body, \
        "/products/{sku} must pass own_mp_row to _build_store_prices"


def test_get_product_full_endpoint_passes_own_mp_row():
    """The `/api/products/{sku}/full` endpoint feeds the SAME detail modal
    (used in the newer chart+seller-table view) — must also heal."""
    src = (BACKEND / "server.py").read_text()
    a = src.index('@router.get("/products/{sku}/full")')
    b = src.index("@router.get", a + 1)
    body = src[a:b]
    assert 'own_mp = await db.my_products.find_one(' in body
    assert 'own_mp_row=own_mp' in body


# ── Fix 2: Salla estimate catalog widened to 365d ───────────────────────────
def test_salla_estimate_catalog_window_widened_to_365d():
    """A stale Salla store must still receive an estimate. The catalog
    window driving the Salla estimator is now 365d (a full year)."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("# ── iter56: estimated revenue for stores whose platform")
    b = src.index("# ── assemble rows", a)
    body = src[a:b]
    assert "_catalog_floor = now - timedelta(days=365)" in body, \
        "Salla estimate catalog must be windowed at 365 days"
    assert '"last_priced_at": {"$gte": _catalog_floor}' in body, \
        "sku_store_coverage query must use the 365d floor"


def test_velocity_pool_still_reads_30d_prods():
    """CRITICAL: the velocity pool (`_obs`) MUST stay 30d-tight. Widening
    the catalog would let a stale Zid store's units=0 rows pull the
    category mean DOWN and break every other store's estimate. Split
    correctness fence."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("_units_by = {(p[\"store_id\"], p[\"sku\"]): p[\"units\"] for p in sales_pairs}")
    b = src.index("_pools = salla_build_velocity_pools", a)
    body = src[a:b]
    assert "_prods_by_store_30d" in body, \
        "velocity pool must iterate `_prods_by_store_30d` (the tight dict)"
    assert "_prods_by_store_365d.get(sid, [])" not in body, \
        "velocity pool must NEVER read the 365d dict (would fabricate)"


def test_salla_estimate_reads_wide_catalog():
    """Positive fence: the Salla estimate call itself passes the 365d
    catalog to `salla_estimate_with_band` — this is the ONE place the
    widening kicks in."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("est, band, cov, detail = salla_estimate_with_band(")
    b = src.index(")", a) + 1
    call = src[a:b]
    assert "_prods_by_store_365d.get(sid)" in call, \
        "Salla estimator must read the 365d catalog dict"


# ── Fix 3: Sort by revenue (regression fence) ───────────────────────────────
def test_ranking_sorts_by_revenue_desc_then_score():
    """iter62 already sorts by revenue desc; the client complained after
    the redeploy but the code is correct. Regression fence: the sort key
    must be (no-revenue-last, revenue desc, score desc, breadth desc, name).
    """
    src = (BACKEND / "server.py").read_text()
    a = src.index("rows.sort(key=lambda r: (r[\"revenue_rank_value\"] is None,")
    b = src.index("))", a) + 2
    key = src[a:b]
    assert 'r["revenue_rank_value"] is None' in key, "None revenues sort LAST"
    assert '-(r["revenue_rank_value"] or 0.0)' in key, "revenue desc"
    assert '-r["score"]' in key, "strength score is the tie-break (desc)"


def test_ranking_output_advertises_revenue_sort():
    """The response payload must advertise `sorted_by: revenue_desc` so
    clients (and this test) can assert the contract."""
    src = (BACKEND / "server.py").read_text()
    assert '"sorted_by": "revenue_desc"' in src, \
        "response must self-describe as sorted by revenue"
