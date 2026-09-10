"""iter48 — /api/admin/store-cleanup: trim the registry to the 11 keep-list stores.

Same safety contract as demo-cleanup: dry-run GET, destructive POST behind an
exact confirm_count, backup-before-delete, full cascade, recompute.

The three hard guards are the point of this suite — each one must abort with 409
and must NOT be overridable by passing a matching confirm_count:

  1. an is_own_store store landing in the delete set  (Pets houses)
  2. the keep-list not resolving to exactly 11 live stores, naming every
     zero-match domain so a format mismatch can't delete a store we meant to keep
  3. the 50-store catastrophe cap
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_store_cleanup"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_store_cleanup"
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}

# the 11 that stay, spelled EXACTLY as the live registry does — deliberately
# with scheme/www/trailing-slash noise, which normalization must absorb
KEEP = [
    ("Aleef", "https://aleef.com/"),
    ("Petsy", "www.petsysa.com"),
    ("Zarafa", "zarafaksa.com"),
    ("Caty", "http://caty-store.com"),
    ("CutePets", "cutepets.com.sa"),
    ("Hamtaro", "hamtaro.sa"),
    ("Hobba", "hobbapet.com"),
    ("Lana Pets", "lanapets.com"),
    ("Mowkly", "mowkly.com"),
    ("Panda Store", "matjarpanda.com"),
    ("Pets Houses", "pets-houses.com"),          # is_own_store
]
DROP = [("Waggy", "waggy.sa"), ("Cat Fans", "catfansksa.com"),
        ("Cat City", "catcity11.com"), ("CuteCat", "cutecat.com.sa")]

CASCADE_COLLECTIONS = [c for c, _ in server._store_cascade_queries({"x"}, {"x"}, {"x"})]


def _store(i, name, domain, own=False):
    return {"id": f"st-{i}", "name": name, "domain": domain, "platform": "zid",
            "is_active": True, "is_own_store": own, "last_crawled_at": "2026-07-20T00:00:00Z"}


async def _seed(db, keep=KEEP, drop=DROP):
    for c in ("stores", "product_snapshots", "product_matches", "match_blacklist",
              "sku_store_coverage", "sku_sales_daily", "metric_daily_rollups",
              "crawl_logs", "otp_requests", "alerts", "alert_events", "proxy_usage",
              "market_leaderboard", "market_intelligence_baseline", "products"):
        await db[c].delete_many({})
    for name in await db.list_collection_names():
        if name.startswith("store_cleanup_backup_"):
            await db[name].drop()

    stores = []
    for i, (name, domain) in enumerate(keep):
        stores.append(_store(i, name, domain, own=(name == "Pets Houses")))
    for j, (name, domain) in enumerate(drop):
        stores.append(_store(100 + j, name, domain))
    await db.stores.insert_many(stores)

    # one referencing document per cascaded collection, for a KEPT store and a
    # DROPPED store, so the cascade must remove exactly half of them
    keeper, dropper = stores[0], stores[len(keep)]
    for s, tag in ((keeper, "keep"), (dropper, "drop")):
        sid, dom, nm = s["id"], server.normalize_store_domain(s["domain"]), s["name"]
        await db.product_snapshots.insert_one({"id": f"sn-{tag}", "sku": f"SKU-{tag}",
                                               "store_id": sid, "store_name": nm, "price": 10})
        await db.product_matches.insert_one({"my_sku": "M1", "competitor_sku": f"C-{tag}",
                                             "competitor_store_id": sid})
        await db.match_blacklist.insert_one({"my_sku": "M1", "competitor_sku": f"B-{tag}",
                                             "competitor_store_id": sid})
        await db.sku_store_coverage.insert_one({"_id": f"{tag}|{sid}", "sku": f"SKU-{tag}",
                                                "store_id": sid})
        await db.sku_sales_daily.insert_one({"store_id": sid, "sku": f"SKU-{tag}", "date": "2026-07-01"})
        await db.metric_daily_rollups.insert_one({"_id": f"{sid}|2026-07-01", "store_id": sid,
                                                  "date": "2026-07-01"})
        await db.crawl_logs.insert_one({"id": f"cl-{tag}", "store_id": sid, "store_name": nm})
        await db.otp_requests.insert_one({"id": f"otp-{tag}", "store_id": sid, "status": "pending"})
        await db.alerts.insert_one({"id": f"al-{tag}", "store_id": sid, "product_sku": "M1"})
        await db.alert_events.insert_one({"id": f"ev-{tag}", "store_name": nm, "sku": "M1"})
        await db.proxy_usage.insert_one({"store_id": sid, "store_domain": dom, "bytes_estimate": 1})
        await db.market_leaderboard.insert_one({"rank": 1, "store_domain": dom})
        await db.market_intelligence_baseline.insert_one({"store_domain": dom})
        await db.products.insert_one({"id": f"p-{tag}", "sku": f"SKU-{tag}"})
    server.db = db
    return stores


def _patch_recompute():
    orig = (server.recompute_all_store_metrics, server.maybe_recompute_dashboard_cache,
            server.maybe_recompute_page_caches, server.unregister_crawl_job)
    calls = {"metrics": 0, "dashboard": 0, "pages": 0, "unregistered": []}

    async def _m(db):
        calls["metrics"] += 1
        return {"stores": 0}

    async def _d(db, min_interval_secs=600, force=False):
        calls["dashboard"] += 1
        return True

    async def _p(db, min_interval_secs=600, force=False):
        calls["pages"] += 1
        return True

    def _u(sid):
        calls["unregistered"].append(sid)

    server.recompute_all_store_metrics = _m
    server.maybe_recompute_dashboard_cache = _d
    server.maybe_recompute_page_caches = _p
    server.unregister_crawl_job = _u
    return orig, calls


def _unpatch(orig):
    (server.recompute_all_store_metrics, server.maybe_recompute_dashboard_cache,
     server.maybe_recompute_page_caches, server.unregister_crawl_job) = orig


# ── normalization ────────────────────────────────────────────────────────────
def test_domain_normalization():
    n = server.normalize_store_domain
    for raw in ("aleef.com", "https://aleef.com", "http://aleef.com/", "www.aleef.com",
                "https://www.aleef.com/", "  HTTPS://WWW.Aleef.com/  ",
                "https://aleef.com/products/15"):
        assert n(raw) == "aleef.com", raw
    assert n("") == "" and n(None) == ""
    # distinct domains stay distinct
    assert n("cutepets.com.sa") != n("cutecat.com.sa")


# ── dry run ──────────────────────────────────────────────────────────────────
def test_dry_run_resolves_keep_list_and_writes_nothing():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        rep = await server.store_cleanup_get(dry_run=True, user=SUPER)

        assert rep["dry_run"] is True
        assert rep["live_stores_total"] == 15
        assert rep["guard"]["ok"] is True, rep["guard"]["reasons"]
        assert rep["guard"]["keep_list_resolved_stores"] == 11
        assert len(rep["keep_list"]) == 11
        assert all(k["matched"] == 1 and k["matched_on"] == "domain" for k in rep["keep_list"])
        # every keep-list row carries the resolved store_id
        assert all(len(k["store_ids"]) == 1 for k in rep["keep_list"])

        assert rep["delete_count"] == 4 == rep["guard"]["confirm_count_required"]
        assert {d["domain"] for d in rep["delete_set"]} == {d for _, d in DROP}
        # per-store product + snapshot counts are surfaced
        dropped = [d for d in rep["delete_set"] if d["domain"] == "waggy.sa"][0]
        assert dropped["snapshots"] == 1 and dropped["products"] == 1

        # cascade covers every collection with a store reference, one doc each
        for coll in CASCADE_COLLECTIONS:
            assert coll in rep["cascade_counts"], coll
        assert rep["cascade_counts"]["stores"] == 4
        for coll in ("product_snapshots", "product_matches", "match_blacklist",
                     "sku_store_coverage", "sku_sales_daily", "metric_daily_rollups",
                     "crawl_logs", "otp_requests", "alerts", "alert_events",
                     "proxy_usage", "market_leaderboard", "market_intelligence_baseline"):
            assert rep["cascade_counts"][coll] == 1, (coll, rep["cascade_counts"][coll])
        # collections deliberately left alone are declared with a reason
        assert "products" in rep["cascade_skipped"] and rep["cascade_skipped"]["products"]

        # ZERO writes
        assert await db.stores.count_documents({}) == 15
        assert await db.product_snapshots.count_documents({}) == 2
        assert not [c for c in await db.list_collection_names()
                    if c.startswith("store_cleanup_backup_")]
    asyncio.run(main())


def test_get_is_dry_run_only_and_requires_super_admin():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        try:
            await server.store_cleanup_get(dry_run=False, user=SUPER)
            raise AssertionError("GET with dry_run=false must be rejected")
        except HTTPException as e:
            assert e.status_code == 405, e.status_code
        try:
            await server.store_cleanup(dry_run=True, user={"role": "viewer", "email": "v@v"})
            raise AssertionError("viewer must be rejected")
        except HTTPException as e:
            assert e.status_code == 403
        assert await db.stores.count_documents({}) == 15
    asyncio.run(main())


# ── guard 1: the own store is never deletable ────────────────────────────────
def test_own_store_never_in_delete_set():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        # the own store's domain is re-pointed, so the keep-list can no longer
        # resolve it by domain — it must NOT silently fall into the delete set
        await _seed(db)
        await db.stores.update_one({"is_own_store": True},
                                   {"$set": {"domain": "pets-houses.example"}})

        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        # matched by NAME, so it stays out of the delete set entirely
        own = [k for k in rep["keep_list"] if k["is_own_store"]]
        assert own and own[0]["matched_on"] == "name", rep["keep_list"]
        assert not any(d["name"] == "Pets Houses" for d in rep["delete_set"])

        # ...and if it somehow does land there (name changed too), the guard fires
        await db.stores.update_one({"is_own_store": True},
                                   {"$set": {"name": "Renamed Own Store"}})
        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        assert any(d["name"] == "Renamed Own Store" for d in rep["delete_set"])
        assert rep["guard"]["ok"] is False
        assert rep["guard"]["own_store_in_delete_set"], rep["guard"]
        assert any("is_own_store" in r for r in rep["guard"]["reasons"]), rep["guard"]["reasons"]

        # the guard is NOT overridable — even with a perfectly matching confirm_count
        n = rep["delete_count"]
        try:
            await server.store_cleanup(dry_run=False, confirm_count=n, user=SUPER)
            raise AssertionError("own-store guard must abort the real run")
        except HTTPException as e:
            assert e.status_code == 409 and "is_own_store" in e.detail, e.detail
        assert await db.stores.count_documents({}) == 15      # nothing deleted
    asyncio.run(main())


# ── guard 2: keep-list must resolve to exactly 11 ────────────────────────────
def test_keep_list_not_eleven_aborts():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        # a duplicate row for one keep domain -> 12 resolved live stores
        await _seed(db)
        await db.stores.insert_one(_store(900, "Aleef Duplicate", "aleef.com"))
        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        assert rep["guard"]["keep_list_resolved_stores"] == 12
        assert rep["guard"]["ok"] is False
        assert any("resolved to 12" in r for r in rep["guard"]["reasons"]), rep["guard"]["reasons"]
        try:
            await server.store_cleanup(dry_run=False, confirm_count=rep["delete_count"], user=SUPER)
            raise AssertionError("keep-list count guard must abort")
        except HTTPException as e:
            assert e.status_code == 409 and "expected 11" in e.detail, e.detail
        assert await db.stores.count_documents({}) == 16
    asyncio.run(main())


def test_zero_match_keep_domain_aborts_and_names_it():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        # hobbapet.com is gone from the registry entirely — a domain-format
        # mismatch looks exactly like this, and must never delete silently
        await _seed(db, keep=[k for k in KEEP if k[1] != "hobbapet.com"])
        rep = await server.store_cleanup(dry_run=True, user=SUPER)

        assert rep["guard"]["ok"] is False
        un = rep["guard"]["keep_list_unresolved"]
        assert [u["keep_domain"] for u in un] == ["hobbapet.com"], un
        assert un[0]["keep_name"] == "Hobba" and un[0]["matched"] == 0
        # the reason text names the offending domain
        assert any("hobbapet.com" in r for r in rep["guard"]["reasons"]), rep["guard"]["reasons"]

        try:
            await server.store_cleanup(dry_run=False, confirm_count=rep["delete_count"], user=SUPER)
            raise AssertionError("zero-match keep-domain must abort")
        except HTTPException as e:
            assert e.status_code == 409 and "hobbapet.com" in e.detail, e.detail
        assert await db.stores.count_documents({}) == 14
    asyncio.run(main())


# ── guard 3: catastrophe cap ─────────────────────────────────────────────────
def test_catastrophe_cap_aborts_above_fifty():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        await db.stores.insert_many([_store(200 + i, f"Junk {i}", f"junk{i}.example")
                                     for i in range(50)])
        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        assert rep["delete_count"] == 54
        assert rep["guard"]["ok"] is False
        assert any("catastrophe cap" in r for r in rep["guard"]["reasons"]), rep["guard"]["reasons"]
        try:
            await server.store_cleanup(dry_run=False, confirm_count=54, user=SUPER)
            raise AssertionError("catastrophe cap must abort")
        except HTTPException as e:
            assert e.status_code == 409 and "catastrophe cap" in e.detail
        assert await db.stores.count_documents({}) == 65
    asyncio.run(main())


# ── confirm_count contract ───────────────────────────────────────────────────
def test_confirm_count_must_match_exactly():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        for bad in (None, 0, 3, 5):
            try:
                await server.store_cleanup(dry_run=False, confirm_count=bad, user=SUPER)
                raise AssertionError(f"confirm_count={bad} must be rejected")
            except HTTPException as e:
                assert e.status_code == 409 and "confirm_count" in e.detail
        assert await db.stores.count_documents({}) == 15
    asyncio.run(main())


# ── real run ─────────────────────────────────────────────────────────────────
def test_real_run_backs_up_before_delete_and_leaves_no_orphans():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        orig, calls = _patch_recompute()
        try:
            rep = await server.store_cleanup(dry_run=False, confirm_count=4, user=SUPER)
        finally:
            _unpatch(orig)

        assert rep["dry_run"] is False and rep["delete_count"] == 4
        ts = rep["backup_timestamp"]

        # ── backups written BEFORE the delete: every cascaded collection has a
        # backup collection holding exactly what was removed ──
        for coll in CASCADE_COLLECTIONS:
            b = rep["backups"][coll]
            assert b["backup_collection"] == f"store_cleanup_backup_{ts}_{coll}"
            assert await db[b["backup_collection"]].count_documents({}) == b["docs"], coll
            assert b["docs"] == 1 if coll != "stores" else b["docs"] == 4
        manifest = await db[f"store_cleanup_backup_{ts}_manifest"].find_one({"_id": "manifest"})
        assert manifest and len(manifest["store_ids"]) == 4
        assert set(manifest["domains"]) == {d for _, d in DROP}
        # the backup is a faithful copy — the dropped snapshot is recoverable
        bs = await db[f"store_cleanup_backup_{ts}_product_snapshots"].find_one({"id": "sn-drop"})
        assert bs and bs["sku"] == "SKU-drop"

        # ── the delete itself ──
        assert await db.stores.count_documents({}) == 11
        assert {s["domain"] for s in await db.stores.find({}, {"_id": 0}).to_list(None)} \
            == {d for _, d in KEEP}
        assert rep["after"]["stores"] == 11

        # ── no orphan store references anywhere ──
        assert rep["orphan_store_references"] == {c: 0 for c in CASCADE_COLLECTIONS}, \
            rep["orphan_store_references"]
        live_ids = {s["id"] for s in await db.stores.find({}, {"_id": 0, "id": 1}).to_list(None)}
        for coll, field in (("product_snapshots", "store_id"), ("sku_store_coverage", "store_id"),
                            ("sku_sales_daily", "store_id"), ("metric_daily_rollups", "store_id"),
                            ("crawl_logs", "store_id"), ("otp_requests", "store_id"),
                            ("alerts", "store_id"), ("proxy_usage", "store_id"),
                            ("product_matches", "competitor_store_id"),
                            ("match_blacklist", "competitor_store_id")):
            async for d in db[coll].find({}, {"_id": 0, field: 1}):
                assert d.get(field) in live_ids, (coll, d)

        # kept-store data is untouched
        assert await db.product_snapshots.count_documents({"id": "sn-keep"}) == 1
        assert await db.product_matches.count_documents({}) == 1

        # ── recompute ran, and the dead stores' crawl jobs were unregistered ──
        assert calls["metrics"] == 1 and calls["dashboard"] == 1 and calls["pages"] == 1
        assert len(calls["unregistered"]) == 4
        assert rep["recompute"]["crawl_jobs_unregistered"] == 4

        # products is SKU-keyed and NOT cascaded — reported, not silently dropped
        assert rep["orphan_products_not_deleted"] == 1
        assert await db.products.count_documents({}) == 2
    asyncio.run(main())


# ── iter49: destructive-path robustness ──────────────────────────────────────
# Production symptom: POST ?dry_run=false&confirm_count=37 returned a bare 500
# with NOTHING deleted, while the dry run was fine. The destructive path read
# each collection with find(q).to_list(length=None) and handed the whole result
# to one insert_many — ~63k CuteCat snapshots in a single round trip, against a
# client capped at socketTimeoutMS=45000.
class _SpyColl:
    """Wraps one Motor collection so a single method can be observed or made to
    fail. Motor builds a NEW collection object on every db[name] access, so
    patching an attribute on db.foo would be silently discarded — the wrapper
    has to sit on the database object instead."""

    def __init__(self, coll, batches, fail_on=None):
        self._c, self._b, self._fail = coll, batches, fail_on

    def __getattr__(self, name):
        return getattr(self._c, name)

    async def insert_many(self, docs, ordered=True):
        self._b.append(len(docs))
        return await self._c.insert_many(docs, ordered=ordered)

    async def delete_many(self, q):
        if self._fail == "delete_many":
            raise OSError("connection closed (socket timeout after 45000ms)")
        return await self._c.delete_many(q)


class _SpyDB:
    def __init__(self, real, target, fail_on=None):
        self._real, self._target, self._fail = real, target, fail_on
        self.batches = []

    def __getitem__(self, name):
        coll = self._real[name]
        return _SpyColl(coll, self.batches, self._fail) if name == self._target else coll

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_backup_is_batched_not_one_giant_insert():
    """The backup must move in bounded batches, so a large collection can never
    be one unbounded round trip again."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        # a "CuteCat-sized" collection, scaled down but well over one batch
        await db.product_snapshots.insert_many(
            [{"id": f"sn-big-{i}", "sku": f"S{i}", "store_id": "st-100", "price": 1}
             for i in range(2500)])

        orig, _ = _patch_recompute()
        try:
            rep = await server.store_cleanup(dry_run=False, confirm_count=4, user=SUPER)
        finally:
            _unpatch(orig)

        ts = rep["backup_timestamp"]
        bcoll = f"store_cleanup_backup_{ts}_product_snapshots"
        # 2500 seeded + 1 from _seed's dropped store = 2501 backed up and deleted
        assert rep["backups"]["product_snapshots"]["docs"] == 2501
        assert rep["backups"]["product_snapshots"]["verified"] is True
        assert await db[bcoll].count_documents({}) == 2501
        assert rep["deleted_counts"]["product_snapshots"] == 2501
        # only the kept store's snapshot survives
        assert await db.product_snapshots.count_documents({}) == 1
        assert rep["orphan_store_references"]["product_snapshots"] == 0
        assert server._STORE_CLEANUP_BATCH == 1000
    asyncio.run(main())


