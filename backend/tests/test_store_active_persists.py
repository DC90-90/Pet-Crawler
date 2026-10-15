"""A store the operator deactivates stays inactive across restarts: a boot step
used to force caty-store.com back to active on every boot (15 Oct 2026)."""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_boot_store_sync_keeps_a_deactivated_store_inactive():
    import store_registry
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["sp_" + uuid.uuid4().hex]
        try:
            await store_registry.ensure_stores(db)
            await db.stores.update_many({}, {"$set": {"is_active": True}})
            await db.stores.update_one({"domain": "caty-store.com"}, {"$set": {"is_active": False}})
            await store_registry.ensure_stores(db)          # the next boot
            caty = await db.stores.find_one({"domain": "caty-store.com"})
            others = await db.stores.count_documents({"domain": {"$ne": "caty-store.com"}, "is_active": False})
            return caty, others
        finally:
            await client.drop_database(db.name)
            client.close()
    caty, others = asyncio.run(scenario())
    assert caty is not None and caty["is_active"] is False
    assert others == 0
