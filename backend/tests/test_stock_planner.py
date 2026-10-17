"""Stock planner arithmetic (17 Oct 2026): velocity over in-stock days only,
days of cover, reorder quantity, and the estimate of sales lost while out."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import stock_planner as sp  # noqa: E402


def test_velocity_counts_in_stock_days_only_and_lost_sales_use_it():
    r = sp.plan_row(qty=10, units=20, in_stock_days=10, oos_days=5, price=50.0, lead_days=7, cover_days=30)
    assert r["velocity_per_day"] == 2.0 and r["days_of_cover"] == 5.0
    assert r["reorder_qty"] == 2 * 37 - 10
    assert r["lost_units_est"] == 10.0 and r["lost_revenue_est"] == 500.0
    assert r["status"] == "critical"                      # 5 days <= 7-day lead time


def test_statuses():
    assert sp.plan_row(0, 0, 0, 30, 10.0, 7, 30)["status"] == "out"
    assert sp.plan_row(5, 0, 30, 0, 10.0, 7, 30)["status"] == "no_sales"
    assert sp.plan_row(12, 30, 30, 0, 10.0, 7, 30)["status"] == "low"        # 12 days of cover
    assert sp.plan_row(200, 30, 30, 0, 10.0, 7, 30)["status"] == "overstock"  # 200 days
    assert sp.plan_row(60, 30, 30, 0, 10.0, 7, 30)["status"] == "ok"
    assert sp.plan_row(200, 30, 30, 0, 10.0, 7, 30)["reorder_qty"] == 0