def test_copy_in_batches_respects_the_batch_size():
    """The actual regression guard: 2500 documents must never leave as one
    insert_many, which is what blew the 45s socket cap in production."""
    async def main():
        real = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await real.copy_src.delete_many({})
        await real.copy_dst.delete_many({})
        await real.copy_src.insert_many([{"n": i} for i in range(2500)])

        spy = _SpyDB(real, "copy_dst")
        copied = await server._copy_in_batches(spy, "copy_src", "copy_dst", {}, batch=500)
        assert copied == 2500
        assert spy.batches == [500] * 5, spy.batches         # never one giant insert
        assert await real.copy_dst.count_documents({}) == 2500

        # and the default bound is enforced too
        await real.copy_dst.delete_many({})
        spy2 = _SpyDB(real, "copy_dst")
        await server._copy_in_batches(spy2, "copy_src", "copy_dst", {})
        assert max(spy2.batches) <= server._STORE_CLEANUP_BATCH, spy2.batches
    asyncio.run(main())


def test_backup_failure_aborts_with_the_collection_named_and_deletes_nothing():
    """A backup failure is the safe failure: it must abort before any delete and
    say WHICH collection failed and WHY, not 500 blindly."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        before_stores = await db.stores.count_documents({})
        before_snaps = await db.product_snapshots.count_documents({})

        real_copy = server._copy_in_batches

        async def _boom(db_, src, dst, q, batch=1000, tolerate_duplicates=False):
            if src == "crawl_logs":
                raise OSError("connection closed (socket timeout after 45000ms)")
            return await real_copy(db_, src, dst, q, batch=batch,
                                   tolerate_duplicates=tolerate_duplicates)

        server._copy_in_batches = _boom
        orig, _ = _patch_recompute()
        try:
            await server.store_cleanup(dry_run=False, confirm_count=4, user=SUPER)
            raise AssertionError("expected the backup failure to surface")
        except HTTPException as e:
            assert e.status_code == 500
            d = e.detail
            assert isinstance(d, dict), d
            assert d["phase"] == "backup"
            assert d["collection"] == "crawl_logs"
            assert d["exception"] == "OSError"
            assert "socket timeout" in d["message"]
            assert "nothing was deleted" in d["error"]
            # the collections already backed up are reported, so the operator
            # knows exactly what state the DB is in
            assert "product_snapshots" in d["completed_backups"]
            assert "crawl_logs" not in d["completed_backups"]
            assert d["backup_timestamp"] and d["delete_count"] == 4
        finally:
            server._copy_in_batches = real_copy
            _unpatch(orig)

        # NOTHING deleted — matches the production symptom, now explained
        assert await db.stores.count_documents({}) == before_stores
        assert await db.product_snapshots.count_documents({}) == before_snaps
    asyncio.run(main())


def test_backup_verification_catches_a_short_copy():
    """A backup that silently copies fewer docs than the source holds must abort
    rather than let the delete proceed against an incomplete safety net."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        real_copy = server._copy_in_batches

        async def _short(db_, src, dst, q, batch=1000, tolerate_duplicates=False):
            if src == "product_snapshots":
                return 0        # claims success, copies nothing
            return await real_copy(db_, src, dst, q, batch=batch,
                                   tolerate_duplicates=tolerate_duplicates)

        server._copy_in_batches = _short
        orig, _ = _patch_recompute()
        try:
            await server.store_cleanup(dry_run=False, confirm_count=4, user=SUPER)
            raise AssertionError("expected verification to abort")
        except HTTPException as e:
            assert e.status_code == 500
            assert e.detail["phase"] == "backup"
            assert e.detail["collection"] == "product_snapshots"
            assert "verification failed" in e.detail["message"]
        finally:
            server._copy_in_batches = real_copy
            _unpatch(orig)
        assert await db.stores.count_documents({}) == 15
    asyncio.run(main())


