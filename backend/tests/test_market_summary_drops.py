"""Overview price summary (20 Oct 2026): price drops are day-over-day closing
price falls from the daily ledger, read per store on its index — the whole-
window snapshot scan outran the background budget at 30/90 days."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_drops_count_day_over_day_falls_per_store_and_sku(monkeypatch):
    import comparison_views
    import ledger
    import store_views
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    async def fake_context(db, price_fn, competitor_store_ids=None):
        return {"id": "own"}, [], {}

    async def fake_latest(db, **kwargs):
        return []
    monkeypatch.setattr(comparison_views, "context", fake_context)
    monkeypatch.setattr(store_views, "latest", fake_latest)

    def day(n):
        return ledger.ksa_day_str(datetime.now(timezone.utc) - timedelta(days=n))

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["ms_" + uuid.uuid4().hex]
        try:
            await db.stores.insert_many([{"id": "a"}, {"id": "b"}])
            rows = [("a", "x", 5, 100.0), ("a", "x", 4, 90.0), ("a", "x", 3, 95.0), ("a", "x", 2, 80.0),   # 2 drops
                    ("a", "y", 3, 10.0), ("a", "y", 2, 10.0),                                              # flat
                    ("b", "x", 4, 50.0), ("b", "x", 3, 45.0),                                              # 1 drop (other store, same sku)
                    ("a", "z", 40, 30.0), ("a", "z", 39, 20.0),                                            # outside 30 days
                    ("b", "w", 3, None), ("b", "w", 2, 5.0)]                                               # no price: no drop
            await db.daily_ledger.insert_many([{"store_id": s, "sku": k, "ksa_date": day(n), "close_price": p} for s, k, n, p in rows])
            return await store_views.market_summary(db, 30, lambda p: 0)
        finally:
            await client.drop_database(db.name)
            client.close()
    out = asyncio.run(scenario())
    assert out["price_drops"] == 3
