"""Regression tests — own-store sold-count capture (Feb 2026 KPI fix).

Root cause being locked down: own-store snapshots used to hardcode
sold_count=0 (and _fetch_zid_api_catalog never extracted any sold field), so
the estimator's sold_count_diff method could never fire for the own store.
Combined with is_infinite products writing qty_available=0, BOTH estimation
methods dead-ended → "My Revenue (Est.)" = 0 SAR and "Avg Market Share" = 0%
on the dashboard regardless of real sales.

These tests pin:
  1. _extract_zid_sold_count — tolerant extraction across Zid field variants
  2. _own_sync_fallback_warning — alert fires only on unexpected fallback
  3. End-to-end estimator behavior with sold counters present (the fix) and
     absent (the old broken shape, kept as a documented contract)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from crawlers import _extract_zid_sold_count, _own_sync_fallback_warning  # noqa: E402
from core.utils import _estimate_sales_from_snapshots  # noqa: E402


# ── 1. Sold-field extraction ────────────────────────────────

def test_extracts_sold_quantity_primary_field():
    assert _extract_zid_sold_count({"sold_quantity": 42}) == 42


def test_extracts_alternate_field_names():
    assert _extract_zid_sold_count({"sold_count": 7}) == 7
    assert _extract_zid_sold_count({"sales_count": 13}) == 13
    assert _extract_zid_sold_count({"total_sold": 99}) == 99
    assert _extract_zid_sold_count({"sold": 3}) == 3


def test_prefers_priority_order():
    # sold_quantity wins over later candidates
    assert _extract_zid_sold_count({"sold_quantity": 10, "sold": 999}) == 10


def test_string_and_float_values_coerced():
    assert _extract_zid_sold_count({"sold_quantity": "150"}) == 150
    assert _extract_zid_sold_count({"sold_quantity": 12.0}) == 12


def test_absent_or_junk_returns_zero():
    assert _extract_zid_sold_count({}) == 0
    assert _extract_zid_sold_count({"sku": "X", "quantity": 5}) == 0
    assert _extract_zid_sold_count({"sold_quantity": None}) == 0
    assert _extract_zid_sold_count({"sold_quantity": "n/a"}) == 0


def test_negative_counter_skipped_falls_through():
    # A negative primary value is junk; a valid later candidate still counts.
    assert _extract_zid_sold_count({"sold_quantity": -5, "sold_count": 8}) == 8
    assert _extract_zid_sold_count({"sold_quantity": -5}) == 0


# ── 2. Fallback warning policy ──────────────────────────────

def test_no_warning_when_api_ok():
    assert _own_sync_fallback_warning("ok") is None


def test_no_warning_when_creds_not_configured():
    # missing_token is a setup state, not a runtime failure — no red banner.
    assert _own_sync_fallback_warning("missing_token") is None
    assert _own_sync_fallback_warning(None) is None


def test_warning_on_auth_and_network_failures():
    for status in ("auth_failed", "network_failed", "partial"):
        w = _own_sync_fallback_warning(status)
        assert w is not None
        assert status in w
        assert "My Revenue" in w


# ── 3. Estimator end-to-end with the fixed snapshot shape ───

def _own_snap(price=12.17, qty=0, sold=0):
    """Own-store snapshot exactly as sync_own_store_prices writes it."""
    return {"price": price, "qty_available": qty, "sold_count": sold}


def test_old_broken_shape_yields_zero_units():
    # Pre-fix contract: sold_count hardcoded 0 + is_infinite qty=0 → no signal.
    snaps = [_own_snap(sold=0, qty=0) for _ in range(120)]
    units, revenue, method = _estimate_sales_from_snapshots(snaps, 30)
    assert (units, revenue) == (0, 0.0)


def test_fixed_shape_recovers_real_sales_for_infinite_qty_product():
    # 31 daily syncs, counter grows 5/day, qty stays 0 (is_infinite product):
    # the sold_count_diff method must recover the full 150 units.
    snaps = [_own_snap(sold=1000 + day * 5, qty=0) for day in range(31)]
    units, revenue, method = _estimate_sales_from_snapshots(snaps, 30)
    assert method == "sold_count_diff"
    assert units == 150
    assert revenue == round(150 * 12.17, 2)


def test_counter_reset_does_not_go_negative():
    # Counter reset mid-window (e.g. product re-created in Zid) is ignored,
    # later growth still counts.
    sold_series = [100, 105, 110, 0, 5, 10]
    snaps = [_own_snap(sold=s) for s in sold_series]
    units, _, method = _estimate_sales_from_snapshots(snaps, 30)
    assert method == "sold_count_diff"
    assert units == 20  # 5+5 before reset, 5+5 after — reset step contributes 0


def test_counter_spike_clamped_per_interval():
    # A single +500 jump (backfill/manual import) is clamped to
    # MAX_SOLD_COUNT_DELTA_PER_INTERVAL (50), not counted as 500 sales.
    snaps = [_own_snap(sold=0), _own_snap(sold=500), _own_snap(sold=505)]
    units, _, _ = _estimate_sales_from_snapshots(snaps, 30)
    assert units == 55  # 50 (clamped) + 5
