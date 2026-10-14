"""The full export writes every collection as raw BSON parts, skips caches and
accounts, and the parts decode back to the exact documents (14 Oct 2026)."""
import asyncio
import gzip
import os
import sys
import uuid
from datetime import datetime

import bson
from bson import ObjectId

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    client = AsyncIOMotorClient(_loopback_mongo_url())
    return client, client["fx_" + uuid.uuid4().hex]


def test_export_round_trips_every_collection(monkeypatch):
    import archive
    import full_export
    store = {}
    monkeypatch.setattr(archive, "put_object", lambda path, data, ctype: store.__setitem__(path, data) or {"path": path, "size": len(data)})
    monkeypatch.setattr(full_export, "CHUNK_DOCS", 3)

    async def scenario():
        client, db = _db()
        try:
            when = datetime(2026, 9, 1)            # naive UTC, as BSON decodes it
            snaps = [{"_id": ObjectId(), "sku": f"S{i}", "price": 10.5 + i, "crawled_at": when, "is_synthetic": False} for i in range(7)]
            snaps.append({"_id": "evt-1", "sku": "S8", "price": 1, "crawled_at": "2026-08-01T00:00:00"})
            await db.product_snapshots.insert_many(snaps)
            await db.stores.insert_one({"id": "s1", "name": "Hamtaro"})
            await db.users.insert_one({"email": "a@b.c", "password": "hash"})
            await db.cache_blobs.insert_one({"_id": "k", "blob": b"x"})
            run_id = await full_export.start(db, "owner@test")
            assert await full_export.start(db, "again@test") is None      # one export at a time
            await full_export._tasks[run_id]
            run = await db.export_runs.find_one({"id": run_id})
            files = await db.export_files.find({"run_id": run_id}).to_list(100)
            return snaps, run, files
        finally:
            await client.drop_database(db.name)
            client.close()

    snaps, run, files = asyncio.run(scenario())
    assert run["status"] == "done" and run["failed"] == []
    assert set(run["collections"]) == {"product_snapshots", "stores"}   # users and caches skipped
    snap_parts = sorted((f for f in files if f["collection"] == "product_snapshots"), key=lambda f: f["part"])
    assert [f["docs"] for f in snap_parts] == [3, 3, 2]
    raw = b"".join(gzip.decompress(store[f["path"]]) for f in snap_parts)
    assert list(bson.decode_all(raw)) == snaps                          # exact types, ids, dates
    assert any(f["collection"] == "_manifest" for f in files)