def test_mid_cascade_delete_failure_rolls_back_and_leaves_no_orphans():
    """The dangerous failure: some collections already deleted. Everything must
    be restored from the backups so no orphan store reference survives."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        before = {c: await db[c].count_documents({}) for c in CASCADE_COLLECTIONS}

        # crawl_logs sits mid-cascade: product_snapshots et al. are already gone
        # by the time its delete blows up
        server.db = _SpyDB(db, "crawl_logs", fail_on="delete_many")
        orig, _ = _patch_recompute()
        try:
            await server.store_cleanup(dry_run=False, confirm_count=4, user=SUPER)
            raise AssertionError("expected the delete failure to surface")
        except HTTPException as e:
            assert e.status_code == 500
            d = e.detail
            assert d["phase"] == "delete" and d["collection"] == "crawl_logs"
            assert d["exception"] == "OSError"
            assert "rolled back" in d["error"]
            # the collections deleted before the failure are named...
            assert d["deleted_before_failure"]["product_snapshots"] == 1
            assert "crawl_logs" not in d["deleted_before_failure"]
            # ...and every one of them, plus the failing collection, restored
            assert d["restore_errors"] == {}, d["restore_errors"]
            assert "product_snapshots" in d["restored"]
            assert "crawl_logs" in d["restored"]
            assert d["backup_timestamp"] and f"store_cleanup_backup_{d['backup_timestamp']}" in d["hint"]
        finally:
            server.db = db
            _unpatch(orig)

        # ── the whole point: the DB is back where it started ──
        after = {c: await db[c].count_documents({}) for c in CASCADE_COLLECTIONS}
        assert after == before, {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        # stores is last in the cascade, so it was never touched
        assert await db.stores.count_documents({}) == 15
        # and no orphan references were left behind by the partial cascade
        live_ids = {s["id"] for s in await db.stores.find({}, {"_id": 0, "id": 1}).to_list(None)}
        async for s in db.product_snapshots.find({}, {"_id": 0, "store_id": 1}):
            assert s["store_id"] in live_ids
    asyncio.run(main())


def test_recompute_failure_does_not_mask_a_successful_delete():
    """Once the data is gone and backed up, a recompute failure must be reported
    in the body — not turned into a 500 that makes the operator re-run a cleanup
    that already happened."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        orig, _ = _patch_recompute()

        async def _boom(db_, min_interval_secs=600, force=False):
            raise RuntimeError("dashboard cache rebuild exploded")

        server.maybe_recompute_dashboard_cache = _boom
        try:
            rep = await server.store_cleanup(dry_run=False, confirm_count=4, user=SUPER)
        finally:
            _unpatch(orig)

        assert rep["after"]["stores"] == 11              # the delete stands
        assert rep["deleted_counts"]["stores"] == 4
        assert rep["recompute"]["dashboard_cache"].startswith("ERROR: RuntimeError")
        assert "exploded" in rep["recompute"]["dashboard_cache"]
        # the other steps still ran
        assert rep["recompute"]["page_caches"] == "recomputed"
        assert rep["recompute"]["crawl_jobs_unregistered"] == 4
    asyncio.run(main())


