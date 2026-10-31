"""A previous page result is served (labelled stale) for up to
STALE_SERVE_MAX_AGE_SECS, not only for the 6 h fresh limit: after an overnight
restart the last rebuild was 11 h old and pages answered "being prepared"
(15 Oct 2026)."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _server():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "test_stale_age")
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    from cryptography.fernet import Fernet
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import server
    return server


def test_previous_page_served_beyond_the_fresh_limit_but_not_forever():
    server = _server()
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["sa_" + uuid.uuid4().hex]
        try:
            await db.data_versions.insert_one({"_id": "observations", "revision": 7})
            await server._store_page_cache(db, "price-intel/store-ranking", None, {"stores": [{"name": "A"}]}, revision={"revision": 7})
            ages = {}
            for hours in (11, 47, 49):
                await db.dashboard_cache.update_many({}, {"$set": {"computed_at": datetime.now(timezone.utc) - timedelta(hours=hours)}})
                payload, meta = await server._previous_page_cache(db, "price-intel/store-ranking", None)
                ages[hours] = (payload, meta)
            return ages
        finally:
            await client.drop_database(db.name)
            client.close()
    ages = asyncio.run(scenario())
    assert server.STALE_SERVE_MAX_AGE_SECS > server.DASHBOARD_CACHE_MAX_AGE_SECS
    assert ages[11][0] == {"stores": [{"name": "A"}]} and ages[11][1]["stale"] is True
    assert ages[47][0] is not None
    assert ages[49] == (None, None)


def test_the_last_builds_page_is_served_after_a_republish():
    """31 Oct 2026: after every Republish all pages answered "being prepared"
    for ~15 minutes; the previous build's result is served, labelled stale."""
    server = _server()
    import price_cohort
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["sa_" + uuid.uuid4().hex]
        try:
            await db.data_versions.insert_one({"_id": "observations", "revision": 7})
            await server._store_page_cache(db, "price-intel/store-ranking", None, {"stores": [{"name": "A"}]}, revision={"revision": 7})
            doc = await db.dashboard_cache.find_one({"base": "price-intel/store-ranking"})
            old = doc["key"].replace(doc["key"].split(":")[2], "0123456789ab", 1)    # written by the last build
            await db.dashboard_cache.update_one({"_id": doc["_id"]}, {"$set": {"key": old}})
            served = await server._previous_page_cache(db, "price-intel/store-ranking", None)
            other = old.replace(f":{price_cohort.POLICY_VERSION}:", ":another-policy:", 1)
            await db.dashboard_cache.update_one({"_id": doc["_id"]}, {"$set": {"key": other}})
            refused = await server._previous_page_cache(db, "price-intel/store-ranking", None)
            return served, refused
        finally:
            await client.drop_database(db.name)
            client.close()
    served, refused = asyncio.run(scenario())
    assert served[0] == {"stores": [{"name": "A"}]} and served[1]["stale"] is True
    assert refused == (None, None)
