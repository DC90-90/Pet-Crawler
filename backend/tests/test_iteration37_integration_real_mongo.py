"""iteration37 integration suite — real Mongo writes/reads across adapters.

Scope: process_crawled_products, cohort/view adapters, ledger facts, ingest v2,
job control leases/queue, cron dispatch envelope/auth, own orders aggregation.
"""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient

import catalog_views
import comparison_views
import crawlers
import evidence_ledger
import ingest_v2
import integrity_indexes
import job_control
import market_share
import price_cohort
import server


MONGO_URL = os.environ["MONGO_URL"]
OWN_STORE_ID = "own-iter37"
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def _run(coro):
    return LOOP.run_until_complete(coro)


@pytest.fixture(scope="module")
def db_name():
    return f"test_iter37_integration_{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def db(db_name):
    client = AsyncIOMotorClient(MONGO_URL)
    test_db = client[db_name]
    _run(integrity_indexes.ensure(test_db))
    yield test_db
    _run(client.drop_database(db_name))
    client.close()


def _store(store_id, name, own=False):
    return {
        "id": store_id,
        "name": name,
        "domain": f"{store_id}.example.org",
        "platform": "salla" if not own else "zid",
        "is_active": True,
        "is_own_store": own,
    }


# modules/features: ingestion + variant identity + cross-store SKU isolation
def test_process_crawled_products_keeps_variant_prices_and_store_isolation(db):
    async def _go():
        await db.stores.delete_many({})
        await db.products.delete_many({})
        await db.product_snapshots.delete_many({})
        await db.observation_events.delete_many({})
        await db.observation_quarantine.delete_many({})
        await db.sales_facts_v2.delete_many({})

        s1 = _store("comp-a-iter37", "Comp A")
        s2 = _store("comp-b-iter37", "Comp B")
        await db.stores.insert_many([s1, s2])

        now = datetime(2026, 2, 2, 8, 0, tzinfo=timezone.utc)
        raw_s1 = [{
            "id": "listing-A",
            "name": "Cat Wet Food",
            "price": {"amount": "999", "currency": "SAR"},
            "skus": [
                {
                    "id": "v1",
                    "sku": "LOCAL-100",
                    "barcode": "4006381333931",
                    "price": {"amount": "20", "currency": "SAR"},
                    "quantity": 2,
                },
                {
                    "id": "v2",
                    "sku": "LOCAL-100",
                    "barcode": "01234567890128",
                    "price": {"amount": "200", "currency": "SAR"},
                    "quantity": 5,
                },
            ],
        }]
        raw_s2 = [{
            "id": "listing-B",
            "name": "Dog Cage",
            "sku": "LOCAL-100",
            "barcode": "4006381333931",
            "price": {"amount": "500", "currency": "SAR"},
            "quantity": 1,
        }]

        await crawlers.process_crawled_products(db, s1, raw_s1, now, tier=1, confidence=99)
        await crawlers.process_crawled_products(db, s2, raw_s2, now, tier=1, confidence=99)

        snaps = await db.product_snapshots.find({"store_id": {"$in": [s1["id"], s2["id"]]}}, {"_id": 0}).to_list(20)
        assert len(snaps) == 3

        s1_prices = sorted([r["price"] for r in snaps if r["store_id"] == s1["id"]])
        assert s1_prices == [20.0, 200.0]  # no parent-price borrowing from 999
        s1_qty = sorted([r["qty_available"] for r in snaps if r["store_id"] == s1["id"]])
        assert s1_qty == [2, 5]
        assert {r.get("barcode") for r in snaps if r["store_id"] == s1["id"]} == {
            "4006381333931", "01234567890128"
        }

        products = await db.products.find({"sku": "LOCAL-100"}, {"_id": 0, "store_id": 1, "name_ar": 1, "price": 1}).to_list(10)
        # Same local SKU across stores yields distinct offer identities.
        assert {p["store_id"] for p in products} == {"comp-a-iter37", "comp-b-iter37"}
        assert {p["name_ar"] for p in products} == {"Cat Wet Food", "Dog Cage"}

    _run(_go())


