"""Iteration 51 — read-path optimization verification (backend-first).

Scope:
- Disposable loopback Mongo only (never production URL).
- Index family verification exactly as observed in production report.
- Old-vs-new parity/benchmark for cohort snapshot and store latest pipelines.
- Ranking parity (full-history+exclusion vs explicit 7d bound).
- Bounded failure contract: retryable 503 (not 200 empty / not raw 500).
- Preview smoke GETs for heavy endpoints using shared auth helper.
"""

from __future__ import annotations

# Historical experiment: pointer/$lookup optimization was rejected after its
# measured ~2x cold regression. Retain evidence/fixture helpers, not acceptance.
__test__ = False

import asyncio
import json
import os
import statistics
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import requests
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import monitoring
from pymongo.errors import ExecutionTimeout, NetworkTimeout

import comparison_views
import market_share
import my_products_cache
import price_cohort
import release_database
import server
import snapshot_reads
import store_views
from test_p0_my_products_baseline import _fake_user


def _env_value(key: str) -> str:
    for line in Path("/app/backend/.env").read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# Required by instruction: use DALEEL_TEST_PASSWORD from backend env BEFORE import _auth.
if not os.environ.get("DALEEL_TEST_PASSWORD"):
    os.environ["DALEEL_TEST_PASSWORD"] = _env_value("DALEEL_TEST_PASSWORD") or _env_value("SUPER_ADMIN_PASSWORD")

from _auth import auth_headers, base_url  # noqa: E402


BENCH_PATH = Path("/app/test_reports/iter51_readpath_benchmark.json")
SMOKE_PATH = Path("/app/test_reports/iter51_preview_smoke.json")


def _loopback_mongo_url() -> str:
    mongo_url = _env_value("MONGO_URL") or os.environ.get("MONGO_URL", "")
    assert mongo_url, "MONGO_URL must be configured"
    parsed = urlparse(mongo_url)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}, (
        f"Refusing non-loopback Mongo host for iter51: {parsed.hostname}"
    )
    return mongo_url


def _compute_check_digit(base: str) -> str:
    check = sum(int(n) * (3 if i % 2 == 0 else 1) for i, n in enumerate(reversed(base)))
    return str((10 - (check % 10)) % 10)


def _make_gtin13(payload12: str) -> str:
    assert len(payload12) == 12
    return payload12 + _compute_check_digit(payload12)


class CommandProbe(monitoring.CommandListener):
    READS = {"aggregate", "find", "distinct", "getMore"}

    def __init__(self) -> None:
        self.started_rows: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.started_rows.clear()
        self.events.clear()

    def started(self, event):  # type: ignore[override]
        if event.command_name in self.READS:
            self.started_rows[event.request_id] = {
                "name": event.command_name,
                "command": dict(event.command),
            }

    def succeeded(self, event):  # type: ignore[override]
        row = self.started_rows.pop(event.request_id, None)
        if row:
            self.events.append({
                **row,
                "duration_ms": round(float(event.duration_micros) / 1000.0, 3),
                "failed": False,
            })

    def failed(self, event):  # type: ignore[override]
        row = self.started_rows.pop(event.request_id, None)
        if row:
            self.events.append({
                **row,
                "duration_ms": round(float(event.duration_micros) / 1000.0, 3),
                "failed": True,
            })

    def summary(self) -> dict[str, Any]:
        by = {k: {"count": 0, "duration_ms": 0.0} for k in self.READS}
        for ev in self.events:
            by[ev["name"]]["count"] += 1
            by[ev["name"]]["duration_ms"] += ev.get("duration_ms", 0.0)
        return {
            "by_command": by,
            "total_read_commands": sum(v["count"] for v in by.values()),
        }


