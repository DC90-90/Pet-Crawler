"""P0 pre-fix baseline harness for /api/my-products timeout investigation.

Requirements covered:
- Loopback-only disposable MongoDB.
- Seed 2,832 own products and >=100k competitor snapshots across 180 days.
- Keep GuardedDatabase observer/no-write behavior for measured requests.
- Measure cold/repeat /api/my-products timings + Mongo read command counts.
- Capture explain stats for the original price_cohort aggregate pipeline.
- Inject synthetic ExecutionTimeout and NetworkTimeout at aggregate level; expect 500.
- Persist baseline evidence JSON for post-fix comparison.
"""

from __future__ import annotations

# Historical pre-fix replay (expects the old 500/no-cache behavior), not a
# post-fix regression suite. Retained for evidence and reusable fixture helpers.
# Current acceptance lives in test_p0_my_products_fix/cache_boundaries and
# test_p0_fully_matched_catalog; baseline_pre_fix.json must never be overwritten.
__test__ = False

import asyncio
import json
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import monitoring
from pymongo.errors import ExecutionTimeout, NetworkTimeout

import price_cohort
import release_database
import server
from release_control import state as release_state


BASE_QUERY = {
    "sort_by": "revenue_est",
    "sort_order": "desc",
    "limit": 100,
    "offset": 0,
    "days": 30,
}


def _loopback_mongo_url() -> str:
    mongo_url = os.environ.get("MONGO_URL")
    assert mongo_url, "MONGO_URL must be set"
    parsed = urlparse(mongo_url.strip().strip('"').strip("'"))
    host = parsed.hostname
    assert host in {"localhost", "127.0.0.1", "::1"}, (
        f"Refusing non-loopback Mongo host for baseline: {host}"
    )
    return mongo_url


class ReadProbe(monitoring.CommandListener):
    """Track Mongo read command counts/durations during endpoint calls."""

    READS = {"aggregate", "find", "distinct", "getMore"}

    def __init__(self) -> None:
        self.inflight: dict[int, str] = {}
        self.events: list[dict[str, Any]] = []

    def started(self, event):  # type: ignore[override]
        if event.command_name in self.READS:
            self.inflight[event.request_id] = event.command_name

    def succeeded(self, event):  # type: ignore[override]
        cmd = self.inflight.pop(event.request_id, None)
        if cmd:
            self.events.append({"name": cmd, "duration_ms": float(event.duration_micros) / 1000.0})

    def failed(self, event):  # type: ignore[override]
        cmd = self.inflight.pop(event.request_id, None)
        if cmd:
            self.events.append({"name": cmd, "duration_ms": float(event.duration_micros) / 1000.0, "failed": True})

    def reset(self) -> None:
        self.inflight.clear()
        self.events.clear()

    def summary(self) -> dict[str, Any]:
        out = {k: {"count": 0, "duration_ms": 0.0} for k in self.READS}
        for row in self.events:
            out[row["name"]]["count"] += 1
            out[row["name"]]["duration_ms"] += row.get("duration_ms", 0.0)
        return {
            "by_command": out,
            "total_read_commands": sum(v["count"] for v in out.values()),
            "total_read_duration_ms": round(sum(v["duration_ms"] for v in out.values()), 2),
        }


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


