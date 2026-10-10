"""iter56 — isolated regressions for snapshot_strategy + read_diagnostics.

Modules/features covered:
- snapshot_strategy safe index selection, TTL/cooldown lifecycle, metadata fallback
- read_diagnostics capture coalescing/rate-limit and timeout-trigger hint-selection policy
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import uuid

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import read_diagnostics
import snapshot_strategy
from read_plan_policy import summarize_plan
from release_database import GuardedDatabase
from test_p0_my_products_baseline import _loopback_mongo_url


class _FakeIndexes:
    def __init__(self, payload=None, exc: Exception | None = None):
        self.payload = payload or {}
        self.exc = exc

    async def index_information(self):
        if self.exc:
            raise self.exc
        return self.payload


class _FakeRawDB:
    def __init__(self, indexes=None):
        self.client = object()
        self.name = f"iter56_{uuid.uuid4().hex[:8]}"
        self.product_snapshots = _FakeIndexes(indexes or {})

    def __getitem__(self, name):
        if name == "product_snapshots":
            return self.product_snapshots
        raise KeyError(name)


class _FakeGuarded(GuardedDatabase):
    def __init__(self, *, indexes, default_raw_plan=None, alternative_raw_plan=None):
        super().__init__(_FakeRawDB(indexes))
        self._default = default_raw_plan or {
            "queryPlanner": {
                "winningPlan": {
                    "stage": "IXSCAN",
                    "indexName": "idx_store_time",
                    "keyPattern": {"store_id": 1, "crawled_at": -1},
                }
            }
        }
        self._alt = alternative_raw_plan or self._default
        self.calls = []

    async def explain_snapshot_read(self, pipeline, *, hint=None):
        self.calls.append({"pipeline": pipeline, "hint": hint})
        if hint is None:
            return self._default
        return self._alt


def _safe_indexes():
    return {
        "idx_store_time": {"key": [("store_id", 1), ("crawled_at", -1)]},
    }


def test_safe_store_index_strict_key_order_and_metadata_filters():
    # snapshot_strategy.safe_store_index checks exact order + metadata safety.
    safe = {"key": [("store_id", 1), ("crawled_at", -1)]}
    wrong_order = {"key": [("crawled_at", -1), ("store_id", 1)]}
    sparse = {"key": [("store_id", 1), ("crawled_at", -1)], "sparse": True}
    partial = {"key": [("store_id", 1), ("crawled_at", -1)], "partialFilterExpression": {"x": 1}}
    hidden = {"key": [("store_id", 1), ("crawled_at", -1)], "hidden": True}
    bad_collation = {
        "key": [("store_id", 1), ("crawled_at", -1)],
        "collation": {"locale": "en"},
    }
    missing = {}

    assert snapshot_strategy.safe_store_index(safe) is True
    for candidate in (wrong_order, sparse, partial, hidden, bad_collation, missing):
        assert snapshot_strategy.safe_store_index(candidate) is False


@pytest.mark.anyio
async def test_selected_hint_ttl_before_success_expires(monkeypatch):
    # snapshot_strategy.selected_hint: pre-success hint must expire by TTL.
    db = _FakeRawDB(_safe_indexes())
    snapshot_strategy.select_after_timeout(db, "idx_store_time")

    state = snapshot_strategy.state(db)
    future = state["until"] + 1
    monkeypatch.setattr(snapshot_strategy.time, "monotonic", lambda: future)

    chosen = await snapshot_strategy.selected_hint(db)
    assert chosen is None


@pytest.mark.anyio
async def test_selected_hint_ttl_after_success_expires(monkeypatch):
    # snapshot_strategy.selected_hint: transient 5m policy should expire even after success.
    # Regression: logged_success used to bypass expiry indefinitely.
    db = _FakeRawDB(_safe_indexes())
    snapshot_strategy.select_after_timeout(db, "idx_store_time")
    snapshot_strategy.completed_hint(db, "idx_store_time", elapsed_ms=20.0)

    state = snapshot_strategy.state(db)
    future = state["until"] + 1
    monkeypatch.setattr(snapshot_strategy.time, "monotonic", lambda: future)

    chosen = await snapshot_strategy.selected_hint(db)
    assert chosen is None, "Expired successful hint should not survive beyond TTL"
    assert state["hint"] is None


@pytest.mark.anyio
async def test_selected_hint_metadata_failure_clears_fallback():
    # snapshot_strategy.selected_hint must fail-closed when index metadata is unavailable.
    db = _FakeRawDB(_safe_indexes())
    snapshot_strategy.select_after_timeout(db, "idx_store_time")
    state = snapshot_strategy.state(db)
    state["logged_success"] = True
    db.product_snapshots = _FakeIndexes(exc=RuntimeError("metadata failure"))

    chosen = await snapshot_strategy.selected_hint(db)
    assert chosen is None
    assert snapshot_strategy.state(db)["hint"] is None


@pytest.mark.anyio
async def test_failed_hint_cooldown_blocks_and_then_allows(monkeypatch):
    # snapshot_strategy.failed_hint should remove hint and enforce cooldown block.
    db = _FakeRawDB(_safe_indexes())
    snapshot_strategy.select_after_timeout(db, "idx_store_time")
    snapshot_strategy.failed_hint(db, "idx_store_time")
    now = snapshot_strategy.time.monotonic()

    monkeypatch.setattr(snapshot_strategy.time, "monotonic", lambda: now + 1)
    assert snapshot_strategy.select_after_timeout(db, "idx_store_time") is False

    monkeypatch.setattr(snapshot_strategy.time, "monotonic", lambda: now + snapshot_strategy.TTL_SECONDS + 1)
    assert snapshot_strategy.select_after_timeout(db, "idx_store_time") is True


@pytest.mark.anyio
async def test_collect_read_plan_manual_never_sets_selected_hint():
    # read_diagnostics.collect_read_plan manual diagnostics must not alter selected hint.
    fake = _FakeGuarded(indexes=_safe_indexes())
    result = await read_diagnostics.collect_read_plan(
        fake,
        "cohort",
        generated_pipeline=[{"$match": {"store_id": {"$in": ["s1"]}}}, {"$sort": {"crawled_at": -1}}],
        after_timeout=False,
        applied_hint=None,
        trigger="manual",
    )
    assert result.status == "available"
    assert result.selected_hint is None


@pytest.mark.anyio
async def test_collect_read_plan_timeout_selects_only_safe_existing_index():
    # read_diagnostics.collect_read_plan may select alternative only after confirmed timeout + safe alternative plan.
    safe_alt = {
        "queryPlanner": {
            "winningPlan": {
                "stage": "FETCH",
                "inputStage": {
                    "stage": "IXSCAN",
                    "indexName": "idx_store_time",
                    "keyPattern": {"store_id": 1, "crawled_at": -1},
                },
            }
        }
    }
    fake = _FakeGuarded(indexes=_safe_indexes(), alternative_raw_plan=safe_alt)
    result = await read_diagnostics.collect_read_plan(
        fake,
        "cohort",
        generated_pipeline=[{"$match": {"store_id": {"$in": ["s1"]}}}, {"$sort": {"crawled_at": -1}}],
        after_timeout=True,
        applied_hint=None,
        trigger="timeout",
    )
    assert result.status == "available"
    assert result.alternative_index == "idx_store_time"
    assert result.selected_hint == "idx_store_time"


@pytest.mark.anyio
async def test_collect_read_plan_timeout_does_not_select_sort_or_collscan():
    # read_diagnostics.collect_read_plan must reject alternatives with SORT/COLLSCAN.
    bad_alt = {
        "queryPlanner": {
            "winningPlan": {
                "stage": "SORT",
                "inputStage": {
                    "stage": "COLLSCAN",
                },
            }
        }
    }
    fake = _FakeGuarded(indexes=_safe_indexes(), alternative_raw_plan=bad_alt)
    result = await read_diagnostics.collect_read_plan(
        fake,
        "cohort",
        generated_pipeline=[{"$match": {"store_id": {"$in": ["s1"]}}}, {"$sort": {"crawled_at": -1}}],
        after_timeout=True,
        applied_hint=None,
        trigger="timeout",
    )
    assert result.alternative_index == "idx_store_time"
    assert result.selected_hint is None


@pytest.mark.anyio
async def test_collect_read_plan_cancelled_trigger_never_selects_hint():
    # read_diagnostics.collect_read_plan with unconfirmed timeout (cancelled) should not select hint.
    safe_alt = {
        "queryPlanner": {
            "winningPlan": {
                "stage": "IXSCAN",
                "indexName": "idx_store_time",
                "keyPattern": {"store_id": 1, "crawled_at": -1},
            }
        }
    }
    fake = _FakeGuarded(indexes=_safe_indexes(), alternative_raw_plan=safe_alt)
    result = await read_diagnostics.collect_read_plan(
        fake,
        "cohort",
        generated_pipeline=[{"$match": {"store_id": {"$in": ["s1"]}}}, {"$sort": {"crawled_at": -1}}],
        after_timeout=False,
        applied_hint=None,
        trigger="cancelled",
    )
    assert result.trigger == "cancelled"
    assert result.selected_hint is None


@pytest.mark.anyio
async def test_capture_after_timeout_coalesces_per_5min(monkeypatch):
    # read_diagnostics.capture_after_timeout should coalesce same key inside 5-minute interval.
    calls = {"n": 0}

    async def fake_collect(*_args, **_kwargs):
        calls["n"] += 1

        class _Result:
            def model_dump(self):
                return {"status": "available", "query": "cohort"}

        return _Result()

    monkeypatch.setattr(read_diagnostics, "collect_read_plan", fake_collect)
    db = _FakeRawDB(_safe_indexes())

    read_diagnostics.capture_after_timeout(db, "cohort", [{"$match": {"x": 1}}], applied_hint=None, confirmed_timeout=True)
    read_diagnostics.capture_after_timeout(db, "cohort", [{"$match": {"x": 1}}], applied_hint=None, confirmed_timeout=True)

    await asyncio.sleep(0.05)
    assert calls["n"] == 1


@pytest.mark.anyio
async def test_capture_after_timeout_swallow_errors_preserves_original_failure(monkeypatch):
    # read_diagnostics.capture_after_timeout must never replace original request errors.
    def boom(*_args, **_kwargs):
        raise RuntimeError("capture failed")

    monkeypatch.setattr(read_diagnostics, "_enqueue_capture", boom)
    db = _FakeRawDB(_safe_indexes())
    # No raise expected.
    read_diagnostics.capture_after_timeout(db, "cohort", [{"$match": {"x": 1}}], applied_hint=None, confirmed_timeout=True)


@pytest.mark.anyio
async def test_real_mongo_queryplanner_hint_parity_isolated_loopback():
    # Real Mongo parity (safe isolated): explain_snapshot_read queryPlanner with and without explicit safe hint.
    client = AsyncIOMotorClient(_loopback_mongo_url(), serverSelectionTimeoutMS=5000)
    db_name = f"iter56_real_{uuid.uuid4().hex[:8]}"
    raw = client[db_name]
    guarded = GuardedDatabase(raw)
    now = datetime.now(timezone.utc)
    try:
        await raw.product_snapshots.insert_many([
            {
                "store_id": "s1",
                "offer_id": "o1",
                "crawled_at": now,
                "observation_version": 2,
                "is_synthetic": False,
            },
            {
                "store_id": "s1",
                "offer_id": "o2",
                "crawled_at": now,
                "observation_version": 2,
                "is_synthetic": False,
            },
        ])
        await raw.product_snapshots.create_index([("store_id", 1), ("crawled_at", -1)], name="idx_store_time")

        pipeline = [{"$match": {"store_id": {"$in": ["s1"]}}}, {"$sort": {"crawled_at": -1}}]
        plan_default = await guarded.explain_snapshot_read(pipeline)
        plan_hinted = await guarded.explain_snapshot_read(pipeline, hint="idx_store_time")

        s_default = summarize_plan(plan_default)
        s_hinted = summarize_plan(plan_hinted)
        assert s_default is not None
        assert s_hinted is not None
        assert not s_hinted.collection_scan
    finally:
        await client.drop_database(db_name)
        client.close()
