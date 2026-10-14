"""Revenue evidence from the sealed daily ledger (14 Oct 2026): the whole
window instead of the days since 12 Oct, Zid stock only, Salla counters only
when reported on both days, caps from sales_evidence, and one count for a
sale that storefronts sharing one stock all report."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ledger_sales  # noqa: E402

STORES = {"z": {"name": "Zid A", "platform": "zid"}, "y": {"name": "Zid B", "platform": "zid"},
          "s": {"name": "Salla", "platform": "salla"}, "o": {"name": "Other", "platform": "zid"}}


def _row(sid, sku, date, qty=None, sold=None, price=10.0):
    return {"store_id": sid, "sku": sku, "ksa_date": date, "qty_available": qty,
            "sold_count_cumulative": sold, "close_price": price}


def _day(n):
    return (datetime(2026, 10, 1) + timedelta(days=n)).strftime("%Y-%m-%d")


def _run(rows, start=_day(0), end=_day(30)):
    sealed = {(r["store_id"], r["ksa_date"]) for r in rows}
    facts, groups, _observed = ledger_sales.compute(rows, sealed, start, end, STORES, {})
    per = {}
    for f in facts:
        p = per.setdefault(f["store_id"], [0, 0.0])
        p[0] += f["units"]
        p[1] += f["revenue"]
    return per, groups


def test_stock_drops_with_caps_gaps_and_zid_counter_ignored():
    rows = [_row("z", "a", _day(0), 10), _row("z", "a", _day(1), 7),              # 3 units
            _row("z", "a", _day(2), 7), _row("z", "a", _day(3), 9),               # restock: no sale
            _row("z", "b", _day(0), 100), _row("z", "b", _day(1), 40),            # 60 > cap 30: adjustment
            _row("z", "c", _day(0), 10), _row("z", "c", _day(5), 2),              # 5-day gap: no interval
            _row("z", "d", _day(0), 5, sold=0), _row("z", "d", _day(1), 4, sold=25)]  # Zid counter appears: stock says 1
    per, _ = _run(rows)
    assert per["z"] == [4, 40.0]


def test_salla_counter_counts_only_when_reported_on_both_days():
    rows = [_row("s", "a", _day(0), 0, sold=0), _row("s", "a", _day(1), 0, sold=12),   # first report: not a sale
            _row("s", "a", _day(2), 0, sold=15), _row("s", "a", _day(3), 0, sold=90)]  # +3, then +75 > cap 50
    per, _ = _run(rows)
    assert per["s"] == [3, 30.0]


def test_shared_stock_is_counted_once_for_the_lead():
    rows = []
    for i in range(40):                                  # 40 identical stock movements in z and y
        sku = f"p{i}"
        for sid, extra in (("z", 0), ("y", 0)):
            rows += [_row(sid, sku, _day(i % 10), 50 + i), _row(sid, sku, _day(i % 10 + 1), 45 + i)]
    rows += [_row("z", "own", _day(0), 30), _row("z", "own", _day(1), 20)]   # z only
    rows += [_row("o", f"q{i}", _day(i % 10), 2) for i in range(40)]         # unrelated small drops
    rows += [_row("o", f"q{i}", _day(i % 10 + 1), 1) for i in range(40)]
    per, groups = _run(rows)
    assert [sorted(g["members"]) for g in groups] == [["y", "z"]]
    lead = groups[0]["lead"]
    other = "y" if lead == "z" else "z"
    assert per[lead][0] == 40 * 5 + (10 if lead == "z" else 0)
    assert per.get(other, [0])[0] == (10 if other == "z" else 0)            # only its own drop
    assert per["o"][0] == 40


def test_unchanged_in_stock_reading_is_a_measured_zero_only_for_a_live_store():
    rows = [_row("z", "sold", _day(0), 9), _row("z", "sold", _day(1), 8),      # z is live (a sale)
            _row("z", "flat", _day(0), 5), _row("z", "flat", _day(1), 5),      # read twice, no sale -> zero
            _row("z", "oos", _day(0), 0), _row("z", "oos", _day(1), 0),        # 0 -> 0 proves nothing
            _row("z", "restock", _day(0), 2), _row("z", "restock", _day(1), 6),  # a restock can hide sales
            _row("o", "static", _day(0), 4), _row("o", "static", _day(1), 4)]  # store never moves: no zeros
    sealed = {(r["store_id"], r["ksa_date"]) for r in rows}
    _facts, _groups, observed = ledger_sales.compute(rows, sealed, _day(0), _day(30), STORES, {})
    assert [(o["store_id"], o["sku"], o["dates"]) for o in observed] == [("z", "flat", [_day(1)])]


def test_a_store_day_missing_from_the_ledger_is_completed_from_snapshots():
    """11 Oct 2026: snapshots saved, ledger rows not; the hole broke the chain."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    from archive import ksa_day_bounds_utc

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["lh_" + uuid.uuid4().hex]
        try:
            skus = [f"p{i}" for i in range(60)]
            rows = [_row("z", s, d, q) for s in skus for d, q in (("2026-10-10", 20), ("2026-10-12", 14))]
            noon = ksa_day_bounds_utc("2026-10-11")[0] + timedelta(hours=9)
            await db.product_snapshots.insert_many(
                [{"store_id": "z", "sku": s, "crawled_at": noon, "qty_available": 17, "price": 10.0, "is_synthetic": False} for s in skus]
                + [{"store_id": "z", "sku": "p0", "crawled_at": noon - timedelta(hours=2), "qty_available": 19, "price": 10.0}])
            filled, pairs = await ledger_sales.fill_ledger_holes(db, rows, ["z"], "2026-10-10", "2026-10-12")
            return rows, filled, pairs
        finally:
            await client.drop_database(db.name)
            client.close()
    rows, filled, pairs = asyncio.run(scenario())
    assert pairs == [("z", "2026-10-11")] and len(filled) == 60
    assert {r["qty_available"] for r in filled} == {17}                  # the day's LAST reading
    sealed = {(r["store_id"], r["ksa_date"]) for r in rows + filled}
    facts, _g, _o = ledger_sales.compute(rows + filled, sealed, "2026-10-11", "2026-10-12", STORES, {})
    assert sum(f["units"] for f in facts) == 60 * 6                       # 20 -> 17 -> 14, every SKU


