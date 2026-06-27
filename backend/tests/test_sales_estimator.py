"""Regression tests for the sales estimator's sold_count sanity behaviour.

The Feb 2026 P1 data accuracy guard rewrote `_estimate_sales_from_snapshots`'s
Method 1 (sold_count) to sum CLAMPED per-step diffs instead of the raw
`last - first`. This guards against:
  • Counter resets / partner-sync backfills (suspicious downward jumps)
  • Single-step spikes (one bad data point inflating the window total by 1000+)
  • Long-window totals exceeding MAX_DAILY_SALES_PER_SKU * days
"""
from datetime import datetime, timedelta, timezone

import pytest

from core.utils import (
    _estimate_sales_from_snapshots,
    MAX_SOLD_COUNT_DELTA_PER_INTERVAL,
    MAX_DAILY_SALES_PER_SKU,
)


_BASE = datetime.now(timezone.utc)


def _snap(days_back: int, sold_count=None, qty=None, price=10.0):
    return {
        "crawled_at": _BASE - timedelta(days=days_back),
        "sold_count": sold_count,
        "qty_available": qty,
        "price": price,
    }


def test_monotonic_counter_growth_sums_correctly():
    snaps = [_snap(3, sold_count=10), _snap(2, sold_count=12),
             _snap(1, sold_count=15), _snap(0, sold_count=20)]
    units, _rev, method = _estimate_sales_from_snapshots(snaps, days=3)
    assert units == 10
    assert method == "sold_count_diff"


def test_counter_reset_captures_both_growth_runs():
    """5 → 10 (drop) 3 → 8 should yield 5 + 5 = 10 units, not 8 - 5 = 3."""
    snaps = [_snap(4, sold_count=5), _snap(3, sold_count=10),
             _snap(2, sold_count=3), _snap(1, sold_count=8)]
    units, _rev, method = _estimate_sales_from_snapshots(snaps, days=4)
    assert units == 10
    assert method == "sold_count_diff"


def test_per_step_spike_is_clamped():
    """A single jump of 4990 in one snapshot must be clamped to the per-step max."""
    snaps = [_snap(2, sold_count=10), _snap(1, sold_count=5000),
             _snap(0, sold_count=5005)]
    units, _rev, _method = _estimate_sales_from_snapshots(snaps, days=2)
    expected = min(
        MAX_SOLD_COUNT_DELTA_PER_INTERVAL + 5,
        MAX_DAILY_SALES_PER_SKU * 2,
    )
    assert units == expected


def test_falls_back_to_qty_depletion_when_no_sold_counter():
    snaps = [_snap(2, sold_count=0, qty=20), _snap(1, sold_count=0, qty=15),
             _snap(0, sold_count=0, qty=10)]
    units, _rev, method = _estimate_sales_from_snapshots(snaps, days=2)
    assert units == 10
    assert method == "qty_positive_delta_sum"


def test_single_snapshot_returns_zero():
    units, _rev, method = _estimate_sales_from_snapshots(
        [_snap(0, sold_count=10)], days=1
    )
    assert units == 0
    assert method == "insufficient_data"


def test_daily_cap_enforced_for_long_window():
    """40 units/day × 9 deltas = 360. Capped to MAX_DAILY_SALES_PER_SKU × days = 300."""
    snaps = [_snap(i, sold_count=(10 - i) * 40) for i in range(10, 0, -1)]
    units, _rev, _method = _estimate_sales_from_snapshots(snaps, days=10)
    assert units == MAX_DAILY_SALES_PER_SKU * 10
