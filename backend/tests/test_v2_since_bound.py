"""Reads that only use v2 observations stop at the contract cut-over date, and
crawl persistence survives transient database timeouts (11 Oct 2026).

Production (8.45M snapshots) scanned 90 days of legacy rows for every cohort
build; the database starved until the crawl's own writes exceeded the socket
timeout and whole stores were discarded ("Observation persistence failed:
NetworkTimeout")."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from pymongo.errors import ExecutionTimeout, NetworkTimeout, OperationFailure

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import observation_contract as oc  # noqa: E402

CUTOVER = "2026-10-07T00:00:00+00:00"


def _match(pipeline):
    return pipeline[0]["$match"]["crawled_at"]["$gte"]


def test_since_bound_never_goes_before_the_cutover(monkeypatch):
    monkeypatch.setenv("OBSERVATIONS_V2_SINCE", CUTOVER)
    cutover = datetime.fromisoformat(CUTOVER)
    assert oc.v2_since() == cutover
    assert oc.since_bound(cutover - timedelta(days=80)) == cutover
    later = cutover + timedelta(days=3)
    assert oc.since_bound(later) == later
    assert oc.since_bound(None) == cutover
    naive = (cutover + timedelta(days=1)).replace(tzinfo=None)
    assert oc.since_bound(naive) == cutover + timedelta(days=1)
    monkeypatch.setenv("OBSERVATIONS_V2_SINCE", "not a date")
    assert oc.v2_since() == datetime.fromisoformat(oc.OBSERVATIONS_V2_SINCE_DEFAULT)


def test_cohort_and_market_share_pipelines_are_bounded(monkeypatch):
    import price_cohort
    import market_share
    monkeypatch.setenv("OBSERVATIONS_V2_SINCE", CUTOVER)
    cutover = datetime.fromisoformat(CUTOVER)
    now = cutover + timedelta(days=4)
    assert _match(price_cohort.snapshot_pipeline(["s1"], now)) == cutover
    assert _match(market_share._latest_snapshot_pipeline(["s1"], now - timedelta(days=90))) == cutover
    # A window that starts after the cut-over is unchanged.
    assert _match(market_share._latest_snapshot_pipeline(["s1"], now - timedelta(days=1))) == now - timedelta(days=1)
    # Test fixtures seed older history: the bound steps aside when configured so.
    monkeypatch.setenv("OBSERVATIONS_V2_SINCE", "2000-01-01T00:00:00+00:00")
    assert _match(price_cohort.snapshot_pipeline(["s1"], now)) == now - timedelta(days=price_cohort.cohort_history_days())


def test_store_views_latest_is_bounded(monkeypatch):
    import store_views
    monkeypatch.setenv("OBSERVATIONS_V2_SINCE", CUTOVER)
    seen = []

    async def fake_complete_latest(db, pipeline):
        seen.append(pipeline)
        return []
    monkeypatch.setattr(store_views, "complete_latest", fake_complete_latest)
    asyncio.run(store_views.latest(object(), days=90))
    assert _match(seen[0]) == datetime.fromisoformat(CUTOVER)


def test_persistence_retries_transient_errors_only(monkeypatch):
    import crawl_persistence as cp
    monkeypatch.setattr(cp, "RETRY_WAITS", (0, 0, 0))
    calls = []

    def flaky(failures, exc=NetworkTimeout):
        async def op():
            calls.append(1)
            if len(calls) <= failures:
                raise exc("socket timeout")
            return "persisted"
        return op

    assert asyncio.run(cp.retry_transient(flaky(2), "chunk")) == "persisted"
    assert len(calls) == 3
    calls.clear()
    assert asyncio.run(cp.retry_transient(flaky(1, ExecutionTimeout), "chunk")) == "persisted"
    calls.clear()
    with pytest.raises(NetworkTimeout):          # budget exhausted → the failure surfaces
        asyncio.run(cp.retry_transient(flaky(10), "chunk"))
    assert len(calls) == len(cp.RETRY_WAITS) + 1
    calls.clear()
    with pytest.raises(OperationFailure):        # a real error is never retried
        asyncio.run(cp.retry_transient(flaky(1, OperationFailure), "chunk"))
    assert len(calls) == 1


def test_persist_keeps_the_store_when_a_chunk_write_times_out_once(monkeypatch):
    import crawl_persistence as cp
    monkeypatch.setattr(cp, "RETRY_WAITS", (0, 0, 0))

    class _Checkpoints:
        def __init__(self):
            self.docs = {}

        async def update_one(self, q, update, upsert=False):
            key = q["_id"]
            if "$setOnInsert" in update:
                self.docs.setdefault(key, {"_id": key, **update["$setOnInsert"]})
            else:
                doc = self.docs[key]
                if "state" in q and doc.get("state") != q["state"]:
                    return
                doc.update(update.get("$set", {}))

        async def find_one(self, q, proj=None):
            return dict(self.docs[q["_id"]])

    class _DB:
        crawl_checkpoints = _Checkpoints()

    attempts = []

    async def process(db, store, rows, observed_at, tier=1, confidence=95):
        attempts.append(len(rows))
        if len(attempts) == 1:
            raise NetworkTimeout("busy")
        return len(rows), len(rows)

    async def no_supplement(*a, **k):
        return None
    import crawlers
    monkeypatch.setattr(crawlers, "process_crawled_products", process)
    monkeypatch.setattr(crawlers, "_maybe_salla_detail_supplement", no_supplement)
    log = {"id": "run-1"}
    rows = [{"sku": f"S{i}"} for i in range(60)]
    new, snaps = asyncio.run(cp.persist(_DB(), {"id": "st", "name": "Store"}, rows, datetime.now(timezone.utc), log))
    assert (new, snaps) == (60, 60)
    assert attempts == [50, 50, 10]          # first chunk retried once, then both persisted
    assert "error" not in log
    states = {k: v["state"] for k, v in _DB.crawl_checkpoints.docs.items()}
    assert states == {"capture:run-1:0": "persisted", "capture:run-1:50": "persisted"}


def test_revision_read_uses_the_background_budget():
    import my_products_cache as mpc
    import price_read_limits as prl

    class _Versions:
        def __init__(self, failures):
            self.failures, self.calls, self.limits = failures, 0, []

        async def find_one(self, q, proj=None, max_time_ms=None):
            self.calls += 1
            self.limits.append(max_time_ms)
            if self.calls <= self.failures:
                raise ExecutionTimeout("operation exceeded time limit")
            return {"revision": 9}

    class _DB:
        def __init__(self, failures):
            self.data_versions = _Versions(failures)

    db = _DB(2)
    assert asyncio.run(prl.bounded_read(mpc.revision(db), background=True)) == 9
    assert db.data_versions.calls == 3
    assert all(limit == prl.BACKGROUND_SNAPSHOT_QUERY_MAX_MS for limit in db.data_versions.limits)
    db = _DB(2)
    with pytest.raises(ExecutionTimeout):        # request path: still two attempts, 15 s each
        asyncio.run(mpc.revision(db))
    assert db.data_versions.limits == [mpc.REVISION_READ_MAX_MS] * 2
