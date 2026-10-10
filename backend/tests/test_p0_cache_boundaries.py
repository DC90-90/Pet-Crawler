"""Targeted P0 temporal/cache boundary coverage (backend-only, no app edits).

Scope added for previously-untested criteria only:
- exact 7-day freshness crossing while cache age < 300s
- own stock precedence for quantity_observed_at and future(+5m) eligibility
- 180-day history window impact on outlier escape decision
- revision bump invalidates warm memory cache
- malformed/future cache docs and key-family separation
- failure is not cached; immediate retry succeeds without manual _loops clear
- benchmark slices with per-scenario read counts and maxTimeMS validation
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import monitoring
from pymongo.errors import ExecutionTimeout, NetworkTimeout, OperationFailure

import catalog_views
import comparison_views
import my_products_cache
import price_cohort
import release_database
import server
import stock_evidence
from _auth import base_url
from release_control import state as release_state
from test_p0_my_products_baseline import BASE_QUERY, _fake_user, _loopback_mongo_url, _seed_baseline


RESULTS_PATH = Path("/app/test_reports/p0_my_products/cache_boundaries_results.json")
BENCH_PATH = Path("/app/test_reports/p0_my_products/cache_boundaries_benchmarks.json")


class CommandProbe(monitoring.CommandListener):
    """Per-request read-command counters/durations (includes getMore)."""

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
        by = {k: {"count": 0, "duration_ms": 0.0} for k in self.READS}
        for ev in self.events:
            by[ev["name"]]["count"] += 1
            by[ev["name"]]["duration_ms"] += ev.get("duration_ms", 0.0)
        return {
            "by_command": by,
            "total_read_commands": sum(v["count"] for v in by.values()),
            "events": list(self.events),
        }


class CountingGuardedDatabase(release_database.GuardedDatabase):
    """Read-only observer should never perform writes from request path."""

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


def make_gtin13(payload12: str) -> str:
    assert len(payload12) == 12
    return payload12 + _compute_check_digit(payload12)


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
            "maxAccumulatorMemoryUsageBytes",
        ):
            if key in node and key not in out:
                out[key] = node[key]
        for value in node.values():
            _walk_explain(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_explain(value, out)


@pytest.fixture(scope="module")
def boundary_env():
    """Disposable loopback-only dataset and ASGI wiring for deterministic cache tests."""

    mongo_url = _loopback_mongo_url()
    db_name = f"p0_cache_boundaries_{uuid.uuid4().hex[:10]}"

    async def setup():
        seed_client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
        raw_db = seed_client[db_name]

        cmd_probe = CommandProbe()
        measured_client = AsyncIOMotorClient(
            mongo_url,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            socketTimeoutMS=45000,
            event_listeners=[cmd_probe],
        )

        seeded = await _seed_baseline(raw_db)
        guarded = CountingGuardedDatabase(measured_client[db_name])
        return {
            "seed_client": seed_client,
            "measured_client": measured_client,
            "raw_db": raw_db,
            "guarded": guarded,
            "seeded": seeded,
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


def _parse_dt(v: str | datetime | None) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, initial: datetime) -> dict[str, datetime]:
    """Coherent frozen clock across cache + cohort + server + catalog + stock modules."""

    state = {"now": initial}

    class FrozenMeta(type):
        def __instancecheck__(cls, value):
            # Mongo returns base datetime values, not instances of this subclass.
            return isinstance(value, datetime)

    class FrozenDatetime(datetime, metaclass=FrozenMeta):
        @classmethod
        def now(cls, tz=None):
            base = state["now"]
            if tz is None:
                return base.replace(tzinfo=None)
            return base.astimezone(tz)

        @classmethod
        def utcnow(cls):
            return state["now"].astimezone(timezone.utc).replace(tzinfo=None)

    for module in (price_cohort, server, catalog_views, stock_evidence):
        monkeypatch.setattr(module, "datetime", FrozenDatetime, raising=True)
    monkeypatch.setattr(my_products_cache, "utcnow", lambda: state["now"], raising=True)
    return state


@pytest.mark.parametrize("boundary", ["own_price", "competitor", "quantity", "future", "history"])
def test_endpoint_warm_cache_crosses_domain_boundary(boundary_env, monkeypatch, boundary):
    """A cached real API result must change at its domain boundary, not after TTL."""
    async def run():
        raw = boundary_env["raw_db"]
        anchor = datetime.now(timezone.utc).replace(microsecond=0)
        clock = _freeze_clock(monkeypatch, anchor)
        sku, barcode = "ZZ-P0-TIME", make_gtin13("723456789012")
        edge = anchor-timedelta(days=7)+timedelta(seconds=120)
        own = {"sku": sku, "barcode": barcode, "name_en": "Temporal Product", "price": 100,
               "currency": "SAR", "price_basis": "storefront_inc_vat", "quantity": 8,
               "in_stock": True, "present_on_store": True,
               "last_synced_at": edge if boundary == "own_price" else anchor,
               "quantity_observed_at": edge if boundary == "quantity" else anchor}
        stamp = edge if boundary == "competitor" else anchor+timedelta(minutes=6) if boundary == "future" else anchor
        snap = {"store_id": "comp-01", "store_name": "Boundary", "sku": sku, "barcode": barcode,
                "offer_id": "time-offer", "name_en": "Temporal Product", "price": 19 if boundary == "history" else 40,
                "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True,
                "qty_available": 4, "present_on_store": True, "observation_version": 2,
                "confidence_score": 99, "comparable": True, "crawled_at": stamp}
        snapshots = [snap]
        if boundary == "history":
            snapshots += [{**snap, "price": 90, "crawled_at": anchor-timedelta(days=180)+timedelta(seconds=120)},
                          {**snap, "store_id": "comp-02", "offer_id": "time-reference", "price": 100}]
        await raw.my_products.insert_one(dict(own))
        await raw.product_snapshots.insert_many([dict(r) for r in snapshots])
        my_products_cache._loops.clear()
        params = {**BASE_QUERY, "sort_by": "sku", "sort_order": "desc"}
        writes = boundary_env["guarded"].write_attempted
        try:
            cold = await _call_my_products(params)
            assert cold["status"] == 200, cold["body"]
            row = next(r for r in cold["body"]["products"] if r["sku"] == sku)
            assert row["price"] == 100 and row["quantity"] == 8
            assert row["competitor_min_price"] == (None if boundary == "future" else 19 if boundary == "history" else 40)
            seconds = 60 if boundary == "future" else 120
            assert _parse_dt(cold["body"]["cache"]["valid_until"]) == anchor+timedelta(seconds=seconds)
            clock["now"] = anchor+timedelta(seconds=seconds-1)
            warm = await _call_my_products(params)
            assert warm["status"] == 200 and warm["body"]["cache"]["source"] == "memory_cache"
            assert warm["body"]["products"] == cold["body"]["products"]
            # 180-day range is inclusive; just past it makes the history expire.
            clock["now"] = anchor+timedelta(seconds=seconds, milliseconds=1 if boundary == "history" else 0)
            refreshed = await _call_my_products(params)
            assert refreshed["status"] == 200, refreshed["body"]
            assert refreshed["body"]["cache"]["source"] == "live_fallback"
            row = next(r for r in refreshed["body"]["products"] if r["sku"] == sku)
            assert row["price"] == (None if boundary == "own_price" else 100)
            assert row["quantity"] == (None if boundary == "quantity" else 8)
            assert row["competitor_min_price"] == (None if boundary == "competitor" else 100 if boundary == "history" else 40)
            assert boundary_env["guarded"].write_attempted == writes
            _record_result("endpoint_boundary_"+boundary, {"before": cold["status"], "warm": warm["body"]["cache"]["source"],
                           "after": refreshed["status"], "boundary_seconds": seconds, "price": row["price"],
                           "quantity": row["quantity"], "competitor_min_price": row["competitor_min_price"]})
        finally:
            await raw.my_products.delete_one({"sku": sku})
            await raw.product_snapshots.delete_many({"offer_id": {"$in": ["time-offer", "time-reference"]}})
            my_products_cache._loops.clear()
    boundary_env["loop"].run_until_complete(run())


async def _call_my_products(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = dict(BASE_QUERY if params is None else params)
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        t0 = time.perf_counter()
        resp = await ac.get("/api/my-products", params=params)
        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"non_json": True}
    return {"status": resp.status_code, "elapsed_ms": elapsed, "body": body}


async def _call_with_probe(env, params: dict[str, Any] | None = None) -> dict[str, Any]:
    probe: CommandProbe = env["cmd_probe"]
    probe.reset()
    resp = await _call_my_products(params)
    return {**resp, "reads": probe.summary()}


@contextmanager
def _patch_guarded_aggregate(patched):
    original = release_database.GuardedCollection.aggregate
    release_database.GuardedCollection.aggregate = patched  # type: ignore[assignment]
    try:
        yield
    finally:
        release_database.GuardedCollection.aggregate = original  # type: ignore[assignment]


def _record_result(section: str, payload: dict[str, Any]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    data[section] = payload
    RESULTS_PATH.write_text(json.dumps(data, indent=2, default=str))


def test_01_exact_7d_transition_invalidates_cache_under_300s(boundary_env, monkeypatch):
    """Freshness deadline crossing (own+competitor @ 7d) must invalidate warm cache before 300s TTL."""

    async def run() -> dict[str, Any]:
        raw_db = boundary_env["raw_db"]
        anchor = datetime.now(timezone.utc)
        edge = anchor - timedelta(days=7) + timedelta(seconds=120)
        barcode = make_gtin13("823456789012")

        await raw_db.my_products.update_one(
            {"sku": "SKU-EDGE-7D"},
            {
                "$set": {
                    "sku": "SKU-EDGE-7D",
                    "barcode": barcode,
                    "name_ar": "حد 7 ايام",
                    "name_en": "Boundary 7d",
                    "price": 88.0,
                    "sale_price": None,
                    "currency": "SAR",
                    "price_basis": "storefront_inc_vat",
                    "in_stock": True,
                    "quantity": 7,
                    "present_on_store": True,
                    "last_synced_at": (anchor - timedelta(minutes=15)).isoformat(),
                    "quantity_observed_at": edge.isoformat(),
                }
            },
            upsert=True,
        )
        await raw_db.product_snapshots.delete_many({"offer_id": {"$in": ["edge7-offer-a", "edge7-offer-b"]}})
        await raw_db.product_snapshots.insert_many([
            {
                "id": "edge7-a",
                "product_id": "edge7-a",
                "store_id": "comp-01",
                "store_name": "Store comp-01",
                "sku": "EDGE7-A",
                "offer_id": "edge7-offer-a",
                "barcode": barcode,
                "name_ar": "A",
                "name_en": "A",
                "price": 99.0,
                "currency": "SAR",
                "price_basis": "storefront_inc_vat",
                "in_stock": True,
                "qty_available": 5,
                "crawled_at": edge,
                "observation_version": 2,
                "confidence_score": 97,
                "comparable": True,
                "is_synthetic": False,
                "present_on_store": True,
                "variant_skus": ["EDGE7-A"],
                "variant_barcodes": [barcode],
            },
            {
                "id": "edge7-b",
                "product_id": "edge7-b",
                "store_id": "comp-02",
                "store_name": "Store comp-02",
                "sku": "EDGE7-B",
                "offer_id": "edge7-offer-b",
                "barcode": barcode,
                "name_ar": "B",
                "name_en": "B",
                "price": 101.0,
                "currency": "SAR",
                "price_basis": "storefront_inc_vat",
                "in_stock": True,
                "qty_available": 3,
                "crawled_at": edge,
                "observation_version": 2,
                "confidence_score": 97,
                "comparable": True,
                "is_synthetic": False,
                "present_on_store": True,
                "variant_skus": ["EDGE7-B"],
                "variant_barcodes": [barcode],
            },
        ])

        try:
            own_row = await raw_db.my_products.find_one({"sku": "SKU-EDGE-7D"}, {"_id": 0})
            assert own_row is not None
            cohort = (await price_cohort.build_cohorts(
                boundary_env["guarded"],
                [own_row],
                "own-store-p0",
                lambda r: float(r.get("sale_price") or r.get("price") or 0),
                now=anchor,
                competitor_store_ids=["comp-01", "comp-02"],
            ))["SKU-EDGE-7D"]

            valid_until = _parse_dt(cohort.get("valid_until"))
            assert valid_until is not None
            assert abs((valid_until - (anchor + timedelta(seconds=120))).total_seconds()) <= 3

            cache_doc = {
                "cache_schema": my_products_cache.SCHEMA,
                "source_revision": 1,
                "computed_at": anchor,
                "valid_until": valid_until,
                "dataset": {
                    "rows": [{"sku": "SKU-EDGE-7D"}],
                    "total": 1,
                    "kpis": {"total_products": 1},
                    "categories": [],
                },
            }

            assert my_products_cache.valid(cache_doc, source_revision=1, max_age=300, now=anchor + timedelta(seconds=119))
            assert not my_products_cache.valid(cache_doc, source_revision=1, max_age=300, now=anchor + timedelta(seconds=121))

            return {
                "derived_valid_until": valid_until.isoformat(),
                "valid_at_119s": True,
                "valid_at_121s": False,
            }
        finally:
            await raw_db.my_products.delete_one({"sku": "SKU-EDGE-7D"})
            await raw_db.product_snapshots.delete_many({"offer_id": {"$in": ["edge7-offer-a", "edge7-offer-b"]}})

    out = boundary_env["loop"].run_until_complete(run())
    _record_result("exact_7d_transition", out)


def test_02_quantity_observed_at_precedence_and_future_threshold(monkeypatch):
    """own_stock must use quantity_observed_at independently from last_synced_at."""

    anchor = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
    clock = _freeze_clock(monkeypatch, anchor)

    stale_qty = {
        "quantity": 8,
        "in_stock": True,
        "quantity_observed_at": (anchor - timedelta(days=8)).isoformat(),
        "last_synced_at": anchor.isoformat(),
    }
    stale = stock_evidence.own_stock(stale_qty)
    assert stale["stock_unavailable_reason"] == "stale_or_unknown_observation"
    assert stale["quantity"] is None

    future_qty = {
        "quantity": 5,
        "in_stock": True,
        "quantity_observed_at": (anchor + timedelta(minutes=6)).isoformat(),
        "last_synced_at": (anchor - timedelta(days=1)).isoformat(),
    }
    too_future = stock_evidence.own_stock(future_qty)
    assert too_future["stock_unavailable_reason"] == "stale_or_unknown_observation"

    clock["now"] = anchor + timedelta(minutes=2, seconds=1)
    eligible = stock_evidence.own_stock(future_qty)
    assert eligible["stock_unavailable_reason"] is None
    assert eligible["quantity"] == 5
    assert _parse_dt(eligible["stock_observed_at"]) == _parse_dt(future_qty["quantity_observed_at"])


def test_03_my_products_uses_quantity_observed_at_field(boundary_env, monkeypatch):
    """API row stock_observed_at should track quantity_observed_at (not last_synced_at)."""

    async def run() -> dict[str, Any]:
        raw_db = boundary_env["raw_db"]
        anchor = datetime.now(timezone.utc)
        q_obs = anchor - timedelta(hours=2)
        l_sync = anchor - timedelta(minutes=5)
        await raw_db.my_products.update_one(
            {"sku": "SKU-MANUAL"},
            {"$set": {"quantity_observed_at": q_obs.isoformat(), "last_synced_at": l_sync.isoformat(), "quantity": 12, "in_stock": True}},
        )

        my_products_cache._loops.clear()
        resp = await _call_my_products({**BASE_QUERY, "search": "SKU-MANUAL"})
        assert resp["status"] == 200, resp["body"]
        products = resp["body"].get("products") or []
        row = next((p for p in products if p.get("sku") == "SKU-MANUAL"), None)
        assert row is not None
        assert _parse_dt(row.get("stock_observed_at")) == q_obs
        assert _parse_dt(row.get("stock_observed_at")) != l_sync
        return {
            "sku": "SKU-MANUAL",
            "stock_observed_at": row.get("stock_observed_at"),
            "last_synced_at": row.get("last_synced_at"),
        }

    out = boundary_env["loop"].run_until_complete(run())
    _record_result("quantity_observed_precedence_api", out)


def test_04_180d_history_window_changes_outlier_escape(boundary_env):
    """Crossing 180d history boundary should change discount escape decision only."""

    async def run() -> dict[str, Any]:
        raw_db = boundary_env["raw_db"]
        anchor = boundary_env["seeded"]["seed_now"] + timedelta(days=20)
        barcode = make_gtin13("923456789012")

        await raw_db.my_products.update_one(
            {"sku": "SKU-HIST-BOUND"},
            {
                "$set": {
                    "sku": "SKU-HIST-BOUND",
                    "barcode": barcode,
                    "name_ar": "حد تاريخ 180",
                    "name_en": "History Boundary 180",
                    "price": 100.0,
                    "sale_price": None,
                    "currency": "SAR",
                    "price_basis": "storefront_inc_vat",
                    "in_stock": True,
                    "quantity": 11,
                    "present_on_store": True,
                    "last_synced_at": (anchor - timedelta(hours=1)).isoformat(),
                    "quantity_observed_at": (anchor - timedelta(hours=1)).isoformat(),
                }
            },
            upsert=True,
        )

        await raw_db.product_snapshots.delete_many({"offer_id": {"$in": ["hist-offer-a", "hist-offer-b"]}})
        await raw_db.product_snapshots.insert_many([
            {
                "id": "hist-a-new",
                "product_id": "hist-a-new",
                "store_id": "comp-03",
                "store_name": "Store comp-03",
                "sku": "COMP-HIST-A",
                "offer_id": "hist-offer-a",
                "barcode": barcode,
                "name_ar": "A",
                "name_en": "A",
                "price": 19.0,
                "currency": "SAR",
                "price_basis": "storefront_inc_vat",
                "in_stock": True,
                "qty_available": 5,
                "crawled_at": anchor - timedelta(hours=1),
                "observation_version": 2,
                "confidence_score": 97,
                "comparable": True,
                "is_synthetic": False,
                "present_on_store": True,
                "variant_skus": ["COMP-HIST-A"],
                "variant_barcodes": [barcode],
            },
            {
                "id": "hist-a-old",
                "product_id": "hist-a-old",
                "store_id": "comp-03",
                "store_name": "Store comp-03",
                "sku": "COMP-HIST-A",
                "offer_id": "hist-offer-a",
                "barcode": barcode,
                "name_ar": "A old",
                "name_en": "A old",
                "price": 90.0,
                "currency": "SAR",
                "price_basis": "storefront_inc_vat",
                "in_stock": True,
                "qty_available": 4,
                "crawled_at": anchor - timedelta(days=179, hours=23, minutes=58),
                "observation_version": 2,
                "confidence_score": 97,
                "comparable": True,
                "is_synthetic": False,
                "present_on_store": True,
                "variant_skus": ["COMP-HIST-A"],
                "variant_barcodes": [barcode],
            },
            {
                "id": "hist-b-new",
                "product_id": "hist-b-new",
                "store_id": "comp-04",
                "store_name": "Store comp-04",
                "sku": "COMP-HIST-B",
                "offer_id": "hist-offer-b",
                "barcode": barcode,
                "name_ar": "B",
                "name_en": "B",
                "price": 100.0,
                "currency": "SAR",
                "price_basis": "storefront_inc_vat",
                "in_stock": True,
                "qty_available": 3,
                "crawled_at": anchor - timedelta(hours=1),
                "observation_version": 2,
                "confidence_score": 97,
                "comparable": True,
                "is_synthetic": False,
                "present_on_store": True,
                "variant_skus": ["COMP-HIST-B"],
                "variant_barcodes": [barcode],
            },
        ])

        try:
            own_row = await raw_db.my_products.find_one({"sku": "SKU-HIST-BOUND"}, {"_id": 0})
            assert own_row is not None
            cohort_in = (await price_cohort.build_cohorts(
                boundary_env["guarded"],
                [own_row],
                "own-store-p0",
                lambda r: float(r.get("sale_price") or r.get("price") or 0),
                now=anchor,
            ))["SKU-HIST-BOUND"]
            assert any(s.get("offer_id") == "hist-offer-a" for s in cohort_in["sellers"])

            # Move history beyond 180d window: same latest 7d-eligible offer should now be excluded as outlier.
            await raw_db.product_snapshots.update_one(
                {"id": "hist-a-old"},
                {"$set": {"crawled_at": anchor - timedelta(days=181)}},
            )
            cohort_out = (await price_cohort.build_cohorts(
                boundary_env["guarded"],
                [own_row],
                "own-store-p0",
                lambda r: float(r.get("sale_price") or r.get("price") or 0),
                now=anchor,
            ))["SKU-HIST-BOUND"]
            assert all(s.get("offer_id") != "hist-offer-a" for s in cohort_out["sellers"])
            flagged = [e for e in cohort_out["excluded"] if e.get("offer_id") == "hist-offer-a"]
            assert flagged and any(e.get("excluded_reason") == "below_corroborated_cluster" for e in flagged)

            # Eligibility cutoff remains 7d-driven for latest observation.
            assert all(e.get("excluded_reason") != "stale_or_unknown_observation" for e in flagged)

            return {
                "in_window_sellers": len(cohort_in["sellers"]),
                "out_window_sellers": len(cohort_out["sellers"]),
                "out_window_reasons": sorted({e.get("excluded_reason") for e in flagged if e.get("excluded_reason")}),
            }
        finally:
            await raw_db.my_products.delete_one({"sku": "SKU-HIST-BOUND"})
            await raw_db.product_snapshots.delete_many({"offer_id": {"$in": ["hist-offer-a", "hist-offer-b"]}})

    out = boundary_env["loop"].run_until_complete(run())
    _record_result("history_180d_boundary", out)


def test_05_revision_increment_invalidates_warm_memory_cache(boundary_env):
    """Revision bump must invalidate already-warm process cache without manual loop clear."""

    async def run() -> dict[str, Any]:
        raw_db = boundary_env["raw_db"]
        await raw_db.dashboard_cache.delete_many({})
        my_products_cache._loops.clear()

        cold = await _call_with_probe(boundary_env)
        assert cold["status"] == 200

        warm = await _call_with_probe(boundary_env)
        assert warm["status"] == 200
        assert warm["body"].get("cache", {}).get("source") == "memory_cache"

        rev_doc = await raw_db.data_versions.find_one({"_id": "observations"}, {"_id": 0, "revision": 1}) or {"revision": 0}
        await raw_db.data_versions.update_one(
            {"_id": "observations"},
            {"$set": {"revision": int(rev_doc.get("revision", 0)) + 1, "observed_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

        # No _loops clear here by design.
        after_rev = await _call_with_probe(boundary_env)
        assert after_rev["status"] == 200
        assert after_rev["body"].get("cache", {}).get("source") == "live_fallback"
        assert after_rev["reads"]["by_command"]["aggregate"]["count"] >= 1

        return {
            "cold_source": cold["body"].get("cache", {}).get("source"),
            "warm_source": warm["body"].get("cache", {}).get("source"),
            "after_revision_source": after_rev["body"].get("cache", {}).get("source"),
            "after_revision_reads": after_rev["reads"]["by_command"],
        }

    out = boundary_env["loop"].run_until_complete(run())
    _record_result("revision_invalidation", out)


def test_06_malformed_future_docs_and_key_family_separation(boundary_env):
    """Malformed/future metadata must not be trusted; wrong key families must not hit cache."""

    async def run() -> dict[str, Any]:
        raw_db = boundary_env["raw_db"]
        key30 = server._dashboard_cache_key(30)

        dataset = await my_products_cache.compute_dataset(
            boundary_env["guarded"],
            lambda: server._my_products_dataset(boundary_env["guarded"], 30, None, None, None, None, None, None, True),
            max_age=300,
        )
        good_doc = my_products_cache.envelope(dataset)

        await raw_db.dashboard_cache.delete_many({})
        bad_doc = dict(good_doc)
        bad_doc["dataset"] = {**bad_doc["dataset"], "total": 1}
        await raw_db.dashboard_cache.replace_one({"key": key30}, {"key": key30, **bad_doc}, upsert=True)
        my_products_cache._loops.clear()
        malformed = await _call_with_probe(boundary_env)
        assert malformed["status"] == 200
        assert malformed["body"].get("cache", {}).get("source") == "live_fallback"

        await raw_db.dashboard_cache.delete_many({})
        future_doc = dict(good_doc)
        future_doc["computed_at"] = dataset["_computed_at"] + timedelta(hours=1)
        future_doc["valid_until"] = future_doc["computed_at"] + timedelta(minutes=10)
        await raw_db.dashboard_cache.replace_one({"key": key30}, {"key": key30, **future_doc}, upsert=True)
        my_products_cache._loops.clear()
        future = await _call_with_probe(boundary_env)
        assert future["status"] == 200
        assert future["body"].get("cache", {}).get("source") == "live_fallback"

        await raw_db.dashboard_cache.delete_many({})
        parts = key30.split(":")
        assert len(parts) >= 6
        wrong_keys = {
            "wrong_policy": ":".join([parts[0], parts[1], "wrong-policy", parts[3], parts[4], parts[5]]),
            "wrong_build": ":".join([parts[0], parts[1], parts[2], "deadbeefcafe", parts[4], parts[5]]),
            "wrong_ksa_day": ":".join([parts[0], parts[1], parts[2], parts[3], "1999-12-31", parts[5]]),
            "wrong_window": key30.replace("days=30", "days=7"),
        }
        key_checks: dict[str, Any] = {}
        for label, bad_key in wrong_keys.items():
            await raw_db.dashboard_cache.delete_many({})
            await raw_db.dashboard_cache.insert_one({"key": bad_key, **good_doc})
            my_products_cache._loops.clear()
            req = await _call_with_probe(boundary_env)
            assert req["status"] == 200
            assert req["body"].get("cache", {}).get("source") == "live_fallback"
            key_checks[label] = {
                "key": bad_key,
                "source": req["body"].get("cache", {}).get("source"),
                "reads": req["reads"]["by_command"],
            }

        return {
            "malformed_source": malformed["body"].get("cache", {}).get("source"),
            "future_source": future["body"].get("cache", {}).get("source"),
            "wrong_key_checks": key_checks,
        }

    out = boundary_env["loop"].run_until_complete(run())
    _record_result("malformed_future_and_key_separation", out)


def test_07_failure_not_cached_retry_succeeds_without_loop_clear(boundary_env):
    """First failure should not poison cache/singleflight; next retry succeeds naturally."""

    async def run() -> dict[str, Any]:
        raw_db = boundary_env["raw_db"]
        await raw_db.dashboard_cache.delete_many({})
        my_products_cache._loops.clear()

        original_aggregate = release_database.GuardedCollection.aggregate
        state = {"raised": False}

        def flaky_once(self, pipeline, *args, **kwargs):
            if getattr(self.raw, "name", "") == "product_snapshots" and not state["raised"]:
                state["raised"] = True
                raise NetworkTimeout("synthetic transient timeout")
            return original_aggregate(self, pipeline, *args, **kwargs)

        with _patch_guarded_aggregate(flaky_once):
            first = await _call_with_probe(boundary_env)
            assert first["status"] == 503
            assert first["body"].get("detail", {}).get("code") == "price_query_timeout"

            # Intentionally no my_products_cache._loops.clear() here.
            second = await _call_with_probe(boundary_env)
            assert second["status"] == 200
            expected_total = await raw_db.my_products.count_documents({"present_on_store": {"$ne": False}})
            assert second["body"].get("total") == expected_total

        entries, flights = my_products_cache._loops.get(asyncio.get_running_loop(), (OrderedDict(), {}))
        assert isinstance(entries, OrderedDict)
        assert len(flights) == 0

        return {
            "first_status": first["status"],
            "second_status": second["status"],
            "second_source": second["body"].get("cache", {}).get("source"),
            "second_reads": second["reads"]["by_command"],
            "flights_after_retry": len(flights),
        }

    out = boundary_env["loop"].run_until_complete(run())
    _record_result("failure_not_cached_retry", out)


def test_08_benchmarks_and_real_timeout(boundary_env):
    """Targeted benchmark slices + real maxTimeMS handling + explain comparison."""

    async def run() -> dict[str, Any]:
        raw_db = boundary_env["raw_db"]
        guarded = boundary_env["guarded"]
        seeded = boundary_env["seeded"]
        active = seeded["competitor_store_ids"]
        seed_now = seeded["seed_now"]

        report: dict[str, Any] = {
            "seed": {
                "own_products": seeded["seeded_products"],
                "snapshots": seeded["seeded_snapshots"],
                "fixture_note": "Baseline fixture intentionally includes many invalid GTIN-style SKUs for robustness.",
            },
            "scenarios": {},
        }

        assert seeded["seeded_products"] == 2832

        async def run_once(params: dict[str, Any] | None = None) -> dict[str, Any]:
            return await _call_with_probe(boundary_env, params)

        # cold: 3 isolated runs
        cold_runs = []
        for _ in range(3):
            await raw_db.dashboard_cache.delete_many({})
            my_products_cache._loops.clear()
            r = await run_once()
            assert r["status"] == 200
            cold_runs.append({
                "elapsed_ms": r["elapsed_ms"],
                "source": r["body"].get("cache", {}).get("source"),
                "read_counts": r["reads"]["by_command"],
            })

        # warm: 5 successive reads
        warm_runs = []
        for _ in range(5):
            r = await run_once()
            assert r["status"] == 200
            warm_runs.append({
                "elapsed_ms": r["elapsed_ms"],
                "source": r["body"].get("cache", {}).get("source"),
                "read_counts": r["reads"]["by_command"],
            })
        assert any(x["source"] == "memory_cache" for x in warm_runs)

        # stored valid cache path
        ds = await my_products_cache.compute_dataset(
            guarded,
            lambda: server._my_products_dataset(guarded, 30, None, None, None, None, None, None, True),
            max_age=300,
        )
        key30 = server._dashboard_cache_key(30)
        await raw_db.dashboard_cache.replace_one(
            {"key": key30},
            {"key": key30, **my_products_cache.envelope(ds)},
            upsert=True,
        )
        my_products_cache._loops.clear()
        stored = await run_once()
        assert stored["status"] == 200
        assert stored["body"].get("cache", {}).get("source") == "cache"

        # full pagination coverage with per-page read counts (non-cumulative)
        pages = []
        unique_skus = set()
        for offset in (0, 500, 1000, 1500, 2000, 2500):
            my_products_cache._loops.clear()
            page = await run_once({**BASE_QUERY, "limit": 500, "offset": offset})
            assert page["status"] == 200
            for row in page["body"].get("products", []):
                if row.get("sku"):
                    unique_skus.add(row["sku"])
            pages.append({
                "offset": offset,
                "elapsed_ms": page["elapsed_ms"],
                "total": page["body"].get("total"),
                "source": page["body"].get("cache", {}).get("source"),
                "read_counts": page["reads"]["by_command"],
            })
        assert len(unique_skus) == seeded["seeded_products"]
        assert all(p["total"] == seeded["seeded_products"] for p in pages)

        # concurrent cold singleflight benchmark
        await raw_db.dashboard_cache.delete_many({})
        my_products_cache._loops.clear()
        call_counter = {"n": 0}
        original_build = comparison_views.build_cohorts

        async def counted_build(*args, **kwargs):
            call_counter["n"] += 1
            await asyncio.sleep(0.2)
            return await original_build(*args, **kwargs)

        comparison_views.build_cohorts = counted_build  # type: ignore[assignment]
        try:
            boundary_env["cmd_probe"].reset()
            tasks = [asyncio.create_task(_call_my_products()) for _ in range(5)]
            burst = await asyncio.gather(*tasks)
            burst_reads = boundary_env["cmd_probe"].summary()["by_command"]
        finally:
            comparison_views.build_cohorts = original_build  # type: ignore[assignment]
        assert all(r["status"] == 200 for r in burst)
        assert call_counter["n"] == 1, f"expected one compute, observed {call_counter['n']}"

        # Real (non-injected) maxTimeMS handling check
        timeout_attempts = []
        real_timeout_seen = False
        for _ in range(5):
            try:
                await raw_db.product_snapshots.aggregate(
                    price_cohort.snapshot_pipeline(active, seed_now),
                    allowDiskUse=True,
                    maxTimeMS=1,
                ).to_list(5)
                timeout_attempts.append({"timed_out": False})
            except ExecutionTimeout as exc:
                real_timeout_seen = True
                timeout_attempts.append({"timed_out": True, "type": type(exc).__name__})
                break
            except OperationFailure as exc:
                code = getattr(exc, "code", None)
                if code == 50 or "time limit" in str(exc).lower():
                    real_timeout_seen = True
                    timeout_attempts.append({"timed_out": True, "type": type(exc).__name__, "code": code})
                    break
                raise
        assert real_timeout_seen, "Expected at least one real Mongo maxTimeMS timeout with maxTimeMS=1"

        old_snapshot_max = price_cohort.SNAPSHOT_QUERY_MAX_MS
        price_cohort.SNAPSHOT_QUERY_MAX_MS = 1
        try:
            await raw_db.dashboard_cache.delete_many({})
            my_products_cache._loops.clear()
            timeout_resp = await run_once()
        finally:
            price_cohort.SNAPSHOT_QUERY_MAX_MS = old_snapshot_max
        assert timeout_resp["status"] == 503
        assert timeout_resp["body"].get("detail", {}).get("code") == "price_query_timeout"

        explain_new = await raw_db.command({
            "explain": {
                "aggregate": "product_snapshots",
                "pipeline": price_cohort.snapshot_pipeline(active, seed_now),
                "cursor": {},
                "allowDiskUse": True,
            },
            "verbosity": "executionStats",
        })
        explain_old = await raw_db.command({
            "explain": {
                "aggregate": "product_snapshots",
                "pipeline": _old_pipeline(active, seed_now),
                "cursor": {},
                "allowDiskUse": True,
            },
            "verbosity": "executionStats",
        })
        m_new: dict[str, Any] = {}
        m_old: dict[str, Any] = {}
        _walk_explain(explain_new, m_new)
        _walk_explain(explain_old, m_old)

        # Coverage expectation: same examined docs/keys; do not claim speedup from compact projection.
        assert m_new.get("totalDocsExamined") == m_old.get("totalDocsExamined")
        assert m_new.get("totalKeysExamined") == m_old.get("totalKeysExamined")

        report["scenarios"] = {
            "cold_3_runs": cold_runs,
            "warm_5_runs": warm_runs,
            "stored_valid_cache": {
                "elapsed_ms": stored["elapsed_ms"],
                "source": stored["body"].get("cache", {}).get("source"),
                "read_counts": stored["reads"]["by_command"],
            },
            "full_pagination": {
                "pages": pages,
                "unique_skus": len(unique_skus),
            },
            "concurrent_cold": {
                "requests": len(burst),
                "compute_calls": call_counter["n"],
                "sources": [r["body"].get("cache", {}).get("source") for r in burst],
                "read_counts": burst_reads,
            },
            "timeouts": {
                "real_max_time_ms_1": {
                    "attempts": timeout_attempts,
                    "seen": real_timeout_seen,
                },
                "api_with_snapshot_query_max_1": {
                    "status": timeout_resp["status"],
                    "detail": timeout_resp["body"].get("detail", {}),
                },
                "injection_note": "No synthetic injection used in this scenario; real Mongo maxTimeMS bound only.",
            },
            "compact_projection_explain": {
                "old": {k: m_old.get(k) for k in ("totalDocsExamined", "totalKeysExamined", "executionTimeMillis", "maxAccumulatorMemoryUsageBytes")},
                "new": {k: m_new.get(k) for k in ("totalDocsExamined", "totalKeysExamined", "executionTimeMillis", "maxAccumulatorMemoryUsageBytes")},
                "note": "Projection-before-group did not change examined docs/keys; execution time is reported, not claimed as speedup.",
            },
        }
        return report

    out = boundary_env["loop"].run_until_complete(run())
    BENCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    BENCH_PATH.write_text(json.dumps(out, indent=2, default=str))
    _record_result("benchmarks", {"path": str(BENCH_PATH), "base_url": base_url().rstrip("/")})
