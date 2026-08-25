"""iter67 — Ledger Phase 1: append-only writer, KSA day-seal, no_data marker.

The audit established that the existing rollups are a CACHE — wiped and
rebuilt from product_snapshots on every crawl — so every past day is a pure
function of the present. Phase 1 starts the approved history-first migration:
an immutable daily record written ALONGSIDE the rollups. Nothing reads it yet.

Ahmad's rulings pinned here:
  KSA days     boundaries at Asia/Riyadh midnight (UTC+3), matching the own
               orders ledger — a 21:30 UTC observation belongs to TOMORROW's
               KSA day.
  levels       sold_count_cumulative stores the counter LEVEL, never a delta.
  sealing      once a day is sealed it is immutable — later writes are
               refused and counted, not applied.
  no_data      a store that produced nothing gets a no_data STORE-day row.
               Absence is recorded as a fact; a missing day must never read
               as zero, and stale values must never stand in for it.
  honesty      only observed values, ever. backfilled=False from this writer.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_ledger_p1"
import ledger  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")

# 12:00 UTC = 15:00 KSA — safely mid-day on both calendars
T0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
DAY = "2026-08-01"


def _db():
    return AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]


async def _reset(db):
    for c in ("daily_ledger", "daily_ledger_store", "stores", "sku_store_coverage"):
        await db[c].delete_many({})


def _obs(sku, price=100.0, sale=None, qty=5, in_stock=True, sold=0, disc=0):
    return {"sku": sku, "close_price": price, "close_sale_price": sale,
            "close_original_price": price, "discount_pct": disc,
            "on_sale": bool(sale) or disc > 0, "in_stock": in_stock,
            "qty_available": qty, "sold_count_cumulative": sold}


def _run(coro):
    return asyncio.run(coro)


# ── (d) KSA day boundary ────────────────────────────────────────────────────

def test_ksa_boundary_for_utc_timestamps_near_midnight():
    # 21:30 UTC = 00:30 KSA next day
    assert ledger.ksa_day_str(datetime(2026, 8, 1, 21, 30, tzinfo=timezone.utc)) == "2026-08-02"
    # 20:59 UTC = 23:59 KSA same day
    assert ledger.ksa_day_str(datetime(2026, 8, 1, 20, 59, tzinfo=timezone.utc)) == "2026-08-01"
    # naive datetimes are treated as UTC, matching how crawl `now` is produced
    assert ledger.ksa_day_str(datetime(2026, 8, 1, 21, 0)) == "2026-08-02"
    # the crawl window (01:00-01:55 UTC = 04:00-04:55 KSA) is mid-day KSA-wise
    assert ledger.ksa_day_str(datetime(2026, 8, 1, 1, 30, tzinfo=timezone.utc)) == "2026-08-01"


# ── (a) one row per (store, sku, KSA day), latest wins intra-day ────────────

def test_intraday_upsert_latest_wins_and_counts_observations():
    async def main():
        db = _db()
        await _reset(db)
        # 04:00 KSA crawl says 100; 14:00 KSA ingest says 95
        r1 = await ledger.record_observations(
            db, "zarafa", "Zarafa", [_obs("SKU-1", price=100.0, qty=5, sold=40)],
            T0, source_tier=2, confidence=88)
        r2 = await ledger.record_observations(
            db, "zarafa", "Zarafa", [_obs("SKU-1", price=95.0, qty=4, sold=42)],
            T0 + timedelta(hours=3), source_tier=0, confidence=99)
        assert r1["written"] == 1 and r2["written"] == 1
        rows = await db.daily_ledger.find({"store_id": "zarafa"}, {"_id": 1}).to_list(10)
        assert len(rows) == 1                                # ONE row for the day
        row = await db.daily_ledger.find_one({"_id": f"zarafa|SKU-1|{DAY}"})
        assert row["close_price"] == 95.0                    # latest observation won
        assert row["qty_available"] == 4
        assert row["observations_that_day"] == 2
        assert row["ksa_date"] == DAY
        assert row["sealed_at"] is None
        assert row["backfilled"] is False
        assert row["writer_version"] == ledger.LEDGER_WRITER_VERSION
        # store-day doc reflects the day so far
        sd = await db.daily_ledger_store.find_one({"_id": f"zarafa|{DAY}"})
        assert sd["status"] == "ok" and sd["skus_observed"] == 1
    asyncio.run(main())


def test_two_stores_and_two_days_never_collide():
    async def main():
        db = _db()
        await _reset(db)
        await ledger.record_observations(db, "a", "A", [_obs("X")], T0)
        await ledger.record_observations(db, "b", "B", [_obs("X")], T0)
        await ledger.record_observations(db, "a", "A", [_obs("X")], T0 + timedelta(days=1))
        ids = sorted([r["_id"] async for r in db.daily_ledger.find({}, {"_id": 1})])
        assert ids == ["a|X|2026-08-01", "a|X|2026-08-02", "b|X|2026-08-01"]
    asyncio.run(main())


# ── (e) sold_count stored as LEVEL ──────────────────────────────────────────

def test_sold_count_cumulative_is_stored_as_the_level():
    async def main():
        db = _db()
        await _reset(db)
        await ledger.record_observations(db, "z", "Z", [_obs("S", sold=137)], T0)
        await ledger.record_observations(
            db, "z", "Z", [_obs("S", sold=150)], T0 + timedelta(days=1))
        d1 = await db.daily_ledger.find_one({"_id": f"z|S|{DAY}"})
        d2 = await db.daily_ledger.find_one({"_id": "z|S|2026-08-02"})
        assert d1["sold_count_cumulative"] == 137            # the LEVEL...
        assert d2["sold_count_cumulative"] == 150            # ...on each day
        # no delta field exists anywhere on the row
        assert not any("delta" in k or k == "units_sold" for k in d2)
    asyncio.run(main())


# ── (b) sealing: sealed rows are immutable ──────────────────────────────────

def test_seal_sets_sealed_at_and_later_writes_are_rejected():
    async def main():
        db = _db()
        await _reset(db)
        await db.stores.insert_one({"id": "z", "name": "Z", "is_active": True})
        await ledger.record_observations(db, "z", "Z", [_obs("S", price=80.0)], T0)

        out = await ledger.seal_ksa_day(db, day=DAY, now=T0 + timedelta(hours=13))
        assert out["stores_sealed"] == 1 and out["rows_sealed"] == 1
        row = await db.daily_ledger.find_one({"_id": f"z|S|{DAY}"})
        sd = await db.daily_ledger_store.find_one({"_id": f"z|{DAY}"})
        assert row["sealed_at"] is not None and sd["sealed_at"] is not None

        # a late write to the sealed day is refused and counted, never applied
        late = await ledger.record_observations(
            db, "z", "Z", [_obs("S", price=1.0)], T0 + timedelta(minutes=5))
        assert late["rejected_sealed"] == 1 and late["written"] == 0
        row2 = await db.daily_ledger.find_one({"_id": f"z|S|{DAY}"})
        assert row2["close_price"] == 80.0                   # unchanged
        assert row2["observations_that_day"] == 1

        # re-sealing is an idempotent no-op
        again = await ledger.seal_ksa_day(db, day=DAY, now=T0 + timedelta(hours=14))
        assert again["stores_sealed"] == 0 and again["rows_sealed"] == 0
        row3 = await db.daily_ledger.find_one({"_id": f"z|S|{DAY}"})
        assert row3["sealed_at"] == row["sealed_at"]
    asyncio.run(main())


def test_row_level_seal_rejection_without_store_day_gate():
    """Belt and braces: even if only the ROW is sealed (store-day doc missing),
    the writer's filter refuses it via the duplicate-key path."""
    async def main():
        db = _db()
        await _reset(db)
        await ledger.record_observations(db, "z", "Z", [_obs("S", price=80.0)], T0)
        await db.daily_ledger.update_one(
            {"_id": f"z|S|{DAY}"}, {"$set": {"sealed_at": T0}})
        await db.daily_ledger_store.delete_many({})          # remove the day gate
        late = await ledger.record_observations(
            db, "z", "Z", [_obs("S", price=1.0)], T0 + timedelta(hours=1))
        assert late["rejected_sealed"] == 1 and late["written"] == 0
        row = await db.daily_ledger.find_one({"_id": f"z|S|{DAY}"})
        assert row["close_price"] == 80.0
    asyncio.run(main())


