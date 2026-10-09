"""Acceptance regressions for six reviewed fixes (isolated loopback Mongo only)."""

import asyncio
import copy
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

import comparison_scope
import comparison_views
import crawl_persistence
import catalog_views
import job_control
import market_share
import matcher
import observation_contract as oc
import own_quarantine
import price_cohort
import server
import verified_matching


# modules/features: disposable local Mongo fixture with strict loopback guard
@pytest.fixture
def db():
    url = os.environ.get("DALEEL_TEST_MONGO_URL") or os.environ.get("MONGO_URL")
    if not url or urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Acceptance regressions require loopback MongoDB")
    name = f"test_reviewed_acceptance_{uuid.uuid4().hex}"
    client = AsyncIOMotorClient(url)
    database = client[name]
    yield database
    with MongoClient(url) as sync_client:
        sync_client.drop_database(name)
    client.close()


FIXTURE = json.loads((Path(__file__).parent / "fixtures/reviewed_beso_sources.json").read_text())


def _run(coro):
    return asyncio.run(coro)


def _store(sid, own=False):
    return {
        "id": sid,
        "name": sid,
        "domain": f"{sid}.example.test",
        "platform": "zid",
        "is_active": True,
        "is_own_store": own,
    }


# modules/features: parent/variant observation identity + quarantine contracts
def test_parent_with_empty_or_invalid_variants_is_unresolved():
    a = {"id": "p1", "sku": "P1", "has_options": True, "variants": []}
    b = {"id": "p1", "sku": "P1", "variants": [{"name": "idless"}]}
    c = {"id": "p1", "sku": "P1", "variants": [{"id": "dup", "sku": "A"}, {"id": "dup", "sku": "B"}]}

    row_a = list(oc.expand_variants(a))[0]
    row_b = list(oc.expand_variants(b))[0]
    row_c = list(oc.expand_variants(c))[0]

    assert row_a["_unresolved_parent"] is True
    assert row_b["_unresolved_parent"] is True
    assert row_c["_unresolved_parent"] is True


def test_reobserved_known_parent_without_flags_stays_quarantined(db):
    async def go():
        now = datetime.now(timezone.utc)
        store = _store("own", own=True)
        await db.products.insert_one({"id": "child", "store_id": "own", "listing_id": "L1", "variant_id": "child-v", "offer_id": "child-offer", "sku": "CHILD"})
        root = {"id": "L1", "sku": "PARENT", "name": "Parent", "price": 99, "quantity": 10, "currency": "SAR"}
        await __import__("crawlers").process_crawled_products(db, store, [root], now, tier=1, confidence=95)
        snap = await db.product_snapshots.find_one({}, {"_id": 0, "quarantined": 1, "comparable": 1})
        assert snap["quarantined"] is True
        assert snap["comparable"] is False
    _run(go())


def test_quarantine_preserves_original_historical_quantity_timestamp(db):
    async def go():
        seen = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        now = datetime.now(timezone.utc)
        await db.my_products.insert_one({
            "sku": "SKU-H",
            "quantity": 17,
            "in_stock": True,
            "quantity_observed_at": seen,
            "last_synced_at": seen,
            "price": 85.0,
        })
        await own_quarantine.quarantine(db, _store("own", own=True), {"sku": "SKU-H", "listing_id": "L-H"}, "unresolved_parent_variants", now)
        row = await db.my_products.find_one({"sku": "SKU-H"}, {"_id": 0})
        assert row["quantity"] is None and row["in_stock"] is None
        assert row["historical_quantity"] == 17
        assert row["historical_quantity_at"] == seen
    _run(go())


def test_hair_skin_variants_keep_native_ids_prices_and_qty(db):
    async def go():
        now = datetime.now(timezone.utc)
        await __import__("crawlers").process_crawled_products(db, _store("own", own=True), [copy.deepcopy(FIXTURE["hair_skin"])], now, tier=1, confidence=95)
        rows = {r["sku"]: r async for r in db.product_snapshots.find({}, {"_id": 0})}
        assert set(rows) == {"5065023629268", "5065023629848"}
        assert rows["5065023629268"]["price"] == 46.0 and rows["5065023629268"]["qty_available"] == 15
        assert rows["5065023629848"]["price"] == 85.0 and rows["5065023629848"]["qty_available"] == 2
    _run(go())


