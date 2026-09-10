"""iter78 — nightly PRICE HISTORY ARCHIVE.

Client ask: *"Set up a nightly cloud backup of every store's crawled prices so I
keep the full history forever"*.

These tests stub the storage transport (the HTTP PUT) and exercise everything
around it: the KSA day boundary, what lands in each file, the manifest, the
`archive_files` index the admin panel lists from, and the idempotency that
matters most here — the storage API OVERWRITES silently and has no delete, so a
second run must not touch a night that is already frozen unless asked to.
"""
import asyncio
import gzip
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["DB_NAME"] = "test_iter78_archive"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_iter78_archive"
import pytest  # noqa: E402
import archive  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
DAY = "2026-08-24"
KSA = timezone(timedelta(hours=3))


@pytest.fixture(autouse=True)
def _fake_storage(monkeypatch):
    """No network: capture what would have been uploaded."""
    uploaded = {}

    def _put(path, data, content_type):
        uploaded[path] = {"data": data, "content_type": content_type}
        return {"path": path, "size": len(data), "etag": "x"}

    monkeypatch.setattr(archive, "put_object", _put)
    monkeypatch.setattr(archive, "get_object",
                        lambda p: (uploaded[p]["data"], uploaded[p]["content_type"]))
    monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-test")
    archive.uploaded = uploaded
    yield uploaded


def _db():
    return AsyncIOMotorClient(MONGO)[_TEST_DB]


async def _seed(db):
    for c in ("stores", "product_snapshots", "sku_sales_daily", "daily_ledger",
              "archive_files"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": "s1", "name": "Caty", "domain": "caty-store.com"},
        {"id": "s2", "name": "Pets Houses", "domain": "pets-houses.com"},
        {"id": "s3", "name": "Never Crawled", "domain": "nope.com"},
    ])
    # 03:00 KSA on the target day, and one an hour BEFORE the day opened
    inside = datetime(2026, 8, 24, 3, 0, tzinfo=KSA).astimezone(timezone.utc)
    before = datetime(2026, 8, 23, 23, 0, tzinfo=KSA).astimezone(timezone.utc)
    await db.product_snapshots.insert_many([
        {"id": "a", "sku": "SKU-1", "store_id": "s1", "store_name": "Caty",
         "price": 10.5, "sale_price": 9.0, "discount_pct": 14, "qty_available": 3,
         "in_stock": True, "product_url": "https://caty-store.com/products/x",
         "confidence_score": 99, "crawled_at": inside, "internal_note": "drop me"},
        {"id": "b", "sku": "SKU-2", "store_id": "s1", "store_name": "Caty",
         "price": 20.0, "in_stock": False, "crawled_at": inside},
        {"id": "c", "sku": "SKU-1", "store_id": "s2", "store_name": "Pets Houses",
         "price": 12.0, "in_stock": True, "crawled_at": inside},
        {"id": "d", "sku": "SKU-9", "store_id": "s1", "store_name": "Caty",
         "price": 99.0, "crawled_at": before},          # previous KSA day
    ])
    await db.sku_sales_daily.insert_many([
        {"store_id": "s1", "sku": "SKU-1", "date": DAY, "units_sold": 2, "rev_sold": 21.0},
        {"store_id": "s1", "sku": "SKU-1", "date": "2026-08-23", "units_sold": 5},
    ])
    await db.daily_ledger.insert_many([
        {"store_id": "s1", "ksa_date": DAY, "sku": "SKU-1", "open_price": 10.5},
        {"store_id": "s1", "ksa_date": "2026-08-23", "sku": "SKU-1", "open_price": 11.0},
    ])


def _rows(blob):
    return [json.loads(l) for l in gzip.decompress(blob).decode().splitlines()]


# ── the KSA day boundary ─────────────────────────────────────────────────────
def test_a_ksa_day_starts_at_21_00_utc_the_day_before():
    start, end = archive.ksa_day_bounds_utc(DAY)
    assert start == datetime(2026, 8, 23, 21, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc)


def test_previous_ksa_day_is_yesterday_in_riyadh():
    now = datetime(2026, 8, 25, 0, 30, tzinfo=timezone.utc)   # 03:30 KSA
    assert archive.previous_ksa_day(now) == "2026-08-24"