async def _seed_baseline(raw_db, own_count: int = 2832) -> dict[str, Any]:
    for coll in (
        "stores",
        "my_products",
        "products",
        "product_snapshots",
        "product_matches",
        "match_blacklist",
        "dashboard_cache",
        "data_versions",
        "release_control",
    ):
        await raw_db[coll].delete_many({})

    now = datetime.now(timezone.utc)
    own_store = "own-store-p0"
    comp_ids = [f"comp-{i:02d}" for i in range(1, 8)]

    await raw_db.stores.insert_many([
        {
            "id": own_store,
            "name": "Own Store",
            "domain": "own.local",
            "platform": "zid",
            "is_active": True,
            "is_own_store": True,
        },
        *[
            {
                "id": sid,
                "name": f"Store {sid}",
                "domain": f"{sid}.local",
                "platform": "salla",
                "is_active": True,
            }
            for sid in comp_ids
        ],
    ])

    own_rows: list[dict[str, Any]] = []
    products_rows: list[dict[str, Any]] = []
    for i in range(own_count):
        sku = f"OWN-{i:05d}"
        barcode = f"6281110{i:06d}"[-13:]
        own_rows.append({
            "sku": sku,
            "offer_id": f"own-offer-{i:05d}",
            "name_ar": f"منتج {i}",
            "name_en": f"Product {i}",
            "barcode": barcode,
            "price": round(40 + (i % 200) * 0.9, 2),
            "sale_price": None,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "quantity": 15 + (i % 35),
            "present_on_store": True,
            "last_synced_at": now.isoformat(),
        })
        products_rows.append({
            "id": f"prod-{i:05d}",
            "sku": sku,
            "store_id": own_store,
            "offer_id": f"own-offer-{i:05d}",
            "brand": "BrandX",
            "brand_source": "store_supplied",
        })

    # Fixture SKUs for explicit behavior checks.
    fixture_skus = [
        ("SKU-MANUAL", "6281110000001"),
        ("SKU-BLACKLIST", "6281110000002"),
        ("SKU-LATEST-OOS", "6281110000003"),
        ("SKU-STALE", "6281110000004"),
        ("SKU-PARENT", "6281110000005"),
        ("SKU-OUTLIER", "6281110000006"),
    ]
    for i, (sku, bc) in enumerate(fixture_skus):
        own_rows[i]["sku"] = sku
        own_rows[i]["barcode"] = bc

    await raw_db.my_products.insert_many(own_rows)
    await raw_db.products.insert_many(products_rows)

    await raw_db.product_matches.insert_many([
        {
            "my_sku": "SKU-MANUAL",
            "competitor_store_id": comp_ids[0],
            "competitor_offer_id": "manual-offer-1",
            "manually_confirmed": True,
            "identity_version": 2,
        },
        {
            "my_sku": "SKU-BLACKLIST",
            "competitor_store_id": comp_ids[1],
            "competitor_offer_id": "blocked-offer-1",
            "manually_confirmed": True,
            "identity_version": 2,
        },
    ])
    await raw_db.match_blacklist.insert_one({
        "my_sku": "SKU-BLACKLIST",
        "competitor_store_id": comp_ids[1],
        "competitor_offer_id": "blocked-offer-1",
    })

    random.seed(707)
    days_back = [0, 22, 45, 70, 95, 130, 160, 179]
    extra_blob = "X" * 256

    batch: list[dict[str, Any]] = []
    total_snapshots = 0

    async def flush() -> None:
        nonlocal total_snapshots
        if batch:
            await raw_db.product_snapshots.insert_many(batch, ordered=False)
            total_snapshots += len(batch)
            batch.clear()

    def emit(doc: dict[str, Any]) -> None:
        batch.append(doc)

    # Base volume: 7 stores × 1800 SKUs × 8 snapshots = 100,800 snapshots.
    for sid_i, sid in enumerate(comp_ids):
        for sku_i in range(1800):
            idx = (sid_i * 257 + sku_i) % own_count
            own_sku = own_rows[idx]["sku"]
            barcode = own_rows[idx]["barcode"]
            offer_id = f"{sid}-offer-{sku_i:05d}"
            base_price = round(35 + (sku_i % 220) * 0.8 + sid_i, 2)
            for d in days_back:
                emit({
                    "id": f"{sid}-{sku_i}-{d}",
                    "product_id": f"prod-{idx:05d}",
                    "store_id": sid,
                    "store_name": f"Store {sid}",
                    "sku": own_sku,
                    "offer_id": offer_id,
                    "barcode": barcode,
                    "name_ar": f"منافس {own_sku}",
                    "name_en": f"Competitor {own_sku}",
                    "price": round(base_price * (1 + (d % 5) * 0.01), 2),
                    "currency": "SAR",
                    "price_basis": "storefront_inc_vat",
                    "in_stock": True,
                    "qty_available": 20 + (sku_i % 40),
                    "crawled_at": now - timedelta(days=d, hours=(sku_i + sid_i) % 24),
                    "observation_version": 2,
                    "confidence_score": 96,
                    "comparable": True,
                    "is_synthetic": False,
                    "present_on_store": True,
                    "variant_skus": [own_sku],
                    "variant_barcodes": [barcode],
                    "unused_payload": extra_blob,
                })
                if len(batch) >= 5000:
                    await flush()

    # Differential fixtures.
    for doc in [
        # manual match keeps candidate despite missing strong identifiers
        {
            "id": "manual-fixture-1",
            "product_id": "manual-1",
            "store_id": comp_ids[0],
            "store_name": "Manual Store",
            "sku": "MANUAL-NONMATCH",
            "offer_id": "manual-offer-1",
            "barcode": "",
            "name_ar": "Manual Offer",
            "name_en": "Manual Offer",
            "price": 88.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 9,
            "crawled_at": now - timedelta(hours=3),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": [],
            "variant_barcodes": [],
            "unused_payload": extra_blob,
        },
        # blacklisted candidate
        {
            "id": "blocked-fixture-1",
            "product_id": "blocked-1",
            "store_id": comp_ids[1],
            "store_name": "Blocked Store",
            "sku": "SKU-BLACKLIST",
            "offer_id": "blocked-offer-1",
            "barcode": "6281110000002",
            "name_ar": "Blocked",
            "name_en": "Blocked",
            "price": 77.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 10,
            "crawled_at": now - timedelta(hours=2),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": ["SKU-BLACKLIST"],
            "variant_barcodes": ["6281110000002"],
            "unused_payload": extra_blob,
        },
        # latest OOS suppresses older in-stock
        {
            "id": "oos-new",
            "product_id": "oos-1",
            "store_id": comp_ids[2],
            "store_name": "OOS Store",
            "sku": "SKU-LATEST-OOS",
            "offer_id": "oos-offer-1",
            "barcode": "6281110000003",
            "name_ar": "OOS New",
            "name_en": "OOS New",
            "price": 91.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": False,
            "qty_available": 0,
            "crawled_at": now - timedelta(hours=1),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": ["SKU-LATEST-OOS"],
            "variant_barcodes": ["6281110000003"],
            "unused_payload": extra_blob,
        },
        {
            "id": "oos-old",
            "product_id": "oos-1",
            "store_id": comp_ids[2],
            "store_name": "OOS Store",
            "sku": "SKU-LATEST-OOS",
            "offer_id": "oos-offer-1",
            "barcode": "6281110000003",
            "name_ar": "OOS Old",
            "name_en": "OOS Old",
            "price": 79.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 14,
            "crawled_at": now - timedelta(days=2),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": ["SKU-LATEST-OOS"],
            "variant_barcodes": ["6281110000003"],
            "unused_payload": extra_blob,
        },
        # stale fixture
        {
            "id": "stale-1",
            "product_id": "stale-1",
            "store_id": comp_ids[3],
            "store_name": "Stale Store",
            "sku": "SKU-STALE",
            "offer_id": "stale-offer-1",
            "barcode": "6281110000004",
            "name_ar": "Stale",
            "name_en": "Stale",
            "price": 66.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 8,
            "crawled_at": now - timedelta(days=8),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": ["SKU-STALE"],
            "variant_barcodes": ["6281110000004"],
            "unused_payload": extra_blob,
        },
        # parent suppression fixture
        {
            "id": "parent-1",
            "product_id": "parent-1",
            "store_id": comp_ids[4],
            "store_name": "Parent Store",
            "sku": "SKU-PARENT",
            "offer_id": "parent-offer-1",
            "barcode": "6281110000005",
            "name_ar": "Parent",
            "name_en": "Parent",
            "price": 72.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 6,
            "crawled_at": now - timedelta(hours=6),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "superseded_parent": True,
            "variant_skus": ["SKU-PARENT"],
            "variant_barcodes": ["6281110000005"],
            "unused_payload": extra_blob,
        },
        # outlier + historical boundary
        {
            "id": "out-normal-1",
            "product_id": "out-1",
            "store_id": comp_ids[5],
            "store_name": "Out A",
            "sku": "SKU-OUTLIER",
            "offer_id": "out-offer-1",
            "barcode": "6281110000006",
            "name_ar": "OutA",
            "name_en": "OutA",
            "price": 120.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 6,
            "crawled_at": now - timedelta(hours=4),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": ["SKU-OUTLIER"],
            "variant_barcodes": ["6281110000006"],
            "unused_payload": extra_blob,
        },
        {
            "id": "out-normal-2",
            "product_id": "out-1",
            "store_id": comp_ids[6],
            "store_name": "Out B",
            "sku": "SKU-OUTLIER",
            "offer_id": "out-offer-2",
            "barcode": "6281110000006",
            "name_ar": "OutB",
            "name_en": "OutB",
            "price": 122.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 6,
            "crawled_at": now - timedelta(hours=3),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": ["SKU-OUTLIER"],
            "variant_barcodes": ["6281110000006"],
            "unused_payload": extra_blob,
        },
        {
            "id": "out-low-now",
            "product_id": "out-1",
            "store_id": comp_ids[0],
            "store_name": "Out Low",
            "sku": "SKU-OUTLIER",
            "offer_id": "out-low-offer",
            "barcode": "6281110000006",
            "name_ar": "OutLow",
            "name_en": "OutLow",
            "price": 40.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 6,
            "crawled_at": now - timedelta(hours=2),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": ["SKU-OUTLIER"],
            "variant_barcodes": ["6281110000006"],
            "unused_payload": extra_blob,
        },
        {
            "id": "out-low-h180",
            "product_id": "out-1",
            "store_id": comp_ids[0],
            "store_name": "Out Low",
            "sku": "SKU-OUTLIER",
            "offer_id": "out-low-offer",
            "barcode": "6281110000006",
            "name_ar": "Out180",
            "name_en": "Out180",
            "price": 150.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 6,
            "crawled_at": now - timedelta(days=180),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": ["SKU-OUTLIER"],
            "variant_barcodes": ["6281110000006"],
            "unused_payload": extra_blob,
        },
        {
            "id": "out-low-old181",
            "product_id": "out-1",
            "store_id": comp_ids[0],
            "store_name": "Out Low",
            "sku": "SKU-OUTLIER",
            "offer_id": "out-low-offer",
            "barcode": "6281110000006",
            "name_ar": "Out181",
            "name_en": "Out181",
            "price": 160.0,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "qty_available": 6,
            "crawled_at": now - timedelta(days=181),
            "observation_version": 2,
            "confidence_score": 97,
            "comparable": True,
            "is_synthetic": False,
            "present_on_store": True,
            "variant_skus": ["SKU-OUTLIER"],
            "variant_barcodes": ["6281110000006"],
            "unused_payload": extra_blob,
        },
    ]:
        emit(doc)
        if len(batch) >= 5000:
            await flush()

    await flush()

    # Keep only observed production index family.
    try:
        await raw_db.product_snapshots.drop_indexes()
    except Exception:
        pass
    await raw_db.product_snapshots.create_index("crawled_at")
    await raw_db.product_snapshots.create_index([("crawled_at", -1), ("sku", 1)])
    await raw_db.product_snapshots.create_index("product_id")
    await raw_db.product_snapshots.create_index([("crawled_at", -1), ("store_id", 1)])

    await raw_db.data_versions.update_one(
        {"_id": "observations"},
        {"$set": {"revision": 1, "observed_at": now}},
        upsert=True,
    )

    return {
        "own_store_id": own_store,
        "competitor_store_ids": comp_ids,
        "seeded_products": own_count,
        "seeded_snapshots": total_snapshots,
        "seed_now": now,
    }