def test_same_second_rerun_refuses_to_merge_two_backups():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        # Pre-create backup collections for both the current second AND the
        # next second so a wall-clock tick between this compute and the one
        # inside `server.store_cleanup` cannot make the pre-created backup
        # miss the timestamp actually used. This test asserts the "backup
        # already exists" abort — the actual value of ts is irrelevant, only
        # that a collision exists.
        now = server.datetime.now(server.timezone.utc)
        ts_now = now.strftime("%Y%m%d%H%M%S")
        ts_next = (now + server.timedelta(seconds=1)).strftime("%Y%m%d%H%M%S")
        for ts in (ts_now, ts_next):
            await db[f"store_cleanup_backup_{ts}_product_snapshots"].insert_one({"stale": True})
        orig, _ = _patch_recompute()
        try:
            await server.store_cleanup(dry_run=False, confirm_count=4, user=SUPER)
            raise AssertionError("expected the pre-existing backup to abort the run")
        except HTTPException as e:
            assert e.status_code == 500 and e.detail["phase"] == "backup"
            assert "already exists" in e.detail["message"]
        finally:
            _unpatch(orig)
            for ts in (ts_now, ts_next):
                await db[f"store_cleanup_backup_{ts}_product_snapshots"].drop()
        assert await db.stores.count_documents({}) == 15
    asyncio.run(main())