def _own_price(row):
    return float(row.get("sale_price") or row.get("price") or 0)


async def _orders_none(_db, _start, _end):
    return None


async def _sales_rows_none(_db, _start, until=None):
    _ = until
    return []


# modules/features: shared cohort consistency across dataset/intel/scanner/detail/market share
def test_shared_cohort_is_consistent_across_adapters_and_exclusions_are_explicit(db):
    async def _go():
        for c in (
            "stores", "my_products", "products", "product_snapshots", "product_matches",
            "match_blacklist", "sales_facts_v2", "daily_ledger_store"
        ):
            await db[c].delete_many({})

        # All current-price adapters use the live clock. A fixed historical date
        # would correctly be stale in the live adapters but fresh in the injected one.
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=9)
        await db.stores.insert_many([
            _store(OWN_STORE_ID, "My Store", own=True),
            _store("c1", "Comp 1"), _store("c2", "Comp 2"), _store("c3", "Comp 3"),
            _store("c4", "Comp 4"), _store("c5", "Comp 5"), _store("c6", "Comp 6"),
        ])
        await db.my_products.insert_one({
            "sku": "OWN-SKU-1",
            "offer_id": "offer-own-1",
            "barcode": "4006381333931",
            "name_ar": "Cat Food 400g",
            "name_en": "Cat Food 400g",
            "category": "cat_food",
            "price": 130.0,
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "quantity": 6,
            "last_synced_at": now.isoformat(),
        })
        await db.products.insert_one({"sku": "OWN-SKU-1", "name_ar": "Cat Food 400g", "category": "cat_food"})

        base = {
            "is_synthetic": False,
            "observation_version": 2,
            "comparable": True,
            "currency": "SAR",
            "price_basis": "storefront_inc_vat",
            "in_stock": True,
            "present_on_store": True,
            "confidence_score": 99,
            "variant_barcodes": ["4006381333931"],
            "barcode": "4006381333931",
            "name_ar": "Cat Food 400g",
            "name_en": "Cat Food 400g",
        }
        docs = [
            {**base, "store_id": "c1", "store_name": "Comp 1", "sku": "C1-A", "offer_id": "c1-off", "price": 100.0, "crawled_at": now},
            {**base, "store_id": "c2", "store_name": "Comp 2", "sku": "C2-A", "offer_id": "c2-off", "price": 105.0, "crawled_at": now},
            {**base, "store_id": "c3", "store_name": "Comp 3", "sku": "C3-A", "offer_id": "c3-off", "price": 110.0, "crawled_at": now},
            {**base, "store_id": "c4", "store_name": "Comp 4", "sku": "C4-A", "offer_id": "c4-off", "price": 95.0, "in_stock": False, "crawled_at": now},
            {**base, "store_id": "c5", "store_name": "Comp 5", "sku": "C5-A", "offer_id": "c5-off", "price": 92.0, "in_stock": None, "crawled_at": now},
            {**base, "store_id": "c6", "store_name": "Comp 6", "sku": "C6-A", "offer_id": "c6-off", "price": 90.0, "present_on_store": False, "crawled_at": now},
            # latest invalid replaces earlier valid for same store/offer
            {**base, "store_id": "c2", "store_name": "Comp 2", "sku": "C2-A", "offer_id": "c2-off", "price": 101.0, "crawled_at": old, "currency": "SAR"},
            {**base, "store_id": "c2", "store_name": "Comp 2", "sku": "C2-A", "offer_id": "c2-off", "price": 0, "currency": "USD", "crawled_at": now + timedelta(seconds=5)},
            {**base, "store_id": "c1", "store_name": "Comp 1", "sku": "C1-OLD", "offer_id": "c1-old", "price": 99.0, "crawled_at": old},
            {**base, "store_id": "c3", "store_name": "Comp 3", "sku": "C3-LOWCONF", "offer_id": "c3-low", "price": 93.0, "confidence_score": 65, "crawled_at": now},
            {**base, "store_id": "c3", "store_name": "Comp 3", "sku": "C3-LEG", "offer_id": "c3-leg", "price": 97.0, "observation_version": 1, "crawled_at": now},
        ]
        for i, d in enumerate(docs):
            d.setdefault("event_id", f"evt-{i}")
        await db.product_snapshots.insert_many(docs)

        cohorts = await price_cohort.build_cohorts(db, await db.my_products.find({}, {"_id": 0}).to_list(50), OWN_STORE_ID, _own_price, now=now)
        c = cohorts["OWN-SKU-1"]
        assert [s["store_id"] for s in c["sellers"]] == ["c1", "c3"]
        assert c["min"] == 100.0
        reasons = {e.get("excluded_reason") for e in c["excluded"]}
        assert "out_of_stock" in reasons
        assert "stock_unknown" in reasons
        assert "hidden_listing" in reasons
        assert "stale_or_unknown_observation" in reasons
        assert "low_source_confidence" in reasons
        assert "legacy_or_unverified_offer" in reasons
        assert "currency_or_tax_unverified" in reasons

        intel = await comparison_views.intel(db, _own_price)
        scanner = await comparison_views.scanner(db, 30, _own_price, _orders_none, _sales_rows_none)
        dataset = await catalog_views.dataset(db, 30, None, None, None, None, None, None, False, _own_price, _orders_none)
        detail = await catalog_views.detail(db, "OWN-SKU-1", 30, _own_price)
        intel_detail = await catalog_views.intel_detail(db, "OWN-SKU-1", _own_price)
        ms = await market_share.build_dataset(
            db, 30, OWN_STORE_ID,
            own_price_fn=_own_price,
            brand_fn=lambda a, b, existing="": existing or "BrandX",
            category_fn=lambda _n: "cat_food",
            orders_by_sku=None,
            min_confidence=70,
            window_start=now - timedelta(days=30),
            window_end=now,
            now=now,
        )

        cohort_ids = {
            next(r for r in intel["full_table"] if r["my_sku"] == "OWN-SKU-1")["cohort_id"],
            next(r for r in dataset["rows"] if r["sku"] == "OWN-SKU-1")["cohort_id"],
            detail["cohort_id"],
            intel_detail["cohort_id"],
            next(r for r in ms["my_products"] if r["sku"] == "OWN-SKU-1")["cohort_id"],
        }
        assert len(cohort_ids) == 1
        assert next(r for r in intel["full_table"] if r["my_sku"] == "OWN-SKU-1")["cheapest_price"] == 100.0
        assert next(r for r in dataset["rows"] if r["sku"] == "OWN-SKU-1")["competitor_min_price"] == 100.0
        assert detail["price_range"]["min"] == 100.0
        assert scanner["opportunities"][0]["market_lowest"] == 100.0
        assert scanner["opportunities"][0]["cohort_id"] in cohort_ids
        assert scanner["summary"]["excluded_offers"] >= 1

    _run(_go())