async def _fake_user():
    return {
        "id": "p0-user",
        "email": "p0@example.invalid",
        "role": "super_admin",
        "allowed_pages": server.ALL_PAGES,
    }


async def _call_my_products(probe: ReadProbe) -> dict[str, Any]:
    probe.reset()
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        t0 = time.perf_counter()
        resp = await ac.get("/api/my-products", params=BASE_QUERY)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"non_json": True}
    return {
        "status": resp.status_code,
        "elapsed_ms": round(elapsed_ms, 2),
        "body": body,
        "reads": probe.summary(),
    }


async def _cohort_fixture_checks(db) -> dict[str, Any]:
    own_rows = await db.my_products.find(
        {"sku": {"$in": ["SKU-MANUAL", "SKU-BLACKLIST", "SKU-LATEST-OOS", "SKU-STALE", "SKU-PARENT", "SKU-OUTLIER"]}},
        {"_id": 0},
    ).to_list(100)

    cohorts = await price_cohort.build_cohorts(
        db,
        own_rows,
        "own-store-p0",
        lambda r: float(r.get("sale_price") or r.get("price") or 0),
    )

    manual = cohorts["SKU-MANUAL"]
    blocked = cohorts["SKU-BLACKLIST"]
    oos = cohorts["SKU-LATEST-OOS"]
    stale = cohorts["SKU-STALE"]
    parent = cohorts["SKU-PARENT"]

    assert any(s.get("offer_id") == "manual-offer-1" for s in manual["sellers"])
    assert not any(s.get("offer_id") == "blocked-offer-1" for s in blocked["sellers"])
    oos_rows = [r for r in (oos["excluded"] + oos["sellers"]) if r.get("offer_id") == "oos-offer-1"]
    assert not oos_rows or any(r.get("excluded_reason") == "out_of_stock" for r in oos_rows)
    assert all(s.get("offer_id") != "oos-offer-1" for s in oos["sellers"])
    stale_rows = [r for r in (stale["excluded"] + stale["sellers"]) if r.get("offer_id") == "stale-offer-1"]
    assert not stale_rows or any(r.get("excluded_reason") == "stale_or_unknown_observation" for r in stale_rows)
    parent_rows = [r for r in (parent["excluded"] + parent["sellers"]) if r.get("offer_id") == "parent-offer-1"]
    assert not parent_rows or any(r.get("excluded_reason") == "parent_listing_not_an_offer" for r in parent_rows)

    return {
        "manual_sellers": len(manual["sellers"]),
        "blacklist_sellers": len(blocked["sellers"]),
        "oos_excluded": sorted({e.get("excluded_reason") for e in oos["excluded"] if e.get("excluded_reason")}),
        "stale_excluded": sorted({e.get("excluded_reason") for e in stale["excluded"] if e.get("excluded_reason")}),
        "parent_excluded": sorted({e.get("excluded_reason") for e in parent["excluded"] if e.get("excluded_reason")}),
    }