def _old_cohort_pipeline(active: list[str], now: datetime) -> list[dict[str, Any]]:
    return [
        {"$match": {"store_id": {"$in": active}, "crawled_at": {"$gte": now - timedelta(days=180)}}},
        {"$project": {
            "_id": 1, "store_id": 1, "sku": 1, "offer_id": 1, "crawled_at": 1,
            "price": 1, "observation_version": 1, "comparable": 1,
            "barcode": 1, "name_ar": 1, "name_en": 1, "currency": 1, "price_basis": 1,
            "in_stock": 1, "qty_available": 1, "product_url": 1, "confidence_score": 1,
            "is_synthetic": 1, "present_on_store": 1, "store_name": 1,
            "variant_skus": 1, "variant_barcodes": 1,
        }},
        {"$sort": {"crawled_at": -1}},
        {"$group": {
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
        }},
        {"$replaceRoot": {"newRoot": {"$mergeObjects": ["$latest", {"historical_max_price": "$historical_max"}]}}},
        {"$project": {**price_cohort.FIELDS, "historical_max_price": 1}},
    ]


def _old_store_latest_pipeline(query: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"$match": query},
        {"$sort": {"crawled_at": -1}},
        {"$group": {
            "_id": {"$ifNull": ["$offer_id", {"store": "$store_id", "sku": "$sku"}]},
            "latest": {"$first": "$$ROOT"},
        }},
        {"$replaceRoot": {"newRoot": "$latest"}},
        {"$project": {"_id": 0}},
    ]


