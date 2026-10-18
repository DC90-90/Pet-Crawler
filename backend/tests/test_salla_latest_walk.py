"""The Salla "latest" listing walk that completes a category crawl (19 Oct
2026): adds only products not seen, keeps its cursor when throttled, resumes
from it next time, and starts over from a stale cursor."""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import crawlers  # noqa: E402

START = "https://api.salla.dev/store/v1/products?source=latest&limit=50"


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._body = code, body or {}

    def json(self):
        return self._body


class _Salla:
    """Three pages: ids 1-2, 3-4, 5. Optionally throttles page 2 forever."""
    def __init__(self, throttle_page2=False):
        self.throttle, self.calls = throttle_page2, []

    async def get(self, url):
        self.calls.append(url)
        if url == START:
            return _Resp(200, {"data": [{"id": 1}, {"id": 2}], "cursor": {"next": "p2"}})
        if url == "p2":
            if self.throttle:
                return _Resp(429)
            return _Resp(200, {"data": [{"id": 3}, {"id": 4}], "cursor": {"next": "p3"}})
        if url == "p3":
            return _Resp(200, {"data": [{"id": 5}], "cursor": {}})
        return _Resp(410)


def test_walk_adds_unseen_products_saves_and_resumes_cursor(monkeypatch):
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    monkeypatch.setattr(crawlers, "SALLA_WALK_PAUSE", (0, 0))
    monkeypatch.setattr(crawlers, "SALLA_WALK_THROTTLE_WAITS", (0, 0))

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["sw_" + uuid.uuid4().hex]
        store = {"id": "s1", "name": "Hamtaro"}
        try:
            seen, captured, log = {2}, [{"id": 2}], {"endpoints_tried": []}
            added = await crawlers._salla_latest_walk(db, store, _Salla(throttle_page2=True), seen, captured, log)
            saved = await db.salla_walk_cursors.find_one({"_id": "s1"})
            first = (added, sorted(seen), saved["next"], saved["stop"], log["endpoints_tried"][-1]["error"])
            salla = _Salla()
            seen2, cap2, log2 = set(), [], {"endpoints_tried": []}
            added2 = await crawlers._salla_latest_walk(db, store, salla, seen2, cap2, log2)
            second = (added2, salla.calls[0], await db.salla_walk_cursors.find_one({"_id": "s1"}))
            await db.salla_walk_cursors.update_one({"_id": "s1"}, {"$set": {"next": "gone", "saved_at": saved["saved_at"]}}, upsert=True)
            salla3 = _Salla()
            added3 = await crawlers._salla_latest_walk(db, store, salla3, set(), [], {"endpoints_tried": []})
            third = (added3, salla3.calls[:2])
            return first, second, third
        finally:
            await client.drop_database(db.name)
            client.close()

    first, second, third = asyncio.run(scenario())
    assert first[0] == 1 and first[1] == [1, 2]                      # id 2 was already seen
    assert first[2] == "p2" and first[3] == "http_429" and "resumed=False" in first[4]
    assert second[0] == 3 and second[1] == "p2" and second[2] is None   # resumed at p2, finished, cursor cleared
    assert third[0] == 5 and third[1] == ["gone", START]               # stale cursor: start over