# modules/features: ledger intervals, idempotent events, quarantine, sealed cutoff and KSA day mapping
def test_ledger_idempotency_quarantine_and_sealed_cutoff(db):
    async def _go():
        for c in (
            "stores", "products", "product_snapshots", "observation_events", "observation_quarantine",
            "sales_facts_v2", "daily_ledger_store", "late_observations"
        ):
            await db[c].delete_many({})

        store = _store("seal-store", "Seal Store")
        await db.stores.insert_one(store)
        t1 = datetime(2026, 2, 10, 20, 30, tzinfo=timezone.utc)
        t2 = datetime(2026, 2, 10, 21, 30, tzinfo=timezone.utc)  # next KSA day
        raw = [{
            "id": "list-seal",
            "name": "Seal Product",
            "sku": "SEAL-SKU",
            "barcode": "4006381333931",
            "price": {"amount": "10", "currency": "SAR"},
            "sold_count": 10,
            "quantity": 20,
        }]
        raw2 = [{**raw[0], "sold_count": 15}]
        bad = [{"id": "bad", "name": "Bad", "sku": "BAD-SKU", "price": None, "quantity": 2}]

        await crawlers.process_crawled_products(db, store, raw, t1, tier=1, confidence=99)
        await crawlers.process_crawled_products(db, store, raw2, t2, tier=1, confidence=99)
        await crawlers.process_crawled_products(db, store, raw2, t2, tier=1, confidence=99)  # duplicate event idempotent
        await crawlers.process_crawled_products(db, store, bad, t2, tier=1, confidence=99)

        assert await db.observation_events.count_documents({"offer_id": {"$exists": True}}) == 3
        facts = await db.sales_facts_v2.find({}, {"_id": 0}).to_list(20)
        assert len(facts) == 1
        assert facts[0]["units"] == 5
        assert facts[0]["date"] == "2026-02-11"  # KSA day boundary at 21:00 UTC
        assert await db.observation_quarantine.count_documents({"sku": "BAD-SKU"}) == 1

        sealed_at = datetime.now(timezone.utc)
        await db.daily_ledger_store.insert_one({"store_id": "seal-store", "ksa_date": "2026-02-11", "sealed_at": sealed_at})
        await db.sales_facts_v2.insert_one({
            "_id": f"late-{uuid.uuid4().hex}",
            "store_id": "seal-store",
            "sku": "SEAL-SKU",
            "offer_id": facts[0]["offer_id"],
            "date": "2026-02-11",
            "units": 100,
            "revenue": 1000,
            "source": "sold_count_diff",
            "algorithm_version": 2,
            "created_at": sealed_at + timedelta(seconds=3),
        })

        sales = await evidence_ledger.sales_map(
            db,
            datetime(2026, 2, 10, 21, 0, tzinfo=timezone.utc),
            datetime(2026, 2, 12, 0, 0, tzinfo=timezone.utc),
            sealed=True,
        )
        key = ("seal-store", facts[0]["offer_id"])
        assert sales[key]["units"] == 5  # late ingestion ignored after seal cutoff

    _run(_go())