# modules/features: own stock unavailable/stale/removed semantics
def test_own_stock_unknown_stale_removed_quarantined_and_zero_quantity_contract():
    now = datetime.now(timezone.utc)
    fresh = now.isoformat()

    removed = {"quantity": 12, "in_stock": True, "quantity_observed_at": fresh, "present_on_store": False}
    out = __import__("stock_evidence").own_stock(removed, now=now)
    assert out["stock_unavailable_reason"] == "removed_from_store"
    assert out["quantity"] is None and out["historical_quantity"] == 12

    stale = {"quantity": 5, "in_stock": True, "quantity_observed_at": (now - timedelta(days=8)).isoformat()}
    assert __import__("stock_evidence").own_stock(stale, now=now)["stock_unavailable_reason"] == "stale_or_unknown_observation"

    quarantined = {"quantity": 3, "in_stock": True, "quantity_observed_at": fresh, "quarantine_active": True}
    assert __import__("stock_evidence").own_stock(quarantined, now=now)["stock_unavailable_reason"] == "quarantined"

    unknown = {"quantity": None, "in_stock": None, "quantity_observed_at": fresh}
    assert __import__("stock_evidence").own_stock(unknown, now=now)["stock_unavailable_reason"] == "stock_unknown"

    zero = {"quantity": 0, "in_stock": False, "quantity_observed_at": fresh}
    row = __import__("stock_evidence").own_stock(zero, now=now)
    assert row["stock_unavailable_reason"] is None and row["stock_status"] == "out_of_stock"
    assert row["quantity"] == 0


# modules/features: matcher abort semantics, latest-invalid precedence, scoped offer blacklisting
def test_matcher_no_candidates_abort_keeps_existing_matches_untouched(db):
    async def go():
        await db.stores.insert_one(_store("own", own=True))
        await db.my_products.insert_one({"sku": "M1", "store_id": "own", "is_own_store": True, "barcode": "01234567890128", "name_en": "x", "price": 10, "price_basis": "storefront_inc_vat", "last_synced_at": datetime.now(timezone.utc).isoformat()})
        await db.product_matches.insert_one({"my_sku": "M1", "competitor_sku": "COMP", "competitor_store_id": "s1", "competitor_offer_id": "o1", "manually_confirmed": False})
        with pytest.raises(RuntimeError):
            await matcher.run_matching_for_all(db)
        assert await db.product_matches.count_documents({"my_sku": "M1"}) == 1
    _run(go())


