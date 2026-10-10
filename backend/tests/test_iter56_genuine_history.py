"""Real loopback Mongo regression: invented prices cannot corroborate discounts."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from price_cohort import exclusion, snapshot_pipeline
from test_p0_my_products_baseline import _loopback_mongo_url


@pytest.mark.anyio
async def test_synthetic_history_excluded_without_resurrecting_older_offers():
    client = AsyncIOMotorClient(_loopback_mongo_url())
    db_name = "history_verify_" + uuid.uuid4().hex
    db = client[db_name]
    now = datetime.now(timezone.utc)
    base = dict(store_id="store", observation_version=2, is_synthetic=False,
                comparable=True, currency="SAR", price_basis="storefront_inc_vat",
                confidence_score=99, in_stock=True, present_on_store=True)
    try:
        rows = []
        for oid, flags in (("synthetic", {"is_synthetic": True}),
                           ("demo", {"data_origin": "demo_seed"})):
            rows.extend([
                {**base, "offer_id": oid, "price": 120, "crawled_at": now-timedelta(days=179)},
                {**base, "offer_id": oid, "price": 9999, "crawled_at": now-timedelta(days=10), **flags},
                {**base, "offer_id": oid, "price": 40, "crawled_at": now},
                {**base, "offer_id": oid, "price": 8888, "crawled_at": now-timedelta(days=181)},
                {**base, "offer_id": oid+"-latest", "price": 60, "crawled_at": now-timedelta(hours=1)},
                {**base, "offer_id": oid+"-latest", "price": 7777, "crawled_at": now, **flags},
                {**base, "offer_id": oid+"-only", "price": 9999, "crawled_at": now, **flags},
            ])
        await db.product_snapshots.insert_many(rows)
        observed = {r["offer_id"]: r async for r in db.product_snapshots.aggregate(
            snapshot_pipeline(["store"], now), maxTimeMS=2000)}
        for oid in ("synthetic", "demo"):
            valid = observed[oid]
            assert valid["historical_max_price"] == 120
            assert valid["price"] == 40
            assert exclusion(valid, now) is None
            assert valid["history_oldest_at"].replace(tzinfo=timezone.utc).date() == (now-timedelta(days=179)).date()
            latest = observed[oid+"-latest"]
            assert latest["price"] == 7777  # Select latest before eligibility, never resurrect60.
            assert latest["historical_max_price"] == 60
            assert exclusion(latest, now) == "synthetic_observation"
            assert observed[oid+"-only"]["historical_max_price"] is None
    finally:
        await client.drop_database(db_name)
        client.close()