# modules/features: ingest v2 lease ownership and replay-safe run dedupe
def test_ingest_v2_concurrent_same_run_has_single_writer(db):
    async def _go():
        for c in ("stores", "products", "product_snapshots", "ingest_runs", "job_leases", "observation_quarantine"):
            await db[c].delete_many({})

        await db.stores.insert_one({
            "id": "ingest-store",
            "name": "Ingest Store",
            "domain": "ingest-store.sa",
            "platform": "salla",
            "is_active": True,
        })
        payload = SimpleNamespace(
            store_id="ingest-store",
            store_name="Ingest Store",
            domain="ingest-store.sa",
            platform="salla",
            run_id="run-abc",
            observed_at="2026-02-12T10:00:00+00:00",
            catalog_complete=True,
            products=[{
                "listing_id": "l-1",
                "id": "l-1",
                "name_ar": "Ingest Cat Food",
                "sku": "ING-1",
                "barcode": "4006381333931",
                "price": {"amount": "55", "currency": "SAR"},
                "quantity": 3,
            }],
        )

        r1, r2 = await asyncio.gather(
            ingest_v2.ingest(db, payload),
            ingest_v2.ingest(db, payload),
            return_exceptions=True,
        )
        statuses = []
        for r in (r1, r2):
            if isinstance(r, dict):
                statuses.append(r["status"])
            elif isinstance(r, HTTPException):
                statuses.append(f"http_{r.status_code}")
            else:
                statuses.append(type(r).__name__)

        assert any(s in ("complete", "partial", "duplicate") for s in statuses)
        assert any(s in ("duplicate", "http_409", "complete") for s in statuses)
        assert await db.product_snapshots.count_documents({"store_id": "ingest-store", "crawled_at": datetime.fromisoformat("2026-02-12T10:00:00+00:00")}) == 1

    _run(_go())


