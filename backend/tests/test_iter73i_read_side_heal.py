"""iter73i (read-side) — `_effective_own_price` heal for phantom Zid sales.

The write-time fix (see test_iter73i_phantom_sale.py) prevents NEW my_products
rows from carrying the phantom `sale_price × 1.15`. This test suite covers
the READ-time helper `server._effective_own_price` which heals rows written
by pre-iter73i code so operators see the shopper-facing shelf price
IMMEDIATELY after a redeploy — no sync or backfill wait required.

Reference case: SKU 8595602540877 written by iter73d as
    price=180.17 (sale × 1.15), sale_price=180.17, original_price=237.02
    (list × 1.15), price_basis="merchant_assumed_inc_vat"
must now render 237.02 SAR at read time.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import server  # noqa: E402


eop = server._effective_own_price


# ── canonical repro: SKU 8595602540877 ─────────────────────────────────────
def test_repro_sku_8595602540877_heals_to_237_02():
    """A pre-iter73i my_products row carrying the phantom-sale shape must
    return the LIST price (237.02), matching what the shopper actually pays
    on the storefront."""
    mp = {
        "sku": "8595602540877",
        "price": 180.17,           # phantom sale × 1.15
        "sale_price": 180.17,      # phantom sale × 1.15
        "original_price": 237.02,  # LIST × 1.15 (the real shelf)
        "price_basis": "merchant_assumed_inc_vat",
    }
    assert eop(mp) == 237.02


# ── storefront rows are truth — trust as-written ───────────────────────────
def test_storefront_row_trusts_effective_price():
    """`storefront_inc_vat` rows come from the actual public shelf; sale
    or list, whatever's there is what the shopper pays."""
    mp = {"price": 200.0, "sale_price": 170.0, "original_price": 200.0,
          "price_basis": "storefront_inc_vat"}
    assert eop(mp) == 170.0            # on-sale shelf


def test_storefront_row_no_sale_uses_price():
    mp = {"price": 170.0, "sale_price": None, "original_price": 170.0,
          "price_basis": "storefront_inc_vat"}
    assert eop(mp) == 170.0


# ── merchant paths: heal ONLY when original materially exceeds price ───────
def test_merchant_row_with_higher_original_returns_original():
    mp = {"price": 100.0, "sale_price": 100.0, "original_price": 130.0,
          "price_basis": "merchant_computed_inc_vat"}
    assert eop(mp) == 130.0            # 30% "phantom" heals up to list


def test_merchant_row_original_equals_price_no_heal():
    """No phantom → fall back to the effective as-written."""
    mp = {"price": 100.0, "sale_price": None, "original_price": 100.0,
          "price_basis": "merchant_computed_inc_vat"}
    assert eop(mp) == 100.0


def test_merchant_row_original_within_rounding_no_heal():
    """0.5% margin absorbs VAT-rounding drift so a 100.00 vs 100.30 pair
    (from `round(x * 1.15, 2)` on legitimate 87 vs 87.26 ex-VAT prices)
    doesn't flip on us."""
    mp = {"price": 100.00, "sale_price": None, "original_price": 100.30,
          "price_basis": "merchant_computed_inc_vat"}
    assert eop(mp) == 100.0            # within 1.005 margin → no heal


def test_merchant_row_original_just_above_margin_heals():
    """1% higher is well outside the rounding margin — the phantom heals."""
    mp = {"price": 100.00, "sale_price": None, "original_price": 101.50,
          "price_basis": "merchant_computed_inc_vat"}
    assert eop(mp) == 101.50


# ── legacy rows without original_price ─────────────────────────────────────
def test_legacy_row_no_original_falls_back_to_effective():
    """Pre-iter73d rows didn't persist `original_price`. No heal → return the
    effective (sale OR price)."""
    mp = {"price": 150.0, "sale_price": 120.0}     # no original_price, no basis
    assert eop(mp) == 120.0


def test_legacy_row_no_sale_falls_back_to_price():
    mp = {"price": 150.0}                          # bare row
    assert eop(mp) == 150.0


