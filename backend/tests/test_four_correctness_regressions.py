"""Four follow-up acceptance gaps. Disposable loopback Mongo; no live refresh."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import pytest
from motor.motor_asyncio import AsyncIOMotorCollection

from test_acceptance_six_regressions import db as acceptance_db, _run, _store
from observation_contract import expand_variants, stable_id
from own_quarantine import filter_own_rows
from crawlers import _normalize_raw_product, process_crawled_products
from price_cohort import build_cohorts
from comparison_views import context
import crawl_persistence
import ledger
import server

db = acceptance_db


def raw(sku="8699245859829", listing="L", price=85):
    return {"id": listing, "sku": sku, "name": "Beso 20kg", "price": price, "quantity": 5, "currency": "SAR", "_price_basis": "storefront_inc_vat"}


def expanded(row):
    return list(expand_variants(row))


def test_first_seen_parent_without_catalog_row_survives_flagless_own_response(db):
    async def go():
        now, store = datetime.now(timezone.utc), _store("own", True)
        root = raw("PARENT")
        accepted, rejected = await filter_own_rows(db, store, expanded({**root, "has_options": True}), "public_crawl", now, _normalize_raw_product)
        assert not accepted and rejected == 1 and await db.my_products.count_documents({}) == 0
        assert await db.listing_identities.count_documents({"store_id": "own", "listing_id": "L"}) == 1
        later, rejected = await filter_own_rows(db, store, expanded(root), "public_crawl", now+timedelta(minutes=1), _normalize_raw_product)
        assert not later and rejected == 1
        children = expanded({**root, "variants": [{"id": "v1", "sku": "A", "price": 46, "quantity": 15}, {"id": "v2", "sku": "B", "price": 85, "quantity": 2}]})
        valid, rejected = await filter_own_rows(db, store, children, "public_crawl", now+timedelta(minutes=2), _normalize_raw_product)
        assert not rejected and {x["sku"] for x in valid} == {"A", "B"}
        assert {x["_variant_id"] for x in valid} == {"v1", "v2"}
        # SKU-only later response also cannot evade remembered listing identity.
        again, _ = await filter_own_rows(db, store, [{"sku": "PARENT", "price": 85, "quantity": 17}], "merchant_api", now, _normalize_raw_product)
        assert not again
    _run(go())


def test_first_seen_competitor_parent_survives_flagless_response(db):
    async def go():
        now, store = datetime.now(timezone.utc), _store("comp")
        await process_crawled_products(db, store, [{**raw(), "has_options": True}], now)
        await process_crawled_products(db, store, [raw()], now+timedelta(seconds=1))
        snaps = await db.product_snapshots.find({}, {"_id": 0}).to_list(None)
        assert len(snaps) == 2 and all(s["comparable"] is False and s["price"] is None for s in snaps)
    _run(go())


def test_root_first_children_later_excludes_root_without_editing_history(db):
    async def go():
        now, store = datetime.now(timezone.utc), _store("comp")
        await db.stores.insert_many([store, _store("own", True)])
        own = {"sku": "8699245859829", "name_en": "Beso 20kg", "price": 90, "price_basis": "storefront_inc_vat", "last_synced_at": now.isoformat()}
        await process_crawled_products(db, store, [raw(price=10)], now)
        before = await db.product_snapshots.find_one({"variant_id": "root"}, {"_id": 0})
        await process_crawled_products(db, store, [{**raw(price=10), "variants": [
            {"id": "v1", "sku": "8699245859829", "price": 46, "quantity": 15},
            {"id": "v2", "sku": "5065023629848", "price": 85, "quantity": 2}]}], now+timedelta(seconds=1))
        cohort = (await build_cohorts(db, [own], "own", server._effective_own_price, now=now+timedelta(seconds=2)))[own["sku"]]
        assert cohort["min"] == 46
        assert [s["variant_id"] for s in cohort["sellers"]] == ["v1"]
        assert any(s["variant_id"] == "root" and s["excluded_reason"] == "parent_listing_not_an_offer" for s in cohort["excluded"])
        assert before == await db.product_snapshots.find_one({"variant_id": "root"}, {"_id": 0})
        assert await db.product_snapshots.count_documents({"variant_id": {"$in": ["v1", "v2"]}}) == 2
    _run(go())


def test_read_through_excludes_own_root_even_without_registry_backfill(db):
    async def go():
        now = datetime.now(timezone.utc)
        await db.stores.insert_one(_store("own", True))
        root = {"sku": "P", "listing_id": "L", "variant_id": "root", "price": 85, "price_basis": "storefront_inc_vat", "quantity": 17, "in_stock": True, "last_synced_at": now.isoformat()}
        await db.my_products.insert_one(dict(root))
        await db.products.insert_one({"id": "child", "store_id": "own", "listing_id": "L", "variant_id": "v1"})
        _, products, _ = await context(db, server._effective_own_price)
        assert server._effective_own_price(products[0]) == 0
        assert products[0]["superseded_parent"] is True
        assert await db.my_products.find_one({}, {"_id": 0}) == root
        assert await db.listing_identities.count_documents({}) == 0
    _run(go())


def test_interruption_after_successful_ledger_before_checkpoint_is_noop_on_replay(db):
    async def go():
        now, store = datetime.now(timezone.utc).replace(microsecond=123456), _store("S")
        original = AsyncIOMotorCollection.update_one
        async def interrupt(collection, query, update, *args, **kwargs):
            if collection.name == "crawl_checkpoints" and update.get("$set", {}).get("state") == "persisted":
                raise asyncio.CancelledError()
            return await original(collection, query, update, *args, **kwargs)
        with patch.object(AsyncIOMotorCollection, "update_one", new=interrupt):
            with pytest.raises(asyncio.CancelledError):
                await crawl_persistence.persist(db, store, [raw()], now, {"id": "after-ledger"})
        before = await db.daily_ledger.find_one({}, {"_id": 0})
        store_before = await db.daily_ledger_store.find_one({}, {"_id": 0})
        assert before["observations_that_day"] == 1 and store_before["first_seen_count"] == 1
        assert await crawl_persistence.recover(db, store) == 1
        assert await db.daily_ledger.find_one({}, {"_id": 0}) == before
        assert await db.daily_ledger_store.find_one({}, {"_id": 0}) == store_before
        assert await db.product_snapshots.count_documents({}) == await db.observation_events.count_documents({}) == 1
    _run(go())


def test_older_observation_and_replay_cannot_replace_newer_closing_values(db):
    async def go():
        t = datetime.now(timezone.utc).replace(hour=12, microsecond=123456)
        new = {"sku": "S", "event_id": "new", "close_price": 200, "qty_available": 9}
        old = {"sku": "S", "event_id": "old", "close_price": 100, "qty_available": 3}
        await ledger.record_observations(db, "comp", "Comp", [new], t+timedelta(hours=1))
        await ledger.record_observations(db, "comp", "Comp", [old], t)
        dup = await ledger.record_observations(db, "comp", "Comp", [old], t)
        assert dup["duplicate"] == 1 and dup["written"] == 0 and dup["first_seen"] == 0
        row = await db.daily_ledger.find_one({}, {"_id": 0})
        assert row["close_price"] == 200 and row["qty_available"] == 9 and row["observations_that_day"] == 2
        sd = await db.daily_ledger_store.find_one({}, {"_id": 0})
        assert sd["first_seen_count"] == 1
    _run(go())


def test_actual_row_operationfailure_marks_incomplete_and_recovers_without_duplicates(db):
    async def go():
        await db.create_collection("daily_ledger", validator={"sku": {"$ne": "FAIL"}})
        now, store = datetime.now(timezone.utc), _store("S")
        log = {"id": "real-validation-failure"}
        await crawl_persistence.persist(db, store, [raw("GOOD", "L1"), raw("FAIL", "L2")], now, log)
        assert log["complete"] is False and log.get("error")
        capture = await db.crawl_checkpoints.find_one({}, {"_id": 0})
        assert capture["state"] == "recovery_required"
        assert capture["recovery_error"]["detail"]["skipped"] == 1
        assert capture["recovery_error"]["detail"]["errors"][0]["code"] == 121
        with pytest.raises(crawl_persistence.RecoveryIncomplete) as error:
            await crawl_persistence.recover(db, store)
        assert error.value.result["unresolved"]
        assert (await db.daily_ledger_store.find_one({}, {"_id": 0}))["status"] == "partial"
        assert await db.product_snapshots.count_documents({}) == await db.observation_events.count_documents({}) == 2
        await db.command({"collMod": "daily_ledger", "validator": {}})
        assert await crawl_persistence.recover(db, store) == 1
        rows = await db.daily_ledger.find({}, {"_id": 0}).to_list(None)
        assert len(rows) == 2 and all(r["observations_that_day"] == 1 for r in rows)
        sd = await db.daily_ledger_store.find_one({}, {"_id": 0})
        assert sd["first_seen_count"] == 2 and sd["status"] == "ok" and not sd["unresolved_observation_ids"]
        capture = await db.crawl_checkpoints.find_one({}, {"_id": 0})
        assert capture["state"] == "persisted" and "recovery_error" not in capture
    _run(go())


def test_sealed_unapplied_recovery_is_explicit_and_preserves_history(db):
    async def go():
        t, store = datetime.now(timezone.utc)-timedelta(days=1), _store("S")
        await db.stores.insert_one(store)
        await process_crawled_products(db, store, [raw(price=85)], t)
        await ledger.seal_ksa_day(db, day=ledger.ksa_day_str(t))
        before = await db.daily_ledger.find_one({}, {"_id": 0})
        sd = await db.daily_ledger_store.find_one({}, {"_id": 0})
        await crawl_persistence.checkpoint(db, store, [raw(price=1)], t+timedelta(minutes=1), "sealed-late", 1, 95)
        with pytest.raises(crawl_persistence.RecoveryIncomplete) as error:
            await crawl_persistence.recover(db, store)
        assert "sealed_history_requires_reconciliation" in str(error.value.result)
        assert await db.daily_ledger.find_one({}, {"_id": 0}) == before
        assert await db.daily_ledger_store.find_one({}, {"_id": 0}) == sd
        assert (await db.crawl_checkpoints.find_one({}, {"_id": 0}))["state"] == "recovery_required"
    _run(go())


def test_proven_duplicate_sealed_observation_is_acknowledged_without_write(db):
    async def go():
        t = datetime.now(timezone.utc)-timedelta(days=1)
        await db.stores.insert_one(_store("S"))
        obs = {"sku": "SKU", "event_id": "once", "close_price": 85}
        await ledger.record_observations(db, "S", "S", [obs], t)
        await ledger.seal_ksa_day(db, ledger.ksa_day_str(t))
        row, sd = await db.daily_ledger.find_one({}), await db.daily_ledger_store.find_one({})
        result = await ledger.record_observations(db, "S", "S", [obs], t)
        assert result["complete"] and result["duplicate"] == 1
        assert await db.daily_ledger.find_one({}) == row and await db.daily_ledger_store.find_one({}) == sd
    _run(go())


def test_legacy_unreceipted_replay_is_not_guessed_or_backfilled(db):
    async def go():
        t = datetime.now(timezone.utc)
        old = {"_id": f"S|SKU|{ledger.ksa_day_str(t)}", "store_id": "S", "sku": "SKU", "ksa_date": ledger.ksa_day_str(t), "sealed_at": None,
               "last_observed_at": t, "close_price": 85, "observations_that_day": 4, "is_first_day_for_store": True, "writer_version": 1}
        await db.daily_ledger.insert_one(dict(old))
        result = await ledger.record_observations(db, "S", "S", [{"sku": "SKU", "event_id": "unknown", "close_price": 1}], t-timedelta(minutes=1))
        assert not result["complete"] and result["errors"][0]["reason"] == "legacy_observation_identity_unresolved"
        assert (await db.daily_ledger.find_one({}))["observations_that_day"] == 4
        assert (await db.daily_ledger.find_one({}))["close_price"] == 85
        same_stamp = await ledger.record_observations(db, "S", "S", [{"sku": "SKU", "event_id": "unknown-same-ms", "close_price": 1}], t)
        assert not same_stamp["complete"] and same_stamp["errors"][0]["reason"] == "legacy_observation_identity_unresolved"
        assert (await db.daily_ledger.find_one({}))["observations_that_day"] == 4
    _run(go())