# ── (c) no_data rows for silent stores ──────────────────────────────────────

def test_seal_writes_no_data_rows_for_silent_active_stores():
    async def main():
        db = _db()
        await _reset(db)
        await db.stores.insert_many([
            {"id": "loud", "name": "Loud", "is_active": True},
            {"id": "silent", "name": "Silent", "is_active": True},
            {"id": "retired", "name": "Retired", "is_active": False},
        ])
        await ledger.record_observations(db, "loud", "Loud", [_obs("S")], T0)
        out = await ledger.seal_ksa_day(db, day=DAY, now=T0 + timedelta(hours=13))
        assert out["no_data_stores"] == 1

        silent = await db.daily_ledger_store.find_one({"_id": f"silent|{DAY}"})
        assert silent["status"] == "no_data"
        assert silent["skus_observed"] == 0
        assert silent["sealed_at"] is not None
        # no PRODUCT rows were invented for the silent store — absence is a
        # store-day fact, never fabricated per-sku values
        assert await db.daily_ledger.count_documents({"store_id": "silent"}) == 0
        # inactive stores get nothing at all
        assert await db.daily_ledger_store.find_one({"_id": f"retired|{DAY}"}) is None
    asyncio.run(main())


def test_seal_marks_thin_days_partial_and_counts_absentees():
    async def main():
        db = _db()
        await _reset(db)
        await db.stores.insert_one({"id": "z", "name": "Z", "is_active": True})
        # the store is known to carry 10 skus (coverage = catalogue-bounded truth)
        await db.sku_store_coverage.insert_many([
            {"_id": f"K{i}|z", "sku": f"K{i}", "store_id": "z"} for i in range(10)])
        # today's crawl only saw 3 of them
        await ledger.record_observations(
            db, "z", "Z", [_obs(f"K{i}") for i in range(3)], T0)
        await ledger.seal_ksa_day(db, day=DAY, now=T0 + timedelta(hours=13))
        sd = await db.daily_ledger_store.find_one({"_id": f"z|{DAY}"})
        assert sd["status"] == "partial"                     # 3 < 50% of 10
        assert sd["absent_count"] == 7
        assert sd["skus_observed"] == 3
    asyncio.run(main())


