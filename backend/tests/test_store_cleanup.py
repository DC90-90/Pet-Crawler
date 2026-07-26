"""store-cleanup endpoint — delete every competitor store NOT in the 11-store
keep-list, plus all of its data.

Covers: keep-list resolves against normalized domains (scheme/www/case/trailing
slash), delete set = everything not kept; dry run reports without writing; the
hard guards (own-store never deleted, keep-list must resolve to exactly 11, a
keep-domain matching zero stores aborts with a clear message, 50-store
catastrophe cap, confirm_count contract); backups written BEFORE delete; the
cascade leaves ZERO orphan store references; kept stores + own-store data
survive; recomputes triggered."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_store_cleanup")
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}
NOW = datetime.now(timezone.utc)

# 11 keep stores — domains formatted with scheme/www/case/slash to exercise the
# normalizer. The own store (pets-houses.com) is one of the 11.
KEEP = [
    ("k_aleef",    "aleef",       "https://aleef.com/",  False),
    ("k_petsy",    "Petsy",       "www.petsysa.com",     False),
    ("k_zarafa",   "Zarafa",      "zarafaksa.com",       False),
    ("k_caty",     "Caty",        "caty-store.com",      False),
    ("k_cutepets", "CutePets",    "CUTEPETS.COM.SA",     False),
    ("k_hamtaro",  "Hamtaro",     "hamtaro.sa",          False),
    ("k_hobba",    "Hobba",       "hobbapet.com",        False),
    ("k_lana",     "Lana Pets",   "lanapets.com",        False),
    ("k_mowkly",   "Mowkly",      "mowkly.com",          False),
    ("k_panda",    "Panda Store", "matjarpanda.com",     False),
    ("own",        "Pets Houses", "pets-houses.com",     True),
]
DELETE = [
    ("d_cutecat", "CuteCat",               "cutecat.com.sa"),
    ("d_petzone", "Petzone",               "petzone.com"),
    ("d_testreg", "TEST_Regression_Store", "test-regression.example.com"),
]
DELETE_IDS = {d[0] for d in DELETE}

STORE_ID_COLLS = ["product_snapshots", "sku_store_coverage", "sku_sales_daily",
                  "metric_daily_rollups", "crawl_logs", "alerts", "my_products",
                  "product_matches"]
DOMAIN_COLLS = ["market_leaderboard", "market_intelligence_baseline"]


async def _seed(db):
    for c in STORE_ID_COLLS + DOMAIN_COLLS + ["stores", "metric_rollup_meta"]:
        await db[c].delete_many({})
    for name in await db.list_collection_names():
        if name.startswith("store_cleanup_backup_"):
            await db.drop_collection(name)

    for sid, name, domain, is_own in KEEP:
        doc = {"id": sid, "name": name, "domain": domain, "is_active": True}
        if is_own:
            doc["is_own_store"] = True
        await db.stores.insert_one(doc)
    for sid, name, domain in DELETE:
        await db.stores.insert_one({"id": sid, "name": name, "domain": domain, "is_active": True})

    # per DELETE store: one referencing doc in every store_id-keyed collection
    for i, (sid, _n, _d) in enumerate(DELETE):
        sku = f"DEL{i}"
        await db.product_snapshots.insert_one({"id": f"ps_{sid}", "sku": sku, "store_id": sid,
                                               "price": 10.0, "confidence_score": 99, "crawled_at": NOW})
        await db.sku_store_coverage.insert_one({"_id": f"{sku}|{sid}", "sku": sku, "store_id": sid,
                                                "last_priced_at": NOW, "last_seen_any_at": NOW})
        await db.sku_sales_daily.insert_one({"_id": f"{sid}|{sku}|d", "store_id": sid, "sku": sku,
                                             "date": "2099-01-01", "units_sold": 1})
        await db.metric_daily_rollups.insert_one({"store_id": sid, "date": "2099-01-01", "conf_count": 1})
        await db.crawl_logs.insert_one({"id": f"cl_{sid}", "store_id": sid, "store_name": _n})
        await db.alerts.insert_one({"id": f"al_{sid}", "store_id": sid, "product_sku": sku})
        await db.product_matches.insert_one({"my_sku": "MINE", "competitor_sku": sku,
                                             "competitor_store_id": sid, "confidence": 99})

    # KEPT-store data that MUST survive (a keep store's snapshot + a match onto it)
    await db.product_snapshots.insert_one({"id": "ps_keep", "sku": "KEEP1", "store_id": "k_aleef",
                                           "price": 5.0, "confidence_score": 99, "crawled_at": NOW})
    await db.sku_store_coverage.insert_one({"_id": "KEEP1|k_aleef", "sku": "KEEP1", "store_id": "k_aleef",
                                            "last_priced_at": NOW, "last_seen_any_at": NOW})
    await db.product_matches.insert_one({"my_sku": "MINE", "competitor_sku": "KEEP1",
                                         "competitor_store_id": "k_aleef", "confidence": 99})
    # own-store data (my_products) — never touched
    await db.my_products.insert_one({"sku": "OWN1", "store_id": "own", "is_own_store": True, "price": 7.0})

    # domain-keyed baselines: one for a DELETE store, one for a KEEP store, one external
    await db.market_leaderboard.insert_one({"store_domain": "cutecat.com.sa", "rank": 1})    # delete
    await db.market_leaderboard.insert_one({"store_domain": "aleef.com", "rank": 2})          # keep
    await db.market_leaderboard.insert_one({"store_domain": "external-store.com", "rank": 3}) # external
    await db.market_intelligence_baseline.insert_one({"store_domain": "petzone.com"})         # delete
    await db.market_intelligence_baseline.insert_one({"store_domain": "pets-houses.com"})      # keep/own


def _stub_recomputes(calls):
    orig = (server.recompute_all_store_metrics, server.maybe_recompute_dashboard_cache,
            server.maybe_recompute_page_caches)

    async def _metrics(db):
        calls.append("metrics"); return {"stores": 0}

    async def _dash(db, force=False, **kw):
        calls.append("dash"); return {"ok": 1}

    async def _pages(db, force=False, **kw):
        calls.append("pages"); return {"ok": 1}
    server.recompute_all_store_metrics = _metrics
    server.maybe_recompute_dashboard_cache = _dash
    server.maybe_recompute_page_caches = _pages
    return orig


def _restore_recomputes(orig):
    (server.recompute_all_store_metrics, server.maybe_recompute_dashboard_cache,
     server.maybe_recompute_page_caches) = orig


def test_normalize_domain():
    n = server._normalize_store_domain
    assert n("https://Aleef.com/") == "aleef.com"
    assert n("www.petsysa.com") == "petsysa.com"
    assert n("http://www.hamtaro.sa//") == "hamtaro.sa"
    assert n("  CUTEPETS.COM.SA ") == "cutepets.com.sa"
    assert n(None) == "" and n("") == ""
    print("PASS: domain normalization")


def test_dry_run_resolves_and_reports_without_writing():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        before_stores = await db.stores.count_documents({})

        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        assert rep["dry_run"] is True
        assert rep["guard"]["ok"] is True, rep["guard"]
        assert rep["guard"]["keep_resolved_count"] == 11
        assert rep["guard"]["own_store_in_delete_set"] is False
        assert rep["guard"]["confirm_count_required"] == 3
        assert rep["delete_set_size"] == 3
        assert {r["store_id"] for r in rep["delete_set"]} == DELETE_IDS
        # every keep-list entry resolved to exactly one store
        for kr in rep["keep_list_resolution"]:
            assert len(kr["matched_store_ids"]) == 1, kr
        # cascade counts (one referencing doc per delete store)
        cc = rep["cascade_counts"]
        assert cc["product_snapshots"] == 3
        assert cc["sku_store_coverage"] == 3
        assert cc["sku_sales_daily"] == 3
        assert cc["metric_daily_rollups"] == 3
        assert cc["crawl_logs"] == 3
        assert cc["alerts"] == 3
        assert cc["product_matches"] == 3
        assert cc["my_products"] == 0                      # own-store only
        assert cc["stores"] == 3
        assert cc["market_leaderboard"] == 1               # only cutecat.com.sa
        assert cc["market_intelligence_baseline"] == 1     # only petzone.com
        assert "after" not in rep and "backups" not in rep

        # nothing written
        assert await db.stores.count_documents({}) == before_stores
        assert await db.product_snapshots.count_documents({}) == 4
        assert await db.market_leaderboard.count_documents({}) == 3

        # non-admin rejected
        try:
            await server.store_cleanup(dry_run=True, user={"role": "viewer", "email": "v@v"})
            raise AssertionError("viewer should be 403")
        except HTTPException as e:
            assert e.status_code == 403

        # GET is dry-run only
        rep_get = await server.store_cleanup_get(dry_run=True, user=SUPER)
        assert rep_get["dry_run"] is True and rep_get["delete_set_size"] == 3
        try:
            await server.store_cleanup_get(dry_run=False, user=SUPER)
            raise AssertionError("GET dry_run=false must be 405")
        except HTTPException as e:
            assert e.status_code == 405 and "POST" in e.detail
        assert await db.stores.count_documents({}) == before_stores
    asyncio.run(main())


def test_own_store_never_in_delete_set():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        # an own-store whose domain is NOT in the keep-list would land in the
        # delete set → hard guard must abort (keep-list still resolves to 11)
        await db.stores.insert_one({"id": "own_stray", "name": "Stray Own",
                                    "domain": "not-in-keeplist.com", "is_own_store": True, "is_active": True})
        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        assert rep["guard"]["ok"] is False
        assert rep["guard"]["own_store_in_delete_set"] is True
        assert rep["guard"]["keep_resolved_count"] == 11
        n = rep["guard"]["confirm_count_required"]
        try:
            await server.store_cleanup(dry_run=False, confirm_count=n, user=SUPER)
            raise AssertionError("real run must refuse when an own-store is in the delete set")
        except HTTPException as e:
            assert e.status_code == 409 and "own-store" in e.detail
        # nothing deleted
        assert await db.stores.count_documents({}) == len(KEEP) + len(DELETE) + 1
    asyncio.run(main())


def test_keeplist_zero_match_aborts_with_named_entry():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        # a keep store missing (its domain resolves to zero stores) — we must
        # STOP so we never delete a store we meant to keep
        await db.stores.delete_one({"id": "k_zarafa"})
        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        assert rep["guard"]["ok"] is False
        assert rep["guard"]["keep_resolved_count"] == 10
        assert any("did not resolve" in r and "Zarafa" in r for r in rep["guard"]["reasons"]), rep["guard"]["reasons"]
        zarafa = next(k for k in rep["keep_list_resolution"] if k["keep_name"] == "Zarafa")
        assert zarafa["matched_store_ids"] == []
        n = rep["guard"]["confirm_count_required"]
        try:
            await server.store_cleanup(dry_run=False, confirm_count=n, user=SUPER)
            raise AssertionError("real run must refuse when a keep-domain matches zero stores")
        except HTTPException as e:
            assert e.status_code == 409 and "did not resolve" in e.detail and "Zarafa" in e.detail
        assert await db.stores.count_documents({}) == len(KEEP) + len(DELETE) - 1
    asyncio.run(main())


def test_catastrophe_cap_and_confirm_count():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        # confirm_count contract: mismatch/missing → 409, nothing deleted
        for wrong in (None, 2, 4, 0):
            try:
                await server.store_cleanup(dry_run=False, confirm_count=wrong, user=SUPER)
                raise AssertionError(f"must refuse confirm_count={wrong}")
            except HTTPException as e:
                assert e.status_code == 409 and "confirm_count" in e.detail
        assert await db.stores.count_documents({}) == len(KEEP) + len(DELETE)

        # catastrophe cap: push the delete set above 50 store docs
        await db.stores.insert_many(
            [{"id": f"junk{i}", "name": f"Junk{i}", "domain": f"junk{i}.example", "is_active": True}
             for i in range(51)])
        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        assert rep["guard"]["ok"] is False
        assert rep["delete_set_size"] == 3 + 51
        assert any("catastrophe cap" in r for r in rep["guard"]["reasons"])
        try:
            await server.store_cleanup(dry_run=False, confirm_count=54, user=SUPER)
            raise AssertionError("real run must refuse above the catastrophe cap")
        except HTTPException as e:
            assert e.status_code == 409 and "catastrophe cap" in e.detail
    asyncio.run(main())


def test_real_run_backs_up_cascades_and_leaves_no_orphans():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        calls = []
        orig = _stub_recomputes(calls)
        try:
            rep = await server.store_cleanup(dry_run=False, confirm_count=3, user=SUPER)
        finally:
            _restore_recomputes(orig)

        ts = rep["backup_timestamp"]
        # backups written before delete, one per referencing collection
        assert rep["backups"]["stores"]["docs"] == 3
        assert rep["backups"]["product_snapshots"]["docs"] == 3
        assert rep["backups"]["product_matches"]["docs"] == 3
        assert rep["backups"]["market_leaderboard"]["docs"] == 1
        assert await db[f"store_cleanup_backup_{ts}_stores"].count_documents({}) == 3
        manifest = await db[f"store_cleanup_backup_{ts}_manifest"].find_one({"_id": "manifest"})
        assert manifest and set(manifest["delete_store_ids"]) == DELETE_IDS

        # ZERO orphan store references anywhere
        for coll in ["product_snapshots", "sku_store_coverage", "sku_sales_daily",
                     "metric_daily_rollups", "crawl_logs", "alerts", "my_products"]:
            assert await db[coll].count_documents({"store_id": {"$in": sorted(DELETE_IDS)}}) == 0, coll
        assert await db.product_matches.count_documents({"competitor_store_id": {"$in": sorted(DELETE_IDS)}}) == 0
        assert await db.stores.count_documents({"id": {"$in": sorted(DELETE_IDS)}}) == 0

        # kept stores + their data survive
        assert await db.stores.count_documents({}) == 11
        assert await db.product_snapshots.count_documents({"store_id": "k_aleef"}) == 1
        assert await db.product_matches.count_documents({"competitor_store_id": "k_aleef"}) == 1
        # own-store survives + its my_products untouched
        assert await db.stores.count_documents({"is_own_store": True}) == 1
        assert await db.my_products.count_documents({"store_id": "own"}) == 1

        # domain cascade: only the delete-store baselines removed
        lb = {d["store_domain"] async for d in db.market_leaderboard.find({}, {"_id": 0, "store_domain": 1})}
        assert lb == {"aleef.com", "external-store.com"}       # cutecat.com.sa removed
        mib = {d["store_domain"] async for d in db.market_intelligence_baseline.find({}, {"_id": 0, "store_domain": 1})}
        assert mib == {"pets-houses.com"}                       # petzone.com removed

        assert calls == ["metrics", "dash", "pages"]
        assert rep["after"]["stores_total"] == 11
    asyncio.run(main())


if __name__ == "__main__":
    test_normalize_domain()
    test_dry_run_resolves_and_reports_without_writing()
    test_own_store_never_in_delete_set()
    test_keeplist_zero_match_aborts_with_named_entry()
    test_catastrophe_cap_and_confirm_count()
    test_real_run_backs_up_cascades_and_leaves_no_orphans()
    print("PASS: store cleanup")