# modules/features: own orders completeness window semantics
def test_own_orders_aggregate_requires_complete_coverage_and_normalizes_invalid_orders(db):
    async def _go():
        for c in ("orders_sync_coverage", "own_store_orders"):
            await db[c].delete_many({})

        start = datetime(2026, 2, 1, tzinfo=timezone.utc)
        end = datetime(2026, 2, 2, tzinfo=timezone.utc)
        # no coverage -> None
        assert await server._own_orders_aggregate(db, start, end) is None

        await db.orders_sync_coverage.insert_one({"status": "complete", "window_start": start, "window_end": end})
        # complete coverage + empty window -> exact zeros
        z = await server._own_orders_aggregate(db, start, end)
        assert z["orders_count"] == 0 and z["revenue"] == 0.0 and z["units"] == 0

        await db.own_store_orders.insert_many([
            {
                "created_at": start + timedelta(hours=1),
                "excluded": False,
                "financials_complete": True,
                "currency": "SAR",
                "total": 100,
                "units": 2,
                "items": [{"sku": "OWN-SKU-1", "qty": 2, "line_total": 100}],
            },
            {
                "created_at": start + timedelta(hours=2),
                "excluded": False,
                "financials_complete": False,
                "currency": "SAR",
                "total": 999,
                "units": 9,
                "items": [{"sku": "OWN-SKU-1", "qty": 9, "line_total": 999}],
            },
            {
                "created_at": start + timedelta(hours=3),
                "excluded": False,
                "financials_complete": True,
                "currency": "USD",
                "total": 55,
                "units": 1,
                "items": [{"sku": "OWN-SKU-1", "qty": 1, "line_total": 55}],
            },
        ])
        agg = await server._own_orders_aggregate(db, start, end)
        assert agg["orders_count"] == 1
        assert agg["revenue"] == 100.0
        assert agg["by_sku"]["OWN-SKU-1"]["units"] == 2

    _run(_go())


# Store profiles and ranking must not extrapolate a short interval into monthly revenue.
def test_store_views_use_same_observed_window_without_extrapolation(db):
    async def _go():
        import store_views
        for name in ("stores", "products", "product_snapshots", "observation_events", "sales_facts_v2", "daily_ledger_store"):
            await db[name].delete_many({})
        store = _store("metrics-v2", "Metrics V2")
        await db.stores.insert_one(store)
        at = datetime.now(timezone.utc)-timedelta(days=2)
        first = {"id": "observed", "sku": "M", "name": "Actual offer", "quantity": 20, "price": {"amount": 10, "currency": "SAR"}}
        await crawlers.process_crawled_products(db, store, [first], at, tier=1)
        await crawlers.process_crawled_products(db, store, [{**first, "quantity": 18}], at+timedelta(hours=1), tier=1)
        import ledger
        await db.daily_ledger_store.insert_one({"store_id": store["id"], "ksa_date": ledger.ksa_day_str(at+timedelta(hours=1)), "sealed_at": datetime.now(timezone.utc)})
        profile = await store_views.profile(db, store["id"], _orders_none)
        ranking = await store_views.ranking(db, _orders_none)
        assert profile["kpis"]["est_monthly_revenue"] == ranking["stores"][0]["revenue_30d"] == 20
        assert profile["kpis"]["revenue_basis"] == "inventory_proxy"
        assert ranking["stores"][0]["revenue_tier"] != "exact"
        assert ranking["sorted_by"] == "verified_offer_coverage_desc"
        assert profile["top_products"][0]["name_ar"] == "Actual offer"
        assert sum(day["revenue"] for day in profile["revenue_trend_daily"]) == 20
    _run(_go())


