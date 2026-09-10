"""iter73y (Aug 10 2026) — the product-detail hang, fixed at the query level.

Client re-reported the iter73x symptom AFTER redeploying the hotfix: clicking
any product on "My Products" left the panel on "LOADING…" forever, and the
dashboard's "Checking data freshness…" spinner never resolved either.

iter73x added the three missing indexes. That was necessary but not
sufficient, because the query itself was structurally unsafe:

  * ONE `find()` merged every key class into a single `$or`
    (sku / store-scoped aliases / barcode / variant_skus / variant_barcodes),
    sorted it by `crawled_at`, and pulled up to 8000 FULL snapshot documents.
    An `$or` is only as fast as its worst branch — one unindexed or multikey
    branch and MongoDB collapses the whole thing into a COLLSCAN.
  * `product_matches` had NO index on production at all: its indexes were only
    ever created inside `seed_database()` (early-returns on a live DB) and the
    CSV-import path. Three COLLSCANs of it per click.
  * `/api/data-freshness` ran a `$group` over the WHOLE product_snapshots
    collection with no `$match` — a full scan every 60s cache miss, competing
    for the same database.
  * All ~35 startup indexes lived in ONE try/except: the first failure skipped
    every index after it, so the iter73x indexes could be deployed and still
    not exist.
  * The frontend request had no timeout and a bare `.catch(console.error)`, so
    a backend stall showed as an eternal "Loading…" with no way out.

This suite fences all five.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_iter73y_bounded"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_iter73y_bounded"
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
SRC = Path(server.__file__).read_text()
FRONTEND = Path(__file__).parent.parent.parent / "frontend" / "src"


def _seller_fn():
    a = SRC.index("async def _seller_snapshots(db, sku, product,")
    b = SRC.index("    return kept, set(sku_keys), len(excluded)", a)
    return SRC[a:b]


# ── 1. structural fences ────────────────────────────────────────────────────
def test_iter73y_marker_present():
    assert "iter73y" in SRC


def test_seller_snapshots_no_longer_merges_key_classes_into_one_or():
    """The single mega-`$or` is what allowed one bad branch to COLLSCAN the
    whole collection. It must not come back."""
    fn = _seller_fn()
    assert 'query["$or"]' not in fn
    assert "all_clauses" not in fn


def test_seller_snapshots_queries_each_key_class_separately():
    fn = _seller_fn()
    assert "_discover_snapshot_pairs(" in fn
    assert "_pair_snapshot_rows(" in fn
    # the four key classes are still consulted (iter73u/iter73v contract)
    for field in ("sku", "barcode", "variant_skus", "variant_barcodes"):
        assert f'"{field}"' in fn


def test_every_snapshot_read_has_a_server_side_deadline():
    """No request may hang for minutes again: each read carries maxTimeMS."""
    disc = SRC.split("async def _discover_snapshot_pairs(", 1)[1].split(
        "\nasync def ", 1)[0]
    pair = SRC.split("async def _pair_snapshot_rows(", 1)[1].split(
        "\nasync def ", 1)[0]
    assert "maxTimeMS=SELLER_QUERY_MAX_MS" in disc
    assert "max_time_ms(" in pair
    assert server.SELLER_QUERY_MAX_MS <= 15000


def test_bounded_caps_are_sane():
    assert 0 < server.SELLER_PAIR_CAP <= 500
    assert 0 < server.SELLER_ROWS_PER_PAIR <= 500
    assert 0 < server._SELLER_FETCH_FANOUT <= 50


def test_projection_excludes_the_heavy_variant_arrays():
    """Fetching thousands of docs carrying `variant_skus` /
    `variant_barcodes` was megabytes of BSON decoded on the event loop."""
    fields = server._SELLER_SNAP_FIELDS
    assert fields["_id"] == 0
    for heavy in ("variant_skus", "variant_barcodes", "variants"):
        assert heavy not in fields
    for needed in ("store_id", "store_name", "sku", "price", "qty_available",
                   "in_stock", "crawled_at", "confidence_score", "product_url"):
        assert fields.get(needed) == 1, needed


def test_data_freshness_no_longer_groups_the_whole_collection():
    block = SRC.split("async def data_freshness(", 1)[1].split(
        "\n@router", 1)[0]
    assert '"$group"' not in block, \
        "data-freshness must not aggregate the whole product_snapshots collection"
    assert "_store_freshness" in block
    assert 'find(\n                {"store_id": sid}' in block or \
        '{"store_id": sid}' in block


def test_index_registry_covers_product_matches():
    """product_matches was UNINDEXED on production — three COLLSCANs per
    product click."""
    specs = {(coll, tuple(keys)) for coll, keys, _o in server.INDEX_SPECS}
    assert ("product_matches",
            (("my_sku", 1), ("competitor_sku", 1), ("competitor_store_id", 1))) in specs
    assert ("product_matches",
            (("competitor_sku", 1), ("competitor_store_id", 1))) in specs
    assert ("product_snapshots",
            (("store_id", 1), ("sku", 1), ("crawled_at", -1))) in specs


def test_each_index_is_created_independently():
    """One failure must not skip every index after it — the reason the
    iter73x hotfix could deploy without its indexes."""
    helper = SRC.split("async def ensure_all_indexes(", 1)[1].split(
        "\n@router", 1)[0]
    assert "for coll, keys, opts in INDEX_SPECS" in helper
    assert "except Exception as exc" in helper


def test_perf_probe_endpoint_registered_and_gated():
    routes = {getattr(r, "path", None) for r in server.app.router.routes}
    assert "/api/admin/perf-probe" in routes
    ep = SRC.split("async def admin_perf_probe(", 1)[1].split("\n@router", 1)[0]
    assert "require_super_admin" in SRC.split(
        "async def admin_perf_probe(", 1)[1][:200]
    assert "executionStats" in ep


def test_frontend_panel_cannot_load_forever():
    panel = (FRONTEND / "components" / "ProductDetailPanel.jsx").read_text()
    assert "timeout: 45000" in panel
    assert 'data-testid="product-detail-error"' in panel
    assert 'data-testid="product-detail-retry-btn"' in panel
    i18n = (FRONTEND / "lib" / "i18n.js").read_text()
    for key in ("detail_timeout", "detail_failed", "retry"):
        assert f"{key}:" in i18n


# ── 2. behaviour against a real MongoDB ─────────────────────────────────────
MY_SKU = "052742024363"
PRODUCT = {"sku": MY_SKU, "barcode": "052742024363",
           "name_ar": "", "name_en": "Applaws Chicken 400g"}


async def _seed(db):
    now = datetime.now(timezone.utc)
    await db.product_snapshots.delete_many({})
    await db.product_matches.delete_many({})
    await db.products.delete_many({})
    await db.products.insert_one(dict(PRODUCT))
    rows = []
    # A — variant-only barcode carrier (the Zarafa case): synthetic primary sku
    for d in (1, 3, 5):
        rows.append({"store_id": "storeA", "store_name": "Zarafa",
                     "sku": "S-zarafa-1", "barcode": "",
                     "variant_skus": ["052742024363"],
                     "variant_barcodes": ["052742024363", "052742024370"],
                     "price": 100.0 + d, "qty_available": 5, "in_stock": True,
                     "crawled_at": now - timedelta(days=d)})
    # B — exact SKU match, several rows inside the chart window
    for d in (1, 2, 4, 6):
        rows.append({"store_id": "storeB", "store_name": "Petsy",
                     "sku": MY_SKU, "barcode": "052742024363",
                     "price": 90.0 + d, "qty_available": 3, "in_stock": True,
                     "crawled_at": now - timedelta(days=d)})
    # C — reachable only through product_matches, and STALE (100 days old)
    rows.append({"store_id": "storeC", "store_name": "Hamtaro",
                 "sku": "COMP-C", "barcode": "",
                 "price": 80.0, "qty_available": 1, "in_stock": True,
                 "crawled_at": now - timedelta(days=100)})
    # D — unrelated product, must never surface
    rows.append({"store_id": "storeD", "store_name": "Other",
                 "sku": "UNRELATED", "barcode": "999999999999",
                 "variant_barcodes": ["999999999998"],
                 "price": 70.0, "qty_available": 9, "in_stock": True,
                 "crawled_at": now - timedelta(days=1)})
    await db.product_snapshots.insert_many(rows)
    await db.product_matches.insert_one(
        {"my_sku": MY_SKU, "competitor_sku": "COMP-C",
         "competitor_store_id": "storeC", "confidence": 100})
    await server.ensure_all_indexes(db)


def _run(coro_fn):
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        server.db = db
        await _seed(db)
        return await coro_fn(db)
    return asyncio.run(main())


def test_all_three_seller_classes_surface_and_the_stranger_does_not():
    async def body(db):
        rows, sku_keys, excluded = await server._seller_snapshots(
            db, MY_SKU, PRODUCT, series_days=30)
        stores = {r["store_id"] for r in rows}
        assert stores == {"storeA", "storeB", "storeC"}, stores
        return rows
    _run(body)


def test_stale_seller_returns_exactly_one_row_not_zero():
    """storeC's only snapshot predates the 30-day chart window. It must still
    appear once so the table can render "price as of <date>"."""
    async def body(db):
        rows, _k, _e = await server._seller_snapshots(
            db, MY_SKU, PRODUCT, series_days=30)
        c_rows = [r for r in rows if r["store_id"] == "storeC"]
        assert len(c_rows) == 1
        assert c_rows[0]["price"] == 80.0
    _run(body)


def test_rows_come_back_oldest_to_newest():
    async def body(db):
        rows, _k, _e = await server._seller_snapshots(
            db, MY_SKU, PRODUCT, series_days=30)
        stamps = [server._as_aware(r["crawled_at"]) for r in rows]
        assert stamps == sorted(stamps)
    _run(body)


def test_cap_drops_the_oldest_rows_never_the_newest():
    async def body(db):
        rows, _k, _e = await server._seller_snapshots(
            db, MY_SKU, PRODUCT, cap=2, series_days=30)
        assert len(rows) == 2
        all_rows, _k2, _e2 = await server._seller_snapshots(
            db, MY_SKU, PRODUCT, series_days=30)
        newest = sorted(server._as_aware(r["crawled_at"]) for r in all_rows)[-2:]
        assert sorted(server._as_aware(r["crawled_at"]) for r in rows) == newest
    _run(body)


def test_returned_rows_carry_no_variant_arrays():
    async def body(db):
        rows, _k, _e = await server._seller_snapshots(
            db, MY_SKU, PRODUCT, series_days=30)
        for r in rows:
            assert "variant_skus" not in r
            assert "variant_barcodes" not in r
            assert "_id" not in r
    _run(body)


def test_no_key_class_lookup_falls_back_to_a_collection_scan():
    """THE regression fence for the reported hang: every discovery lookup must
    be served by an index."""
    async def body(db):
        since = datetime.now(timezone.utc) - timedelta(days=180)
        keys = ["052742024363", "00052742024363"]
        for field in ("sku", "barcode", "variant_skus", "variant_barcodes"):
            res = await db.command({
                "explain": {
                    "aggregate": "product_snapshots",
                    "pipeline": [
                        {"$match": {field: {"$in": keys},
                                    "crawled_at": {"$gte": since}}},
                        {"$group": {"_id": {"s": "$store_id", "k": "$sku"}}},
                    ],
                    "cursor": {},
                },
                "verbosity": "executionStats",
            })
            summary = server._plan_summary(res)
            assert not summary["collscan"], f"{field} lookup COLLSCANs: {summary}"
    _run(body)


def test_pair_read_is_bounded_by_rows_per_pair():
    async def body(db):
        now = datetime.now(timezone.utc)
        await db.product_snapshots.insert_many([
            {"store_id": "storeE", "store_name": "Bulk", "sku": MY_SKU,
             "price": 10.0 + i, "qty_available": 1, "in_stock": True,
             "crawled_at": now - timedelta(hours=i)}
            for i in range(server.SELLER_ROWS_PER_PAIR + 50)
        ])
        rows = await server._pair_snapshot_rows(
            db, "storeE", MY_SKU, now - timedelta(days=30),
            now - timedelta(days=180))
        assert len(rows) == server.SELLER_ROWS_PER_PAIR
    _run(body)


def test_perf_probe_reports_timings_and_plans():
    async def body(db):
        out = await server.admin_perf_probe(
            sku=MY_SKU, user={"id": "t", "email": "t@t", "role": "super_admin"})
        assert out["counts"]["product_found"] is True
        assert out["timings_ms"]["seller_snapshots"] >= 0
        assert out["counts"]["stores"] == 3
        assert set(out["plans"]) >= {"sku", "barcode", "variant_skus",
                                     "variant_barcodes"}
        for field, plan in out["plans"].items():
            assert plan["collscan"] is False, (field, plan)
    _run(body)


def test_ensure_all_indexes_is_idempotent_and_reports_failures_by_name():
    async def body(db):
        r1 = await server.ensure_all_indexes(db)
        r2 = await server.ensure_all_indexes(db)
        assert r1.keys() == r2.keys()
        failed = {k: v for k, v in r2.items() if not v.get("ok")}
        assert not failed, failed
    _run(body)