# ── what lands in the files ──────────────────────────────────────────────────
def test_one_file_per_store_holding_only_that_stores_day(_fake_storage):
    async def main():
        db = _db()
        await _seed(db)
        res = await archive.archive_day(db, DAY)
        assert res["status"] == "archived"

        p1 = f"daleel/archive/{DAY}/snapshots/s1.jsonl.gz"
        p2 = f"daleel/archive/{DAY}/snapshots/s2.jsonl.gz"
        assert set(_fake_storage) == {
            p1, p2,
            f"daleel/archive/{DAY}/rollups/sku_sales_daily.jsonl.gz",
            f"daleel/archive/{DAY}/rollups/daily_ledger.jsonl.gz",
            f"daleel/archive/{DAY}/manifest.json",
        }, "a store with nothing that night gets no file"

        caty = _rows(_fake_storage[p1]["data"])
        assert {r["sku"] for r in caty} == {"SKU-1", "SKU-2"}, "the 23rd is not in the 24th"
        assert len(_rows(_fake_storage[p2]["data"])) == 1

        # prices, stock AND discounts are kept; mongo internals are not
        row = next(r for r in caty if r["sku"] == "SKU-1")
        assert row["price"] == 10.5 and row["sale_price"] == 9.0
        assert row["discount_pct"] == 14 and row["in_stock"] is True
        assert row["qty_available"] == 3 and row["product_url"].endswith("/x")
        assert "_id" not in row and "internal_note" not in row

        # the rollups are filtered to the same day, on their own date fields
        assert len(_rows(_fake_storage[f"daleel/archive/{DAY}/rollups/sku_sales_daily.jsonl.gz"]["data"])) == 1
        assert len(_rows(_fake_storage[f"daleel/archive/{DAY}/rollups/daily_ledger.jsonl.gz"]["data"])) == 1
    asyncio.run(main())


def test_the_manifest_and_the_index_agree(_fake_storage):
    async def main():
        db = _db()
        await _seed(db)
        res = await archive.archive_day(db, DAY)
        man = json.loads(_fake_storage[f"daleel/archive/{DAY}/manifest.json"]["data"])
        assert man["date"] == DAY and man["rows"] == 5      # 3 snapshots + 2 rollup rows
        assert {f["kind"] for f in man["files"]} == {"snapshots", "sku_sales_daily", "daily_ledger"}

        rows = await db.archive_files.find({"date": DAY, "is_deleted": False}).to_list(50)
        assert len(rows) == res["files"] == 5
        assert all(r["path"].startswith(f"daleel/archive/{DAY}/") for r in rows)
        # the panel reads store names from here, not from the storage path
        assert {r["store_name"] for r in rows if r["kind"] == "snapshots"} == {"Caty", "Pets Houses"}

        st = await archive.archive_status(db)
        assert st["configured"] and st["latest_day"] == DAY
        assert st["days"][0]["files"] == 5 and st["days"][0]["rows"] == man["rows"] == 5
    asyncio.run(main())


# ── never overwrite a frozen night ───────────────────────────────────────────
def test_a_second_run_leaves_an_archived_night_alone(_fake_storage):
    async def main():
        db = _db()
        await _seed(db)
        await archive.archive_day(db, DAY)
        _fake_storage.clear()
        again = await archive.archive_day(db, DAY)
        assert again["status"] == "skipped" and again["reason"] == "already_archived"
        assert _fake_storage == {}, "storage PUT overwrites silently — do not call it"
        assert await db.archive_files.count_documents({"date": DAY, "is_deleted": False}) == 5
    asyncio.run(main())


def test_force_rewrites_and_retires_the_old_index_rows(_fake_storage):
    async def main():
        db = _db()
        await _seed(db)
        await archive.archive_day(db, DAY)
        res = await archive.archive_day(db, DAY, force=True)
        assert res["status"] == "archived"
        # storage has no delete, so the superseded rows are soft-deleted
        assert await db.archive_files.count_documents({"date": DAY, "is_deleted": True}) == 5
        assert await db.archive_files.count_documents({"date": DAY, "is_deleted": False}) == 5
    asyncio.run(main())


def test_a_day_with_no_data_writes_nothing(_fake_storage):
    async def main():
        db = _db()
        await _seed(db)
        res = await archive.archive_day(db, "2026-01-01")
        assert res["status"] == "empty" and _fake_storage == {}
        assert await db.archive_files.count_documents({"date": "2026-01-01"}) == 0
    asyncio.run(main())


def test_without_a_storage_key_the_archive_is_a_no_op(monkeypatch, _fake_storage):
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)

    async def main():
        db = _db()
        await _seed(db)
        res = await archive.archive_day(db, DAY)
        assert res["status"] == "skipped" and res["reason"] == "no_emergent_key"
        st = await archive.archive_status(db)
        assert st["configured"] is False
    asyncio.run(main())