# ── the registry itself ──────────────────────────────────────────────────────
def test_required_stores_is_exactly_the_eleven_keep_domains():
    """iter48 follow-up — ensure_stores() re-creates every REQUIRED_STORES entry
    on each boot, so a store deleted by the cleanup comes straight back unless
    the registry is pruned too. The registry and the keep-list must agree
    exactly, or the cleanup is not durable."""
    import store_registry

    keep_domains = {server.normalize_store_domain(d) for _, d in server.STORE_CLEANUP_KEEP_LIST}
    assert len(keep_domains) == server.STORE_CLEANUP_EXPECTED_KEEP == 11

    registry_domains = [server.normalize_store_domain(s["domain"])
                        for s in store_registry.REQUIRED_STORES]
    assert len(registry_domains) == 11, registry_domains
    assert len(set(registry_domains)) == 11, "duplicate domain in REQUIRED_STORES"
    assert set(registry_domains) == keep_domains, {
        "only_in_registry": sorted(set(registry_domains) - keep_domains),
        "only_in_keep_list": sorted(keep_domains - set(registry_domains)),
    }

    # none of the stores the cleanup deletes may linger in the registry
    for gone in ("cutecat.com.sa", "waggy.sa", "catfansksa.com", "catcity11.com",
                 "baboonstore.com", "anyabstore.com", "mycat.com.sa", "mycat.sa",
                 "petzone.com", "petarabia.sa", "petshouse-sa.com",
                 "snwr.zid.store", "salla.sa/catoutlet"):
        assert server.normalize_store_domain(gone) not in set(registry_domains), gone

    # the prune must not have disturbed the own-store flag or the rollout gate
    own = [s for s in store_registry.REQUIRED_STORES if s.get("is_own_store")]
    assert [s["domain"] for s in own] == ["pets-houses.com"], own
    assert store_registry.ACTIVATE_NEW_STORES is False
    # every surviving store still carries the fields ensure_stores() reads
    for s in store_registry.REQUIRED_STORES:
        assert s["name"] and s["domain"] and s["platform"] and s["priority"] in (1, 2), s