async def _explain_baseline(raw_db, now: datetime, comp_ids: list[str]) -> dict[str, Any]:
    pipeline = [
        {"$match": {"store_id": {"$in": comp_ids}, "crawled_at": {"$gte": now - timedelta(days=180)}}},
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
    explain_doc = await raw_db.command(
        {
            "explain": {
                "aggregate": "product_snapshots",
                "pipeline": pipeline,
                "cursor": {},
                "allowDiskUse": True,
            },
            "verbosity": "executionStats",
        }
    )
    metrics: dict[str, Any] = {"stages": []}
    _walk_explain(explain_doc, metrics)
    return {
        "pipeline_reference": {
            "function": "price_cohort.build_cohorts",
            "file": str(Path(price_cohort.__file__).resolve()),
            "first_line": price_cohort.build_cohorts.__code__.co_firstlineno,
            "policy_version": price_cohort.POLICY_VERSION,
        },
        "metrics": {
            "totalDocsExamined": metrics.get("totalDocsExamined"),
            "totalKeysExamined": metrics.get("totalKeysExamined"),
            "executionTimeMillis": metrics.get("executionTimeMillis"),
            "nReturned": metrics.get("nReturned"),
            "usedDisk": metrics.get("usedDisk"),
            "spills": metrics.get("spills"),
            "spilledBytes": metrics.get("spilledBytes"),
            "stages_sample": metrics.get("stages", [])[:20],
        },
    }


async def _inject_timeout(exc: Exception) -> dict[str, Any]:
    original = release_database.GuardedCollection.aggregate

    def patched(self, pipeline, *args, **kwargs):
        if getattr(self.raw, "name", "") == "product_snapshots":
            raise exc
        return original(self, pipeline, *args, **kwargs)

    release_database.GuardedCollection.aggregate = patched  # type: ignore[assignment]
    try:
        transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get("/api/my-products", params=BASE_QUERY)
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"non_json": True}
        assert resp.status_code == 500
        assert not (resp.status_code == 200 and isinstance(body, dict) and body.get("total") in (0, None))
        return {"status": resp.status_code, "body": body}
    finally:
        release_database.GuardedCollection.aggregate = original  # type: ignore[assignment]


