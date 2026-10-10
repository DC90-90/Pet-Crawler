"""A throttled Salla cursor walk waits and retries the same cursor instead of
ending the crawl as partial (10 Oct 2026)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "test_pagination_rate_limit")
os.environ.setdefault("ENCRYPTION_KEY", "")

import catalog_pagination as cp  # noqa: E402


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


def _page(ids, next_cursor):
    return {"data": [{"id": i, "sku": f"S{i}"} for i in ids], "cursor": {"next": next_cursor}}


def test_429_is_waited_out_and_the_same_cursor_retried(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(cp.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(cp, "CURSOR_PAGE_PAUSE", (0, 0))
    answers = {"https://x.test/en/api/v1/products?c=2": [_Resp(429), _Resp(429), _Resp(200, _page([3, 4], None))]}
    calls = []

    async def fetch(http, url, params=None, **_):
        calls.append(url)
        queue = answers.get(url)
        return queue.pop(0) if queue else _Resp(404)

    ep = {"url": "https://x.test/en/api/v1/products", "tag": "/en/api/v1/products", "pagination": "cursor",
          "_initial_body": _page([1, 2], "https://x.test/api/v1/products?c=2"), "_cursor_next": "https://x.test/api/v1/products?c=2"}
    rows = asyncio.run(cp.paginate(None, ep, _page([1, 2], None)["data"], fetch))
    assert [r["id"] for r in rows] == [1, 2, 3, 4]
    assert ep["_pagination"]["complete"] is True and ep["_pagination"]["stop_reason"] == "explicit_end"
    assert ep["_pagination"]["rate_limit_waits"] == 2
    assert calls.count("https://x.test/en/api/v1/products?c=2") == 3
    assert [s for s in sleeps if s >= 1] == [cp.RATE_LIMIT_WAITS[0], cp.RATE_LIMIT_WAITS[1]]  # inter-page pauses are 0 here


def test_persistent_429_still_ends_as_partial(monkeypatch):
    async def fake_sleep(s):
        pass
    monkeypatch.setattr(cp.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(cp, "CURSOR_PAGE_PAUSE", (0, 0))

    async def fetch(http, url, params=None, **_):
        return _Resp(429)

    ep = {"url": "https://x.test/en/api/v1/products", "tag": "/en/api/v1/products", "pagination": "cursor",
          "_initial_body": _page([1], "https://x.test/en/api/v1/products?c=2"), "_cursor_next": "https://x.test/en/api/v1/products?c=2"}
    rows = asyncio.run(cp.paginate(None, ep, [{"id": 1, "sku": "S1"}], fetch))
    assert [r["id"] for r in rows] == [1]
    assert ep["_pagination"]["complete"] is False and ep["_pagination"]["stop_reason"] == "http_429"
    assert ep["_pagination"]["rate_limit_waits"] == len(cp.RATE_LIMIT_WAITS)