# ── iter73i hidden branch (write-side already list-anchored) ───────────────
def test_iter73i_hidden_branch_no_double_heal():
    """When the write-side has already list-anchored (iter73i), the row
    carries price == original_price. The read-side must be a no-op — never
    an inflation."""
    mp = {"price": 237.02, "sale_price": None, "original_price": 237.02,
          "price_basis": "merchant_hidden_from_storefront_inc_vat"}
    assert eop(mp) == 237.02


def test_iter73i_hidden_non_taxable_no_double_heal():
    mp = {"price": 60.0, "sale_price": None, "original_price": 60.0,
          "price_basis": "merchant_hidden_non_taxable"}
    assert eop(mp) == 60.0


# ── defensive: bad inputs never crash the read path ────────────────────────
def test_none_row_returns_zero():
    assert eop(None) == 0.0


def test_empty_row_returns_zero():
    assert eop({}) == 0.0


def test_string_price_survives_coercion():
    """product_snapshots occasionally have string prices from legacy ingest.
    _effective_own_price must never throw."""
    mp = {"price": "100.0", "sale_price": None, "original_price": "130.0",
          "price_basis": "merchant_computed_inc_vat"}
    assert eop(mp) == 130.0


def test_none_original_price_falls_back():
    mp = {"price": 100.0, "sale_price": None, "original_price": None,
          "price_basis": "merchant_computed_inc_vat"}
    assert eop(mp) == 100.0


# ── wiring: the 5 my_price computation sites all call _effective_own_price ─
def test_price_intel_dashboard_uses_effective_helper():
    """The Price Intel dashboard 'My Advantage' / 'Full Comparison' / 'Un-
    verified' rows must all route my_price through `_effective_own_price` —
    the exact fix for the client-reported bug on SKU 8595602540877."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def _price_intel_dashboard_compute")
    b = src.index("# ── Saved Filters", a) if "# ── Saved Filters" in src[a:] else len(src)
    body = src[a:b]
    # every my_price computation inside this function uses the helper
    assert body.count("_effective_own_price(mp)") >= 2, \
        "both by_sku and unverified_by_sku loops must use _effective_own_price"


def test_my_products_dataset_uses_effective_helper():
    """The My Products page's per-row headline Price column must also heal."""
    src = (BACKEND / "server.py").read_text()
    # positive assertion: the helper is present near the row builder
    a = src.index('mp_name_ar = mp_doc.get("name_ar")')
    b = src.index("row[\"my_price\"] =", a)
    assert "_effective_own_price(mp_doc)" in src[a:b], \
        "My Products row builder must heal my_price"


def test_market_position_uses_effective_helper():
    """The market-position section (line ~3660) also reads `my_price` and
    must heal."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("for sku in my_skus:\n                mp_row = my_price_lookup")
    b = src.index("continue", a)
    assert "_effective_own_price(mp_row)" in src[a:b]


def test_product_detail_panel_uses_effective_helper():
    """The product detail panel (opened by clicking a card) must also render
    the healed price. Site: `my_price_live = ...` in the panel loader."""
    src = (BACKEND / "server.py").read_text()
    # regression fence: the raw sale-first shape must not reappear at this exact site
    assert 'my_price_live = float(mp.get("sale_price") or mp.get("price") or 0)' not in src, \
        "product detail panel still uses raw sale-first pattern"
    assert "my_price_live = _effective_own_price(mp)" in src


def test_alerts_generation_uses_effective_helper():
    """Auto-generated price alerts must fire against the healed my_price so
    a phantom-sale doesn't spuriously flag a store as overpriced."""
    src = (BACKEND / "server.py").read_text()
    # locate the alert-generation loop
    a = src.index("# 1) Price drop alerts for RED overpriced products")
    b = src.index("db.alerts.insert_one", a)
    body = src[a:b]
    assert "_effective_own_price(mp)" in body, \
        "alert-generation loop must heal my_price"
