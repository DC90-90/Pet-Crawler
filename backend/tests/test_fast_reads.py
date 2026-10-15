"""Faster reads (15 Oct 2026): decoded page payloads are kept per process and
re-read only when the stored entry changes; slow read-only answers are served
from a stored stale-while-revalidate cache; list rows drop fields no list
renders."""
import asyncio
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    client = AsyncIOMotorClient(_loopback_mongo_url())
    return client, client["fr_" + uuid.uuid4().hex]


def test_page_payload_is_read_once_until_the_entry_changes(monkeypatch):
    import cache_blobs
    cache_blobs.memo_clear()
    unpacked = []
    real_unpack = cache_blobs.unpack
    monkeypatch.setattr(cache_blobs, "unpack", lambda blob: unpacked.append(1) or real_unpack(blob))

    async def scenario():
        client, db = _db()
        try:
            await cache_blobs.write_blob(db, "k", {"rows": [1, 2]}, {"computed_at": 1})
            head = await db.dashboard_cache.find_one({"key": "k"}, cache_blobs.HEAD_PROJECTION)
            first = await cache_blobs.read_blob(db, head)                     # fetched + decoded
            second = await cache_blobs.read_blob(db, head)                    # memo
            await asyncio.sleep(0.01)
            await cache_blobs.write_blob(db, "k", {"rows": [3]}, {"computed_at": 2})
            head2 = await db.dashboard_cache.find_one({"key": "k"}, cache_blobs.HEAD_PROJECTION)
            third = await cache_blobs.read_blob(db, head2)                    # new entry: re-read
            return head, first, second, third
        finally:
            await client.drop_database(db.name)
            client.close()
    head, first, second, third = asyncio.run(scenario())
    assert "payload_zlib" not in head
    assert first == {"rows": [1, 2]} and second is first and third == {"rows": [3]}
    assert len(unpacked) == 2


def test_stored_cache_serves_stale_at_once_and_refreshes_in_background():
    import api_cache
    api_cache.clear_memo()
    calls = []

    async def scenario():
        client, db = _db()
        try:
            async def compute():
                calls.append(1)
                await asyncio.sleep(0.05)
                return {"n": len(calls)}
            a = await api_cache.get(db, "k", compute, fresh_secs=60)           # missing: computed
            b = await api_cache.get(db, "k", compute, fresh_secs=60)           # fresh: memo
            api_cache.clear_memo()                                             # another process / restart
            c = await api_cache.get(db, "k", compute, fresh_secs=60)           # stored copy
            api_cache._memo["k"] = (c, time.time() - 120)                      # now stale
            t0 = time.perf_counter()
            d = await api_cache.get(db, "k", compute, fresh_secs=60)           # served at once...
            waited = time.perf_counter() - t0
            await asyncio.sleep(0.2)                                           # ...refreshed behind it
            e = await api_cache.get(db, "k", compute, fresh_secs=60)
            return a, b, c, d, e, waited
        finally:
            await client.drop_database(db.name)
            client.close()
    a, b, c, d, e, waited = asyncio.run(scenario())
    assert a == b == c == d == {"n": 1} and e == {"n": 2}
    assert waited < 0.04 and len(calls) == 2


def test_concurrent_misses_compute_once():
    import api_cache
    api_cache.clear_memo()
    calls = []

    async def scenario():
        client, db = _db()
        try:
            async def compute():
                calls.append(1)
                await asyncio.sleep(0.05)
                return [1]
            return await asyncio.gather(*[api_cache.get(db, "same", compute, 60) for _ in range(5)])
        finally:
            await client.drop_database(db.name)
            client.close()
    out = asyncio.run(scenario())
    assert out == [[1]] * 5 and len(calls) == 1


def test_list_rows_drop_fields_no_list_renders():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "test_fast_reads")
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    from cryptography.fernet import Fernet
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import server
    row = {"sku": "1", "my_price": 5, "market_position": {"rank": 1}, "excluded_sellers": [{"x": 1}],
           "description_ar": "long", "description_en": "long", "store_categories": [{"name": "c"}]}
    slim = server._list_row(row)
    assert slim == {"sku": "1", "my_price": 5, "market_position": {"rank": 1}}
    assert "excluded_sellers" in row                       # the cached row itself is untouched
    plain = {"sku": "2"}
    assert server._list_row(plain) is plain
