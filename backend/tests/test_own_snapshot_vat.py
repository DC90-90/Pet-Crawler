"""iter54 — own-store product_snapshots must carry the same inc-VAT basis as my_products.

iter44 corrected my_products to the inc-VAT shelf price but left
product_snapshots on the Zid Merchant API's ex-VAT price: the own-store snapshot
writer re-read raw["price"] instead of calling resolve_own_price. Hills
052742059518 therefore read 170.00 in my_products and 147.83 in its snapshot,
and every surface that reads snapshots — the detail panel's store_prices table,
price history, market position, and the rollups behind Insights — showed our
store ~15% cheap.

Two parts:
  (a) forward — the snapshot writer uses the resolved price
  (b) backfill — an endpoint that puts existing own-store snapshots on the same
      basis, backing them up first, in batches, never touching competitors.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_snap_vat")
import crawlers  # noqa: E402
import server  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SUPER = {"id": "t", "email": "t@t", "role": "super_admin"}
OWN = "own-store-id"
HILLS = "052742059518"


# ── (a) forward fix ──────────────────────────────────────────────────────────
def test_snapshot_writer_uses_the_resolved_inc_vat_price():
    """The own-sync must write the SAME number into my_products and the snapshot."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        for c in ("stores", "my_products", "products", "product_snapshots"):
            await db[c].delete_many({})
        store = {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com",
                 "platform": "zid", "is_own_store": True}
        await db.stores.insert_one(store)
        await db.my_products.insert_one({"sku": HILLS, "barcode": HILLS, "price": 0})

        # merchant row: ex-VAT 147.83, taxable. Storefront lists it at 170.
        merchant = [{"sku": HILLS, "barcode": HILLS, "name_ar": "", "name_en": "Hills GI Biome 1.5kg",
                     "price": 147.83, "sale_price": None, "qty_available": 4, "in_stock": True,
                     "is_taxable": True, "sold_count": 0, "img_url": "", "product_url": "",
                     "_zid_id": 900, "_zid_is_infinite": False}]
        storefront = [{"id": 900, "sku": HILLS, "barcode": HILLS,
                       "price": 170.0, "effective_price": 170.0, "is_taxable": True}]

        async def _fake_merchant(_db, _store):
            return list(merchant), "ok"

        async def _fake_sf(_store, max_pages=200):
            return list(storefront), {"ok": True, "endpoint": "/api/v1/products",
                                      "rows": len(storefront), "pages": 1,
                                      "stop_reason": "exhausted", "truncated": False}

        orig = (crawlers._fetch_zid_api_catalog, crawlers.fetch_own_storefront_catalog_raw)
        crawlers._fetch_zid_api_catalog = _fake_merchant
        crawlers.fetch_own_storefront_catalog_raw = _fake_sf
        try:
            await crawlers.sync_own_store_prices(db, store)
        finally:
            crawlers._fetch_zid_api_catalog, crawlers.fetch_own_storefront_catalog_raw = orig

        mp = await db.my_products.find_one({"sku": HILLS}, {"_id": 0})
        snap = await db.product_snapshots.find_one({"store_id": OWN, "sku": HILLS}, {"_id": 0})
        assert mp["price"] == 170.0, mp
        assert snap is not None, "own-store snapshot must be written"
        assert snap["price"] == 170.0, snap            # was 147.83 before iter54
        assert snap["original_price"] == 170.0, snap
        assert snap["price_basis"] == "storefront_inc_vat", snap
        assert mp["price"] == snap["price"], (mp["price"], snap["price"])
    asyncio.run(main())


