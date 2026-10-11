"""Background cache rebuilds get their own budget; large page caches are stored
compressed and chunked under MongoDB's 16 MB document limit (11 Oct 2026)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import price_read_limits as prl  # noqa: E402


def test_query_budget_follows_the_background_context():
    assert prl.query_max_ms() == prl.SNAPSHOT_QUERY_MAX_MS

    async def inner():
        return prl.query_max_ms(), prl.in_background()

    async def nested():
        # A request-mode bounded read inside a background one inherits background.
        return await prl.bounded_read(inner())

    assert asyncio.run(prl.bounded_read(inner())) == (prl.SNAPSHOT_QUERY_MAX_MS, False)
    assert asyncio.run(prl.bounded_read(inner(), background=True)) == (prl.BACKGROUND_SNAPSHOT_QUERY_MAX_MS, True)
    assert asyncio.run(prl.bounded_read(nested(), background=True)) == (prl.BACKGROUND_SNAPSHOT_QUERY_MAX_MS, True)
    assert prl.query_max_ms() == prl.SNAPSHOT_QUERY_MAX_MS  # context restored


def test_background_budget_is_larger_than_request_budget():
    assert prl.BACKGROUND_TIMEOUT_SECONDS > prl.REQUEST_TIMEOUT_SECONDS
    assert prl.BACKGROUND_SNAPSHOT_QUERY_MAX_MS > prl.SNAPSHOT_QUERY_MAX_MS


def test_request_timeout_is_still_an_unavailable_result(monkeypatch):
    monkeypatch.setattr(prl, "REQUEST_TIMEOUT_SECONDS", 1)

    async def slow():
        await asyncio.sleep(5)

    from fastapi import HTTPException
    try:
        asyncio.run(prl.bounded_read(slow()))
    except HTTPException as exc:
        assert exc.status_code == 503 and exc.detail["code"] == "price_query_timeout"
    else:
        raise AssertionError("expected a 503 unavailable result")


def test_cache_miss_policy_blocks_live_compute_only_on_the_request_path(monkeypatch):
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "test_read_budgets")
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    from cryptography.fernet import Fernet
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import server
    from fastapi import HTTPException
    monkeypatch.setattr(server, "CACHE_MISS_POLICY", "live")
    assert server._cache_miss_live_allowed() is True
    monkeypatch.setattr(server, "CACHE_MISS_POLICY", "rebuild")
    assert server._cache_miss_live_allowed() is False

    async def inside_background():
        return server._cache_miss_live_allowed()
    assert asyncio.run(prl.bounded_read(inside_background(), background=True)) is True

    started = []
    monkeypatch.setattr(server, "_schedule_cache_rebuild", lambda: started.append(1) or True)
    try:
        server._cache_miss_or_rebuild()
    except HTTPException as exc:
        assert exc.status_code == 503 and exc.detail["code"] == "price_cache_rebuilding"
    else:
        raise AssertionError("expected the rebuilding result")
    assert started == [1]


def test_page_cache_pack_roundtrip_and_chunking():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "test_read_budgets")
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    from cryptography.fernet import Fernet
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import server
    payload = {"rows": [{"sku": f"S{i}", "name": "منتج " * 20, "price": i * 1.5} for i in range(2000)], "kpis": {"x": 1}}
    blob = server._page_cache_pack(payload)
    assert server._page_cache_unpack(blob) == payload
    assert len(blob) < len(str(payload))  # compressed

    class _Chunks:
        def __init__(self):
            self.docs = {}

        async def delete_many(self, q):
            self.docs = {k: v for k, v in self.docs.items() if v["key"] != q["key"]}

        async def replace_one(self, q, doc, upsert=False):
            self.docs[(q["key"], q["n"])] = doc

        def find(self, q, proj):
            rows = sorted([v for v in self.docs.values() if v["key"] == q["key"]], key=lambda d: d["n"])

            class _C:
                def sort(self, *_):
                    return self

                async def to_list(self, n):
                    return rows
            return _C()

    class _Head:
        def __init__(self):
            self.doc = None

        async def replace_one(self, q, doc, upsert=False):
            self.doc = doc

    class _Versions:
        async def find_one(self, q):
            return {"revision": 7}

    class _DB:
        def __init__(self):
            self.dashboard_cache, self.dashboard_cache_chunks, self.data_versions = _Head(), _Chunks(), _Versions()

    db = _DB()
    import server as s
    s.PAGE_CACHE_INLINE_LIMIT, s.PAGE_CACHE_CHUNK_BYTES = 1000, 700  # force chunking for the test
    asyncio.run(s._store_page_cache(db, "market-share/dataset", 30, payload))
    head = db.dashboard_cache.doc
    assert head["encoding"] == "zlib-json" and head["chunks"] >= 2 and "payload_zlib" not in head
    assert asyncio.run(s._load_page_cache_payload(db, head)) == payload
    # A missing chunk is a miss, never a partial payload.
    db.dashboard_cache_chunks.docs.pop((head["key"], 0))
    assert asyncio.run(s._load_page_cache_payload(db, head)) is None
