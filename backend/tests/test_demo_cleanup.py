"""iter41 — demo/seed product cleanup endpoint.

Covers: dry run reports without writing; the safety guard (real-SKU shapes and
the >200 ceiling) blocks the real run; backups are written before deletion and
contain every affected doc; the cascade leaves ZERO orphan references in any
referencing collection; real products survive; recomputes are triggered."""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_demo_cleanup")
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}
NOW = datetime.now(timezone.utc)

# real template SKUs from the actual seed data (the detector's source of truth)
DEMO = sorted(server._demo_seed_skus())[:3]
REAL_SKU = "8595602540877"          # numeric GTIN — must never be touched

CASCADE_COLLS = [c for c, _q in server._demo_cascade_queries({"x"}, {"y"})]


async def _seed(db):
    for c in CASCADE_COLLS + ["metric_rollup_meta"]:
        await db[c].delete_many({})
    for name in await db.list_collection_names():
        if name.startswith("demo_cleanup_backup_"):
            await db.drop_collection(name)
    for i, sku in enumerate(DEMO):
        await db.products.insert_one({"id": f"pid{i}", "sku": sku, "name_ar": f"منتج تجريبي {i}",
                                      "category": "cat_food", "subcategory": "cat_food_dry"})
        await db.product_snapshots.insert_one({"id": f"s{i}", "sku": sku, "product_id": f"pid{i}",
                                               "store_id": f"S{i % 2}", "price": 10.0,
                                               "confidence_score": 99, "crawled_at": NOW})
        await db.sku_store_coverage.insert_one({"_id": f"{sku}|S{i % 2}", "sku": sku,
                                                "store_id": f"S{i % 2}", "last_seen_any_at": NOW})
        await db.sku_sales_daily.insert_one({"_id": f"S0|{sku}|d", "store_id": "S0", "sku": sku,
                                             "date": "2099-01-01", "units_sold": 1, "rev_sold": 10.0,
                                             "units_qty": 0, "rev_qty": 0.0, "qty_drop": 1})
    await db.product_matches.insert_one({"my_sku": "MYSKU1", "competitor_sku": DEMO[0],
                                         "competitor_store_id": "S0", "confidence": 100})
    await db.product_matches.insert_one({"my_sku": DEMO[1], "competitor_sku": "COMP1",
                                         "competitor_store_id": "S1", "confidence": 100})
    await db.match_blacklist.insert_one({"my_sku": DEMO[0], "competitor_sku": "C2"})
    await db.my_products.insert_one({"sku": DEMO[2], "price": 5.0})
    await db.alerts.insert_one({"id": "a1", "product_sku": DEMO[0], "alert_type": "price"})
    await db.alert_events.insert_one({"sku": DEMO[0], "product_sku": DEMO[0], "alert_type": "price"})
    # real product + its references — must survive untouched
    await db.products.insert_one({"id": "rp", "sku": REAL_SKU, "name_ar": "منتج حقيقي",
                                  "category": "cat_food", "subcategory": "cat_food_dry"})
    await db.product_snapshots.insert_one({"id": "rs", "sku": REAL_SKU, "product_id": "rp",
                                           "store_id": "S0", "price": 20.0,
                                           "confidence_score": 99, "crawled_at": NOW})
    await db.product_matches.insert_one({"my_sku": "MYSKU2", "competitor_sku": REAL_SKU,
                                         "competitor_store_id": "S0", "confidence": 100})


def _stub_recomputes(calls):
    orig = (server.recompute_all_store_metrics, server.maybe_recompute_dashboard_cache,
            server.maybe_recompute_page_caches)

    async def _metrics(db):
        calls.append("metrics")
        return {"stores": 0}

    async def _dash(db, force=False, **kw):
        calls.append("dash")
        return {"ok": 1}

    async def _pages(db, force=False, **kw):
        calls.append("pages")
        return {"ok": 1}
    server.recompute_all_store_metrics = _metrics
    server.maybe_recompute_dashboard_cache = _dash
    server.maybe_recompute_page_caches = _pages
    return orig


def test_dry_run_reports_without_writing():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        rep = await server.demo_cleanup(dry_run=True, user=SUPER)
        assert rep["dry_run"] is True and rep["guard"]["ok"] is True
        assert rep["demo_products"] == 3
        assert rep["by_category"] == {"cat_food_dry": 3}
        assert rep["cascade_counts"]["product_snapshots"] == 3
        assert rep["cascade_counts"]["product_matches"] == 2      # both directions
        assert rep["cascade_counts"]["match_blacklist"] == 1
        assert rep["cascade_counts"]["my_products"] == 1
        assert rep["cascade_counts"]["alerts"] == 1
        assert rep["cascade_counts"]["alert_events"] == 1
        assert rep["before"]["my_products_total"] == 1
        assert "after" not in rep and "backups" not in rep
        # nothing was deleted
        assert await db.products.count_documents({}) == 4
        assert await db.product_snapshots.count_documents({}) == 4
        # non-admin rejected
        try:
            await server.demo_cleanup(dry_run=True, user={"role": "viewer", "email": "v@v"})
            raise AssertionError("viewer should be rejected")
        except HTTPException as e:
            assert e.status_code == 403

        # iter42 — GET route: dry run allowed, destructive run REJECTED (GET
        # must never delete; the real run is POST-only)
        rep_get = await server.demo_cleanup_get(dry_run=True, user=SUPER)
        assert rep_get["dry_run"] is True and rep_get["demo_products"] == 3
        try:
            await server.demo_cleanup_get(dry_run=False, user=SUPER)
            raise AssertionError("GET with dry_run=false must be rejected")
        except HTTPException as e:
            assert e.status_code == 405 and "POST" in e.detail
        # ...and nothing was deleted by any of the above
        assert await db.products.count_documents({}) == 4
    asyncio.run(main())


