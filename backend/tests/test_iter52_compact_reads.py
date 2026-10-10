"""iter52 — compact read-path regression verification after iter51 rollback.

Modules/features covered:
- snapshot_reads.latest_pipeline + complete_latest bounded-drain behavior
- price_cohort.snapshot_pipeline parity/perf guard (prechange vs revised)
- store_views latest/ranking/profile/market_summary integration contracts
- market_share latest snapshot compact projection benchmark

Scope:
- Disposable UUID Mongo loopback only; no production writes/index/deploy.
- Preserve iter51 artifacts by writing new iter52 report paths only.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from bson import BSON
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ExecutionTimeout

import comparison_views
import market_share
import my_products_cache
import price_cohort
import release_database
import server
import snapshot_reads
import store_views
from _auth import auth_headers, base_url
from test_iter51_readpath_optimization import CommandProbe, _loopback_mongo_url, _seed_fixture, _walk_explain
from test_p0_my_products_baseline import _fake_user


BENCH_PATH = Path("/app/test_reports/iter52_readpath_benchmark.json")
SMOKE_PATH = Path("/app/test_reports/iter52_preview_smoke.json")


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"min": 0.0, "median": 0.0, "max": 0.0}
    return {
        "min": round(ordered[0], 2),
        "median": round(statistics.median(ordered), 2),
        "max": round(ordered[-1], 2),
    }


def _within_20pct(old_median: float, new_median: float) -> bool:
    if old_median <= 0:
        return True
    return new_median <= (old_median * 1.2)


def _estimate_rows_bytes(rows: list[dict[str, Any]]) -> int:
    return len(json.dumps(rows, default=str, ensure_ascii=False).encode("utf-8"))


def _old_store_latest_offerid_pipeline(query: dict[str, Any]) -> list[dict[str, Any]]:
    # Correct old reference for iter52: group key is offer_id (no ifNull fallback).
    return [
        {"$match": query},
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": "$offer_id", "latest": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$latest"}},
        {"$project": {"_id": 0}},
    ]


def _reference_cohort_pipeline(active: list[str], now: datetime) -> list[dict[str, Any]]:
    # Exact pre-late-materialization compact P0 reference: match/sort/project/group/history.
    return [
        {"$match": {"store_id": {"$in": active}, "crawled_at": {"$gte": now - timedelta(days=180)}}},
        {"$sort": {"crawled_at": -1}},
        {"$project": price_cohort.FIELDS},
        {
            "$group": {
                "_id": {"$ifNull": ["$offer_id", {"store": "$store_id", "sku": "$sku"}]},
                "latest": {"$first": "$$ROOT"},
                "history_oldest_at": {"$min": "$crawled_at"},
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
        {
            "$replaceRoot": {
                "newRoot": {
                    "$mergeObjects": [
                        "$latest",
                        {"historical_max_price": "$historical_max", "history_oldest_at": "$history_oldest_at"},
                    ]
                }
            }
        },
        {"$project": {**price_cohort.FIELDS, "historical_max_price": 1, "history_oldest_at": 1}},
    ]


def _reference_marketshare_postgroup_pipeline(active, since):
    # Exact pre-change ACTIVE function, not the unrelated _retired_* adapter.
    return [
        {"$match": {"store_id": {"$in": active}, "crawled_at": {"$gte": since}, "offer_id": {"$type": "string"}}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": "$offer_id", "row": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$row"}}, {"$project": price_cohort.FIELDS},
    ]


class _CountingGuardedDatabase(release_database.GuardedDatabase):
    def __init__(self, raw):
        super().__init__(raw)
        self.write_attempted = 0
        self.write_actual = 0

    async def perform(self, collection, method, operation, *args, **kwargs):
        self.write_attempted += 1
        out = await super().perform(collection, method, operation, *args, **kwargs)
        self.write_actual += 1
        return out


def test_iter52_compact_reads_benchmark_and_contracts():
    mongo_url = _loopback_mongo_url()
    bench: dict[str, Any] = {
        "scope": "iter52 compact read-path verification",
        "notes": {
            "transport": "MOCKED only for >200k complete_latest drain contract",
            "lookup_id_claim": "not_applicable_lookup_removed",
        },
        "payload_variants": {},
    }

    async def run_payload(payload_size: int) -> dict[str, Any]:
        probe = CommandProbe()
        db_name = f"iter52_{payload_size}_{uuid.uuid4().hex[:8]}"
        client = AsyncIOMotorClient(mongo_url, event_listeners=[probe])
        raw_db = client[db_name]

        try:
            seeded = await _seed_fixture(raw_db, payload_size)
            active = seeded["competitor_store_ids"]
            seed_now = seeded["seed_now"]

            # Frozen prechange reference deliberately retains the old historical
            # predicate. The ONLY allowed change excludes fabricated history;
            # do not restore synthetic/demo prices merely to match that reference.
            ref_pipeline = _reference_cohort_pipeline(active, seed_now)
            revised_pipeline = price_cohort.snapshot_pipeline(active, seed_now)
            expected_pipeline = deepcopy(ref_pipeline)
            expected_pipeline[3]["$group"]["historical_max"]["$max"]["$cond"][0]["$and"].extend([
                {"$not": [{"$ifNull": ["$is_synthetic", False]}]},
                {"$ne": [{"$ifNull": ["$data_origin", ""]}, "demo_seed"]},
            ])
            assert revised_pipeline == expected_pipeline, "Unexpected cohort drift beyond synthetic-history exclusion"

            cohort_timings = {"reference": [], "revised": []}
            cohort_reads = {"reference": [], "revised": []}
            run_order = [("reference", ref_pipeline), ("revised", revised_pipeline)]

            for i in range(3):
                order = run_order if i % 2 == 0 else list(reversed(run_order))
                for label, pipeline in order:
                    probe.reset()
                    t0 = time.perf_counter()
                    rows = await raw_db.product_snapshots.aggregate(pipeline, allowDiskUse=True).to_list(None)
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    assert rows, f"{label} cohort returned no rows"
                    cohort_timings[label].append(elapsed)
                    cohort_reads[label].append(probe.summary())

            reference_rows = await raw_db.product_snapshots.aggregate(ref_pipeline, allowDiskUse=True).to_list(None)
            revised_rows = await raw_db.product_snapshots.aggregate(revised_pipeline, allowDiskUse=True).to_list(None)

            keyify = lambda r: (r.get("store_id"), r.get("offer_id") or r.get("sku"))
            ref_map = {keyify(r): r for r in reference_rows}
            new_map = {keyify(r): r for r in revised_rows}
            assert set(ref_map.keys()) == set(new_map.keys())
            for k in ref_map:
                assert ref_map[k].get("historical_max_price") == new_map[k].get("historical_max_price")
                assert ref_map[k].get("history_oldest_at") == new_map[k].get("history_oldest_at")

            cohort_stats_ref = _stats(cohort_timings["reference"])
            cohort_stats_new = _stats(cohort_timings["revised"])
            assert _within_20pct(cohort_stats_ref["median"], cohort_stats_new["median"]), (
                f"Cohort median regressed >20%: ref={cohort_stats_ref['median']} new={cohort_stats_new['median']}"
            )

            # -------- Store latest full payload vs compact projections --------
            query = {"observation_version": 2, "is_synthetic": False}
            old_full_pipeline = _old_store_latest_offerid_pipeline(query)
            compact_leaderboard_pipeline = snapshot_reads.latest_pipeline(query, {"store_id": 1, "comparable": 1})
            compact_rank_pipeline = snapshot_reads.latest_pipeline(
                {**query, "crawled_at": {"$gte": seed_now - timedelta(days=7)}},
                price_cohort.FIELDS,
            )

            latest_timings = {"full": [], "leaderboard_compact": [], "rank7d_compact": []}
            latest_metrics: dict[str, dict[str, Any]] = {}

            for i in range(3):
                order = [
                    ("full", old_full_pipeline),
                    ("leaderboard_compact", compact_leaderboard_pipeline),
                    ("rank7d_compact", compact_rank_pipeline),
                ]
                if i % 2:
                    order = list(reversed(order))
                for label, pipeline in order:
                    probe.reset()
                    t0 = time.perf_counter()
                    rows = await raw_db.product_snapshots.aggregate(pipeline, allowDiskUse=True).to_list(None)
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    latest_timings[label].append(elapsed)
                    latest_metrics[label] = {
                        "rows": len(rows),
                        "bytes": _estimate_rows_bytes(rows),
                        "reads": probe.summary(),
                    }
                    assert all("_id" not in r for r in rows)

            full_map = {
                (r.get("store_id"), r.get("offer_id")): r
                for r in await raw_db.product_snapshots.aggregate(old_full_pipeline, allowDiskUse=True).to_list(None)
            }
            compact_rank_rows = await raw_db.product_snapshots.aggregate(compact_rank_pipeline, allowDiskUse=True).to_list(None)
            for r in compact_rank_rows[:200]:
                key = (r.get("store_id"), r.get("offer_id"))
                if key in full_map:
                    assert full_map[key].get("price") == r.get("price")

            full_stats = _stats(latest_timings["full"])
            leader_stats = _stats(latest_timings["leaderboard_compact"])
            rank_stats = _stats(latest_timings["rank7d_compact"])
            assert _within_20pct(full_stats["median"], leader_stats["median"]), (
                f"leaderboard compact median regressed >20% vs full: {leader_stats['median']} > {full_stats['median']}"
            )
            assert _within_20pct(full_stats["median"], rank_stats["median"]), (
                f"rank compact median regressed >20% vs full: {rank_stats['median']} > {full_stats['median']}"
            )

            # Market Share restored to the identical old shape after rejection.
            since = seed_now - timedelta(days=30)
            active_all = await raw_db.stores.distinct("id", {"is_active": {"$ne": False}})
            old_market_pipeline = _reference_marketshare_postgroup_pipeline(active_all, since)
            new_market_pipeline = market_share._latest_snapshot_pipeline(active_all, since)
            assert new_market_pipeline == old_market_pipeline
            assert BSON.encode({"pipeline": new_market_pipeline}) == BSON.encode({"pipeline": old_market_pipeline})

            market_times = {"old_postgroup": [], "revised_postgroup": []}
            market_rows_bytes: dict[str, dict[str, Any]] = {}
            for i in range(3):
                order = [
                    ("old_postgroup", old_market_pipeline),
                    ("revised_postgroup", new_market_pipeline),
                ]
                if i % 2:
                    order = list(reversed(order))
                for label, pipeline in order:
                    probe.reset()
                    t0 = time.perf_counter()
                    rows = await raw_db.product_snapshots.aggregate(pipeline, allowDiskUse=True).to_list(None)
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    market_times[label].append(elapsed)
                    market_rows_bytes[label] = {
                        "rows": len(rows),
                        "bytes": _estimate_rows_bytes(rows),
                        "reads": probe.summary(),
                    }
                    assert rows

            old_market_stats = _stats(market_times["old_postgroup"])
            new_market_stats = _stats(market_times["revised_postgroup"])
            # This is now an A/A timing control, NOT an optimization comparison.
            # Keep the measured variability visible; identical command bytes
            # cannot establish a code-induced regression or speedup. Changed
            # leader/ranking/cohort comparisons retain their existing guards.
            market_timing_control_stable = _within_20pct(old_market_stats["median"], new_market_stats["median"])

            explain_old = await raw_db.command({
                "explain": {"aggregate": "product_snapshots", "pipeline": old_market_pipeline, "cursor": {}, "allowDiskUse": True},
                "verbosity": "executionStats",
            })
            explain_new = await raw_db.command({
                "explain": {"aggregate": "product_snapshots", "pipeline": new_market_pipeline, "cursor": {}, "allowDiskUse": True},
                "verbosity": "executionStats",
            })
            old_exec, new_exec = {}, {}
            _walk_explain(explain_old, old_exec)
            _walk_explain(explain_new, new_exec)

            # -------- ASGI integration + contracts --------
            guarded = _CountingGuardedDatabase(raw_db)
            original_db = server.db
            original_override = server.app.dependency_overrides.get(server.get_user)
            server.db = guarded
            server.app.dependency_overrides[server.get_user] = _fake_user

            async def _orders_none(_db, _start, _end):
                return None

            try:
                # full latest keeps stale rows (220d fixture)
                latest_default = await store_views.latest(raw_db)
                assert any(r.get("offer_id") == "stale-offer" for r in latest_default)

                # ranking with 7d projection still returns stores/products metrics
                ranking = await store_views.ranking(raw_db, _orders_none)
                assert ranking.get("stores") and isinstance(ranking["stores"], list)
                assert all("products" in s for s in ranking["stores"]) 

                # profile returns catalog-size semantics from full latest() scope.
                # own-store profile may be zero here (fixture seeds competitor snapshots only),
                # so validate using a seeded competitor store with known observations.
                own_profile = await store_views.profile(raw_db, seeded["own_store_id"], _orders_none)
                comp_profile = await store_views.profile(raw_db, seeded["competitor_store_ids"][0], _orders_none)
                assert own_profile["kpis"].get("catalog_size", 0) >= 0
                assert comp_profile["kpis"].get("catalog_size", 0) > 0

                # market summary must call context once and summarize_positions once.
                calls = {"context": 0, "summarize": 0}
                original_context = comparison_views.context
                original_summarize = comparison_views.summarize_positions

                async def counted_context(*args, **kwargs):
                    calls["context"] += 1
                    return await original_context(*args, **kwargs)

                def counted_summarize(*args, **kwargs):
                    calls["summarize"] += 1
                    return original_summarize(*args, **kwargs)

                comparison_views.context = counted_context  # type: ignore[assignment]
                comparison_views.summarize_positions = counted_summarize  # type: ignore[assignment]
                try:
                    ms = await store_views.market_summary(raw_db, 30, server._effective_own_price)
                finally:
                    comparison_views.context = original_context  # type: ignore[assignment]
                    comparison_views.summarize_positions = original_summarize  # type: ignore[assignment]

                own, products, cohorts = await original_context(raw_db, server._effective_own_price)
                expected_pos = original_summarize(own, products, cohorts, server._effective_own_price)
                assert calls == {"context": 1, "summarize": 1}
                assert ms.get("market_position_summary") == expected_pos

                # Cold/warm my-products via ASGI with large fixture.
                transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
                timings = {"my_products_cold_ms": None, "my_products_warm_ms": None,
                           "store_ranking_ms": None, "leaderboard_ms": None}
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                    t0 = time.perf_counter()
                    cold = await ac.get("/api/my-products", params={"days": 30, "limit": 25, "offset": 0})
                    timings["my_products_cold_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                    assert cold.status_code == 200
                    cold_body = cold.json()
                    assert isinstance(cold_body.get("products"), list) and cold_body.get("products")

                    t1 = time.perf_counter()
                    warm = await ac.get("/api/my-products", params={"days": 30, "limit": 25, "offset": 0})
                    timings["my_products_warm_ms"] = round((time.perf_counter() - t1) * 1000.0, 2)
                    assert warm.status_code == 200

                    t2 = time.perf_counter()
                    rank_resp = await ac.get("/api/price-intel/store-ranking")
                    timings["store_ranking_ms"] = round((time.perf_counter() - t2) * 1000.0, 2)
                    assert rank_resp.status_code == 200

                    t3 = time.perf_counter()
                    lead_resp = await ac.get("/api/insights/leaderboard", params={"days": 30})
                    timings["leaderboard_ms"] = round((time.perf_counter() - t3) * 1000.0, 2)
                    assert lead_resp.status_code == 200

                # explicit timeout 503 contract (initial aggregate path)
                original_aggregate = release_database.GuardedCollection.aggregate

                def raise_timeout(self, pipeline, *args, **kwargs):
                    if getattr(self.raw, "name", "") == "product_snapshots":
                        raise ExecutionTimeout("iter52 synthetic timeout")
                    return original_aggregate(self, pipeline, *args, **kwargs)

                release_database.GuardedCollection.aggregate = raise_timeout  # type: ignore[assignment]
                try:
                    my_products_cache._loops.clear()
                    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
                    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                        fail = await ac.get("/api/my-products", params={"days": 14, "limit": 7, "offset": 3})
                    assert fail.status_code == 503
                    detail = fail.json().get("detail", {})
                    assert detail.get("retryable") is True
                finally:
                    release_database.GuardedCollection.aggregate = original_aggregate  # type: ignore[assignment]

            finally:
                server.db = original_db
                if original_override is None:
                    server.app.dependency_overrides.pop(server.get_user, None)
                else:
                    server.app.dependency_overrides[server.get_user] = original_override

            # >200000 complete cursor contract with MOCKED transport only.
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

            huge = await snapshot_reads.complete_latest(BigDB(), [{"$match": {}}])
            assert len(huge) == 200001

            assert guarded.write_attempted == guarded.write_actual == 0
            return {
                "seed": seeded,
                "cohort": {
                    "reference_ms": cohort_stats_ref,
                    "revised_ms": cohort_stats_new,
                    "read_counts": cohort_reads,
                },
                "latest_bench": {
                    "full_ms": full_stats,
                    "leaderboard_compact_ms": leader_stats,
                    "rank7d_compact_ms": rank_stats,
                    "metrics": latest_metrics,
                },
                "market_share_bench": {
                    "query_bytes_identical": True,
                    "timing_control_within_20pct": market_timing_control_stable,
                    "interpretation": "A/A control only; no Market Share query speedup claim",
                    "old_ms": old_market_stats,
                    "new_ms": new_market_stats,
                    "rows_bytes": market_rows_bytes,
                    "execution_stats": {
                        "old": {k: old_exec.get(k) for k in ("totalDocsExamined", "totalKeysExamined", "executionTimeMillis", "usedDisk", "spills", "spilledBytes", "maxAccumulatorMemoryUsageBytes", "nReturned")},
                        "new": {k: new_exec.get(k) for k in ("totalDocsExamined", "totalKeysExamined", "executionTimeMillis", "usedDisk", "spills", "spilledBytes", "maxAccumulatorMemoryUsageBytes", "nReturned")},
                    },
                },
                "asgi_large_fixture": timings,
                "observer_writes": {"attempted": guarded.write_attempted, "actual": guarded.write_actual},
                "contracts": {
                    "timeout_503": True,
                    "no_200k_cap": len(huge),
                    "mocked_transport": True,
                },
            }
        finally:
            await client.drop_database(db_name)
            client.close()

    async def scenario():
        bench["payload_variants"]["256B"] = await run_payload(256)
        bench["payload_variants"]["4KiB"] = await run_payload(4096)

    asyncio.run(scenario())
    BENCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    BENCH_PATH.write_text(json.dumps(bench, indent=2, default=str))


def test_iter52_preview_heavy_endpoints_smoke():
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
        try:
            body = resp.json()
        except Exception:
            body = {"non_json": True, "text": resp.text[:250]}

        item = {"path": path, "params": params, "status": resp.status_code, "elapsed_ms": elapsed}
        if isinstance(body, dict) and "detail" in body:
            item["detail"] = body["detail"]
        out["results"].append(item)

        assert resp.status_code == 200, f"{path} -> {resp.status_code}: {str(body)[:350]}"
        if path == "/api/my-products":
            assert isinstance(body.get("products"), list)
            assert body.get("products") is not None

    SMOKE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SMOKE_PATH.write_text(json.dumps(out, indent=2, default=str))