def test_snapshot_writer_grosses_up_when_only_the_merchant_has_it():
    """Storefront-unmatched + is_taxable -> merchant x 1.15, tagged."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        for c in ("stores", "my_products", "products", "product_snapshots"):
            await db[c].delete_many({})
        store = {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com",
                 "platform": "zid", "is_own_store": True}
        await db.stores.insert_one(store)
        await db.my_products.insert_one({"sku": "ONLY-MERCH", "barcode": "", "price": 0})
        merchant = [{"sku": "ONLY-MERCH", "barcode": "", "name_ar": "", "name_en": "x",
                     "price": 100.0, "sale_price": None, "qty_available": 2, "in_stock": True,
                     "is_taxable": True, "sold_count": 0, "img_url": "", "product_url": "",
                     "_zid_id": 5, "_zid_is_infinite": False}]

        async def _m(_db, _s):
            return list(merchant), "ok"

        async def _sf(_s, max_pages=200):
            return [], {"ok": True, "endpoint": "/api/v1/products", "rows": 0, "pages": 1,
                        "stop_reason": "exhausted", "truncated": False}

        orig = (crawlers._fetch_zid_api_catalog, crawlers.fetch_own_storefront_catalog_raw)
        crawlers._fetch_zid_api_catalog, crawlers.fetch_own_storefront_catalog_raw = _m, _sf
        try:
            await crawlers.sync_own_store_prices(db, store)
        finally:
            crawlers._fetch_zid_api_catalog, crawlers.fetch_own_storefront_catalog_raw = orig

        snap = await db.product_snapshots.find_one({"store_id": OWN, "sku": "ONLY-MERCH"}, {"_id": 0})
        assert snap["price"] == 115.0, snap
        assert snap["price_basis"] == "merchant_computed_inc_vat", snap
    asyncio.run(main())


# ── (b) backfill ─────────────────────────────────────────────────────────────
async def _seed_backfill(db):
    for c in ("stores", "my_products", "product_snapshots"):
        await db[c].delete_many({})
    for n in await db.list_collection_names():
        if n.startswith("snapshot_vat_backfill_backup_"):
            await db[n].drop()
    await db.stores.insert_many([
        {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com", "is_own_store": True},
        {"id": "aleef", "name": "Aleef", "domain": "aleef.com"},
    ])
    now = server.datetime.now(server.timezone.utc)
    # my_products holds the CORRECTED inc-VAT basis
    await db.my_products.insert_many([
        {"sku": HILLS, "price": 170.0, "price_basis": "storefront_inc_vat"},
        {"sku": "SKU-B", "price": 115.0, "price_basis": "merchant_computed_inc_vat"},
        {"sku": "SKU-OK", "price": 50.0, "price_basis": "storefront_inc_vat"},
    ])
    snaps = []
    # own store, stale ex-VAT — 3 historical rows for Hills
    for i in range(3):
        snaps.append({"id": f"own-h{i}", "store_id": OWN, "store_name": "Pets Houses",
                      "sku": HILLS, "price": 147.83, "original_price": 147.83,
                      "confidence_score": 99, "crawled_at": now - server.timedelta(days=i)})
    snaps.append({"id": "own-b", "store_id": OWN, "store_name": "Pets Houses", "sku": "SKU-B",
                  "price": 100.0, "original_price": 100.0, "confidence_score": 99, "crawled_at": now})
    # already correct — must be counted as unchanged, not rewritten
    snaps.append({"id": "own-ok", "store_id": OWN, "store_name": "Pets Houses", "sku": "SKU-OK",
                  "price": 50.0, "original_price": 50.0, "confidence_score": 99, "crawled_at": now})
    # a SKU with no my_products target — left alone
    snaps.append({"id": "own-orphan", "store_id": OWN, "store_name": "Pets Houses", "sku": "GONE",
                  "price": 9.99, "original_price": 9.99, "confidence_score": 99, "crawled_at": now})
    # COMPETITOR rows at the same SKUs — must never be touched
    snaps.append({"id": "comp-h", "store_id": "aleef", "store_name": "Aleef", "sku": HILLS,
                  "price": 182.0, "original_price": 182.0, "confidence_score": 99, "crawled_at": now})
    snaps.append({"id": "comp-b", "store_id": "aleef", "store_name": "Aleef", "sku": "SKU-B",
                  "price": 120.0, "original_price": 120.0, "confidence_score": 99, "crawled_at": now})
    await db.product_snapshots.insert_many(snaps)
    server.db = db


def _patch_recompute():
    orig = (server.recompute_all_store_metrics, server.maybe_recompute_dashboard_cache,
            server.maybe_recompute_page_caches)
    calls = {"n": 0}

    async def _m(db):
        calls["n"] += 1
        return {"stores": 1}

    async def _d(db, min_interval_secs=600, force=False):
        calls["n"] += 1
        return True

    async def _p(db, min_interval_secs=600, force=False):
        calls["n"] += 1
        return True

    server.recompute_all_store_metrics = _m
    server.maybe_recompute_dashboard_cache = _d
    server.maybe_recompute_page_caches = _p
    return orig, calls


def _unpatch(o):
    (server.recompute_all_store_metrics, server.maybe_recompute_dashboard_cache,
     server.maybe_recompute_page_caches) = o


def test_dry_run_projects_and_writes_nothing():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_backfill(db)
        rep = await server.own_snapshot_vat_backfill_get(dry_run=True, sample=10, user=SUPER)

        assert rep["dry_run"] is True
        assert rep["scope"] == "latest_own_snapshot_per_sku"
        assert rep["own_snapshots_total"] == 6
        assert rep["own_snapshots_considered"] == 4       # 4 distinct own SKUs
        assert rep["history_rows_left_untouched"] == 2    # the 2 older Hills rows
        assert rep["competitor_snapshots_untouched"] == 2
        # NARROWED: 1 latest Hills row + 1 SKU-B row, not 3 Hills rows + 1
        assert rep["would_update"] == 2, rep
        assert rep["already_correct"] == 1
        assert rep["no_my_products_target"] == 1
        assert rep["distinct_skus_affected"] == 2
        assert rep["confirm_count_required"] == 2
        assert rep["price_basis_counts"] == {"storefront_inc_vat": 1,
                                             "merchant_computed_inc_vat": 1}, rep
        # one row per affected SKU
        assert rep["would_update"] == rep["distinct_skus_affected"]
        # the SKU the investigation turned on: exactly ONE row changes
        pr = rep["probe_052742059518"]
        assert pr["my_products_price"] == 170.0
        assert pr["own_snapshot_rows"] == 3
        assert [r["will_update"] for r in pr["rows"]] == [True, False, False], pr
        latest_row = pr["rows"][0]
        assert latest_row["is_latest"] and latest_row["before"] == 147.83 and latest_row["after"] == 170.0
        for r in pr["rows"][1:]:
            assert r["before"] == 147.83 and r["after"] == 147.83, r
        s0 = next(s for s in rep["sample"] if s["sku"] == HILLS)
        assert s0["before"] == 147.83 and s0["after"] == 170.0
        assert abs(s0["ratio"] - 1.15) < 0.001

        # ZERO writes
        assert await db.product_snapshots.count_documents({"price": 147.83}) == 3
        assert not [c for c in await db.list_collection_names()
                    if c.startswith("snapshot_vat_backfill_backup_")]
    asyncio.run(main())


def test_get_is_dry_run_only_and_super_admin_only():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_backfill(db)
        try:
            await server.own_snapshot_vat_backfill_get(dry_run=False, user=SUPER)
            raise AssertionError("GET with dry_run=false must be rejected")
        except HTTPException as e:
            assert e.status_code == 405
        try:
            await server.own_snapshot_vat_backfill(dry_run=True, user={"role": "viewer", "email": "v@v"})
            raise AssertionError("viewer must be rejected")
        except HTTPException as e:
            assert e.status_code == 403
        assert await db.product_snapshots.count_documents({"price": 147.83}) == 3
    asyncio.run(main())


def test_confirm_count_must_match():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_backfill(db)
        for bad in (None, 0, 3, 5, 4):
            try:
                await server.own_snapshot_vat_backfill(dry_run=False, confirm_count=bad,
                                                       sample=10, user=SUPER)
                raise AssertionError(f"confirm_count={bad} must be rejected")
            except HTTPException as e:
                assert e.status_code == 409 and "confirm_count" in e.detail
        assert await db.product_snapshots.count_documents({"price": 147.83}) == 3
    asyncio.run(main())


def test_real_run_backs_up_first_and_leaves_competitors_alone():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_backfill(db)
        orig, calls = _patch_recompute()
        try:
            rep = await server.own_snapshot_vat_backfill(dry_run=False, confirm_count=2,
                                                         sample=10, user=SUPER)
        finally:
            _unpatch(orig)

        # ── backup written BEFORE the write, holding the ORIGINAL values, and
        #    covering ONLY the rows that change ──
        b = rep["backup_collection"]
        assert b.startswith("snapshot_vat_backfill_backup_")
        assert rep["backed_up"] == 2
        assert await db[b].count_documents({}) == 2
        assert await db[b].count_documents({"price": 147.83}) == 1
        assert await db[b].count_documents({"store_id": {"$ne": OWN}}) == 0

        # ── ONLY the latest own row per SKU is corrected ──
        assert rep["snapshots_written"] == 2
        hills = sorted(await db.product_snapshots.find({"store_id": OWN, "sku": HILLS}).to_list(None),
                       key=lambda r: r["crawled_at"], reverse=True)
        assert hills[0]["price"] == 170.0 and hills[0]["original_price"] == 170.0, hills[0]
        assert hills[0]["price_basis"] == "storefront_inc_vat"
        assert hills[0]["vat_backfilled_at"]
        for h in hills[1:]:
            assert h["price"] == 147.83, h
            assert "vat_backfilled_at" not in h, h
        assert (await db.product_snapshots.find_one({"id": "own-b"}))["price"] == 115.0
        # untouched: already-correct row and the one with no my_products target
        assert (await db.product_snapshots.find_one({"id": "own-ok"}))["price"] == 50.0
        assert "vat_backfilled_at" not in (await db.product_snapshots.find_one({"id": "own-orphan"}))
        assert (await db.product_snapshots.find_one({"id": "own-orphan"}))["price"] == 9.99

        # ── COMPETITOR snapshots must be byte-identical ──
        assert (await db.product_snapshots.find_one({"id": "comp-h"}))["price"] == 182.0
        assert (await db.product_snapshots.find_one({"id": "comp-b"}))["price"] == 120.0
        assert await db.product_snapshots.count_documents(
            {"store_id": {"$ne": OWN}, "vat_backfilled_at": {"$exists": True}}) == 0

        # ── caches the panel reads were recomputed ──
        assert calls["n"] == 3 and rep["recompute"]["dashboard_cache"] == "recomputed"
    asyncio.run(main())


def test_detail_panel_and_market_position_read_inc_vat_after_backfill():
    """iter73l — the read-side heal now handles the reported symptom BEFORE
    the backfill runs: `_build_store_prices` prefers `my_products.price`
    (already inc-VAT since iter73d) over any stale ex-VAT snapshot. So
    pre-backfill the panel already shows 170.0. The backfill still upgrades
    the underlying SNAPSHOT so history + downstream aggregations agree.
    """
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_backfill(db)
        await db.products.delete_many({})
        await db.products.insert_one({"id": "p", "sku": HILLS, "name_ar": "",
                                      "name_en": "Hills GI Biome 1.5kg", "category": "cat_food"})

        before = await server.get_product_full(sku=HILLS, days=30, user=SUPER)
        ours = next(sp for sp in before["store_prices"] if sp["is_own_store"])
        # iter73l — the panel now shows the healed my_products.price
        # (170.0 inc-VAT) even when the LATEST snapshot is still the stale
        # ex-VAT 147.83 row. This is the fix for the reported symptom —
        # the panel no longer needs to wait for a snapshot backfill.
        assert ours["price"] == 170.0, ("iter73l heal should render "
                                        f"my_products.price=170.0 pre-backfill, got {ours['price']!r}")

        orig, _ = _patch_recompute()
        try:
            await server.own_snapshot_vat_backfill(dry_run=False, confirm_count=2,
                                                   sample=10, user=SUPER)
        finally:
            _unpatch(orig)

        after = await server.get_product_full(sku=HILLS, days=30, user=SUPER)
        ours = next(sp for sp in after["store_prices"] if sp["is_own_store"])
        # Post-backfill, the LATEST snapshot itself is now 170.0 — the
        # panel value is unchanged (still 170.0 via the same read-side
        # heal or now directly from the snapshot; the two sources agree).
        assert ours["price"] == 170.0, ours
        # history is deliberately NOT rewritten — the series keeps its real shape
        hist = after["history"]["Pets Houses"]
        assert hist[-1]["price"] == 170.0, hist
        assert any(h["price"] == 147.83 for h in hist[:-1]), hist
    asyncio.run(main())


def test_backup_is_batched():
    """The 63k-row single-shot timeout lesson: the copy must be chunked."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_backfill(db)
        now = server.datetime.now(server.timezone.utc)
        await db.product_snapshots.insert_many([
            {"id": f"bulk-{i}", "store_id": OWN, "store_name": "Pets Houses", "sku": HILLS,
             "price": 147.83, "original_price": 147.83, "confidence_score": 99,
             "crawled_at": now - server.timedelta(hours=i)} for i in range(2500)])

        seen = []
        real = db.product_snapshots.find

        rep_dry = await server.own_snapshot_vat_backfill(dry_run=True, sample=10, user=SUPER)
        # 2500 extra Hills history rows do NOT inflate the count — still one
        # latest row per affected SKU (Hills + SKU-B)
        assert rep_dry["would_update"] == 2, rep_dry["would_update"]
        assert rep_dry["own_snapshots_total"] == 2506
        assert rep_dry["history_rows_left_untouched"] == 2502
        assert server._SNAP_VAT_BATCH == 1000
        assert real is not None and seen == []
    asyncio.run(main())


