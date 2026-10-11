"""The cohort is built once per data revision and reused across windows and
pages; a new revision or a different own catalogue rebuilds it (11 Oct 2026)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import price_cohort as pc  # noqa: E402


class _Client:
    pass


class _Versions:
    def __init__(self):
        self.revision = 1

    async def find_one(self, q, proj=None):
        return {"revision": self.revision}


class _DB:
    def __init__(self):
        self.client, self.name, self.data_versions = _Client(), "db", _Versions()


def test_cohort_build_is_memoised_per_revision_and_catalogue(monkeypatch):
    pc.reset_cohort_memo()
    db = _DB()
    calls = []

    async def fake_build(db_, own_rows, own_store_id, own_price_fn, now, scope, parents):
        calls.append(1)
        return {"A": {"sellers": [{"store_id": "s1", "price": 1.0}]}}
    monkeypatch.setattr(pc, "_build_cohorts", fake_build)
    rows = [{"sku": "A", "barcode": "1234567890128"}]
    price = lambda r: 10.0

    first = asyncio.run(pc.build_cohorts(db, rows, "own", price))
    second = asyncio.run(pc.build_cohorts(db, rows, "own", price, competitor_store_ids=None))
    assert first == second and len(calls) == 1
    first["A"]["sellers"][0]["price"] = 999  # callers may mutate their copy
    assert asyncio.run(pc.build_cohorts(db, rows, "own", price))["A"]["sellers"][0]["price"] == 1.0

    asyncio.run(pc.build_cohorts(db, rows, "own", price, competitor_store_ids=["s1"]))
    assert len(calls) == 2  # different scope → new build

    db.data_versions.revision = 2  # new observations → rebuild
    asyncio.run(pc.build_cohorts(db, rows, "own", price))
    assert len(calls) == 3

    asyncio.run(pc.build_cohorts(db, rows + [{"sku": "B"}], "own", price))
    assert len(calls) == 4  # own catalogue changed → rebuild

    pc.reset_cohort_memo()
    asyncio.run(pc.build_cohorts(db, rows, "own", price))
    assert len(calls) == 5


def test_result_is_not_memoised_when_revision_moves_during_the_build(monkeypatch):
    pc.reset_cohort_memo()
    db = _DB()
    calls = []

    async def fake_build(*a, **k):
        calls.append(1)
        db.data_versions.revision += 1  # a crawl landed mid-build
        return {}
    monkeypatch.setattr(pc, "_build_cohorts", fake_build)
    asyncio.run(pc.build_cohorts(db, [], "own", lambda r: 0))
    asyncio.run(pc.build_cohorts(db, [], "own", lambda r: 0))
    assert len(calls) == 2
