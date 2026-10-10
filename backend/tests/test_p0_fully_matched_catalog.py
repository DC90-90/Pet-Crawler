"""Real-Mongo, all-valid-GTIN 2,832-product benchmark; disposable loopback only."""
import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
import server
import my_products_cache
from test_p0_my_products_baseline import _loopback_mongo_url, _fake_user
from test_p0_cache_boundaries import CommandProbe, CountingGuardedDatabase, make_gtin13, _call_my_products


def test_fully_matched_catalog_readonly_benchmark():
    async def run():
        probe = CommandProbe()
        client = AsyncIOMotorClient(_loopback_mongo_url(), event_listeners=[probe])
        name = "p0_full_matches_"+uuid.uuid4().hex
        raw, original = client[name], server.db
        override = server.app.dependency_overrides.get(server.get_user)
        now = datetime.now(timezone.utc)
        try:
            await raw.stores.insert_many([{"id": "own", "is_own_store": True, "is_active": True},
                                         *[{"id": s, "is_active": True, "name": s} for s in ("a", "b", "c")]])
            rows = [{"sku": f"P{i:04}", "barcode": make_gtin13(f"6182{i:08}"), "name_en": "Feed 2kg",
                     "price": 100, "price_basis": "storefront_inc_vat", "currency": "SAR", "in_stock": True,
                     "quantity": 10, "last_synced_at": now} for i in range(2832)]
            await raw.my_products.insert_many([dict(r) for r in rows])
            count = 0
            for store, price in (("a", 80), ("b", 90), ("c", 110)):
                for days in (0, 2, 6, 15, 30, 45, 60, 90, 120, 140, 160, 179):
                    snaps = [{**r, "store_id": store, "store_name": store, "offer_id": store+r["sku"],
                              "listing_id": r["sku"], "variant_id": "2kg", "price": price,
                              "crawled_at": now-timedelta(days=days), "observation_version": 2, "comparable": True,
                              "confidence_score": 99, "unused_payload": "X"*256} for r in rows]
                    await raw.product_snapshots.insert_many(snaps)
                    count += len(snaps)
            # Only the index family observed in production; no store-leading index.
            for spec in ([('crawled_at', 1)], [('crawled_at', -1), ('sku', 1)],
                         [('product_id', 1)], [('crawled_at', -1), ('store_id', 1)]):
                await raw.product_snapshots.create_index(spec)
            guarded = CountingGuardedDatabase(raw)
            server.db = guarded
            server.app.dependency_overrides[server.get_user] = _fake_user
            result = {"products": len(rows), "snapshots": count, "matched_products": 2832, "cold": [], "warm": []}
            for kind, repeats in (("cold", 3), ("warm", 5)):
                for _ in range(repeats):
                    if kind == "cold":
                        my_products_cache._loops.clear()
                    probe.reset()
                    response = await _call_my_products()
                    assert response["status"] == 200, response["body"]
                    body = response["body"]
                    assert body["total"] == 2832 and body["kpis"]["matched_products"] == 2832
                    assert all(r["competitor_min_price"] == 80 and r["market_price"] == 93.33 and r["num_priced_competitors"] == 3 for r in body["products"])
                    assert body["cache"]["source"] == ("live_fallback" if kind == "cold" else "memory_cache")
                    reads = probe.summary()
                    result[kind].append({"milliseconds": response["elapsed_ms"], "reads": reads["total_read_commands"],
                                        "by_command": {k: v["count"] for k, v in reads["by_command"].items()}})
            seen = set()
            for offset in range(0, 2832, 500):
                response = await _call_my_products({"days": 30, "limit": 500, "offset": offset})
                assert response["status"] == 200 and response["body"]["total"] == 2832
                for row in response["body"]["products"]:
                    assert row["competitor_min_price"] == 80 and row["num_priced_competitors"] == 3
                    seen.add(row["sku"])
            assert len(seen) == 2832 and guarded.write_attempted == guarded.write_actual == 0
            assert await raw.dashboard_cache.count_documents({}) == 0
            result.update(unique_skus=len(seen), attempted_writes=0, actual_writes=0, dashboard_cache_documents=0)
            Path('/app/test_reports/p0_my_products/fully_matched_benchmark.json').write_text(json.dumps(result, indent=2))
        finally:
            server.db = original
            if override is None:
                server.app.dependency_overrides.pop(server.get_user, None)
            else:
                server.app.dependency_overrides[server.get_user] = override
            my_products_cache._loops.clear()
            await client.drop_database(name)
            client.close()
    asyncio.run(run())