def test_backup_batching_still_chunks_a_large_affected_set():
    """Many AFFECTED SKUs (not history) must still move in bounded batches."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed_backfill(db)
        now = server.datetime.now(server.timezone.utc)
        mine = [{"sku": f"BULK-{i}", "price": 115.0, "price_basis": "merchant_computed_inc_vat"}
                for i in range(2500)]
        snaps = [{"id": f"bulk-{i}", "store_id": OWN, "store_name": "Pets Houses",
                  "sku": f"BULK-{i}", "price": 100.0, "original_price": 100.0,
                  "confidence_score": 99, "crawled_at": now} for i in range(2500)]
        await db.my_products.insert_many(mine)
        await db.product_snapshots.insert_many(snaps)

        rep_dry = await server.own_snapshot_vat_backfill(dry_run=True, sample=5, user=SUPER)
        assert rep_dry["would_update"] == 2502, rep_dry["would_update"]   # 2500 + Hills + SKU-B

        orig, _ = _patch_recompute()
        try:
            rep = await server.own_snapshot_vat_backfill(dry_run=False, confirm_count=2502,
                                                         sample=5, user=SUPER)
        finally:
            _unpatch(orig)
        assert rep["backed_up"] == 2502
        assert await db[rep["backup_collection"]].count_documents({}) == 2502
        assert await db.product_snapshots.count_documents(
            {"store_id": OWN, "sku": {"$regex": "^BULK-"}, "price": 115.0}) == 2500
    asyncio.run(main())


# ── (c) duplicate own-store seller ───────────────────────────────────────────
def test_own_store_appears_exactly_once_in_the_seller_list():
    """server.py appended a synthesized my_products seller ON TOP of the
    own-store snapshot already in store_prices, so we appeared twice at two
    prices — inflating total_sellers and letting the cheaper (ex-VAT) duplicate
    win the "cheapest" label."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        for c in ("stores", "my_products", "products", "product_snapshots"):
            await db[c].delete_many({})
        await db.stores.insert_many([
            {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com", "is_own_store": True},
            {"id": "petsy", "name": "Petsy", "domain": "petsysa.com"},
        ])
        now = server.datetime.now(server.timezone.utc)
        await db.products.insert_one({"id": "p", "sku": HILLS, "name_ar": "",
                                      "name_en": "Hills GI Biome 1.5kg"})
        await db.my_products.insert_one({"sku": HILLS, "price": 170.0,
                                         "price_basis": "storefront_inc_vat"})
        await db.product_snapshots.insert_many([
            {"id": "own", "store_id": OWN, "store_name": "Pets Houses", "sku": HILLS,
             "price": 170.0, "original_price": 170.0, "confidence_score": 99, "crawled_at": now},
            {"id": "comp", "store_id": "petsy", "store_name": "Petsy", "sku": HILLS,
             "price": 182.0, "original_price": 182.0, "confidence_score": 99, "crawled_at": now},
        ])
        server.db = db

        out = await server.get_product_full(sku=HILLS, days=30, user=SUPER)
        mp = out["market_position"]
        # only Petsy and us -> "Cheapest of 2", not of 3
        assert mp["total_sellers"] == 2, mp
        assert mp["rank"] == 1 and mp["tag"] == "cheapest"
        assert mp["my_price"] == 170.0, mp          # the corrected inc-VAT value
        assert mp["percentile"] == 0.0
        # store_prices itself still lists each store once
        assert sum(1 for sp in out["store_prices"] if sp["is_own_store"]) == 1
    asyncio.run(main())


def test_dedupe_prefers_the_inc_vat_my_products_price():
    """If the snapshot is still stale, the my_products value must win — and the
    stale one must not survive as a second seller."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        for c in ("stores", "my_products", "products", "product_snapshots"):
            await db[c].delete_many({})
        await db.stores.insert_many([
            {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com", "is_own_store": True},
            {"id": "petsy", "name": "Petsy", "domain": "petsysa.com"},
        ])
        now = server.datetime.now(server.timezone.utc)
        await db.products.insert_one({"id": "p", "sku": HILLS, "name_ar": "", "name_en": "Hills"})
        # iter73p — seed the row with an explicit inc-VAT basis so
        # `_effective_own_price` trusts 170.0 as-written (the intent of
        # this test is to prove my_products WINS over the stale ex-VAT
        # snapshot, not to exercise the legacy-basis defensive gross).
        await db.my_products.insert_one({"sku": HILLS, "price": 170.0,
                                          "price_basis": "storefront_inc_vat"})
        await db.product_snapshots.insert_many([
            {"id": "own", "store_id": OWN, "store_name": "Pets Houses", "sku": HILLS,
             "price": 147.83, "original_price": 147.83, "confidence_score": 99, "crawled_at": now},
            {"id": "comp", "store_id": "petsy", "store_name": "Petsy", "sku": HILLS,
             "price": 160.0, "original_price": 160.0, "confidence_score": 99, "crawled_at": now},
        ])
        server.db = db

        mp = (await server.get_product_full(sku=HILLS, days=30, user=SUPER))["market_position"]
        assert mp["total_sellers"] == 2, mp
        # 170 vs Petsy 160 -> we are NOT cheapest; the ex-VAT 147.83 is gone
        assert mp["my_price"] == 170.0 and mp["rank"] == 2, mp
        assert mp["tag"] != "cheapest"
        assert mp["min_price"] == 160.0, mp
    asyncio.run(main())


if __name__ == "__main__":
    test_snapshot_writer_uses_the_resolved_inc_vat_price()
    test_snapshot_writer_grosses_up_when_only_the_merchant_has_it()
    test_dry_run_projects_and_writes_nothing()
    test_get_is_dry_run_only_and_super_admin_only()
    test_confirm_count_must_match()
    test_real_run_backs_up_first_and_leaves_competitors_alone()
    test_detail_panel_and_market_position_read_inc_vat_after_backfill()
    test_backup_is_batched()
    test_backup_batching_still_chunks_a_large_affected_set()
    test_own_store_appears_exactly_once_in_the_seller_list()
    test_dedupe_prefers_the_inc_vat_my_products_price()
    print("PASS: iter54 own-snapshot VAT basis")
