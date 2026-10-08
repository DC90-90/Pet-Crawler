"""iter73 — Ledger Phase 2: sealed-KSA-day windows for revenue / units KPIs.

Numbers must stop shifting between page visits. The primitive is
`ledger.sealed_ksa_window(days)` — a UTC window whose boundaries are always
KSA-midnight and whose end is TODAY's KSA midnight (i.e. yesterday's seal
cutoff). Two calls made at any two clock times within the SAME KSA day must
produce IDENTICAL boundaries; the window only advances at KSA midnight.

Companion `sealed_days_in_window` reports how many of the window's expected
days are actually sealed in the ledger, so callers can render an honest
"N of D days sealed" tooltip. Both must be side-effect-free and never raise.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ledger


# ── sealed_ksa_window: pure function, no db ────────────────────────────────
def test_sealed_window_ends_at_ksa_midnight_today():
    """End is TODAY at KSA-midnight — never `now`. So today's still-accruing
    hours are OUTSIDE the window, which is what makes the read stable."""
    now = datetime(2026, 2, 15, 14, 30, 0, tzinfo=timezone.utc)   # 17:30 KSA
    _s, end = ledger.sealed_ksa_window(14, now)
    # 14:30 UTC + 3 = 17:30 KSA of Feb 15; KSA-midnight of Feb 15 is 21:00 UTC Feb 14
    expected_end = datetime(2026, 2, 14, 21, 0, 0, tzinfo=timezone.utc)
    assert end == expected_end


def test_sealed_window_spans_exactly_days_of_ksa_time():
    now = datetime(2026, 2, 15, 14, 30, 0, tzinfo=timezone.utc)
    start, end = ledger.sealed_ksa_window(14, now)
    # start is 14 KSA-days earlier than end
    assert (end - start).total_seconds() == 14 * 24 * 3600


def test_sealed_window_stable_across_all_clock_times_within_same_ksa_day():
    """Any two invocations WITHIN the same KSA day yield IDENTICAL windows —
    the entire point of Phase 2. Sample 24 minutes across the KSA day and
    verify every result is byte-equal to 03:00 KSA."""
    base_ksa_midnight = datetime(2026, 2, 15, 21, 0, 0, tzinfo=timezone.utc)  # Feb 16 KSA 00:00
    ref = None
    for hour in range(24):
        # sample one clock time per hour within Feb 16 KSA
        probe = base_ksa_midnight + timedelta(hours=hour, minutes=hour * 2 % 60)
        got = ledger.sealed_ksa_window(30, probe)
        if ref is None:
            ref = got
        else:
            assert got == ref, f"window shifted at hour={hour}: {got} vs {ref}"


def test_sealed_window_advances_at_ksa_midnight():
    """The window advances by EXACTLY one day when the clock crosses KSA
    midnight — no earlier, no later."""
    just_before = datetime(2026, 2, 15, 20, 59, 59, tzinfo=timezone.utc)  # 23:59:59 KSA Feb 15
    just_after  = datetime(2026, 2, 15, 21, 0, 0, tzinfo=timezone.utc)   # 00:00:00 KSA Feb 16
    w_before = ledger.sealed_ksa_window(7, just_before)
    w_after  = ledger.sealed_ksa_window(7, just_after)
    assert w_before != w_after
    assert (w_after[1] - w_before[1]) == timedelta(days=1)
    assert (w_after[0] - w_before[0]) == timedelta(days=1)


def test_sealed_window_days_parameter_controls_span():
    now = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)
    _, e7 = ledger.sealed_ksa_window(7, now)
    s7, _ = ledger.sealed_ksa_window(7, now)
    s90, e90 = ledger.sealed_ksa_window(90, now)
    assert e7 == e90                                # same end
    assert (e7 - s7) == timedelta(days=7)
    assert (e90 - s90) == timedelta(days=90)


# ── sealed_days_in_window: reads db.daily_ledger_store ─────────────────────
class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
    def batch_size(self, _n):
        return self
    def __aiter__(self):
        async def gen():
            for r in self._rows:
                yield r
        return gen()


class _FakeColl:
    def __init__(self, rows):
        self._rows = rows
        self.last_query = None
    def find(self, q, proj=None):
        self.last_query = q
        return _FakeCursor([r for r in self._rows
                            if q["ksa_date"]["$gte"] <= r["ksa_date"] <= q["ksa_date"]["$lte"]
                            and (q["sealed_at"]["$ne"] is None) == (r.get("sealed_at") is not None)])


class _FakeDb:
    def __init__(self, rows):
        self.daily_ledger_store = _FakeColl(rows)


async def _sealed_days_counts_distinct(now, rows):
    db = _FakeDb(rows)
    return await ledger.sealed_days_in_window(db, 7, now)


def test_sealed_days_counts_distinct_sealed_days():
    now = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)
    # 7-day window ending at Feb 15 KSA-midnight → Feb 8..Feb 14 KSA (inclusive)
    rows = [
        # sealed
        {"ksa_date": "2026-02-08", "sealed_at": datetime(2026, 2, 9)},
        {"ksa_date": "2026-02-09", "sealed_at": datetime(2026, 2, 10)},
        {"ksa_date": "2026-02-09", "sealed_at": datetime(2026, 2, 10)},  # dup store — same day
        {"ksa_date": "2026-02-10", "sealed_at": datetime(2026, 2, 11)},
        {"ksa_date": "2026-02-11", "sealed_at": datetime(2026, 2, 12)},
        {"ksa_date": "2026-02-12", "sealed_at": datetime(2026, 2, 13)},
        # NOT sealed — must be excluded
        {"ksa_date": "2026-02-13", "sealed_at": None},
        {"ksa_date": "2026-02-14", "sealed_at": None},
        # out of window — must be excluded even though sealed
        {"ksa_date": "2026-02-07", "sealed_at": datetime(2026, 2, 8)},
        {"ksa_date": "2026-02-15", "sealed_at": datetime(2026, 2, 16)},
    ]
    out = asyncio.run(_sealed_days_counts_distinct(now, rows))
    assert out["expected"] == 7
    assert out["sealed_days"] == 5          # Feb 8/9/10/11/12 — dedup 9, exclude 13/14
    assert out["unsealed_days"] == 2
    assert out["start_ksa_date"] == "2026-02-08"
    assert out["end_ksa_date"] == "2026-02-14"


def test_sealed_days_never_raises_when_db_broken():
    class _Boom:
        def find(self, *a, **k): raise RuntimeError("connection lost")
    class _D:
        daily_ledger_store = _Boom()
    now = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)
    out = asyncio.run(ledger.sealed_days_in_window(_D(), 7, now))
    assert out["sealed_days"] == 0
    assert out["unsealed_days"] == 7        # graceful fallback, never raises


# ── downstream contract: server.py wired sealed windows into KPI paths ──
def test_server_uses_sealed_window_in_store_ranking():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text()
    # look inside _store_ranking_compute
    a = src.index("async def _store_ranking_compute")
    b = src.index("\nasync def ", a + 1)
    body = src[a:b]
    assert "store_views import ranking" in body
    import inspect
    from store_views import ranking
    body = inspect.getsource(ranking)
    assert "ledger.sealed_ksa_window" in body, \
        "_store_ranking_compute must resolve its window via ledger.sealed_ksa_window"
    assert "orders_fn(db, start, end)" in body, \
        "own-store revenue must read the sealed window"
    assert "sales_map(db, start, end)" in body, \
        "competitor sales must read the sealed window"


def test_server_uses_sealed_window_in_scanner():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text()
    a = src.index('@router.get("/scanner/opportunities")')
    b = src.index("\n@router.", a + 1)
    body = src[a:b]
    assert "ledger.sealed_ksa_window" in body
    assert "_sales_pairs_from_rollups" in body
    # and the OLD hardcoded 0 must be gone
    assert '"units_sold": 0, "market_sold": 0' not in body, \
        "Scanner still hardcodes units_sold=0 — Phase 2 wiring incomplete"


def test_sales_pairs_helper_signature_accepts_until():
    """_sales_pairs_from_rollups must accept an `until` upper bound so callers
    can clamp to sealed-KSA-day windows without duplicating the helper."""
    import inspect
    from pathlib import Path
    # import lazily so pytest doesn't try to import server at collection time
    # under a stripped env — parse the source instead.
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text()
    a = src.index("async def _sales_pairs_from_rollups")
    b = src.index("\n", a)
    signature = src[a:b]
    assert "until=None" in signature, \
        f"expected `until=None` kw in _sales_pairs_from_rollups; got: {signature}"
