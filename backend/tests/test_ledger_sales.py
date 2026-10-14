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
    facts, groups = ledger_sales.compute(rows, sealed, start, end, STORES, {})
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
                                               _row("z", "a", "2026-10-13", 5, price=20)])
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