def test_registry_recreation_warning_is_now_clean_but_still_works():
    """With the registry pruned, a cleanup of today's junk stores must produce
    NO re-creation warning — and the mechanism must still fire if a deleted
    domain is ever re-added to REQUIRED_STORES."""
    async def main():
        import store_registry
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)

        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        assert rep["delete_count"] == 4
        # none of the four dropped domains is in REQUIRED_STORES any more
        assert rep["warnings"] == [], rep["warnings"]

        # ...but the guard rail is live: put one back and the warning returns
        orig = store_registry.REQUIRED_STORES
        store_registry.REQUIRED_STORES = orig + [
            {"name": "Waggy", "domain": "waggy.sa", "platform": "salla", "priority": 1}]
        try:
            rep = await server.store_cleanup(dry_run=True, user=SUPER)
        finally:
            store_registry.REQUIRED_STORES = orig
        assert rep["warnings"], "expected a re-creation warning"
        joined = " ".join(rep["warnings"])
        assert "ensure_stores" in joined and "waggy.sa" in joined
    asyncio.run(main())


def test_ensure_stores_seeds_only_the_eleven():
    """End-to-end: booting against an EMPTY database must produce exactly the 11
    keep-list stores — nothing the cleanup would immediately delete again."""
    async def main():
        from store_registry import ensure_stores
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await db.stores.delete_many({})
        added = await ensure_stores(db)
        assert added == 11, added
        live = await db.stores.find({}, {"_id": 0}).to_list(None)
        assert len(live) == 11
        assert {server.normalize_store_domain(s["domain"]) for s in live} == \
            {server.normalize_store_domain(d) for _, d in server.STORE_CLEANUP_KEEP_LIST}
        assert [s["domain"] for s in live if s.get("is_own_store")] == ["pets-houses.com"]
        # a second boot is still idempotent
        assert await ensure_stores(db) == 0
        assert await db.stores.count_documents({}) == 11

        # and the cleanup now has nothing to do against a freshly booted DB
        server.db = db
        rep = await server.store_cleanup(dry_run=True, user=SUPER)
        assert rep["guard"]["ok"] is True, rep["guard"]["reasons"]
        assert rep["delete_count"] == 0 and rep["delete_set"] == []
        assert rep["guard"]["keep_list_resolved_stores"] == 11
    asyncio.run(main())


if __name__ == "__main__":
    test_domain_normalization()
    test_dry_run_resolves_keep_list_and_writes_nothing()
    test_get_is_dry_run_only_and_requires_super_admin()
    test_own_store_never_in_delete_set()
    test_keep_list_not_eleven_aborts()
    test_zero_match_keep_domain_aborts_and_names_it()
    test_catastrophe_cap_aborts_above_fifty()
    test_confirm_count_must_match_exactly()
    test_real_run_backs_up_before_delete_and_leaves_no_orphans()
    test_backup_is_batched_not_one_giant_insert()
    test_copy_in_batches_respects_the_batch_size()
    test_backup_failure_aborts_with_the_collection_named_and_deletes_nothing()
    test_backup_verification_catches_a_short_copy()
    test_mid_cascade_delete_failure_rolls_back_and_leaves_no_orphans()
    test_recompute_failure_does_not_mask_a_successful_delete()
    test_same_second_rerun_refuses_to_merge_two_backups()
    test_required_stores_is_exactly_the_eleven_keep_domains()
    test_registry_recreation_warning_is_now_clean_but_still_works()
    test_ensure_stores_seeds_only_the_eleven()
    print("PASS: iter48 store cleanup")
