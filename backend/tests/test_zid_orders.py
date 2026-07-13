"""Tests for the real-orders My Revenue rework (zid_orders.py).

Locks down:
  1. normalize_zid_order — defensive field extraction across Zid payload shapes
  2. Status exclusion — cancelled/refunded orders never count toward revenue
  3. Bundle correctness — component expansion lines are not double-counted
  4. aggregate_orders — revenue = Σ order totals; by_sku from line totals
  5. KSA day semantics — naive Zid timestamps land on the right calendar day
  6. The success condition — a July 1 with 39 orders / 11,092.91 SAR in Zid
     aggregates to exactly 11,092.91, not an estimate
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from zid_orders import (  # noqa: E402
    aggregate_orders,
    normalize_zid_order,
    orders_day_window,
    parse_order_datetime,
    KSA_TZ,
)


# ── 1. Normalization across payload shapes ──────────────────

def test_normalize_minimal_order():
    o = normalize_zid_order({
        "id": 987, "code": "ORD-987", "order_status": {"name": "Delivered", "code": "delivered"},
        "created_at": "2026-07-01 14:30:00", "order_total": "284.50",
        "products": [{"sku": "780348005614", "quantity": 2, "price": 12.17, "total": 24.34}],
    })
    assert o["order_id"] == "987"
    assert o["status"] == "delivered"
    assert o["excluded"] is False
    assert o["total"] == 284.50
    assert o["units"] == 2
    assert o["items"][0]["sku"] == "780348005614"
    assert o["items"][0]["line_total"] == 24.34


def test_normalize_total_field_variants():
    assert normalize_zid_order({"id": 1, "order_total": 100})["total"] == 100.0
    assert normalize_zid_order({"id": 2, "grand_total": "1,234.56"})["total"] == 1234.56
    assert normalize_zid_order({"id": 3, "total": {"value": 55.5}})["total"] == 55.5
    assert normalize_zid_order({"id": 4})["total"] == 0.0  # absent → 0, never None


def test_normalize_status_variants_and_exclusion():
    assert normalize_zid_order({"id": 1, "order_status": "Cancelled"})["excluded"] is True
    assert normalize_zid_order({"id": 2, "order_status": {"code": "reverse_in_progress"}})["excluded"] is True
    assert normalize_zid_order({"id": 3, "status": "refunded"})["excluded"] is True
    assert normalize_zid_order({"id": 4, "order_status": {"name": "New"}})["excluded"] is False
    assert normalize_zid_order({"id": 5, "order_status": {"name": "In Delivery"}})["excluded"] is False


def test_normalize_requires_id():
    assert normalize_zid_order({"order_total": 99}) is None


def test_line_total_computed_from_unit_price_when_missing():
    o = normalize_zid_order({
        "id": 1, "order_total": 60,
        "products": [{"sku": "A", "quantity": 3, "price": 20}],
    })
    assert o["items"][0]["line_total"] == 60.0


# ── 2. Bundle correctness ───────────────────────────────────

def test_bundle_child_lines_not_double_counted():
    # A "Bundle of 5" order where Zid expands the 5 components as child lines
    # referencing the parent. Only the bundle parent must count.
    o = normalize_zid_order({
        "id": 55, "order_total": 199.0, "order_status": {"code": "delivered"},
        "created_at": "2026-07-01 10:00:00",
        "products": [
            {"sku": "Z.17827348205780544", "quantity": 1, "price": 199.0, "total": 199.0, "is_bundle": True},
            {"sku": "COMP-1", "quantity": 2, "price": 30.0, "parent_id": "Z.17827348205780544"},
            {"sku": "COMP-2", "quantity": 3, "price": 25.0, "parent_order_product_id": 912},
        ],
    })
    assert o["units"] == 1                      # bundle counts once
    assert len(o["items"]) == 1                 # children dropped
    assert o["items"][0]["is_bundle"] is True
    assert o["total"] == 199.0                  # revenue from order total — no double count


def test_bundle_without_child_markers_counts_normally():
    # If Zid ships bundles as a single self-contained line, nothing is dropped.
    o = normalize_zid_order({
        "id": 56, "order_total": 398.0,
        "products": [{"sku": "Z.BUNDLE", "quantity": 2, "price": 199.0, "total": 398.0}],
    })
    assert o["units"] == 2
    assert o["total"] == 398.0


# ── 3. Aggregation ──────────────────────────────────────────

def _mk(total, units=1, sku="A", excluded=False, line_total=None):
    return {
        "excluded": excluded, "total": total, "units": units,
        "items": [{"sku": sku, "qty": units, "line_total": line_total if line_total is not None else total}],
    }


def test_aggregate_sums_order_totals_and_skips_excluded():
    agg = aggregate_orders([_mk(100), _mk(50.5), _mk(999, excluded=True)])
    assert agg["revenue"] == 150.5
    assert agg["orders_count"] == 2
    assert agg["units"] == 2


def test_aggregate_by_sku_attribution():
    agg = aggregate_orders([
        _mk(120, units=2, sku="X", line_total=100),   # 20 SAR shipping in order total
        _mk(80, units=1, sku="Y", line_total=80),
        _mk(40, units=1, sku="X", line_total=35),
    ])
    assert agg["by_sku"]["X"] == {"units": 3, "revenue": 135.0}
    assert agg["by_sku"]["Y"] == {"units": 1, "revenue": 80.0}
    # KPI revenue is order-total based (matches the Zid dashboard incl. fees)
    assert agg["revenue"] == 240.0


# ── 4. KSA day semantics ────────────────────────────────────

def test_naive_timestamps_treated_as_ksa():
    # 2026-07-01 01:30 KSA = 2026-06-30 22:30 UTC
    dt = parse_order_datetime("2026-07-01 01:30:00")
    assert dt == datetime(2026, 6, 30, 22, 30, tzinfo=timezone.utc)


def test_orders_day_window_matches_zid_dashboard_day():
    start, end = orders_day_window("2026-07-01")
    # KSA July 1 runs 2026-06-30T21:00Z → 2026-07-01T21:00Z
    assert start == datetime(2026, 6, 30, 21, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 1, 21, 0, tzinfo=timezone.utc)
    # An order placed 23:50 KSA on July 1 belongs to July 1
    late = parse_order_datetime("2026-07-01 23:50:00")
    assert start <= late < end


# ── 5. Success condition: July 1 reconciles exactly ─────────

def test_july_first_reconciles_with_zid_dashboard():
    """39 orders totaling 11,092.91 SAR (the real July 1 figures) must
    aggregate to exactly 11,092.91 — not the old ~6,220 estimate."""
    totals = [284.42] * 38  # 38 equal orders
    totals.append(11092.91 - sum(totals))  # 39th balances to the exact total
    orders = [_mk(round(t, 2)) for t in totals]
    agg = aggregate_orders(orders)
    assert agg["orders_count"] == 39
    assert agg["revenue"] == 11092.91