def _walk_explain(node: Any, out: dict[str, Any]) -> None:
    if isinstance(node, dict):
        for key in (
            "totalDocsExamined",
            "totalKeysExamined",
            "executionTimeMillis",
            "nReturned",
            "usedDisk",
            "spills",
            "spilledBytes",
            "maxAccumulatorMemoryUsageBytes",
        ):
            if key in node and key not in out:
                out[key] = node[key]
        for value in node.values():
            _walk_explain(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_explain(value, out)


async def _seed_fixture(raw_db, payload_size: int) -> dict[str, Any]:
    for coll in (
        "stores", "my_products", "products", "product_snapshots", "product_matches",
        "match_blacklist", "dashboard_cache", "data_versions",
    ):
        await raw_db[coll].delete_many({})

    now = datetime.now(timezone.utc).replace(microsecond=0)
    own_store = "own-store-iter51"
    comp_ids = ["comp-01", "comp-02", "comp-03"]
    history_days = [0, 1, 2, 3, 5, 7, 14, 30, 60, 90, 120, 179]

    await raw_db.stores.insert_many([
        {"id": own_store, "name": "Own", "is_active": True, "is_own_store": True},
        *[{"id": sid, "name": sid, "is_active": True} for sid in comp_ids],
    ])

    own_rows = []
    products_rows = []
    for i in range(2832):
        sku = f"OWN-{i:04d}"
        gtin = _make_gtin13(f"62851{i:07d}"[-12:])
        own_rows.append({
            "sku": sku,
            "barcode": gtin,
            "name_en": "Feed 2kg46" if i == 0 else f"Product {i}",
            "name_ar": f"منتج {i}",
            "price": 100 + (i % 50),
            "sale_price": None,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "quantity": 10 + (i % 25),
            "present_on_store": True,
            "offer_id": f"own-offer-{i:04d}",
            "last_synced_at": now,
            "quantity_observed_at": now,
        })
        products_rows.append({"id": f"prod-{i:04d}", "sku": sku, "store_id": own_store, "offer_id": f"own-offer-{i:04d}"})

    await raw_db.my_products.insert_many(own_rows)
    await raw_db.products.insert_many(products_rows)

    payload = "X" * payload_size
    total = 0
    batch: list[dict[str, Any]] = []

    def emit(doc: dict[str, Any]) -> None:
        batch.append(doc)

    async def flush() -> None:
        nonlocal total
        if batch:
            await raw_db.product_snapshots.insert_many(batch, ordered=False)
            total += len(batch)
            batch.clear()

    # 3 stores * 2832 products * 12 points = 101,952 snapshots.
    for sid, sid_i in zip(comp_ids, range(len(comp_ids))):
        for i, row in enumerate(own_rows):
            for d in history_days:
                offer_id = f"{sid}-offer-{i:04d}"
                if i == 1 and sid == "comp-01":
                    offer_id = None  # fallback grouping path
                emit({
                    "id": f"{sid}-{i}-{d}",
                    "product_id": f"prod-{i:04d}",
                    "store_id": sid,
                    "store_name": sid,
                    "sku": row["sku"],
                    "offer_id": offer_id,
                    "barcode": row["barcode"],
                    "name_ar": "Pack 4kg85" if i == 0 and sid == "comp-02" else f"{sid} {row['name_ar']}",
                    "name_en": "Feed 4kg85" if i == 0 and sid == "comp-02" else f"{sid} {row['name_en']}",
                    "price": round((80 + (i % 40) + sid_i) * (1 + (d % 5) * 0.01), 2),
                    "currency": "SAR",
                    "price_basis": "storefront_inc_vat",
                    "in_stock": False if (i == 2 and d == 0 and sid == "comp-01") else True,
                    "qty_available": 0 if (i == 2 and d == 0 and sid == "comp-01") else 10 + (i % 20),
                    "crawled_at": now - timedelta(days=d, hours=(i + sid_i) % 23),
                    "observation_version": 2,
                    "confidence_score": 99,
                    "comparable": True,
                    "is_synthetic": False,
                    "present_on_store": True,
                    "variant_skus": [row["sku"]],
                    "variant_barcodes": [row["barcode"]],
                    "payload_blob": payload,
                })
                if len(batch) >= 5000:
                    await flush()

    # very stale row should still appear in default latest() output.
    emit({
        "id": "stale-offer",
        "product_id": "stale-prod",
        "store_id": "comp-01",
        "store_name": "comp-01",
        "sku": "STALE-SKU",
        "offer_id": "stale-offer",
        "barcode": _make_gtin13("629999999999"),
        "name_en": "Stale Product",
        "name_ar": "قديم",
        "price": 10.0,
        "currency": "SAR",
        "price_basis": "storefront_inc_vat",
        "in_stock": True,
        "qty_available": 1,
        "crawled_at": now - timedelta(days=220),
        "observation_version": 2,
        "confidence_score": 99,
        "comparable": True,
        "is_synthetic": False,
        "present_on_store": True,
        "payload_blob": payload,
    })
    await flush()

    await raw_db.product_matches.insert_one({
        "my_sku": own_rows[0]["sku"],
        "competitor_store_id": "comp-01",
        "competitor_offer_id": "manual-offer-1",
        "manually_confirmed": True,
        "identity_version": 2,
    })
    await raw_db.match_blacklist.insert_one({
        "my_sku": own_rows[0]["sku"],
        "competitor_store_id": "comp-02",
        "competitor_offer_id": "blocked-offer-1",
    })

    # Only observed production index family.
    await raw_db.product_snapshots.create_index([("crawled_at", 1)])
    await raw_db.product_snapshots.create_index([("sku", 1), ("crawled_at", -1)])
    await raw_db.product_snapshots.create_index([("product_id", 1)])
    await raw_db.product_snapshots.create_index([("store_id", 1), ("crawled_at", -1)])

    await raw_db.data_versions.update_one(
        {"_id": "observations"},
        {"$set": {"revision": 1, "observed_at": now}},
        upsert=True,
    )

    return {
        "own_store_id": own_store,
        "competitor_store_ids": comp_ids,
        "seed_now": now,
        "seeded_products": len(own_rows),
        "seeded_snapshots": total,
        "payload_size": payload_size,
    }


def _stats(values: list[float]) -> dict[str, float]:
    values = sorted(values)
    if not values:
        return {"min": 0.0, "median": 0.0, "p95": 0.0}
    p95_i = max(0, min(len(values) - 1, int(round(0.95 * (len(values) - 1)))))
    return {
        "min": round(values[0], 2),
        "median": round(statistics.median(values), 2),
        "p95": round(values[p95_i], 2),
    }


@contextmanager
def _patch_guarded_aggregate(patched):
    original = release_database.GuardedCollection.aggregate
    release_database.GuardedCollection.aggregate = patched  # type: ignore[assignment]
    try:
        yield
    finally:
        release_database.GuardedCollection.aggregate = original  # type: ignore[assignment]


def test_iter51_disposable_benchmark_and_failure_contracts():
    mongo_url = _loopback_mongo_url()
    bench: dict[str, Any] = {"payload_variants": {}, "failure_contracts": {}}

    async def run_payload(payload_size: int) -> dict[str, Any]:
        probe = CommandProbe()
        db_name = f"iter51_{payload_size}_{uuid.uuid4().hex[:8]}"
        client = AsyncIOMotorClient(mongo_url, event_listeners=[probe])
        raw_db = client[db_name]

        try:
            seeded = await _seed_fixture(raw_db, payload_size)
            assert seeded["seeded_products"] >= 2832
            assert seeded["seeded_snapshots"] >= 101952

            idx_info = await raw_db.product_snapshots.index_information()
            names = sorted(idx_info.keys())
            assert {"_id_", "crawled_at_1", "sku_1_crawled_at_-1", "product_id_1", "store_id_1_crawled_at_-1"}.issubset(set(names))

            active = seeded["competitor_store_ids"]
            now = seeded["seed_now"]
            old_pipeline = _old_cohort_pipeline(active, now)
            new_pipeline = price_cohort.snapshot_pipeline(active, now)

            timings = {"old_compact": [], "new_pointer": []}
            reads = {"old_compact": [], "new_pointer": []}
            run_order = [("old_compact", old_pipeline), ("new_pointer", new_pipeline)]

            for i in range(3):
                order = run_order if i % 2 == 0 else list(reversed(run_order))
                for label, pipeline in order:
                    probe.reset()
                    t0 = time.perf_counter()
                    rows = await raw_db.product_snapshots.aggregate(pipeline, allowDiskUse=True).to_list(None)
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    timings[label].append(elapsed)
                    reads[label].append(probe.summary())
                    assert rows, f"{label} returned no rows"

            old_rows = await raw_db.product_snapshots.aggregate(old_pipeline, allowDiskUse=True).to_list(None)
            new_rows = await raw_db.product_snapshots.aggregate(new_pipeline, allowDiskUse=True).to_list(None)

            def keyify(r):
                return (r.get("store_id"), r.get("offer_id") or r.get("sku"))

            old_map = {keyify(r): {k: r.get(k) for k in [*price_cohort.FIELDS.keys(), "historical_max_price"]} for r in old_rows}
            new_map = {keyify(r): {k: r.get(k) for k in [*price_cohort.FIELDS.keys(), "historical_max_price"]} for r in new_rows}
            assert set(old_map.keys()) == set(new_map.keys())
            for k in old_map:
                assert old_map[k] == new_map[k]

            q = {"observation_version": 2, "is_synthetic": False}
            old_latest = await raw_db.product_snapshots.aggregate(_old_store_latest_pipeline(q), allowDiskUse=True).to_list(None)
            new_latest = await store_views.latest(raw_db)

            old_latest_map = {keyify(r): r for r in old_latest}
            new_latest_map = {keyify(r): r for r in new_latest}
            assert set(old_latest_map.keys()) == set(new_latest_map.keys())
            sample_key = next(iter(new_latest_map.keys()))
            assert "payload_blob" in new_latest_map[sample_key], "raw fields must be preserved in default latest()"
            assert any((r.get("offer_id") == "stale-offer") for r in new_latest), "stale default latest row must be present"

            async def _orders_none(_db, _start, _end):
                return None

            original_latest = store_views.latest

            async def full_history_latest(db, store_id=None, since=None):
                return await original_latest(db, store_id=store_id, since=None)

            store_views.latest = full_history_latest  # type: ignore[assignment]
            try:
                ranking_old = await store_views.ranking(raw_db, _orders_none)
            finally:
                store_views.latest = original_latest  # type: ignore[assignment]
            ranking_new = await store_views.ranking(raw_db, _orders_none)

            old_rank = {r["store_id"]: (r.get("products"), r.get("in_stock_pct"), r.get("rank")) for r in ranking_old["stores"]}
            new_rank = {r["store_id"]: (r.get("products"), r.get("in_stock_pct"), r.get("rank")) for r in ranking_new["stores"]}
            assert old_rank == new_rank

            # Explain snapshots for docs/keys/memory/spills.
            explain_old = await raw_db.command({
                "explain": {"aggregate": "product_snapshots", "pipeline": old_pipeline, "cursor": {}, "allowDiskUse": True},
                "verbosity": "executionStats",
            })
            explain_new = await raw_db.command({
                "explain": {"aggregate": "product_snapshots", "pipeline": new_pipeline, "cursor": {}, "allowDiskUse": True},
                "verbosity": "executionStats",
            })
            old_m: dict[str, Any] = {}
            new_m: dict[str, Any] = {}
            _walk_explain(explain_old, old_m)
            _walk_explain(explain_new, new_m)

            # basic proof that lookup uses _id path is visible in explain text.
            explain_new_text = json.dumps(explain_new, default=str)
            assert "_id_" in explain_new_text or '"_id"' in explain_new_text

            return {
                "seed": seeded,
                "index_names": names,
                "cohort_benchmark_ms": {
                    "old_compact": _stats(timings["old_compact"]),
                    "new_pointer": _stats(timings["new_pointer"]),
                },
                "cohort_read_counts": {
                    "old_compact": reads["old_compact"],
                    "new_pointer": reads["new_pointer"],
                },
                "parity": {
                    "cohort_key_count": len(new_map),
                    "store_latest_key_count": len(new_latest_map),
                    "ranking_store_count": len(new_rank),
                },
                "execution_stats": {
                    "old": {k: old_m.get(k) for k in ("totalDocsExamined", "totalKeysExamined", "executionTimeMillis", "usedDisk", "spills", "spilledBytes", "maxAccumulatorMemoryUsageBytes", "nReturned")},
                    "new": {k: new_m.get(k) for k in ("totalDocsExamined", "totalKeysExamined", "executionTimeMillis", "usedDisk", "spills", "spilledBytes", "maxAccumulatorMemoryUsageBytes", "nReturned")},
                },
            }
        finally:
            await client.drop_database(db_name)
            client.close()

    async def run_failures() -> dict[str, Any]:
        db_name = f"iter51_fail_{uuid.uuid4().hex[:8]}"
        seed_client = AsyncIOMotorClient(mongo_url)
        raw_db = seed_client[db_name]
        await _seed_fixture(raw_db, payload_size=256)

        guarded = release_database.GuardedDatabase(raw_db)
        original_db = server.db
        original_override = server.app.dependency_overrides.get(server.get_user)
        server.db = guarded
        server.app.dependency_overrides[server.get_user] = _fake_user

        async def call(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                resp = await ac.get(path, params=params or {})
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            return {"status": resp.status_code, "body": body}

        out: dict[str, Any] = {}

        original = release_database.GuardedCollection.aggregate

        def raise_timeout(self, pipeline, *args, **kwargs):
            if getattr(self.raw, "name", "") == "product_snapshots":
                raise ExecutionTimeout("iter51 synthetic timeout")
            return original(self, pipeline, *args, **kwargs)

        def raise_network(self, pipeline, *args, **kwargs):
            if getattr(self.raw, "name", "") == "product_snapshots":
                raise NetworkTimeout("iter51 synthetic network timeout")
            return original(self, pipeline, *args, **kwargs)

        # ExecutionTimeout
        with _patch_guarded_aggregate(raise_timeout):
            for path, params in [
                ("/api/my-products", {"days": 30, "limit": 5, "offset": 0}),
                ("/api/price-intel/dashboard", None),
                ("/api/price-intel/store-ranking", None),
                ("/api/market-share/overview", {"days": 30}),
                ("/api/insights/leaderboard", {"days": 30}),
                ("/api/insights/top-sellers", {"days": 30}),
            ]:
                r = await call(path, params)
                out[f"timeout::{path}"] = r
                assert r["status"] == 503
                detail = r["body"].get("detail", {})
                assert detail.get("retryable") is True
                assert detail.get("code") in {"price_query_timeout", "price_source_changed", "price_database_unavailable"}
                assert not (r["status"] == 200 and r["body"].get("total") in (0, None))

        # NetworkTimeout
        with _patch_guarded_aggregate(raise_network):
            r = await call("/api/my-products", {"days": 30, "limit": 5, "offset": 0})
            out["network_timeout::/api/my-products"] = r
            assert r["status"] == 503
            assert r["body"].get("detail", {}).get("retryable") is True

        # Missing lookup row must become price_source_changed (not silent drop).
        class MissingCursor:
            def __init__(self):
                self._done = False

            def batch_size(self, _n):
                return self

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._done:
                    raise StopAsyncIteration
                self._done = True
                return {snapshot_reads.MISSING: True}

            async def close(self):
                return None

        class FakeDB:
            class PS:
                @staticmethod
                def aggregate(*_args, **_kwargs):
                    return MissingCursor()

            product_snapshots = PS()

        with pytest.raises(HTTPException) as miss:
            await snapshot_reads.complete_latest(FakeDB(), [{"$match": {}}])
        assert miss.value.status_code == 503
        assert miss.value.detail.get("code") == "price_source_changed"

        # >200k cursor drain contract (no 200000 cap, all rows returned).
        class BigCursor:
            def __init__(self, n=200001):
                self.i = 0
                self.n = n

            def batch_size(self, _n):
                return self

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self.i >= self.n:
                    raise StopAsyncIteration
                self.i += 1
                return {"store_id": "s", "offer_id": f"o-{self.i}", "price": 1.0}

            async def close(self):
                return None

        class BigDB:
            class PS:
                @staticmethod
                def aggregate(*_args, **_kwargs):
                    return BigCursor()

            product_snapshots = PS()

        rows = await snapshot_reads.complete_latest(BigDB(), [{"$match": {}}])
        assert len(rows) == 200001
        assert len({r["offer_id"] for r in rows}) == 200001

        # Restore + cleanup
        server.db = original_db
        if original_override is None:
            server.app.dependency_overrides.pop(server.get_user, None)
        else:
            server.app.dependency_overrides[server.get_user] = original_override
        my_products_cache._loops.clear()
        await seed_client.drop_database(db_name)
        seed_client.close()
        return out

    async def scenario() -> None:
        bench["payload_variants"]["256B"] = await run_payload(256)
        bench["payload_variants"]["4KiB"] = await run_payload(4096)
        bench["failure_contracts"] = await run_failures()

    asyncio.run(scenario())
    BENCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    BENCH_PATH.write_text(json.dumps(bench, indent=2, default=str))


def test_iter51_preview_heavy_endpoints_smoke():
    url = base_url().rstrip("/")
    if "localhost" in url or "127.0.0.1" in url:
        pytest.skip("Preview URL not configured for external smoke")

    headers = auth_headers()
    checks = [
        ("/api/stores", {}),
        ("/api/insights/leaderboard", {"days": 30}),
        ("/api/price-intel/store-ranking", {}),
        ("/api/market-share/overview", {"days": 30}),
        ("/api/insights/top-sellers", {"days": 30}),
        ("/api/my-products", {"days": 14, "limit": 5, "offset": 0, "sort_by": "revenue_est", "sort_order": "desc"}),
        ("/api/my-products", {"days": 30, "limit": 5, "offset": 0, "sort_by": "revenue_est", "sort_order": "desc"}),
    ]

    out = {"base_url": url, "results": []}
    for path, params in checks:
        t0 = time.perf_counter()
        resp = requests.get(f"{url}{path}", headers=headers, params=params, timeout=180)
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        body = {}
        try:
            body = resp.json()
        except Exception:
            body = {"non_json": True, "text": resp.text[:200]}

        item = {
            "path": path,
            "params": params,
            "status": resp.status_code,
            "elapsed_ms": elapsed,
        }
        if isinstance(body, dict) and "detail" in body:
            item["detail"] = body["detail"]
        out["results"].append(item)

        assert resp.status_code == 200, f"{path} -> {resp.status_code}: {str(body)[:300]}"
        if path == "/api/my-products":
            assert isinstance(body.get("products"), list)
            assert isinstance(body.get("total"), int)

    SMOKE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SMOKE_PATH.write_text(json.dumps(out, indent=2, default=str))