# ── first-seen flag ─────────────────────────────────────────────────────────

def test_first_day_flag_comes_from_prior_coverage():
    async def main():
        db = _db()
        await _reset(db)
        await db.sku_store_coverage.insert_one(
            {"_id": "OLD|z", "sku": "OLD", "store_id": "z"})
        out = await ledger.record_observations(
            db, "z", "Z", [_obs("OLD"), _obs("NEW")], T0)
        assert out["first_seen"] == 1
        old = await db.daily_ledger.find_one({"_id": f"z|OLD|{DAY}"})
        new = await db.daily_ledger.find_one({"_id": f"z|NEW|{DAY}"})
        assert old["is_first_day_for_store"] is False
        assert new["is_first_day_for_store"] is True
        sd = await db.daily_ledger_store.find_one({"_id": f"z|{DAY}"})
        assert sd["first_seen_count"] == 1
    asyncio.run(main())


# ── honesty: observed values only ───────────────────────────────────────────

def test_unobserved_fields_stay_none_never_fabricated():
    async def main():
        db = _db()
        await _reset(db)
        await ledger.record_observations(
            db, "z", "Z",
            [{"sku": "S", "close_price": None, "close_sale_price": None,
              "close_original_price": None, "discount_pct": 0, "on_sale": False,
              "in_stock": False, "qty_available": None, "sold_count_cumulative": None}],
            T0)
        row = await db.daily_ledger.find_one({"_id": f"z|S|{DAY}"})
        assert row["close_price"] is None                    # absent stays absent
        assert row["sold_count_cumulative"] is None
        assert row["backfilled"] is False
    asyncio.run(main())


# ── the wiring exists on all three paths, alongside (not replacing) rollups ─

def test_all_three_persistence_paths_write_the_ledger():
    import inspect

    import crawlers
    import server
    crawl_src = inspect.getsource(crawlers.process_crawled_products)
    assert "ledger.record_observations" in crawl_src
    own_src = inspect.getsource(crawlers.sync_own_store_prices)
    assert "ledger.record_observations" in own_src
    ingest_src = inspect.getsource(server.crawler_ingest)
    assert "ledger.record_observations" in ingest_src
    # Phase 1 is ALONGSIDE: the rollup writer is untouched and never
    # references the ledger
    rollup_src = inspect.getsource(server._recompute_store_metrics)
    assert "ledger" not in rollup_src
    # and the seal job is scheduled at 21:30 UTC = 00:30 KSA
    assert "ledger_day_seal" in Path(server.__file__).read_text()


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception:
            bad += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
