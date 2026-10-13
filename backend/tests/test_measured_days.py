"""A revenue total says on how many days it was measured (13 Oct 2026: one
observed day was shown as a 14-day revenue)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evidence_ledger import measured_days  # noqa: E402


def test_measured_days_are_distinct_per_store():
    sales = {
        ("own", "o1"): {"units": 2, "revenue": 20.0, "days": ["2026-10-12"]},
        ("own", "o2"): {"units": 1, "revenue": 9.0, "days": ["2026-10-12", "2026-10-13"]},
        ("comp", "x"): {"units": 5, "revenue": 50.0, "days": ["2026-10-09", "2026-10-10", "2026-10-11"]},
    }
    assert measured_days(sales, "own") == ["2026-10-12", "2026-10-13"]
    assert len(measured_days(sales, "comp")) == 3
    assert measured_days(sales, "nobody") == []