def test_latest_invalid_offer_does_not_resurrect_older_valid_price(db):
    async def go():
        now = datetime.now(timezone.utc)
        await db.stores.insert_many([_store("own", own=True), _store("A")])
        own = {"sku": "SKU1", "barcode": "01234567890128", "name_en": "Beso 20kg", "name_ar": "Beso 20kg", "brand": "Beso", "brand_source": "store_supplied", "price": 130.0, "price_basis": "storefront_inc_vat", "last_synced_at": now.isoformat(), "in_stock": True}
        await db.product_snapshots.insert_many([
            {"offer_id": "oA", "store_id": "A", "store_name": "A", "sku": "X", "barcode": "01234567890128", "name_en": "Beso 20kg", "name_ar": "Beso 20kg", "brand": "Beso", "brand_source": "store_supplied", "price": 120.0, "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True, "confidence_score": 99, "comparable": True, "observation_version": 2, "crawled_at": now - timedelta(hours=2)},
            {"offer_id": "oA", "store_id": "A", "store_name": "A", "sku": "X", "barcode": "01234567890128", "name_en": "Beso 20kg", "name_ar": "Beso 20kg", "brand": "Beso", "brand_source": "store_supplied", "price": 110.0, "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": False, "confidence_score": 99, "comparable": True, "observation_version": 2, "crawled_at": now},
        ])
        cohort = (await price_cohort.build_cohorts(db, [own], "own", server._effective_own_price, now=now))["SKU1"]
        assert cohort["sellers"] == []
        assert {r["excluded_reason"] for r in cohort["excluded"]} == {"out_of_stock"}
    _run(go())


def test_match_builder_allows_nullable_original_price():
    row = matcher._build_match({"sku": "M1", "price": 100}, {"sku": "C1", "price": 90, "original_price": None, "store_id": "A"}, {}, 99, "barcode")
    assert row["competitor_original_price"] == 90.0


def test_offer_specific_blacklist_blocks_one_offer_not_sibling(db):
    async def go():
        own = {"sku": "OWN1", "barcode": "01234567890128", "name_ar": "Beso", "name_en": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 130.0}
        await db.match_blacklist.insert_one({"my_sku": "OWN1", "competitor_store_id": "A", "competitor_offer_id": "offer-1"})
        snaps = [
            {"offer_id": "offer-1", "store_id": "A", "store_name": "A", "sku": "same", "barcode": "01234567890128", "name_ar": "Beso", "name_en": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 120.0, "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True, "confidence_score": 99, "comparable": True, "observation_version": 2, "crawled_at": datetime.now(timezone.utc)},
            {"offer_id": "offer-2", "store_id": "A", "store_name": "A", "sku": "same", "barcode": "01234567890128", "name_ar": "Beso", "name_en": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 119.0, "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True, "confidence_score": 99, "comparable": True, "observation_version": 2, "crawled_at": datetime.now(timezone.utc)},
        ]
        out = await verified_matching.match(db, own, snapshots=snaps, own_store_id="own")
        assert len(out) == 1
        assert out[0]["competitor_offer_id"] == "offer-2"
    _run(go())


def test_scoped_matcher_writes_distinct_offer_ids(db):
    async def go():
        now = datetime.now(timezone.utc)
        await db.stores.insert_many([_store("own", own=True), _store("A"), _store("B")])
        await db.my_products.insert_one({"sku": "OWN2", "store_id": "own", "is_own_store": True, "barcode": "01234567890128", "name_en": "Beso", "name_ar": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 130, "price_basis": "storefront_inc_vat", "last_synced_at": now.isoformat(), "in_stock": True})
        await db.product_snapshots.insert_many([
            {"offer_id": "A1", "store_id": "A", "store_name": "A", "sku": "a", "barcode": "01234567890128", "name_en": "Beso", "name_ar": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 120, "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True, "confidence_score": 99, "comparable": True, "observation_version": 2, "crawled_at": now},
            {"offer_id": "B1", "store_id": "B", "store_name": "B", "sku": "b", "barcode": "01234567890128", "name_en": "Beso", "name_ar": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 110, "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True, "confidence_score": 99, "comparable": True, "observation_version": 2, "crawled_at": now},
        ])
        stats = await matcher.run_matching_for_all(db, only_skus=["OWN2"])
        rows = await db.product_matches.find({"my_sku": "OWN2"}, {"_id": 0, "competitor_offer_id": 1}).to_list(10)
        assert stats["total_matches"] == 2
        assert {r["competitor_offer_id"] for r in rows} == {"A1", "B1"}
    _run(go())


# modules/features: competitor scope + membership filter separation across adapters
def test_scope_rejects_unknown_and_own_store_ids(db):
    async def go():
        await db.stores.insert_many([_store("own", own=True), _store("A"), _store("B")])
        with pytest.raises(Exception):
            await comparison_scope.resolve(db, "selected", "unknown")
        with pytest.raises(Exception):
            await comparison_scope.resolve(db, "selected", "own")
    _run(go())


def test_selected_scope_consistent_across_intel_scanner_catalog_and_market_share(db):
    async def go():
        now = datetime.now(timezone.utc)
        await db.stores.insert_many([_store("own", own=True), _store("A"), _store("B"), _store("C")])
        my = {"sku": "SCOPE1", "offer_id": "own-off", "store_id": "own", "is_own_store": True, "barcode": "01234567890128", "name_ar": "Beso", "name_en": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 150.0, "price_basis": "storefront_inc_vat", "last_synced_at": now.isoformat(), "quantity": 5, "in_stock": True}
        await db.my_products.insert_one(my)
        await db.product_snapshots.insert_many([
            {"offer_id": "A1", "store_id": "A", "store_name": "A", "sku": "a", "barcode": "01234567890128", "name_ar": "Beso", "name_en": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 120.0, "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True, "confidence_score": 99, "comparable": True, "observation_version": 2, "crawled_at": now},
            {"offer_id": "B1", "store_id": "B", "store_name": "B", "sku": "b", "barcode": "01234567890128", "name_ar": "Beso", "name_en": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 110.0, "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True, "confidence_score": 99, "comparable": True, "observation_version": 2, "crawled_at": now},
            {"offer_id": "C1", "store_id": "C", "store_name": "C", "sku": "c", "barcode": "01234567890128", "name_ar": "Beso", "name_en": "Beso", "brand": "Beso", "brand_source": "store_supplied", "price": 5.0, "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True, "confidence_score": 70, "comparable": True, "observation_version": 2, "crawled_at": now},
        ])

        intel_all = await comparison_views.intel(db, server._effective_own_price)
        intel_a = await comparison_views.intel(db, server._effective_own_price, ["A"])
        intel_b = await comparison_views.intel(db, server._effective_own_price, ["B"])
        intel_none = await comparison_views.intel(db, server._effective_own_price, [])
        row_all = next(r for r in intel_all["full_table"] if r["my_sku"] == "SCOPE1")
        row_a = next(r for r in intel_a["full_table"] if r["my_sku"] == "SCOPE1")
        row_b = next(r for r in intel_b["full_table"] if r["my_sku"] == "SCOPE1")
        row_none = next(r for r in intel_none["full_table"] if r["my_sku"] == "SCOPE1")
        assert row_all["cheapest_price"] == 110.0 and row_all["cheapest_competitor"] == "B"
        assert row_a["cheapest_price"] == 120.0 and row_a["cheapest_competitor"] == "A"
        assert row_b["cheapest_price"] == 110.0 and row_b["cheapest_competitor"] == "B"
        assert row_none["cheapest_price"] is None

        async def orders_fn(*_a, **_k):
            return {"by_sku": {"SCOPE1": {"units": 2}}}

        async def sales_fn(*_a, **_k):
            return []

        scanner_a = await comparison_views.scanner(db, 14, server._effective_own_price, orders_fn, sales_fn, ["A"])
        scanner_b = await comparison_views.scanner(db, 14, server._effective_own_price, orders_fn, sales_fn, ["B"])
        assert scanner_a["opportunities"][0]["market_lowest"] == 120.0
        assert scanner_b["opportunities"][0]["market_lowest"] == 110.0

        detail_a = await catalog_views.intel_detail(db, "SCOPE1", server._effective_own_price, ["A"])
        detail_b = await catalog_views.intel_detail(db, "SCOPE1", server._effective_own_price, ["B"])
        assert detail_a["market_summary"]["lowest_price"] == 120.0
        assert detail_b["market_summary"]["lowest_price"] == 110.0

        ds_a = await market_share.build_dataset(db, 30, "own", own_price_fn=server._effective_own_price,
                                                brand_fn=lambda *a, **k: "", category_fn=lambda *a, **k: "",
                                                orders_by_sku={"SCOPE1": {"units": 1, "revenue": 130.0}},
                                                min_confidence=85,
                                                window_start=now - timedelta(days=30), window_end=now,
                                                competitor_store_ids=["A"], now=now)
        ds_b = await market_share.build_dataset(db, 30, "own", own_price_fn=server._effective_own_price,
                                                brand_fn=lambda *a, **k: "", category_fn=lambda *a, **k: "",
                                                orders_by_sku={"SCOPE1": {"units": 1, "revenue": 130.0}},
                                                min_confidence=85,
                                                window_start=now - timedelta(days=30), window_end=now,
                                                competitor_store_ids=["B"], now=now)
        a_comp = ds_a["my_products"][0]["competitor_price_min"]
        b_comp = ds_b["my_products"][0]["competitor_price_min"]
        assert a_comp == 120.0 and b_comp == 110.0
    _run(go())


def test_membership_filter_is_separate_from_comparison_scope_membership():
    rows = [{"sku": "shared", "sellers": [{"store_id": "B"}], "membership_store_ids": ["A", "B"]}]
    kept = server._ms_filter(rows, store_id="A")
    assert len(kept) == 1


# modules/features: crawl persistence durability, recoverability and failure truthfulness
def test_persist_keeps_raw_and_enriched_separately_and_uses_original_timestamp(db):
    async def go():
        called = []
        now = datetime.now(timezone.utc)
        store = _store("S")

        async def fake_supplement(_db, _store, rows, _log, **_):
            rows[0]["name"] = "enriched"

        async def fake_process(_db, _store, rows, observed_at, tier=1, confidence=95):
            called.append((rows[0]["name"], observed_at))
            return 1, 1

        from unittest.mock import patch
        with patch("crawlers._maybe_salla_detail_supplement", new=fake_supplement), patch("crawlers.process_crawled_products", new=fake_process):
            log = {"id": "run-1"}
            rows = [{"id": "1", "sku": "X", "name": "raw"}]
            await crawl_persistence.persist(db, store, rows, now, log, tier=1, confidence=95)

        doc = await db.crawl_checkpoints.find_one({"_id": "capture:run-1:0"}, {"_id": 0})
        assert doc["raw_rows"][0]["name"] == "raw"
        assert doc["enriched_rows"][0]["name"] == "enriched"
        assert called[0][0] == "enriched"
        assert called[0][1] == now
    _run(go())


def test_persist_supplement_failure_falls_back_to_raw_and_reports_not_full_success(db):
    async def go():
        now = datetime.now(timezone.utc)
        store = _store("S")

        async def boom(*_a, **_k):
            raise RuntimeError("supplement failed")

        async def no_comparable(*_a, **_k):
            return 0, 0

        from unittest.mock import patch
        with patch("crawlers._maybe_salla_detail_supplement", new=boom), patch("crawlers.process_crawled_products", new=no_comparable):
            log = {"id": "run-2"}
            n, s = await crawl_persistence.persist(db, store, [{"id": "1", "sku": "X", "name": "raw"}], now, log)
        assert (n, s) == (0, 0)
        assert log.get("complete") is False
        assert "No comparable observations persisted" in (log.get("error") or "")
    _run(go())


def test_recover_replays_original_timestamp_and_is_idempotent(db):
    async def go():
        now = datetime.now(timezone.utc)
        store = _store("S")
        await db.crawl_checkpoints.insert_one({
            "_id": "capture:run-3:0",
            "store_id": "S",
            "run_id": "run-3",
            "observed_at": now,
            "raw_rows": [{"id": "1", "sku": "X"}],
            "tier": 1,
            "confidence": 95,
            "state": "captured",
            "created_at": now,
        })
        calls = []

        async def fake_process(_db, _store, rows, observed_at, tier=1, confidence=95):
            calls.append((rows, observed_at, tier, confidence))
            return 1, 1

        from unittest.mock import patch
        with patch("crawlers.process_crawled_products", new=fake_process):
            first = await crawl_persistence.recover(db, store)
            second = await crawl_persistence.recover(db, store)
        assert first == 1 and second == 0
        assert calls
        assert abs((calls[0][1] - now).total_seconds()) < 1
    _run(go())


def test_job_control_failed_result_is_not_downgraded_to_degraded(db):
    async def go():
        run_id, _ = await job_control.queue(db, "crawl", "acceptance-failed")
        await job_control.execute(db, run_id, "crawl", lambda: asyncio.sleep(0, result={"status": "failed", "sync_status": "degraded"}))
        row = await db.job_runs.find_one({"_id": run_id}, {"_id": 0, "status": 1})
        assert row["status"] == "failed"
    _run(go())


def test_real_checkpoint_repairs_interrupted_ledger_without_duplicate_observation(db):
    async def go():
        from unittest.mock import patch
        import ledger
        now = datetime.now(timezone.utc).replace(microsecond=123456)
        store = _store("S")
        raw = {"id": "r1", "sku": "r1", "name": "Beso 20kg", "price": 85, "quantity": 5, "currency": "SAR"}
        async def skip(*args, **kwargs):
            return None
        async def fail(*args, **kwargs):
            raise RuntimeError("ledger unavailable")
        with patch("crawlers._maybe_salla_detail_supplement", new=skip), patch.object(ledger, "record_observations", new=fail):
            log = {"id": "torn-run"}
            await crawl_persistence.persist(db, store, [raw], now, log)
            assert log["complete"] is False and log.get("error")
        assert await db.product_snapshots.count_documents({}) == 1
        assert await db.observation_events.count_documents({}) == 1
        await crawl_persistence.recover(db, store)
        assert await db.product_snapshots.count_documents({}) == 1
        assert await db.observation_events.count_documents({}) == 1
        assert await db.daily_ledger.count_documents({}) == 1
        assert await crawl_persistence.recover(db, store) == 0
    _run(go())


def test_cancelled_enrichment_has_durable_replayable_raw_capture(db):
    async def go():
        from unittest.mock import patch
        now = datetime.now(timezone.utc)
        store = _store("S")
        raw = {"id": "r1", "sku": "r1", "name": "Beso 20kg", "price": 85, "quantity": 5, "currency": "SAR"}
        async def cancelled(_db, *_args, **_kwargs):
            assert await _db.crawl_checkpoints.count_documents({"state": "captured"}) == 1
            raise asyncio.CancelledError()
        with patch("crawlers._maybe_salla_detail_supplement", new=cancelled):
            with pytest.raises(asyncio.CancelledError):
                await crawl_persistence.persist(db, store, [raw], now, {"id": "cancelled"})
        assert await db.product_snapshots.count_documents({}) == 0
        await crawl_persistence.recover(db, store)
        assert await db.product_snapshots.count_documents({}) == 1
        row = await db.product_snapshots.find_one({}, {"_id": 0})
        assert row["price"] == 85 and row["qty_available"] == 5
    _run(go())


def test_comparison_selector_preserves_page_permissions():
    from access_policy import enforce
    for page in ("market_share", "price_intel", "scanner", "insights"):
        enforce({"allowed_pages": [page]}, "/api/comparison-stores", "GET")
    with pytest.raises(Exception):
        enforce({"allowed_pages": []}, "/api/comparison-stores", "GET")
    with pytest.raises(Exception):
        enforce({"allowed_pages": ["market_share"]}, "/api/stores", "GET")


def test_variant_never_inherits_parent_sku_barcode_price_or_quantity():
    parent = {"id": "P", "sku": "PARENT", "barcode": "01234567890128", "price": 85, "quantity": 17,
              "currency": "SAR", "variants": [{"id": "v1"}, {"id": "v2"}]}
    children = list(oc.expand_variants(parent))
    assert {c["sku"] for c in children} == {"variant:P:v1", "variant:P:v2"}
    for child in children:
        offer = oc.normalize_offer(child, "Store")
        assert not offer["comparable"] and offer["qty"] is None
        assert not offer.get("barcode")


def test_parent_search_keeps_child_identities_separate(db):
    async def go():
        now = datetime.now(timezone.utc)
        await db.stores.insert_one(_store("own", True))
        await db.my_products.insert_many([
            {"sku": "Hair & Skin", "listing_id": "P1", "known_variant_parent": True, "is_own_store": True, "store_id": "own"},
            {"sku": "child-2kg", "listing_id": "P1", "variant_id": "v1", "name_ar": "بيسو 2 كج", "is_own_store": True, "store_id": "own", "price": 46},
            {"sku": "child-4kg", "listing_id": "P1", "variant_id": "v2", "name_ar": "بيسو 4 كج", "is_own_store": True, "store_id": "own", "price": 85},
        ])
        async def orders(*args, **kwargs): return None
        rows = await catalog_views.dataset(db, 14, None, None, None, None, None, "Hair & Skin", True, server._effective_own_price, orders)
        assert {r["sku"] for r in rows["rows"]} == {"Hair & Skin", "child-2kg", "child-4kg"}
    _run(go())