def test_guard_blocks_real_sku_and_ceiling():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        # (a) detector drift onto a real-crawl-shaped SKU → real run refused
        # EVEN with the correct confirm_count supplied (never overridable)
        extra = ("8595602540877", "x", "x", "x", "cat_food", "cat", 1, 1)
        server.EXTRA_PRODUCT_TEMPLATES.append(extra)
        try:
            rep = await server.demo_cleanup(dry_run=True, user=SUPER)
            assert rep["guard"]["ok"] is False          # dry run REPORTS the violation
            assert rep["guard"]["real_sku_match"] is True
            live_n = rep["guard"]["confirm_count_required"]
            try:
                await server.demo_cleanup(dry_run=False, confirm_count=live_n, user=SUPER)
                raise AssertionError("real run must refuse on real-SKU match even with correct confirm_count")
            except HTTPException as e:
                assert e.status_code == 409 and "real-crawl-shaped" in e.detail
        finally:
            server.EXTRA_PRODUCT_TEMPLATES.remove(extra)
        # real product untouched by the refused run
        assert await db.products.count_documents({"sku": REAL_SKU}) == 1

        # (b) confirm-count contract: missing or mismatched → 409, nothing deleted
        for wrong in (None, 2, 4, 0):
            try:
                await server.demo_cleanup(dry_run=False, confirm_count=wrong, user=SUPER)
                raise AssertionError(f"real run must refuse on confirm_count={wrong}")
            except HTTPException as e:
                assert e.status_code == 409 and "confirm_count" in e.detail
        assert await db.products.count_documents({}) == 4

        # (c) catastrophe cap: >1000 refuses regardless of confirm_count
        fakes = [(f"FAKE-DEMO-{i}", "x", "x", "x", "cat_food", "cat", 1, 1) for i in range(1005)]
        server.EXTRA_PRODUCT_TEMPLATES.extend(fakes)
        try:
            await db.products.insert_many(
                [{"id": f"f{i}", "sku": f"FAKE-DEMO-{i}", "name_ar": "x", "category": "toys"}
                 for i in range(1005)])
            try:
                await server.demo_cleanup(dry_run=False, confirm_count=1008, user=SUPER)
                raise AssertionError("real run must refuse above the catastrophe cap")
            except HTTPException as e:
                assert e.status_code == 409 and "catastrophe cap" in e.detail
        finally:
            for f in fakes:
                server.EXTRA_PRODUCT_TEMPLATES.remove(f)
            await db.products.delete_many({"sku": {"$in": [f"FAKE-DEMO-{i}" for i in range(1005)]}})
    asyncio.run(main())


def test_real_run_backs_up_cascades_and_recomputes():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        calls = []
        orig = _stub_recomputes(calls)
        try:
            rep = await server.demo_cleanup(dry_run=False, confirm_count=3, user=SUPER)
        finally:
            (server.recompute_all_store_metrics, server.maybe_recompute_dashboard_cache,
             server.maybe_recompute_page_caches) = orig

        ts = rep["backup_timestamp"]
        # backups contain every affected doc (counts == the dry-run cascade counts)
        assert rep["backups"]["products"]["docs"] == 3
        assert rep["backups"]["product_matches"]["docs"] == 2
        b_prod = await db[f"demo_cleanup_backup_{ts}_products"].count_documents({})
        assert b_prod == 3
        manifest = await db[f"demo_cleanup_backup_{ts}_manifest"].find_one({"_id": "manifest"})
        assert manifest and set(manifest["skus"]) == set(DEMO)

        # ZERO orphan references in any cascade collection
        skus = set(DEMO)
        ids = {"pid0", "pid1", "pid2"}
        for coll, q in server._demo_cascade_queries(skus, ids):
            assert await db[coll].count_documents(q) == 0, f"orphans left in {coll}"

        # real product + its references survive
        assert await db.products.count_documents({"sku": REAL_SKU}) == 1
        assert await db.product_snapshots.count_documents({"sku": REAL_SKU}) == 1
        assert await db.product_matches.count_documents({"competitor_sku": REAL_SKU}) == 1

        # recomputes triggered; before/after reported
        assert calls == ["metrics", "dash", "pages"]
        assert rep["before"]["subcategory_counts"].get("cat_food_dry") == 4
        assert rep["after"]["subcategory_counts"].get("cat_food_dry") == 1
        assert rep["after"]["my_products_total"] == 0
        assert rep["after"]["total_matches"] == 1
    asyncio.run(main())


if __name__ == "__main__":
    test_dry_run_reports_without_writing()
    test_guard_blocks_real_sku_and_ceiling()
    test_real_run_backs_up_cascades_and_recomputes()
    print("PASS: iter41 demo cleanup")
