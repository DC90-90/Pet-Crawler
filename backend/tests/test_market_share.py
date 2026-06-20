"""Unit tests for true per-product market share + the sold_count crash-guard.

These are PURE-logic tests: core.utils imports only the stdlib, so they run
without FastAPI/Mongo/network. Run from the backend dir:

    python -m pytest tests/test_market_share.py        # or
    python tests/test_market_share.py                  # plain-python fallback
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.utils import compute_market_share, _coerce_int, _estimate_sales_from_snapshots


def _snap(days_ago, qty=None, sold=None, price=10.0):
    return {
        "crawled_at": datetime.now(timezone.utc) - timedelta(days=days_ago),
        "qty_available": qty if qty is not None else 0,
        "sold_count": sold if sold is not None else 0,
        "price": price,
    }


def test_awaiting_history_when_own_snaps_insufficient():
    # No own history yet → share is None (NOT a misleading 0%), competitors still counted.
    # (Counter baseline is the first NON-zero value, per the existing estimator, so use 5->25.)
    comp = [[_snap(7, sold=5), _snap(0, sold=25)]]  # competitor sold 20 via counter
    res = compute_market_share(own_snaps=[], competitor_snaps_by_seller=comp, days=7)
    assert res["status"] == "awaiting_own_history"
    assert res["market_share_pct"] is None
    assert res["competitor_units"] == 20

    res1 = compute_market_share(own_snaps=[_snap(0, sold=5)], competitor_snaps_by_seller=comp, days=7)
    assert res1["status"] == "awaiting_own_history"  # need >= 2 own snaps


def test_true_share_via_sold_count_diff():
    # Own sold 30 (counter 100->130), one competitor sold 10 (counter 5->15).
    own = [_snap(7, sold=100), _snap(0, sold=130)]
    comp = [[_snap(7, sold=5), _snap(0, sold=15)]]
    res = compute_market_share(own, comp, days=7)
    assert res["status"] == "ok"
    assert res["own_units"] == 30
    assert res["competitor_units"] == 10
    assert res["market_units"] == 40
    assert res["market_share_pct"] == 75.0  # 30/40


def test_share_via_qty_depletion_fallback():
    # No sold_count signal → fall back to qty depletion. Own drops 50->40 (10 units).
    own = [_snap(6, qty=50), _snap(3, qty=45), _snap(0, qty=40)]
    # Competitor drops 30->20 (10 units) across 3 points.
    comp = [[_snap(6, qty=30), _snap(3, qty=25), _snap(0, qty=20)]]
    res = compute_market_share(own, comp, days=7)
    assert res["status"] == "ok"
    assert res["own_units"] == 10
    assert res["competitor_units"] == 10
    assert res["market_share_pct"] == 50.0


def test_no_market_data_when_nobody_sells():
    # Enough own snaps but zero measurable sales anywhere.
    own = [_snap(7, qty=10), _snap(0, qty=10)]
    res = compute_market_share(own, [], days=7)
    assert res["status"] == "no_market_data"
    assert res["market_share_pct"] is None


def test_hundred_percent_when_no_competitors_sell():
    own = [_snap(7, sold=3), _snap(0, sold=15)]  # own sold 12
    comp = [[_snap(7, sold=5), _snap(0, sold=5)]]  # competitor counter flat → 0 units
    res = compute_market_share(own, comp, days=7)
    assert res["status"] == "ok"
    assert res["own_units"] == 12
    assert res["competitor_units"] == 0
    assert res["market_share_pct"] == 100.0


def test_coerce_int_crash_guard():
    # The crash-guard: non-numeric / junk sold_count must degrade to 0, never raise.
    assert _coerce_int("150") == 150
    assert _coerce_int("not available") == 0
    assert _coerce_int(None) == 0
    assert _coerce_int("1,250") == 1250
    assert _coerce_int(42.9) == 42


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
