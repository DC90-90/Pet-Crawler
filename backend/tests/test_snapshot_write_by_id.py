"""Competitor snapshots are upserted on _id = event_id, so a write never needs
an index on the event_id field (production has none and Atlas drops the
connection while building it). Replays stay idempotent (12 Oct 2026)."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_snapshot_id_is_the_event_id_and_replay_is_idempotent():
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    import crawlers

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["snapid_" + uuid.uuid4().hex]
        try:
            store = {"id": "comp", "name": "Comp", "domain": "comp.example", "platform": "zid",
                     "currency": "SAR", "is_own_store": False}
            await db.stores.insert_one(dict(store))
            now = datetime.now(timezone.utc)
            raw = {"id": "L1", "sku": "SKU-1", "name": "Cat food 2kg", "price": 50, "quantity": 7,
                   "currency": "SAR", "barcode": "6281000000017"}
            await crawlers.process_crawled_products(db, store, [dict(raw)], now, tier=1, confidence=95)
            await crawlers.process_crawled_products(db, store, [dict(raw)], now, tier=1, confidence=95)
            rows = await db.product_snapshots.find({"store_id": "comp"}).to_list(10)
            # No index on event_id exists in this database.
            assert not any(v.get("key") == [("event_id", 1)] for v in (await db.product_snapshots.index_information()).values())
            return rows
        finally:
            await client.drop_database(db.name)
            client.close()
    rows = asyncio.run(scenario())
    assert len(rows) == 1
    assert rows[0]["_id"] == rows[0]["event_id"]
    assert rows[0]["observation_version"] == 2 and rows[0]["price"] == 50
