"""Controlled verification of tester findings; no production/auth-policy changes."""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
import server
import market_share
import store_views
from price_cohort import exclusion
from release_database import GuardedDatabase
from test_iter51_readpath_optimization import _loopback_mongo_url


@pytest.mark.parametrize("vary_forwarded_for", [False, True])
def test_existing_five_per_minute_limit_with_stable_peer(vary_forwarded_for):
    async def run():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db_name = "rate_verify_"+uuid.uuid4().hex
        original_db, enabled = server.db, server.limiter.enabled
        server.db = GuardedDatabase(client[db_name])
        server.limiter.enabled = True
        server.limiter.reset()  # In-memory limiter of this isolated test process.
        try:
            transport = httpx.ASGITransport(app=server.app, client=("198.51.100.42", 31000))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                statuses = []
                for i in range(6):
                    headers = {"X-Forwarded-For": f"192.0.2.{i+1}"} if vary_forwarded_for else {}
                    response = await ac.post("/api/auth/login", headers=headers, json={
                        "email": "nonexistent-"+uuid.uuid4().hex+"@test.invalid", "password": uuid.uuid4().hex})
                    statuses.append(response.status_code)
            assert statuses == [401, 401, 401, 401, 401, 429], statuses
            assert await client[db_name].users.count_documents({}) == 0
        finally:
            server.limiter.reset()
            server.limiter.enabled = enabled
            server.db = original_db
            await client.drop_database(db_name)
            client.close()
    asyncio.run(run())


def test_latest_low_confidence_and_persisted_exclusion_flags():
    async def run():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db_name = "flags_verify_"+uuid.uuid4().hex
        db = client[db_name]
        now = datetime.now(timezone.utc)
        base = dict(store_id="store", observation_version=2, is_synthetic=False, comparable=True,
                    currency="SAR", price_basis="storefront_inc_vat", price=40, confidence_score=99,
                    crawled_at=now, in_stock=True, present_on_store=True)
        try:
            await db.stores.insert_one({"id": "store", "name": "Store", "is_active": True})
            await db.product_snapshots.insert_many([
                {**base, "offer_id": "low", "crawled_at": now-timedelta(hours=1)},
                {**base, "offer_id": "low", "confidence_score": 30, "price": 80},
                {**base, "offer_id": "demo", "data_origin": "demo_seed"},
                {**base, "offer_id": "parent", "superseded_parent": True},
            ])
            rows = await market_share._latest_snapshots(GuardedDatabase(db), now-timedelta(days=7), 85)
            low = next(r for r in rows if r["offer_id"] == "low")
            assert low["price"] == 80 and exclusion(low, now) == "low_source_confidence"
            projected = await store_views.latest(GuardedDatabase(db), since=now-timedelta(days=7), projection=store_views.ELIGIBILITY_FIELDS)
            reasons = {r["offer_id"]: exclusion(r, now) for r in projected}
            assert reasons == {"low": "low_source_confidence", "demo": "synthetic_observation", "parent": "parent_listing_not_an_offer"}
            async def no_orders(*_args):
                return None
            ranking = await store_views.ranking(GuardedDatabase(db), no_orders)
            assert ranking["stores"][0]["products"] == 0
        finally:
            await client.drop_database(db_name)
            client.close()
    asyncio.run(run())