# modules/features: durable leases, queue dedupe, execute status transitions
def test_discount_offer_identity_and_legacy_quarantine(db):
    async def _go():
        import discount_views
        for name in ("stores", "products", "product_snapshots"):
            await db[name].delete_many({})
        store = _store("discount-offers", "Discount offers")
        await db.stores.insert_one(store)
        now = datetime.now(timezone.utc)
        raw = {"id": "listing-discount", "name": "Parent", "skus": [
            {"id": "small", "sku": "REUSED", "name": "Small 100g", "price": 20, "sale_price": 10, "quantity": 2},
            {"id": "large", "sku": "REUSED", "name": "Large 400g", "price": 80, "quantity": 2},
        ]}
        await crawlers.process_crawled_products(db, store, [raw], now, tier=1)
        await db.product_snapshots.insert_one({"offer_id": "fake", "sku": "REUSED", "store_id": store["id"], "price": 1, "original_price": 1000, "in_stock": True, "crawled_at": now, "is_synthetic": True})
        rows = await discount_views.top(db, 7)
        assert len(rows) == 1 and rows[0]["name_ar"] == "Small 100g"
        assert rows[0]["price"] == 10 and rows[0]["discount_pct"] == 50
    _run(_go())


def test_job_control_lease_queue_and_execute_status(db):
    async def _go():
        for c in ("job_leases", "job_runs"):
            await db[c].delete_many({})

        a = await job_control.acquire(db, "lease:test", "owner-a")
        b = await job_control.acquire(db, "lease:test", "owner-b")
        assert a is True and b is False
        await job_control.release(db, "lease:test", "owner-a")

        run_id, fresh1 = await job_control.queue(db, "digest", key="same-webhook")
        run_id2, fresh2 = await job_control.queue(db, "digest", key="same-webhook")
        assert run_id == run_id2 == "same-webhook"
        assert fresh1 is True and fresh2 is False

        async def ok_action():
            return {"status": "ok", "sync_status": "ok"}

        await job_control.execute(db, run_id, "digest", ok_action)
        row = await db.job_runs.find_one({"_id": run_id}, {"_id": 0})
        assert row["status"] == "completed"

    _run(_go())


# modules/features: cron route auth/envelope validation and duplicate webhook dedupe
def test_cron_dispatch_auth_payload_and_duplicate_queue(db, monkeypatch):
    # Keep this protocol test on its disposable DB; runtime capability behavior
    # is exercised separately through GuardedDatabase deployment-safety tests.
    monkeypatch.setattr(server, "db", db)
    prev_secret = os.environ.get("WEBHOOK_CRON_SECRET")
    os.environ["WEBHOOK_CRON_SECRET"] = "iter37-secret"

    seen = set()

    async def _fake_queue(_db, kind, key=None):
        run_id = key or f"{kind}-{uuid.uuid4().hex[:6]}"
        fresh = run_id not in seen
        if fresh:
            seen.add(run_id)
        return run_id, fresh

    async def _fake_execute(_db, run_id, kind, action):
        _ = (run_id, kind)
        await action()
        return None

    async def _fake_digest():
        return {"status": "ok"}

    monkeypatch.setattr(job_control, "queue", _fake_queue)
    monkeypatch.setattr(job_control, "execute", _fake_execute)
    monkeypatch.setattr(server, "generate_market_digest", _fake_digest)
    client = TestClient(server.app)
    try:
        # wrong secret
        r = client.post("/api/cron/digest", headers={"Authorization": "Bearer wrong"}, json={})
        assert r.status_code == 401

        # malformed payload
        r = client.post(
            "/api/cron/digest",
            headers={"Authorization": "Bearer iter37-secret"},
            json={"event": "x"},
        )
        assert r.status_code == 400

        hdrs = {"Authorization": "Bearer iter37-secret", "X-Webhook-Id": "wh-123"}
        body = {"event": "schedule.triggered", "run_id": "wh-123"}
        ok1 = client.post("/api/cron/digest", headers=hdrs, json=body)
        ok2 = client.post("/api/cron/digest", headers=hdrs, json=body)
        assert ok1.status_code == 200 and ok1.json()["duplicate"] is False
        assert ok2.status_code == 200 and ok2.json()["duplicate"] is True
    finally:
        if prev_secret is None:
            os.environ.pop("WEBHOOK_CRON_SECRET", None)
        else:
            os.environ["WEBHOOK_CRON_SECRET"] = prev_secret
