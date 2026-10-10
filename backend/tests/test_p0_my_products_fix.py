"""P0 post-fix validation for /api/my-products read path (no app-code edits).

Covers timeout contract, cache freshness/revision behavior, singleflight,
read-only observer mode, 2,832+ catalogue pagination integrity, and external
preview authenticated smoke.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import monitoring
from pymongo.errors import ExecutionTimeout, NetworkTimeout

import my_products_cache
import comparison_views
import price_cohort
import price_read_limits
import release_database
import server
from observation_contract import gtin
from _auth import auth_headers, base_url
from release_control import state as release_state
from test_p0_my_products_baseline import BASE_QUERY, ReadProbe, _fake_user, _loopback_mongo_url, _seed_baseline


REPORT_PATH = Path("/app/test_reports/p0_my_products/fix_validation_post_fix.json")


class CommandProbe(monitoring.CommandListener):
    """Capture read command docs/counts/durations including maxTimeMS evidence."""

    READS = {"aggregate", "find", "distinct", "getMore"}

    def __init__(self) -> None:
        self._started: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    def reset(self) -> None:
        self._started.clear()
        self.events.clear()

    def started(self, event):  # type: ignore[override]
        if event.command_name in self.READS:
            self._started[event.request_id] = {
                "name": event.command_name,
                "command": dict(event.command),
            }

    def succeeded(self, event):  # type: ignore[override]
        row = self._started.pop(event.request_id, None)
        if row:
            self.events.append({
                **row,
                "duration_ms": round(float(event.duration_micros) / 1000.0, 3),
                "failed": False,
            })

    def failed(self, event):  # type: ignore[override]
        row = self._started.pop(event.request_id, None)
        if row:
            self.events.append({
                **row,
                "duration_ms": round(float(event.duration_micros) / 1000.0, 3),
                "failed": True,
            })

    def summary(self) -> dict[str, Any]:
        by: dict[str, dict[str, Any]] = {
            k: {"count": 0, "duration_ms": 0.0} for k in self.READS
        }
        for ev in self.events:
            by[ev["name"]]["count"] += 1
            by[ev["name"]]["duration_ms"] += ev.get("duration_ms", 0.0)
        return {
            "by_command": by,
            "total_read_commands": sum(v["count"] for v in by.values()),
            "events": list(self.events),
        }


class CountingGuardedDatabase(release_database.GuardedDatabase):
    """Observer/write guard instrumentation: attempted vs actual writes."""

    def __init__(self, raw):
        super().__init__(raw)
        self.write_attempted = 0
        self.write_actual = 0

    async def perform(self, collection, method, operation, *args, **kwargs):
        self.write_attempted += 1
        out = await super().perform(collection, method, operation, *args, **kwargs)
        self.write_actual += 1
        return out


def _compute_check_digit(base: str) -> str:
    check = sum(int(n) * (3 if i % 2 == 0 else 1) for i, n in enumerate(reversed(base)))
    return str((10 - (check % 10)) % 10)


def make_gtin(length: int, payload_without_check: str) -> str:
    assert length in (8, 12, 13, 14)
    assert len(payload_without_check) == length - 1
    code = payload_without_check + _compute_check_digit(payload_without_check)
    assert gtin(code) is not None
    return code


def _old_pipeline(active: list[str], now: datetime) -> list[dict[str, Any]]:
    return [
        {"$match": {"store_id": {"$in": active}, "crawled_at": {"$gte": now - timedelta(days=180)}}},
        {"$sort": {"crawled_at": -1}},
        {
            "$group": {
                "_id": {"$ifNull": ["$offer_id", {"store": "$store_id", "sku": "$sku"}]},
                "latest": {"$first": "$$ROOT"},
                "historical_max": {
                    "$max": {
                        "$cond": [
                            {"$and": [{"$eq": ["$observation_version", 2]}, {"$eq": ["$comparable", True]}]},
                            "$price",
                            None,
                        ]
                    }
                },
            }
        },
        {"$replaceRoot": {"newRoot": {"$mergeObjects": ["$latest", {"historical_max_price": "$historical_max"}]}}},
        {"$project": {**price_cohort.FIELDS, "historical_max_price": 1}},
    ]


def _walk_explain(node: Any, out: dict[str, Any]) -> None:
    if isinstance(node, dict):
        for key in (
            "totalDocsExamined",
            "totalKeysExamined",
            "executionTimeMillis",
            "usedDisk",
            "spills",
            "spilledBytes",
            "nReturned",
        ):
            if key in node and key not in out:
                out[key] = node[key]
        if isinstance(node.get("stage"), str):
            out.setdefault("stages", []).append(node["stage"])
        for value in node.values():
            _walk_explain(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_explain(value, out)


@pytest.fixture(scope="module")
def p0_env():
    """Disposable loopback-only seeded dataset and ASGI observer wiring."""

    mongo_url = _loopback_mongo_url()
    db_name = f"p0_my_products_fix_{uuid.uuid4().hex[:10]}"

    async def setup():
        seed_client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
        raw_db = seed_client[db_name]

        read_probe = ReadProbe()
        cmd_probe = CommandProbe()
        measured_client = AsyncIOMotorClient(
            mongo_url,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            socketTimeoutMS=45000,
            event_listeners=[read_probe, cmd_probe],
        )

        seeded = await _seed_baseline(raw_db)
        guarded = CountingGuardedDatabase(measured_client[db_name])
        return {
            "seed_client": seed_client,
            "measured_client": measured_client,
            "raw_db": raw_db,
            "guarded": guarded,
            "seeded": seeded,
            "read_probe": read_probe,
            "cmd_probe": cmd_probe,
            "db_name": db_name,
        }

    loop = asyncio.new_event_loop()
    env = loop.run_until_complete(setup())
    env["loop"] = loop
    original_db = server.db
    original_override = server.app.dependency_overrides.get(server.get_user)
    server.db = env["guarded"]
    server.app.dependency_overrides[server.get_user] = _fake_user
    try:
        mode = loop.run_until_complete(release_state(server.db))["mode"]
        assert mode == "observer"
        env["observer_mode"] = mode
        yield env
    finally:
        server.db = original_db
        if original_override is None:
            server.app.dependency_overrides.pop(server.get_user, None)
        else:
            server.app.dependency_overrides[server.get_user] = original_override
        loop.run_until_complete(env["seed_client"].drop_database(db_name))
        env["measured_client"].close()
        env["seed_client"].close()
        loop.close()


async def _call_my_products(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = dict(BASE_QUERY if params is None else params)
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        t0 = time.perf_counter()
        resp = await ac.get("/api/my-products", params=params)
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
    content_type = resp.headers.get("content-type", "")
    body = resp.json() if content_type.startswith("application/json") else {"non_json": True}
    return {"status": resp.status_code, "elapsed_ms": elapsed, "body": body}


@contextmanager
def _patch_guarded_aggregate(patched):
    original = release_database.GuardedCollection.aggregate
    release_database.GuardedCollection.aggregate = patched  # type: ignore[assignment]
    try:
        yield
    finally:
        release_database.GuardedCollection.aggregate = original  # type: ignore[assignment]


def test_00_confirm_timeout_traceback_cause():
    """RCA validation: verify actual traceback text references aggregate timeout path."""
    rca = Path("/app/deployer-agent-docs/RCA_0107107d-2d21-47fb-8ee5-836d2779725f.MD").read_text()
    assert "price_cohort.py:135" in rca
    assert "TimeoutError: The read operation timed out" in rca
    assert "socketTimeoutMS=45000" in rca


def test_10_p0_post_fix_scenarios(p0_env, monkeypatch):
    """Core P0 scenarios: caching, timeout contract, parity, singleflight, pagination scale."""

    report: dict[str, Any] = {
        "db_name": p0_env["db_name"],
        "observer_mode": p0_env["observer_mode"],
        "seed": {
            "own_products": p0_env["seeded"]["seeded_products"],
            "snapshots": p0_env["seeded"]["seeded_snapshots"],
            "competitor_stores": len(p0_env["seeded"]["competitor_store_ids"]),
        },
        "scenarios": {},
    }

    async def run() -> dict[str, Any]:
        raw_db = p0_env["raw_db"]
        guarded: CountingGuardedDatabase = p0_env["guarded"]
        read_probe: ReadProbe = p0_env["read_probe"]
        cmd_probe: CommandProbe = p0_env["cmd_probe"]
        seeded_now = p0_env["seeded"]["seed_now"]
        active = p0_env["seeded"]["competitor_store_ids"]

        # Scenario: cold + memory-warm (observer mode, no writes, no DB cache writes)
        await raw_db.dashboard_cache.delete_many({})
        my_products_cache._loops.clear()
        before_attempted = guarded.write_attempted
        before_actual = guarded.write_actual
        before_docs = await raw_db.dashboard_cache.count_documents({})

        read_probe.reset()
        cmd_probe.reset()
        cold = await _call_my_products()
        cold_reads = read_probe.summary()
        cold_cmds = cmd_probe.summary()

        mid_attempted = guarded.write_attempted
        mid_actual = guarded.write_actual
        read_probe.reset()
        cmd_probe.reset()
        warm = await _call_my_products()
        warm_reads = read_probe.summary()
        warm_cmds = cmd_probe.summary()

        after_docs = await raw_db.dashboard_cache.count_documents({})
        assert cold["status"] == 200
        assert warm["status"] == 200
        assert warm["body"]["cache"]["source"] == "memory_cache"
        assert warm_reads["by_command"]["aggregate"]["count"] == 0
        assert cold["body"]["products"] == warm["body"]["products"]
        assert cold["body"].get("total") == 2832
        assert warm["body"].get("total") == 2832
        assert before_docs == 0 and after_docs == 0
        assert (mid_attempted - before_attempted) == 0
        assert (mid_actual - before_actual) == 0
        assert (guarded.write_attempted - mid_attempted) == 0
        assert (guarded.write_actual - mid_actual) == 0

        max_time_values = [
            ev.get("command", {}).get("maxTimeMS")
            for ev in cold_cmds["events"]
            if ev.get("name") == "aggregate" and ev.get("command", {}).get("aggregate") == "product_snapshots"
        ]
        assert max_time_values and all(v == 15000 for v in max_time_values)

        report["scenarios"]["cold_and_memory_warm"] = {
            "cold": {
                "status": cold["status"],
                "elapsed_ms": cold["elapsed_ms"],
                "cache_source": cold["body"].get("cache", {}).get("source"),
                "total": cold["body"].get("total"),
                "query_counts": cold_reads["by_command"],
                "total_read_commands": cold_reads["total_read_commands"],
            },
            "warm": {
                "status": warm["status"],
                "elapsed_ms": warm["elapsed_ms"],
                "cache_source": warm["body"].get("cache", {}).get("source"),
                "total": warm["body"].get("total"),
                "query_counts": warm_reads["by_command"],
                "total_read_commands": warm_reads["total_read_commands"],
            },
            "dashboard_cache_docs": {"before": before_docs, "after": after_docs},
            "writes": {
                "attempted": guarded.write_attempted - before_attempted,
                "actual": guarded.write_actual - before_actual,
            },
            "aggregate_maxTimeMS": max_time_values,
        }

        # Scenario: valid stored cache read
        ds = await my_products_cache.compute_dataset(
            guarded,
            lambda: server._my_products_dataset(guarded, 30, None, None, None, None, None, None, True),
            max_age=300,
        )
        await raw_db.dashboard_cache.replace_one(
            {"key": server._dashboard_cache_key(30)},
            {"key": server._dashboard_cache_key(30), **my_products_cache.envelope(ds)},
            upsert=True,
        )
        my_products_cache._loops.clear()
        from_db_cache = await _call_my_products()
        assert from_db_cache["status"] == 200
        assert from_db_cache["body"].get("cache", {}).get("source") == "cache"

        # Scenario: TTL-expired cache and malformed/future cache never trusted
        stale_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        await raw_db.dashboard_cache.update_one(
            {"key": server._dashboard_cache_key(30)},
            {"$set": {"computed_at": stale_at, "valid_until": stale_at}},
        )
        my_products_cache._loops.clear()
        stale_resp = await _call_my_products()
        assert stale_resp["status"] == 200
        assert stale_resp["body"].get("cache", {}).get("source") == "live_fallback"

        future_at = datetime.now(timezone.utc) + timedelta(hours=1)
        bad_doc = my_products_cache.envelope(ds)
        bad_doc["dataset"] = {**bad_doc["dataset"], "total": 1}
        bad_doc["computed_at"] = future_at
        await raw_db.dashboard_cache.replace_one(
            {"key": server._dashboard_cache_key(30)},
            {"key": server._dashboard_cache_key(30), **bad_doc},
            upsert=True,
        )
        my_products_cache._loops.clear()
        malformed_resp = await _call_my_products()
        assert malformed_resp["status"] == 200
        assert malformed_resp["body"].get("cache", {}).get("source") == "live_fallback"

        # Scenario: wrong key family should not be used
        await raw_db.dashboard_cache.delete_many({})
        await raw_db.dashboard_cache.insert_one({"key": "my_products:wrong-policy:days=30", **my_products_cache.envelope(ds)})
        my_products_cache._loops.clear()
        wrong_key_resp = await _call_my_products()
        assert wrong_key_resp["status"] == 200
        assert wrong_key_resp["body"].get("cache", {}).get("source") in {"live_fallback", "memory_cache"}

        # Scenario: source revision change mid-compute -> explicit retryable 503
        original_revision = my_products_cache.revision
        revision_counter = {"n": 0}
        await raw_db.dashboard_cache.delete_many({})
        my_products_cache._loops.clear()

        async def flip_revision(db):
            revision_counter["n"] += 1
            if revision_counter["n"] <= 2:
                return 1
            return 2

        my_products_cache.revision = flip_revision  # type: ignore[assignment]
        src_change = await _call_my_products()
        my_products_cache.revision = original_revision  # type: ignore[assignment]
        assert src_change["status"] == 503
        assert src_change["body"].get("detail", {}).get("code") == "price_source_changed"
        assert src_change["body"].get("detail", {}).get("retryable") is True

        # Scenario: app deadline timeout -> explicit retryable 503
        old_timeout = price_read_limits.REQUEST_TIMEOUT_SECONDS
        price_read_limits.REQUEST_TIMEOUT_SECONDS = 0.05
        original_compute_dataset = my_products_cache.compute_dataset

        async def slow_compute(*args, **kwargs):
            await asyncio.sleep(0.2)
            return await original_compute_dataset(*args, **kwargs)

        my_products_cache.compute_dataset = slow_compute  # type: ignore[assignment]
        my_products_cache._loops.clear()
        timeout_resp = await _call_my_products()
        my_products_cache.compute_dataset = original_compute_dataset  # type: ignore[assignment]
        price_read_limits.REQUEST_TIMEOUT_SECONDS = old_timeout
        assert timeout_resp["status"] == 503
        assert timeout_resp["body"].get("detail", {}).get("code") == "price_query_timeout"
        assert timeout_resp["body"].get("detail", {}).get("retryable") is True

        # Scenario: injected DB failures and getMore/partial-cursor failure -> 503, no empty-success
        original_aggregate = release_database.GuardedCollection.aggregate

        def raise_exc(exc):
            def patched(self, pipeline, *args, **kwargs):
                if getattr(self.raw, "name", "") == "product_snapshots":
                    raise exc
                return original_aggregate(self, pipeline, *args, **kwargs)
            return patched

        injected = {}
        for label, exc in {
            "execution_timeout": ExecutionTimeout("synthetic execution timeout"),
            "network_timeout": NetworkTimeout("synthetic network timeout"),
            "raw_timeout_error": TimeoutError("synthetic timeout"),
        }.items():
            my_products_cache._loops.clear()
            with _patch_guarded_aggregate(raise_exc(exc)):
                res = await _call_my_products()
            assert res["status"] == 503
            detail = res["body"].get("detail", {})
            assert detail.get("code") == "price_query_timeout"
            assert detail.get("retryable") is True
            assert not (res["status"] == 200 and res["body"].get("total") in (0, None))
            injected[label] = {"status": res["status"], "detail": detail}

        class PartialCursor:
            def __init__(self):
                self.rows = iter([
                    {
                        "sku": "OWN-00000",
                        "barcode": "6281110000001",
                        "store_id": "comp-01",
                        "store_name": "Store comp-01",
                        "offer_id": "partial-offer",
                        "listing_id": None,
                        "variant_id": None,
                        "name_ar": "x",
                        "name_en": "x",
                        "price": 50.0,
                        "currency": "SAR",
                        "price_basis": "storefront_inc_vat",
                        "in_stock": True,
                        "qty_available": 2,
                        "product_url": "",
                        "crawled_at": datetime.now(timezone.utc),
                        "observation_version": 2,
                        "confidence_score": 99,
                        "comparable": True,
                        "is_synthetic": False,
                        "present_on_store": True,
                        "variant_skus": ["OWN-00000"],
                        "variant_barcodes": ["6281110000001"],
                        "brand": None,
                        "brand_source": None,
                        "historical_max_price": 50.0,
                        "history_oldest_at": datetime.now(timezone.utc) - timedelta(days=1),
                    }
                ])
                self.done = False

            def batch_size(self, _n):
                return self

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.done:
                    raise StopAsyncIteration
                try:
                    return next(self.rows)
                except StopIteration:
                    self.done = True
                    raise NetworkTimeout("synthetic getMore timeout")

            async def close(self):
                return None

        def partial_fail(self, pipeline, *args, **kwargs):
            if getattr(self.raw, "name", "") == "product_snapshots":
                return PartialCursor()
            return original_aggregate(self, pipeline, *args, **kwargs)

        my_products_cache._loops.clear()
        with _patch_guarded_aggregate(partial_fail):
            get_more_fail = await _call_my_products()
        assert get_more_fail["status"] == 503
        assert get_more_fail["body"].get("detail", {}).get("code") == "price_query_timeout"

        # Next successful retry should work and not be poisoned by failure flight/cancel.
        my_products_cache._loops.clear()
        retry_ok = await _call_my_products()
        assert retry_ok["status"] == 200
        assert retry_ok["body"].get("total") == 2832

        # Scenario: concurrent cold singleflight (one compute path)
        my_products_cache._loops.clear()
        call_counter = {"n": 0}
        original_build = comparison_views.build_cohorts

        async def counted_build(*args, **kwargs):
            call_counter["n"] += 1
            await asyncio.sleep(0.15)
            return await original_build(*args, **kwargs)

        comparison_views.build_cohorts = counted_build  # type: ignore[assignment]
        try:
            tasks = [asyncio.create_task(_call_my_products()) for _ in range(5)]
            results = await asyncio.gather(*tasks)
        finally:
            comparison_views.build_cohorts = original_build  # type: ignore[assignment]
        assert all(r["status"] == 200 for r in results)
        singleflight_ok = call_counter["n"] == 1
        assert singleflight_ok, f"expected one compute, observed {call_counter['n']}"

        # Cancellation should not poison other waiters.
        my_products_cache._loops.clear()
        call_counter2 = {"n": 0}

        async def counted_build_2(*args, **kwargs):
            call_counter2["n"] += 1
            await asyncio.sleep(0.25)
            return await original_build(*args, **kwargs)

        comparison_views.build_cohorts = counted_build_2  # type: ignore[assignment]
        try:
            t1 = asyncio.create_task(_call_my_products())
            await asyncio.sleep(0.05)
            t2 = asyncio.create_task(_call_my_products())
            t1.cancel()
            with pytest.raises(asyncio.CancelledError):
                await t1
            r2 = await t2
        finally:
            comparison_views.build_cohorts = original_build  # type: ignore[assignment]
        assert r2["status"] == 200
        cancel_singleflight_ok = call_counter2["n"] == 1
        assert cancel_singleflight_ok, f"expected one compute after cancellation, observed {call_counter2['n']}"

        # Scenario: full 6-page enumeration (no truncation), totals/KPIs stable.
        all_skus = set()
        totals = []
        kpis_samples = []
        page_times = []
        for offset in (0, 500, 1000, 1500, 2000, 2500):
            p = await _call_my_products({**BASE_QUERY, "limit": 500, "offset": offset})
            assert p["status"] == 200
            totals.append(p["body"].get("total"))
            kpis_samples.append(p["body"].get("kpis"))
            page_times.append(p["elapsed_ms"])
            for row in p["body"].get("products", []):
                if row.get("sku"):
                    all_skus.add(row["sku"])
        assert all(t == 2832 for t in totals)
        assert len(all_skus) == 2832
        assert all(k == kpis_samples[0] for k in kpis_samples[1:])

        # Scenario: filtered/uncacheable path explicitly live_uncacheable
        unc = await _call_my_products({**BASE_QUERY, "search": "OWN-000"})
        assert unc["status"] == 200
        assert unc["body"].get("cache", {}).get("source") == "live_uncacheable"

        # Scenario: cache byte budget pressure should not truncate outputs.
        old_bytes = my_products_cache.MAX_CACHE_BYTES
        my_products_cache.MAX_CACHE_BYTES = 2048
        my_products_cache._loops.clear()
        b1 = await _call_my_products()
        b2 = await _call_my_products()
        my_products_cache.MAX_CACHE_BYTES = old_bytes
        assert b1["status"] == 200 and b2["status"] == 200
        assert b1["body"].get("total") == 2832 and b2["body"].get("total") == 2832

        # Scenario: valid GTIN + variant semantic fixtures (2kg46 vs 4kg85 + normalized GTIN).
        own_gtin_13 = make_gtin(13, "123456789012")
        own_gtin_14 = f"0{own_gtin_13}"
        pack_gtin = make_gtin(13, "234567890123")
        now = datetime.now(timezone.utc)
        await raw_db.my_products.insert_many([
            {
                "sku": "SKU-GTIN-NORM",
                "barcode": own_gtin_13,
                "name_ar": "GTIN Normalization",
                "name_en": "GTIN Normalization",
                "price": 99.0,
                "sale_price": None,
                "currency": "SAR",
                "price_basis": "storefront_inc_vat",
                "in_stock": True,
                "quantity": 10,
                "present_on_store": True,
                "last_synced_at": now.isoformat(),
            },
            {
                "sku": "SKU-PACK-2KG46",
                "barcode": pack_gtin,
                "name_ar": "Feed 2kg46",
                "name_en": "Feed 2kg46",
                "price": 85.0,
                "sale_price": None,
                "currency": "SAR",
                "price_basis": "storefront_inc_vat",
                "in_stock": True,
                "quantity": 10,
                "present_on_store": True,
                "last_synced_at": now.isoformat(),
            },
        ])
        await raw_db.product_snapshots.insert_many([
            {
                "id": "norm-1",
                "product_id": "norm-1",
                "store_id": "comp-01",
                "store_name": "Store comp-01",
                "sku": "GTIN-COMP",
                "offer_id": "norm-offer-1",
                "barcode": own_gtin_14,
                "name_ar": "Normalized",
                "name_en": "Normalized",
                "price": 90.0,
                "currency": "SAR",
                "price_basis": "storefront_inc_vat",
                "in_stock": True,
                "qty_available": 9,
                "crawled_at": now - timedelta(hours=2),
                "observation_version": 2,
                "confidence_score": 97,
                "comparable": True,
                "is_synthetic": False,
                "present_on_store": True,
                "variant_skus": ["GTIN-COMP"],
                "variant_barcodes": [own_gtin_14],
            },
            {
                "id": "pack-1",
                "product_id": "pack-1",
                "store_id": "comp-02",
                "store_name": "Store comp-02",
                "sku": "PACK-COMP",
                "offer_id": "pack-offer-1",
                "barcode": pack_gtin,
                "name_ar": "Feed 4kg85",
                "name_en": "Feed 4kg85",
                "price": 70.0,
                "currency": "SAR",
                "price_basis": "storefront_inc_vat",
                "in_stock": True,
                "qty_available": 9,
                "crawled_at": now - timedelta(hours=1),
                "observation_version": 2,
                "confidence_score": 97,
                "comparable": True,
                "is_synthetic": False,
                "present_on_store": True,
                "variant_skus": ["PACK-COMP"],
                "variant_barcodes": [pack_gtin],
            },
        ])
        own_rows = await guarded.my_products.find({"sku": {"$in": ["SKU-GTIN-NORM", "SKU-PACK-2KG46"]}}, {"_id": 0}).to_list(10)
        cohorts = await price_cohort.build_cohorts(guarded, own_rows, "own-store-p0", lambda r: float(r.get("sale_price") or r.get("price") or 0))
        gtin_sellers = cohorts["SKU-GTIN-NORM"]["sellers"]
        pack_sellers = cohorts["SKU-PACK-2KG46"]["sellers"]
        assert any(s.get("offer_id") == "norm-offer-1" for s in gtin_sellers)
        assert all(s.get("offer_id") != "pack-offer-1" for s in pack_sellers)

        # Scenario: old-vs-new snapshot pipeline output parity + explain comparison.
        new_docs = await raw_db.product_snapshots.aggregate(
            price_cohort.snapshot_pipeline(active, seeded_now), allowDiskUse=True
        ).to_list(None)
        old_docs = await raw_db.product_snapshots.aggregate(
            _old_pipeline(active, seeded_now), allowDiskUse=True
        ).to_list(None)

        def keyify(row):
            return (row.get("store_id"), row.get("offer_id") or row.get("sku"))

        new_map = {keyify(r): {k: r.get(k) for k in [*price_cohort.FIELDS.keys(), "historical_max_price"]} for r in new_docs}
        old_map = {keyify(r): {k: r.get(k) for k in [*price_cohort.FIELDS.keys(), "historical_max_price"]} for r in old_docs}
        assert set(new_map.keys()) == set(old_map.keys())
        for k in new_map:
            assert new_map[k] == old_map[k]

        explain_new = await raw_db.command({
            "explain": {
                "aggregate": "product_snapshots",
                "pipeline": price_cohort.snapshot_pipeline(active, seeded_now),
                "cursor": {},
                "allowDiskUse": True,
            },
            "verbosity": "executionStats",
        })
        explain_old = await raw_db.command({
            "explain": {
                "aggregate": "product_snapshots",
                "pipeline": _old_pipeline(active, seeded_now),
                "cursor": {},
                "allowDiskUse": True,
            },
            "verbosity": "executionStats",
        })
        m_new: dict[str, Any] = {"stages": []}
        m_old: dict[str, Any] = {"stages": []}
        _walk_explain(explain_new, m_new)
        _walk_explain(explain_old, m_old)

        # Multi-run medians (local ASGI only, no external network).
        samples = []
        for _ in range(5):
            r = await _call_my_products({**BASE_QUERY, "limit": 100, "offset": 0})
            assert r["status"] == 200
            samples.append(r["elapsed_ms"])
        median_local = sorted(samples)[len(samples) // 2]

        report["scenarios"].update({
            "stored_cache_warm": {
                "status": from_db_cache["status"],
                "cache_source": from_db_cache["body"].get("cache", {}).get("source"),
            },
            "ttl_and_malformed_cache_handling": {
                "ttl_expired_source": stale_resp["body"].get("cache", {}).get("source"),
                "malformed_source": malformed_resp["body"].get("cache", {}).get("source"),
                "wrong_key_source": wrong_key_resp["body"].get("cache", {}).get("source"),
            },
            "timeouts_and_failures": {
                "source_change_mid_compute": src_change,
                "app_deadline_timeout": timeout_resp,
                "injected": injected,
                "getmore_partial_failure": get_more_fail,
                "retry_after_failure": retry_ok,
            },
            "singleflight_and_cancellation": {
                "concurrent_requests": len(results),
                "compute_calls": call_counter["n"],
                "singleflight_one_compute_observed": singleflight_ok,
                "cancel_waiter_status": r2["status"],
                "compute_calls_with_cancel": call_counter2["n"],
                "cancel_path_single_compute_observed": cancel_singleflight_ok,
            },
            "pagination_no_truncation": {
                "pages": 6,
                "unique_skus": len(all_skus),
                "totals": totals,
                "page_elapsed_ms": page_times,
            },
            "uncacheable_and_budget": {
                "uncacheable_source": unc["body"].get("cache", {}).get("source"),
                "budget_pressure_totals": [b1["body"].get("total"), b2["body"].get("total")],
            },
            "gtin_and_variant_semantics": {
                "normalized_gtin_offer_present": any(s.get("offer_id") == "norm-offer-1" for s in gtin_sellers),
                "pack_mismatch_offer_blocked": all(s.get("offer_id") != "pack-offer-1" for s in pack_sellers),
            },
            "pipeline_parity": {
                "rows_old": len(old_docs),
                "rows_new": len(new_docs),
                "explain_old": {
                    k: m_old.get(k)
                    for k in ("totalDocsExamined", "totalKeysExamined", "executionTimeMillis", "usedDisk", "spills", "spilledBytes", "nReturned")
                },
                "explain_new": {
                    k: m_new.get(k)
                    for k in ("totalDocsExamined", "totalKeysExamined", "executionTimeMillis", "usedDisk", "spills", "spilledBytes", "nReturned")
                },
            },
            "latency_medians": {
                "local_asgi_median_ms": median_local,
                "local_asgi_runs_ms": samples,
            },
        })

        return report

    outcome = p0_env["loop"].run_until_complete(run())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(outcome, indent=2, default=str))


def test_20_preview_external_authenticated_smoke():
    """External preview smoke (real network/auth), no app mutation beyond normal auth flows."""
    url = base_url().rstrip("/")
    if "localhost" in url or "127.0.0.1" in url:
        pytest.skip("Preview URL not configured; REACT_APP_BACKEND_URL points to localhost")
    headers = auth_headers()

    t0 = time.perf_counter()
    resp = requests.get(
        f"{url}/api/my-products",
        params={"days": 30, "limit": 5, "offset": 0, "sort_by": "revenue_est", "sort_order": "desc"},
        headers=headers,
        timeout=60,
    )
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    assert resp.status_code == 200, resp.text[:400]
    body = resp.json()
    assert isinstance(body.get("products"), list)
    assert isinstance(body.get("kpis"), dict)
    assert isinstance(body.get("total"), int)

    # Append preview smoke evidence without leaking credentials/tokens.
    payload = json.loads(REPORT_PATH.read_text()) if REPORT_PATH.exists() else {"scenarios": {}}
    payload.setdefault("preview_external_smoke", {})
    payload["preview_external_smoke"] = {
        "base_url": url,
        "status": resp.status_code,
        "elapsed_ms": elapsed_ms,
        "products_len": len(body.get("products") or []),
        "total": body.get("total"),
        "cache_source": (body.get("cache") or {}).get("source"),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, indent=2, default=str))