def test_rebuild_and_sales_map_through_the_evidence_ledger(monkeypatch):
    import evidence_ledger
    import ledger
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    monkeypatch.setenv("SALES_SOURCE", "ledger")
    now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["ls_" + uuid.uuid4().hex]
        try:
            await db.stores.insert_one({"id": "z", "name": "Zid A", "platform": "zid"})
            await db.daily_ledger.insert_many([_row("z", "a", "2026-10-11", 10, price=20), _row("z", "a", "2026-10-12", 6, price=20),
                                               _row("z", "a", "2026-10-13", 5, price=20),
                                               _row("z", "b", "2026-10-12", 3), _row("z", "b", "2026-10-13", 3)])
            await db.daily_ledger_store.insert_many([{"store_id": "z", "ksa_date": d, "sealed_at": now}
                                                     for d in ("2026-10-11", "2026-10-12", "2026-10-13")])
            await db.observation_events.insert_one({"store_id": "z", "sku": "a", "offer_id": "offer-a", "observed_at": now})
            first = await ledger_sales.rebuild_if_stale(db, now=now)
            again = await ledger_sales.rebuild_if_stale(db, now=now)      # same sealed day: no-op
            start, end = ledger.sealed_ksa_window(30, now)
            return first, again, await evidence_ledger.sales_map(db, start, end)
        finally:
            await client.drop_database(db.name)
            client.close()
    first, again, sales = asyncio.run(scenario())
    assert first["facts"] == 2 and again is None
    row = sales[("z", "offer-a")]
    assert row["units"] == 5 and row["revenue"] == 100.0 and row["days"] == ["2026-10-12", "2026-10-13"]
    zero = sales[("z", "b")]                                             # measured: sold nothing
    assert zero["units"] == 0 and zero["revenue"] == 0 and zero["days"] == ["2026-10-13"]
