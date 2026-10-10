"""iter58 — partitioned cohort read correctness, resilience, and performance gates.

Modules/features covered:
- cohort_reads.read_cohort_snapshots partition/fallback semantics and cancellation safety
- price_cohort snapshot parity through new partition reader integration
- real-Mongo benchmark gate vs monolithic default + hinted plans (balanced/skewed)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
import requests
from bson.json_util import CANONICAL_JSON_OPTIONS, dumps as bson_dumps
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import monitoring
from pymongo.errors import NetworkTimeout

import cohort_reads
import my_products_cache
import price_cohort
import release_database
import server
from _auth import auth_headers, base_url
from price_read_limits import SNAPSHOT_QUERY_MAX_MS
from release_database import GuardedDatabase
from test_p0_my_products_baseline import _fake_user, _loopback_mongo_url, _seed_baseline


ITER58_BENCH = Path("/app/test_reports/p0_my_products/iter58_partition_benchmark.json")
ITER58_SMOKE = Path("/app/test_reports/p0_my_products/iter58_preview_read_smoke.json")


class CommandProbe(monitoring.CommandListener):
    """Capture aggregate/getMore command counts and durations."""

    TRACK = {"aggregate", "getMore"}

    def __init__(self) -> None:
        self._started: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    def reset(self) -> None:
        self._started.clear()
        self.events.clear()

    def started(self, event):  # type: ignore[override]
        if event.command_name in self.TRACK:
            self._started[event.request_id] = {
                "name": event.command_name,
                "command": dict(event.command),
            }

    def succeeded(self, event):  # type: ignore[override]
        row = self._started.pop(event.request_id, None)
        if row:
            self.events.append({
                **row,
                "failed": False,
                "duration_ms": round(float(event.duration_micros) / 1000.0, 3),
            })

    def failed(self, event):  # type: ignore[override]
        row = self._started.pop(event.request_id, None)
        if row:
            self.events.append({
                **row,
                "failed": True,
                "duration_ms": round(float(event.duration_micros) / 1000.0, 3),
            })

    def summary(self) -> dict[str, Any]:
        aggs = [e for e in self.events if e["name"] == "aggregate"]
        getmores = [e for e in self.events if e["name"] == "getMore"]
        return {
            "aggregate_count": len(aggs),
            "get_more_count": len(getmores),
            "aggregate_duration_ms": round(sum(e["duration_ms"] for e in aggs), 3),
            "get_more_duration_ms": round(sum(e["duration_ms"] for e in getmores), 3),
            "aggregate_first_batch_ms": [e["duration_ms"] for e in aggs],
            "get_more_ms": [e["duration_ms"] for e in getmores],
        }


class CountingGuardedDatabase(release_database.GuardedDatabase):
    """Observer write-attempt instrumentation for endpoint checks."""

    def __init__(self, raw):
        super().__init__(raw)
        self.write_attempted = 0
        self.write_actual = 0

    async def perform(self, collection, method, operation, *args, **kwargs):
        self.write_attempted += 1
        out = await super().perform(collection, method, operation, *args, **kwargs)
        self.write_actual += 1
        return out


def _canonical(rows: list[dict[str, Any]]) -> list[str]:
    """Canonical FULL-row comparator (type-preserving Extended JSON)."""
    return sorted(
        bson_dumps(row, json_options=CANONICAL_JSON_OPTIONS, sort_keys=True)
        for row in rows
    )


def _canonical_digest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    serialized_rows = _canonical(rows)
    payload = "\n".join(serialized_rows).encode("utf-8")
    return {
        "row_count": len(serialized_rows),
        "serialized_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"min": 0.0, "median": 0.0, "max": 0.0}
    return {
        "min": round(ordered[0], 3),
        "median": round(statistics.median(ordered), 3),
        "max": round(ordered[-1], 3),
    }


@contextmanager
def _patch_attr(obj, name: str, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


@pytest.mark.anyio
async def test_iter58_partition_fallbacks_and_parity_real_mongo(monkeypatch):
    """Real-Mongo parity + explicit strategy-selection assertions."""
    client = AsyncIOMotorClient(_loopback_mongo_url(), serverSelectionTimeoutMS=5000)
    db_name = f"iter58_parity_{uuid.uuid4().hex[:10]}"
    db = GuardedDatabase(client[db_name])
    raw = client[db_name]
    now = datetime.now(timezone.utc)

    original_query = cohort_reads._query
    calls = {"legacy": 0, "partition": 0}

    async def spy_query(db_obj, pipeline, max_time_ms, hint=None, *, legacy=False):
        calls["legacy" if legacy else "partition"] += 1
        return await original_query(db_obj, pipeline, max_time_ms, hint=hint, legacy=legacy)

    monkeypatch.setattr(cohort_reads, "_query", spy_query, raising=True)

    try:
        await raw.stores.insert_many([
            {"id": "own", "is_own_store": True, "is_active": True},
            {"id": "s1", "is_active": True},
            {"id": "s2", "is_active": True},
            {"id": "s3", "is_active": True},
            {"id": "s4", "is_active": True},
        ])
        base = {
            "observation_version": 2,
            "comparable": True,
            "is_synthetic": False,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "confidence_score": 99,
            "in_stock": True,
            "present_on_store": True,
            "qty_available": 5,
            "name_ar": "x",
            "name_en": "x",
            "variant_skus": [],
            "variant_barcodes": [],
        }

        docs = [
            # partition-safe rows (full projected fields) with distinct timestamps
            {**base, "store_id": "s1", "sku": "SAFE-1", "offer_id": "safe-s1", "price": 10, "historical_max_price": 10, "crawled_at": now - timedelta(hours=5)},
            {**base, "store_id": "s2", "sku": "SAFE-2", "offer_id": "safe-s2", "price": 20, "historical_max_price": 20, "crawled_at": now - timedelta(hours=4)},
            {**base, "store_id": "s4", "sku": "SAFE-4", "offer_id": "safe-s4", "price": 22, "historical_max_price": 22, "crawled_at": now - timedelta(hours=3, minutes=58)},
            # null/missing offer IDs rely on store-scoped (store,sku), including null sku
            {**base, "store_id": "s1", "sku": None, "offer_id": None, "price": 30, "crawled_at": now - timedelta(hours=3, minutes=55)},
            {**base, "store_id": "s2", "sku": None, "price": 40, "crawled_at": now - timedelta(hours=3, minutes=50)},
            # same empty-string ID across stores: explicit collision -> legacy fallback
            {**base, "store_id": "s1", "sku": "EMPTY-1", "offer_id": "", "price": 50, "crawled_at": now - timedelta(hours=2, minutes=40)},
            {**base, "store_id": "s2", "sku": "EMPTY-2", "offer_id": "", "price": 60, "crawled_at": now - timedelta(hours=2, minutes=30)},
            # cross-store shared string collision with distinct timestamps/max/oldest
            {**base, "store_id": "s1", "sku": "COL-1", "offer_id": "shared-offer", "price": 55, "crawled_at": now - timedelta(hours=2, minutes=20)},
            {**base, "store_id": "s2", "sku": "COL-2", "offer_id": "shared-offer", "price": 65, "crawled_at": now - timedelta(hours=2, minutes=10)},
            {**base, "store_id": "s1", "sku": "COL-1", "offer_id": "shared-offer", "price": 75, "crawled_at": now - timedelta(days=3, minutes=5)},
            {**base, "store_id": "s2", "sku": "COL-2", "offer_id": "shared-offer", "price": 85, "crawled_at": now - timedelta(days=5, minutes=7)},
            # non-string BSON offer_id -> legacy fallback
            {**base, "store_id": "s3", "sku": "NUM", "offer_id": 123, "price": 70, "crawled_at": now - timedelta(hours=2)},
            # OOS latest should remain latest-selected then excluded by policy later
            {**base, "store_id": "s3", "sku": "OOS", "offer_id": "oos-x", "price": 77, "in_stock": False, "crawled_at": now - timedelta(minutes=5)},
            {**base, "store_id": "s3", "sku": "OOS", "offer_id": "oos-x", "price": 70, "in_stock": True, "crawled_at": now - timedelta(days=1)},
        ]
        await raw.product_snapshots.insert_many(docs)

        await raw.product_snapshots.create_index([("store_id", 1), ("crawled_at", -1)], name="store_id_1_crawled_at_-1")

        # empty active and one-store paths stay safe and return legacy behavior
        assert await cohort_reads.read_cohort_snapshots(db, [], now, price_cohort.snapshot_pipeline, max_time_ms=3000) == []

        calls.update({"legacy": 0, "partition": 0})
        one_store = await cohort_reads.read_cohort_snapshots(db, ["s1"], now, price_cohort.snapshot_pipeline, max_time_ms=3000)
        legacy_one = await raw.product_snapshots.aggregate(price_cohort.snapshot_pipeline(["s1"], now), maxTimeMS=3000).to_list(None)
        assert _canonical(one_store) == _canonical(legacy_one)
        assert calls["legacy"] >= 1
        assert calls["partition"] == 0

        # collision-free two-store partition path + duplicate-active de-dup proof
        calls.update({"legacy": 0, "partition": 0})
        partitioned = await cohort_reads.read_cohort_snapshots(db, ["s1", "s1", "s4"], now, price_cohort.snapshot_pipeline, max_time_ms=3000)
        partitioned_legacy = await raw.product_snapshots.aggregate(price_cohort.snapshot_pipeline(["s1", "s4"], now), maxTimeMS=3000).to_list(None)
        assert _canonical(partitioned) == _canonical(partitioned_legacy)
        assert calls["legacy"] == 0
        assert calls["partition"] >= 2

        # Explicit empty-string cross-store collision -> partition read then legacy parity.
        calls.update({"legacy": 0, "partition": 0})
        fallback = await cohort_reads.read_cohort_snapshots(db, ["s1", "s2"], now, price_cohort.snapshot_pipeline, max_time_ms=3000)
        legacy = await raw.product_snapshots.aggregate(price_cohort.snapshot_pipeline(["s1", "s2"], now), maxTimeMS=3000).to_list(None)
        assert _canonical(fallback) == _canonical(legacy)
        assert calls["legacy"] >= 1
        assert calls["partition"] >= 2

        # Cross-store non-string offer_id fallback parity with distinct timestamps.
        calls.update({"legacy": 0, "partition": 0})
        mixed = await cohort_reads.read_cohort_snapshots(db, ["s1", "s2", "s3"], now, price_cohort.snapshot_pipeline, max_time_ms=3000)
        mixed_legacy = await raw.product_snapshots.aggregate(price_cohort.snapshot_pipeline(["s1", "s2", "s3"], now), maxTimeMS=3000).to_list(None)
        assert _canonical(mixed) == _canonical(mixed_legacy)
        assert calls["legacy"] >= 1
        assert calls["partition"] >= 3

    finally:
        await client.drop_database(db_name)
        client.close()


@pytest.mark.anyio
async def test_iter58_partition_strategy_selection_spy_cases(monkeypatch):
    """Strategy-choice proof: intended branch cannot pass by always falling back."""

    class FakeCollection:
        def __init__(self, idx, opts):
            self._idx = idx
            self._opts = opts

        async def index_information(self):
            value = self._idx
            if isinstance(value, Exception):
                raise value
            return value

        async def options(self):
            value = self._opts
            if isinstance(value, Exception):
                raise value
            return value

    class FakeDB:
        def __init__(self, idx, opts):
            self.product_snapshots = FakeCollection(idx, opts)

    calls: list[dict[str, Any]] = []

    async def fake_query(_db, pipeline, _max_time_ms, hint=None, *, legacy=False):
        calls.append({"legacy": legacy, "hint": hint, "pipeline": pipeline})
        return [{"offer_id": "x", "store_id": "s1", "sku": "A", "price": 1, "crawled_at": datetime.now(timezone.utc)}]

    monkeypatch.setattr(cohort_reads, "_query", fake_query, raising=True)
    now = datetime.now(timezone.utc)

    async def run_case(db):
        calls.clear()
        await cohort_reads.read_cohort_snapshots(db, ["s1", "s2"], now, price_cohort.snapshot_pipeline, max_time_ms=3000)
        return [c for c in calls if c["legacy"]], [c for c in calls if not c["legacy"]]

    # Metadata failure -> immediate legacy, no per-store partition calls.
    legacy_calls, per_store_calls = await run_case(FakeDB(RuntimeError("metadata unavailable"), {}))
    assert len(legacy_calls) == 1
    assert len(per_store_calls) == 0

    # Missing safe index -> immediate legacy.
    legacy_calls, per_store_calls = await run_case(FakeDB({"crawled_at_1": {"key": [("crawled_at", 1)]}}, {}))
    assert len(legacy_calls) == 1
    assert len(per_store_calls) == 0

    # Non-simple collation -> immediate legacy.
    legacy_calls, per_store_calls = await run_case(
        FakeDB({"store_id_1_crawled_at_-1": {"key": [("store_id", 1), ("crawled_at", -1)]}}, {"collation": {"locale": "en"}})
    )
    assert len(legacy_calls) == 1
    assert len(per_store_calls) == 0


@pytest.mark.anyio
async def test_iter58_non_simple_collation_real_collection_legacy_parity(monkeypatch):
    """Disposable real collection with non-simple collation must force legacy parity."""
    client = AsyncIOMotorClient(_loopback_mongo_url(), serverSelectionTimeoutMS=5000)
    db_name = f"iter58_non_simple_{uuid.uuid4().hex[:10]}"
    raw = client[db_name]
    db = GuardedDatabase(raw)
    now = datetime.now(timezone.utc)

    original_query = cohort_reads._query
    calls = {"legacy": 0, "partition": 0}

    async def spy_query(db_obj, pipeline, max_time_ms, hint=None, *, legacy=False):
        calls["legacy" if legacy else "partition"] += 1
        return await original_query(db_obj, pipeline, max_time_ms, hint=hint, legacy=legacy)

    monkeypatch.setattr(cohort_reads, "_query", spy_query, raising=True)

    try:
        await raw.create_collection("product_snapshots", collation={"locale": "en"})
        await raw.stores.insert_many([
            {"id": "own", "is_own_store": True, "is_active": True},
            {"id": "s1", "is_active": True},
            {"id": "s2", "is_active": True},
        ])
        await raw.product_snapshots.insert_many([
            {"store_id": "s1", "sku": "A", "offer_id": "s1-A", "price": 10, "currency": "SAR", "price_basis": "storefront_inc_vat", "observation_version": 2, "comparable": True, "is_synthetic": False, "present_on_store": True, "in_stock": True, "qty_available": 1, "variant_skus": [], "variant_barcodes": [], "name_ar": "a", "name_en": "a", "crawled_at": now - timedelta(hours=2)},
            {"store_id": "s2", "sku": "B", "offer_id": "s2-B", "price": 11, "currency": "SAR", "price_basis": "storefront_inc_vat", "observation_version": 2, "comparable": True, "is_synthetic": False, "present_on_store": True, "in_stock": True, "qty_available": 1, "variant_skus": [], "variant_barcodes": [], "name_ar": "b", "name_en": "b", "crawled_at": now - timedelta(hours=1)},
        ])
        await raw.product_snapshots.create_index([("store_id", 1), ("crawled_at", -1)], name="store_id_1_crawled_at_-1")

        result = await cohort_reads.read_cohort_snapshots(db, ["s1", "s2"], now, price_cohort.snapshot_pipeline, max_time_ms=3000)
        legacy = await raw.product_snapshots.aggregate(price_cohort.snapshot_pipeline(["s1", "s2"], now), maxTimeMS=3000).to_list(None)
        assert _canonical(result) == _canonical(legacy)
        assert calls["legacy"] >= 1
        assert calls["partition"] == 0
    finally:
        await client.drop_database(db_name)
        client.close()


@pytest.mark.anyio
async def test_iter58_tie_timestamp_policy_checked_separately():
    """Tie-only scenario: equal timestamps are accepted per current policy."""
    client = AsyncIOMotorClient(_loopback_mongo_url(), serverSelectionTimeoutMS=5000)
    db_name = f"iter58_tie_{uuid.uuid4().hex[:10]}"
    raw = client[db_name]
    db = GuardedDatabase(raw)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        await raw.stores.insert_many([
            {"id": "own", "is_own_store": True, "is_active": True},
            {"id": "s1", "is_active": True},
        ])
        await raw.product_snapshots.insert_many([
            {"store_id": "s1", "sku": "TIE", "offer_id": "tie-1", "price": 9, "currency": "SAR", "price_basis": "storefront_inc_vat", "observation_version": 2, "comparable": True, "is_synthetic": False, "present_on_store": True, "in_stock": True, "qty_available": 1, "variant_skus": [], "variant_barcodes": [], "name_ar": "t", "name_en": "t", "crawled_at": now - timedelta(hours=1)},
            {"store_id": "s1", "sku": "TIE", "offer_id": "tie-1", "price": 10, "currency": "SAR", "price_basis": "storefront_inc_vat", "observation_version": 2, "comparable": True, "is_synthetic": False, "present_on_store": True, "in_stock": True, "qty_available": 1, "variant_skus": [], "variant_barcodes": [], "name_ar": "t", "name_en": "t", "crawled_at": now - timedelta(hours=1)},
        ])
        out = await cohort_reads.read_cohort_snapshots(db, ["s1"], now, price_cohort.snapshot_pipeline, max_time_ms=3000)
        assert len(out) == 1
        assert out[0].get("price") in {9, 10}
    finally:
        await client.drop_database(db_name)
        client.close()


@pytest.mark.anyio
async def test_iter58_failure_drain_and_task_cancellation_safety(monkeypatch):
    """Caller-cancel and bounded-deadline paths drain workers without partial success."""

    class SlowCursor:
        def __init__(self, sid: str, active_workers: dict[str, int], delay: float = 0.3):
            self.sid = sid
            self.delay = delay
            self.done = False
            self.closed = False
            self._active = active_workers
            self._active["count"] += 1
            self._active["peak"] = max(self._active["peak"], self._active["count"])

        def batch_size(self, _):
            return self

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.done:
                raise StopAsyncIteration
            await asyncio.sleep(self.delay)
            self.done = True
            return {"store_id": self.sid, "offer_id": f"{self.sid}-offer", "price": 1.0}

        async def close(self):
            if not self.closed:
                self.closed = True
                self._active["count"] -= 1

    class FakeProductSnapshots:
        def __init__(self, active_workers: dict[str, int]):
            self._active_workers = active_workers

        async def index_information(self):
            return {"idx_store_time": {"key": [("store_id", 1), ("crawled_at", -1)]}}

        async def options(self):
            return {}

        def aggregate(self, pipeline, *args, **kwargs):
            stores = pipeline[0]["$match"]["store_id"]["$in"]
            sid = stores[0] if len(stores) == 1 else "legacy-batch"
            return SlowCursor(sid, self._active_workers)

    class FakeDB:
        def __init__(self, active_workers: dict[str, int]):
            self.product_snapshots = FakeProductSnapshots(active_workers)

    now = datetime.now(timezone.utc)
    active = ["s1", "s2", "s3", "s4"]

    calls: list[tuple[str, str]] = []
    diag_flags: list[bool] = []
    active_workers = {"count": 0, "peak": 0}
    db = FakeDB(active_workers)

    import read_diagnostics
    import price_read_limits

    def capture_after_timeout_spy(_db, _kind, _pipeline, applied_hint=None, confirmed_timeout=True):
        diag_flags.append(bool(confirmed_timeout))

    monkeypatch.setattr(read_diagnostics, "capture_after_timeout", capture_after_timeout_spy, raising=True)

    # 1) Explicit caller cancellation: drained siblings, no timeout diagnostics selected.
    parent = asyncio.create_task(
        cohort_reads.read_cohort_snapshots(db, active, now, price_cohort.snapshot_pipeline, max_time_ms=3000)
    )
    await asyncio.sleep(0.05)
    parent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await parent

    assert active_workers["count"] == 0
    assert cohort_reads._gate()._value == cohort_reads.MAX_PARALLEL_READS
    assert any(flag is False for flag in diag_flags), diag_flags
    assert not any(flag is True for flag in diag_flags)

    # 2) Genuine bounded deadline expiry: timeout diagnostics marked as confirmed timeout.
    calls.clear()
    diag_flags.clear()
    monkeypatch.setattr(price_read_limits, "REQUEST_TIMEOUT_SECONDS", 0.08, raising=True)

    with pytest.raises(Exception) as exc:
        await price_read_limits.bounded_read(
            cohort_reads.read_cohort_snapshots(db, active, now, price_cohort.snapshot_pipeline, max_time_ms=3000)
        )
    http_exc = exc.value
    assert getattr(http_exc, "status_code", None) == 503
    assert getattr(http_exc, "detail", {}).get("code") == "price_query_timeout"

    assert active_workers["count"] == 0
    assert cohort_reads._gate()._value == cohort_reads.MAX_PARALLEL_READS
    assert any(flag is True for flag in diag_flags)

    # Ensure worker task drain: no lingering partition workers.
    pending = [
        t for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and "worker" in repr(t.get_coro()) and not t.done()
    ]
    assert pending == []


@pytest.mark.anyio
async def test_iter58_query_closes_cursor_on_iteration_failure(monkeypatch):
    """getMore-style iteration failure still attempts cursor close."""

    closed = {"count": 0}

    class FailingCursor:
        def __init__(self):
            self.n = 0

        def batch_size(self, _):
            return self

        def __aiter__(self):
            return self

        async def __anext__(self):
            self.n += 1
            if self.n == 1:
                return {"store_id": "s1", "offer_id": "ok", "price": 1}
            raise NetworkTimeout("synthetic getMore timeout")

        async def close(self):
            closed["count"] += 1

    class P:
        @staticmethod
        def aggregate(*_args, **_kwargs):
            return FailingCursor()

    class DB:
        product_snapshots = P()

    async def patched_close(cursor):
        await cursor.close()

    import read_diagnostics

    monkeypatch.setattr(cohort_reads, "close_read_cursor", patched_close, raising=True)
    monkeypatch.setattr(read_diagnostics, "capture_after_timeout", lambda *args, **kwargs: None, raising=True)

    with pytest.raises(NetworkTimeout):
        await cohort_reads._query(DB(), [{"$match": {}}], max_time_ms=1000)
    assert closed["count"] == 1


@pytest.mark.anyio
async def test_iter58_global_gate_limits_cross_caller_concurrency(monkeypatch):
    """Across concurrent callers, aggregate concurrency peak must remain <=2."""

    peak = {"active": 0, "max": 0}

    class SlowCursor:
        def __init__(self, sid: str):
            self.sid = sid
            self.done = False
            peak["active"] += 1
            peak["max"] = max(peak["max"], peak["active"])

        def batch_size(self, _):
            return self

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.done:
                raise StopAsyncIteration
            self.done = True
            await asyncio.sleep(0.05)
            return {"store_id": self.sid, "offer_id": f"{self.sid}-offer", "price": 1}

        async def close(self):
            peak["active"] -= 1

    class FakeProductSnapshots:
        async def index_information(self):
            return {"idx_store_time": {"key": [("store_id", 1), ("crawled_at", -1)]}}

        async def options(self):
            return {}

        def aggregate(self, pipeline, *args, **kwargs):
            sid = pipeline[0]["$match"]["store_id"]["$in"][0]
            return SlowCursor(sid)

    class FakeDB:
        product_snapshots = FakeProductSnapshots()

    db = FakeDB()
    now = datetime.now(timezone.utc)
    caller1 = cohort_reads.read_cohort_snapshots(db, ["a", "b", "c", "d"], now, price_cohort.snapshot_pipeline, max_time_ms=3000)
    caller2 = cohort_reads.read_cohort_snapshots(db, ["e", "f", "g", "h"], now, price_cohort.snapshot_pipeline, max_time_ms=3000)
    out1, out2 = await asyncio.gather(caller1, caller2)
    assert len(out1) == 4 and len(out2) == 4
    assert peak["max"] <= 2


def _build_perf_fixture_docs(now: datetime, own_count: int, stores: list[str], *, skewed: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    own_rows = []
    snaps = []
    payload = "X" * 4096
    for i in range(own_count):
        sku = f"ITER58-{i:05d}"
        barcode = f"628991{i:07d}"[-13:]
        own_rows.append({
            "sku": sku,
            "barcode": barcode,
            "name_en": f"Product {i}",
            "name_ar": f"منتج {i}",
            "price": 100.0,
            "sale_price": None,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "quantity": 10,
            "present_on_store": True,
            "last_synced_at": now,
        })

    balanced_days = [0, 3, 7, 14, 21, 30, 45, 60, 90, 179]
    heavy_days = list(range(81)) + [179]
    light_days = [0, 179]

    for store_i, sid in enumerate(stores):
        day_points = heavy_days if (skewed and store_i == 0) else light_days if skewed else balanced_days
        for idx in range(own_count):
            sku = own_rows[idx]["sku"]
            barcode = own_rows[idx]["barcode"]
            base_price = round(70 + (idx % 50) + (store_i * 0.3), 2)
            offer_id = f"{sid}-offer-{idx:06d}"
            for day in day_points:
                snaps.append({
                    "id": f"{sid}-{idx}-{day}",
                    "product_id": f"p-{idx:06d}",
                    "store_id": sid,
                    "store_name": sid,
                    "sku": sku,
                    "offer_id": offer_id,
                    "barcode": barcode,
                    "name_ar": "x",
                    "name_en": "x",
                    "price": round(base_price * (1 + (day % 4) * 0.01), 2),
                    "currency": "SAR",
                    "price_basis": "storefront_inc_vat",
                    "in_stock": True,
                    "qty_available": 20,
                    "crawled_at": now - timedelta(days=day, hours=(idx % 12)),
                    "observation_version": 2,
                    "confidence_score": 99,
                    "comparable": True,
                    "is_synthetic": False,
                    "present_on_store": True,
                    "variant_skus": [sku],
                    "variant_barcodes": [barcode],
                    "unused_payload": payload,
                })
    return own_rows, snaps


@pytest.mark.anyio
async def test_iter58_real_mongo_performance_gate_and_parity():
    """Gate: >=200k docs, balanced+skewed, parity + threshold checks + timing evidence."""
    mongo_url = _loopback_mongo_url()
    probe = CommandProbe()
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=6000, event_listeners=[probe])

    async def run_distribution(label: str, *, skewed: bool) -> dict[str, Any]:
        db_name = f"iter58_perf_{label}_{uuid.uuid4().hex[:8]}"
        raw = client[db_name]
        db = GuardedDatabase(raw)
        now = datetime.now(timezone.utc).replace(microsecond=0)

        own_store = "own"
        active = [f"s{i:02d}" for i in range(1, 11)]
        own_rows, snaps = _build_perf_fixture_docs(now, own_count=2000, stores=active, skewed=skewed)
        assert len(snaps) >= 200000

        try:
            await raw.stores.insert_many([{"id": own_store, "is_own_store": True, "is_active": True}] + [{"id": sid, "is_active": True} for sid in active])
            await raw.my_products.insert_many(own_rows)
            # large insert in chunks
            for i in range(0, len(snaps), 5000):
                await raw.product_snapshots.insert_many(snaps[i:i + 5000], ordered=False)

            # Disposable benchmark DB mirrors production-observed index order.
            await raw.product_snapshots.create_index([("crawled_at", 1)], name="crawled_at_1")
            await raw.product_snapshots.create_index([("product_id", 1)], name="product_id_1")
            await raw.product_snapshots.create_index([("store_id", 1), ("crawled_at", -1)], name="store_id_1_crawled_at_-1")
            await raw.product_snapshots.create_index([("sku", 1), ("crawled_at", -1)], name="sku_1_crawled_at_-1")
            indexes = await raw.product_snapshots.index_information()
            assert set(indexes.keys()) == {
                "_id_",
                "crawled_at_1",
                "product_id_1",
                "store_id_1_crawled_at_-1",
                "sku_1_crawled_at_-1",
            }

            pipeline = price_cohort.snapshot_pipeline(active, now)

            async def run_new_reader() -> dict[str, Any]:
                probe.reset()
                t0 = time.perf_counter()
                rows = await cohort_reads.read_cohort_snapshots(db, active, now, price_cohort.snapshot_pipeline, max_time_ms=SNAPSHOT_QUERY_MAX_MS)
                elapsed = (time.perf_counter() - t0) * 1000.0
                reads = probe.summary()
                return {
                    "elapsed_ms": round(elapsed, 3),
                    "rows": rows,
                    "reads": reads,
                    "firstbatch_median_ms": round(statistics.median(reads["aggregate_first_batch_ms"]) if reads["aggregate_first_batch_ms"] else 0.0, 3),
                    "firstbatch_max_ms": round(max(reads["aggregate_first_batch_ms"]) if reads["aggregate_first_batch_ms"] else 0.0, 3),
                }

            async def run_mono(hint: str | None) -> dict[str, Any]:
                probe.reset()
                t0 = time.perf_counter()
                kwargs = {"hint": hint} if hint else {}
                cursor = raw.product_snapshots.aggregate(
                    pipeline,
                    allowDiskUse=True,
                    maxTimeMS=SNAPSHOT_QUERY_MAX_MS,
                    **kwargs,
                ).batch_size(2000)
                rows = await cursor.to_list(None)
                elapsed = (time.perf_counter() - t0) * 1000.0
                reads = probe.summary()
                return {
                    "elapsed_ms": round(elapsed, 3),
                    "rows": rows,
                    "reads": reads,
                    "firstbatch_ms": round(reads["aggregate_first_batch_ms"][0] if reads["aggregate_first_batch_ms"] else 0.0, 3),
                }

            # Warmup (labelled, excluded from measured gates)
            warmup_new = await run_new_reader()
            warmup_default = await run_mono(None)
            warmup_hinted = await run_mono("store_id_1_crawled_at_-1")

            measured = {"new": [], "default": [], "hinted": [], "pair_order": []}
            for i in range(7):
                if i % 2 == 0:
                    order = ["new", "default", "hinted"]
                else:
                    order = ["hinted", "default", "new"]
                measured["pair_order"].append(order)

                run_data: dict[str, Any] = {}
                for name in order:
                    if name == "new":
                        run_data[name] = await run_new_reader()
                    elif name == "default":
                        run_data[name] = await run_mono(None)
                    else:
                        run_data[name] = await run_mono("store_id_1_crawled_at_-1")

                # exact FULL-row canonical parity each iteration
                canon_default = _canonical(run_data["default"]["rows"])
                canon_new = _canonical(run_data["new"]["rows"])
                canon_hinted = _canonical(run_data["hinted"]["rows"])
                assert canon_new == canon_default
                assert canon_hinted == canon_default

                default_digest = _canonical_digest(run_data["default"]["rows"])
                new_digest = _canonical_digest(run_data["new"]["rows"])
                hinted_digest = _canonical_digest(run_data["hinted"]["rows"])
                assert new_digest["sha256"] == default_digest["sha256"]
                assert hinted_digest["sha256"] == default_digest["sha256"]

                for name in ("new", "default", "hinted"):
                    digest = {
                        "new": new_digest,
                        "default": default_digest,
                        "hinted": hinted_digest,
                    }[name]
                    measured[name].append({
                        **{k: v for k, v in run_data[name].items() if k != "rows"},
                        "row_digest": digest,
                    })

            new_elapsed = [r["elapsed_ms"] for r in measured["new"]]
            def_elapsed = [r["elapsed_ms"] for r in measured["default"]]
            hin_elapsed = [r["elapsed_ms"] for r in measured["hinted"]]
            new_firstbatch_medians = [r["firstbatch_median_ms"] for r in measured["new"]]
            new_firstbatch_max = [r["firstbatch_max_ms"] for r in measured["new"]]
            def_firstbatch = [r["firstbatch_ms"] for r in measured["default"]]
            hin_firstbatch = [r["firstbatch_ms"] for r in measured["hinted"]]

            baseline_total_median = min(statistics.median(def_elapsed), statistics.median(hin_elapsed))
            baseline_firstbatch_median = min(statistics.median(def_firstbatch), statistics.median(hin_firstbatch))

            # Deployment gate thresholds
            assert max(new_elapsed) < 20000, f"{label}: new reader exceeded 20s"
            assert statistics.median(new_elapsed) <= baseline_total_median * 1.2, (
                f"{label}: new total median {statistics.median(new_elapsed):.2f} > 120% of baseline {baseline_total_median:.2f}"
            )
            if label == "balanced":
                assert statistics.median(new_firstbatch_max) <= baseline_firstbatch_median * 0.8, (
                    f"balanced: slowest partition median {statistics.median(new_firstbatch_max):.2f} > 80% of monolithic firstbatch {baseline_firstbatch_median:.2f}"
                )

            oldest = min(s["crawled_at"] for s in snaps)
            newest = max(s["crawled_at"] for s in snaps)
            return {
                "label": label,
                "skewed": skewed,
                "seed": {
                    "docs": len(snaps),
                    "stores": len(active),
                    "own_products": len(own_rows),
                    "history_days_filter": 180,
                    "actual_oldest_at": oldest.isoformat(),
                    "actual_newest_at": newest.isoformat(),
                    "actual_span_days": round((newest - oldest).total_seconds() / 86400.0, 3),
                    "unused_payload_bytes": 4096,
                },
                "warmup": {
                    "new_ms": warmup_new["elapsed_ms"],
                    "default_ms": warmup_default["elapsed_ms"],
                    "hinted_ms": warmup_hinted["elapsed_ms"],
                },
                "runs": measured,
                "stats": {
                    "new_total_ms": _stats(new_elapsed),
                    "default_total_ms": _stats(def_elapsed),
                    "hinted_total_ms": _stats(hin_elapsed),
                    "new_firstbatch_median_ms": _stats(new_firstbatch_medians),
                    "new_firstbatch_max_ms": _stats(new_firstbatch_max),
                    "default_firstbatch_ms": _stats(def_firstbatch),
                    "hinted_firstbatch_ms": _stats(hin_firstbatch),
                },
                "gate": {
                    "baseline_total_median_ms": round(baseline_total_median, 3),
                    "baseline_firstbatch_median_ms": round(baseline_firstbatch_median, 3),
                    "new_total_median_ms": round(statistics.median(new_elapsed), 3),
                    "new_slowest_partition_firstbatch_median_ms": round(statistics.median(new_firstbatch_max), 3),
                    "all_under_20s": max(new_elapsed) < 20000,
                },
                "result_digest": _canonical_digest(await raw.product_snapshots.aggregate(pipeline, allowDiskUse=True, maxTimeMS=SNAPSHOT_QUERY_MAX_MS).batch_size(2000).to_list(None)),
                "index_used_reference": "store_id_1_crawled_at_-1",
                "notes": "Seven measured paired runs; report medians/min/max only (not p95 claim).",
            }
        finally:
            await client.drop_database(db_name)

    balanced = await run_distribution("balanced", skewed=False)
    skewed = await run_distribution("skewed", skewed=True)

    ITER58_BENCH.parent.mkdir(parents=True, exist_ok=True)
    if ITER58_BENCH.exists():
        ITER58_BENCH.replace(ITER58_BENCH.with_suffix(".prev.json"))
    ITER58_BENCH.write_text(json.dumps({"balanced": balanced, "skewed": skewed}, indent=2, default=str))

    client.close()


def test_iter58_all_store_failure_503_no_rows_cache_and_no_writes():
    """All-partition failure should return retryable 503 with no rows/cache write side effects."""
    mongo_url = _loopback_mongo_url()
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
    db_name = f"iter58_503_{uuid.uuid4().hex[:10]}"
    raw = client[db_name]
    original_db = server.db
    original_override = server.app.dependency_overrides.get(server.get_user)

    async def setup():
        seeded = await _seed_baseline(raw)
        guarded = CountingGuardedDatabase(raw)
        return seeded, guarded

    loop = asyncio.new_event_loop()
    _, guarded = loop.run_until_complete(setup())
    server.db = guarded
    server.app.dependency_overrides[server.get_user] = _fake_user

    original_aggregate = release_database.GuardedCollection.aggregate
    import read_diagnostics
    original_capture = read_diagnostics.capture_after_timeout

    def fail_all(self, pipeline, *args, **kwargs):
        if getattr(self.raw, "name", "") == "product_snapshots":
            raise TimeoutError("iter58 forced all-store timeout")
        return original_aggregate(self, pipeline, *args, **kwargs)

    release_database.GuardedCollection.aggregate = fail_all  # type: ignore[assignment]
    read_diagnostics.capture_after_timeout = lambda *args, **kwargs: None  # type: ignore[assignment]
    try:
        before_cache = loop.run_until_complete(raw.dashboard_cache.count_documents({}))
        my_products_cache._loops.clear()

        async def call():
            transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                return await ac.get("/api/my-products", params={"days": 30, "limit": 10, "offset": 0})

        response = loop.run_until_complete(call())
        body = response.json()
        assert response.status_code == 503
        assert body.get("detail", {}).get("retryable") is True
        assert body.get("detail", {}).get("code") == "price_query_timeout"
        assert not (response.status_code == 200 and body.get("total") in (0, None))

        after_cache = loop.run_until_complete(raw.dashboard_cache.count_documents({}))
        assert before_cache == after_cache
        assert guarded.write_attempted == 0
        assert guarded.write_actual == 0

        # Ensure no pending partition worker tasks leaked.
        pending = [t for t in asyncio.all_tasks(loop=loop) if not t.done() and "worker" in repr(t.get_coro())]
        assert len(pending) == 0
    finally:
        read_diagnostics.capture_after_timeout = original_capture  # type: ignore[assignment]
        release_database.GuardedCollection.aggregate = original_aggregate  # type: ignore[assignment]
        server.db = original_db
        if original_override is None:
            server.app.dependency_overrides.pop(server.get_user, None)
        else:
            server.app.dependency_overrides[server.get_user] = original_override
        loop.run_until_complete(client.drop_database(db_name))
        client.close()
        loop.close()


def test_iter58_preview_authenticated_read_smoke():
    """Preview smoke: authenticated read-only my-products(14/30), market-share, intel endpoints."""
    url = base_url().rstrip("/")
    if "localhost" in url or "127.0.0.1" in url:
        pytest.skip("External preview URL unavailable")

    headers = auth_headers()
    checks = [
        ("/api/my-products", {"days": 14, "limit": 5, "offset": 0, "sort_by": "revenue_est", "sort_order": "desc"}),
        ("/api/my-products", {"days": 30, "limit": 5, "offset": 0, "sort_by": "revenue_est", "sort_order": "desc"}),
        ("/api/market-share/overview", {"days": 30}),
        ("/api/price-intel/store-ranking", {}),
    ]

    out = {"base_url": url, "results": []}
    for path, params in checks:
        t0 = time.perf_counter()
        resp = requests.get(f"{url}{path}", headers=headers, params=params, timeout=120)
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        try:
            body = resp.json()
        except Exception:
            body = {"non_json": True}

        row = {
            "path": path,
            "params": params,
            "status": resp.status_code,
            "elapsed_ms": elapsed,
        }
        if isinstance(body, dict) and body.get("detail"):
            row["detail"] = body["detail"]
        if path == "/api/my-products" and isinstance(body, dict):
            row["total"] = body.get("total")
            row["page_count"] = len(body.get("products") or [])
        out["results"].append(row)

        assert resp.status_code == 200, f"{path} -> {resp.status_code}"
        if path == "/api/my-products":
            assert isinstance(body.get("products"), list)
            total = body.get("total")
            products = body.get("products") or []
            if not products or total in (None, 0):
                pytest.fail(
                    "Preview my-products dataset empty for non-empty coverage assertion "
                    f"(total={total}, page_count={len(products)})."
                )
            assert total > 0
            assert len(products) > 0

    ITER58_SMOKE.parent.mkdir(parents=True, exist_ok=True)
    ITER58_SMOKE.write_text(json.dumps(out, indent=2, default=str))
