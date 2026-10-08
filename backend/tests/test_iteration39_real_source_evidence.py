"""Captured real products, not invented inventory or parent-only JSON-LD prices.

Provider payload fields are saved with provenance in fixtures/. All writes below
use the supplied reviewed suite's disposable loopback database fixture.
"""
import copy
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import crawlers
import catalog_views
import observation_contract as oc
import price_cohort
import market_share
import server
import pytest
import test_codex_review_gates as reviewed

SOURCE = json.loads((Path(__file__).parent / "fixtures/reviewed_beso_sources.json").read_text())


@pytest.fixture
def source_db():
    yield from reviewed.db.__wrapped__()


def test_real_beso_20kg_uses_valid_sku_and_observed_quantity():
    raw = SOURCE["own_litter"]
    norm = crawlers._normalize_raw_product({**raw, "_price_basis": "storefront_inc_vat"}, "Pets Houses")
    assert norm["barcode"] == "8699245859829"  # observed barcode2048 is not GTIN
    assert norm["price"] == 79.35 and norm["qty"] == 39
    assert norm["sold_count"] is None
    assert norm["comparable"] is True


def test_real_hair_skin_parent_is_not_a_specific_offer():
    norm = crawlers._normalize_raw_product(SOURCE["hair_skin"], "Pets Houses")
    assert norm["sku"] == "Hair & Skin" and norm["barcode"] == ""
    assert norm["price"] is None and norm["comparable"] is False
    assert "unresolved_parent_variants" in norm["quarantine_reasons"]


def test_actual_variant_payload_keeps_ids_prices_and_quantities(source_db):
    db = source_db
    async def run():
        store = {"id": "captured-own", "name": "Pets Houses", "platform": "zid", "is_active": True}
        await crawlers.process_crawled_products(db, store, [copy.deepcopy(SOURCE["hair_skin"])], datetime.now(timezone.utc), tier=1)
        rows = {r["sku"]: r async for r in db.product_snapshots.find({}, {"_id": 0})}
        assert set(rows) == {"5065023629268", "5065023629848"}
        small, large = rows["5065023629268"], rows["5065023629848"]
        assert (small["price"], small["qty_available"]) == (46.0, 15)
        assert (large["price"], large["qty_available"]) == (85.0, 2)
        assert small["variant_id"] == "38c1217d-d68c-47a9-b1bc-e1a65e340348"
        assert large["variant_id"] == "2079c3b2-abfe-4eb4-8b46-34af7f5be63a"
        assert small["offer_id"] != large["offer_id"]
        assert small["listing_id"] == large["listing_id"] == SOURCE["hair_skin"]["id"]
        assert small["sold_count"] is large["sold_count"] is None
    reviewed.run(run())


def test_real_beso_comparison_and_stale_unavailable_observations(source_db):
    db = source_db
    async def run():
        now = datetime.now(timezone.utc)
        own = {**SOURCE["own_litter"], "name_ar": SOURCE["own_litter"]["name"],
               "last_synced_at": now.isoformat(), "price_basis": "storefront_inc_vat"}
        stores = [{"id": "own", "name": "Pets Houses", "platform": "zid", "is_own_store": True},
                  {"id": "zarafa", "name": "Zarafa", "platform": "salla"},
                  {"id": "petsy", "name": "Petsy", "platform": "zid"}]
        await db.stores.insert_many(stores)
        for store, key in zip(stores[1:], ("zarafa_litter", "petsy_litter")):
            await crawlers.process_crawled_products(db, store, [copy.deepcopy(SOURCE[key])], now, tier=1)
        cohorts = await price_cohort.build_cohorts(db, [own], "own", server._effective_own_price, now=now)
        cohort = cohorts[own["sku"]]
        assert cohort["min"] == 83.95 and cohort["max"] == 87.0
        assert {s["store_id"] for s in cohort["sellers"]} == {"zarafa", "petsy"}
        # New unavailable observation supersedes old valid offer, never resurrected.
        unavailable = {**SOURCE["zarafa_litter"], "in_stock": False}
        await crawlers.process_crawled_products(db, stores[1], [unavailable], now+timedelta(seconds=1), tier=1)
        await db.product_snapshots.update_many({"store_id": "petsy"}, {"$set": {"crawled_at": now-timedelta(days=9)}})
        cohort = (await price_cohort.build_cohorts(db, [own], "own", server._effective_own_price, now=now))[own["sku"]]
        assert cohort["min"] is None and cohort["sellers"] == []
        assert {s["excluded_reason"] for s in cohort["excluded"]} == {"out_of_stock", "stale_or_unknown_observation"}
    reviewed.run(run())


def test_beso_stale_own_price_never_becomes_zero_in_details(source_db):
    db = source_db
    async def run():
        now = datetime.now(timezone.utc)
        await db.stores.insert_one({"id": "own", "name": "Pets Houses", "is_own_store": True})
        own = {**SOURCE["own_litter"], "name_ar": SOURCE["own_litter"]["name"],
               "last_synced_at": (now-timedelta(days=30)).isoformat(), "price_basis": "storefront_inc_vat"}
        await db.my_products.insert_one(own)
        result = await catalog_views.intel_detail(db, own["sku"], server._effective_own_price)
        assert result["market_summary"]["my_price"] is None
        assert result["my_product"]["price"] is None
        assert result["my_product"]["historical_price"] == 79.35
        assert result["my_product"]["barcode"] == "8699245859829"
        assert result["market_summary"]["lowest_price"] is None
        await db.stores.insert_one({"id": "old-comp", "name": "Old competitor", "is_active": True})
        await db.product_snapshots.insert_one({"sku": own["sku"], "store_id": "old-comp", "store_name": "Old competitor",
                                              "price": 69.0, "in_stock": True, "crawled_at": now-timedelta(days=28)})
        stale = await catalog_views.intel_detail(db, own["sku"], server._effective_own_price)
        historical = stale["competitors"][0]
        assert historical["competitor_price"] is None
        assert historical["competitor_in_stock"] is None
        assert historical["confidence"] is None
        assert historical["match_method"] == "unverified"
        await db.my_products.update_one({"sku": own["sku"]}, {"$set": {"last_synced_at": now.isoformat()}})
        fresh = await catalog_views.intel_detail(db, own["sku"], server._effective_own_price)
        assert fresh["market_summary"]["my_price"] == 79.35
    reviewed.run(run())


def test_selected_competitor_filters_rows_without_inventing_sales():
    # Store selector is a row-membership filter, not a claim of a new Saudi denominator.
    rows = [{"sku": sku, "sellers": [{"store_id": sid} for sid in stores],
             "my_revenue": None, "my_units": None, "market_revenue": None, "market_units": None,
             "competitor_count": len(stores), "confidence": "unavailable", "price_gap_pct": None,
             "my_units_source": market_share.SRC_NONE}
            for sku, stores in [("A-only", ["A"]), ("B-only", ["B"]), ("both", ["A", "B"])]]
    a = server._ms_filter(rows, store_id="A")
    b = server._ms_filter(rows, store_id="B")
    assert {r["sku"] for r in a} == {"A-only", "both"}
    assert {r["sku"] for r in b} == {"B-only", "both"}
    assert server._ms_filter(rows, store_id="unknown") == []
    summary = market_share.summarize(a, [], [], catalog_total=len(a), orders_connected=False)
    assert summary["my_catalog_products"] == 2
    assert summary["my_revenue_share_pct"] is None
    assert summary["market_revenue"] is None