def test_00_confirm_timeout_cause_from_traceback_doc():
    rca = Path("/app/deployer-agent-docs/RCA_0107107d-2d21-47fb-8ee5-836d2779725f.MD").read_text()
    assert "price_cohort.py:135" in rca
    assert "TimeoutError: The read operation timed out" in rca
    assert "socketTimeoutMS=45000" in rca


def test_10_p0_baseline_harness_and_measurements():
    mongo_url = _loopback_mongo_url()
    db_name = f"p0_my_products_{uuid.uuid4().hex[:10]}"

    async def scenario() -> dict[str, Any]:
        seed_client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
        raw_db = seed_client[db_name]

        probe = ReadProbe()
        measured_client = AsyncIOMotorClient(
            mongo_url,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            socketTimeoutMS=45000,
            event_listeners=[probe],
        )

        original_db = server.db
        original_override = server.app.dependency_overrides.get(server.get_user)

        try:
            seeded = await _seed_baseline(raw_db)
            assert seeded["seeded_products"] == 2832
            assert seeded["seeded_snapshots"] >= 100000

            server.db = release_database.GuardedDatabase(measured_client[db_name])
            server.app.dependency_overrides[server.get_user] = _fake_user

            mode = (await release_state(server.db))["mode"]
            assert mode == "observer"

            index_info = await raw_db.product_snapshots.index_information()
            index_shapes = {name: info.get("key") for name, info in index_info.items()}

            cache_before = await raw_db.dashboard_cache.count_documents({})
            cold = await _call_my_products(probe)
            warm = await _call_my_products(probe)
            cache_after = await raw_db.dashboard_cache.count_documents({})

            assert cold["status"] == 200
            assert warm["status"] == 200
            assert cold["body"].get("total") == 2832
            assert warm["body"].get("total") == 2832
            assert cold["body"].get("cache", {}).get("source") == "live_fallback"
            assert warm["body"].get("cache", {}).get("source") == "live_fallback"
            assert cache_before == 0 and cache_after == 0

            fixtures = await _cohort_fixture_checks(server.db)
            explain = await _explain_baseline(raw_db, seeded["seed_now"], seeded["competitor_store_ids"])
            timeout_exec = await _inject_timeout(ExecutionTimeout("synthetic execution timeout"))
            timeout_net = await _inject_timeout(NetworkTimeout("synthetic network timeout"))

            report = {
                "db_name": db_name,
                "observer_mode": mode,
                "seed": {
                    "own_products": seeded["seeded_products"],
                    "snapshots": seeded["seeded_snapshots"],
                    "competitor_stores": len(seeded["competitor_store_ids"]),
                },
                "index_shapes": index_shapes,
                "endpoint_measurements": {
                    "cold": {
                        "status": cold["status"],
                        "elapsed_ms": cold["elapsed_ms"],
                        "cache_source": cold["body"].get("cache", {}).get("source"),
                        "total": cold["body"].get("total"),
                        "query_counts": cold["reads"]["by_command"],
                        "total_read_commands": cold["reads"]["total_read_commands"],
                        "total_read_duration_ms": cold["reads"]["total_read_duration_ms"],
                    },
                    "repeat": {
                        "status": warm["status"],
                        "elapsed_ms": warm["elapsed_ms"],
                        "cache_source": warm["body"].get("cache", {}).get("source"),
                        "total": warm["body"].get("total"),
                        "query_counts": warm["reads"]["by_command"],
                        "total_read_commands": warm["reads"]["total_read_commands"],
                        "total_read_duration_ms": warm["reads"]["total_read_duration_ms"],
                    },
                    "dashboard_cache_docs": {"before": cache_before, "after": cache_after},
                },
                "cohort_fixture_assertions": fixtures,
                "aggregate_explain": explain,
                "synthetic_timeouts": {
                    "execution_timeout": timeout_exec,
                    "network_timeout": timeout_net,
                },
                "production_traceback_reference": {
                    "source": "/app/deployer-agent-docs/RCA_0107107d-2d21-47fb-8ee5-836d2779725f.MD",
                    "confirmed_cause": "price_cohort aggregate read timed out at socketTimeoutMS=45000 (production traceback)",
                    "note": "Synthetic timeout injection is local-only and intentionally does not wait for a real 45s timeout.",
                },
            }

            out_dir = Path("/app/test_reports/p0_my_products")
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "baseline_pre_fix.json").write_text(json.dumps(report, indent=2, default=str))
            return report
        finally:
            server.db = original_db
            if original_override is None:
                server.app.dependency_overrides.pop(server.get_user, None)
            else:
                server.app.dependency_overrides[server.get_user] = original_override
            await seed_client.drop_database(db_name)
            measured_client.close()
            seed_client.close()

    baseline = asyncio.run(scenario())

    assert baseline["seed"]["own_products"] >= 2832
    assert baseline["seed"]["snapshots"] >= 100000
    assert baseline["endpoint_measurements"]["cold"]["status"] == 200
    assert baseline["endpoint_measurements"]["repeat"]["status"] == 200
    assert baseline["synthetic_timeouts"]["execution_timeout"]["status"] == 500
    assert baseline["synthetic_timeouts"]["network_timeout"]["status"] == 500
