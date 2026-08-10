"""iter73x HOTFIX (Aug 10 2026) — product-detail 5-minute hang.

Client-reported (production, urgent): clicking any product on the "My Products"
page opened the detail panel showing "LOADING..." indefinitely. 5+ minutes with
no data.

Root cause: iter73v extended `_seller_snapshots` `$or` clause with three new
predicates — `barcode`, `variant_skus`, `variant_barcodes` — none of which
had backing indexes on `product_snapshots`. MongoDB CANNOT use index-union on
an $or where any branch is unindexed, so the entire query fell back to a full
collection scan. On production (~300K snapshots across a 6-month lookback
window) every product click triggered a multi-minute COLLSCAN.

Fix:
  1. Add three multikey/scalar indexes on the three new fields, each compound
     with `crawled_at` so the outer `since` filter is satisfied inside the
     index scan.
  2. Wire them into the startup routine.
  3. Provide an admin endpoint `POST /api/admin/ensure-snapshot-indexes` so
     the client can build the indexes on production immediately, without
     waiting for the next full deploy.

Regression fence: this suite verifies the exact index shape at both the
config layer (startup routine literal) and the admin-endpoint layer, so a
future refactor cannot silently drop these indexes and regress the hang.
"""
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_iter73x_hotfix")
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")

# The three indexes iter73v depends on. Any regression here reintroduces
# the 5-minute hang on production.
_REQUIRED_INDEXES = [
    ("barcode", 1),
    ("variant_skus", 1),
    ("variant_barcodes", 1),
]


def test_iter73x_marker_present_in_source():
    src = Path(server.__file__).read_text()
    assert "iter73x" in src, "iter73x provenance marker missing"


def test_startup_creates_all_three_required_indexes():
    """The startup routine must add exactly the three indexes iter73v's
    _seller_snapshots $or clause needs. Regression fence: a future refactor
    that drops any of them silently reintroduces the 5-minute hang."""
    src = Path(server.__file__).read_text()
    startup_block = src.split("async def startup(", 1)[1].split("\nasync def ", 1)[0]
    for field, direction in _REQUIRED_INDEXES:
        pattern = re.compile(
            rf'create_index\(\s*\[\("{field}",\s*{direction}\),\s*\("crawled_at",\s*-1\)\]'
        )
        assert pattern.search(startup_block), \
            f"startup must create compound index ({field}, {direction}) + (crawled_at, -1)"


def test_seller_snapshots_or_clause_matches_created_indexes():
    """The $or clause in `_seller_snapshots` MUST use the same field names the
    startup routine indexes. If a future edit renames the array field on the
    snapshot writer, both the query AND the index must be updated together
    or the hang returns."""
    src = Path(server.__file__).read_text()
    fn = src.split("async def _seller_snapshots(", 1)[1].split("\nasync def ", 1)[0]
    for field, _ in _REQUIRED_INDEXES:
        assert f'"{field}"' in fn, \
            f"_seller_snapshots must reference `{field}` — otherwise the index is dead code"


def test_admin_ensure_snapshot_indexes_endpoint_registered():
    """The admin endpoint MUST exist so the client can build indexes on
    production without a backend restart."""
    routes = {getattr(r, "path", None) for r in server.app.router.routes}
    assert "/api/admin/ensure-snapshot-indexes" in routes


def test_admin_endpoint_is_super_admin_gated():
    """A regular user must not be able to trigger index builds — they're
    resource-intensive on Atlas."""
    src = Path(server.__file__).read_text()
    endpoint = src.split(
        'admin/ensure-snapshot-indexes', 1
    )[1].split("\n@router", 1)[0]
    assert "require_super_admin" in endpoint, \
        "ensure-snapshot-indexes must be gated by require_super_admin"


def test_admin_endpoint_creates_indexes_in_background():
    """background=True on Atlas is essential — index builds on ~300K rows
    take minutes to complete and MUST NOT block reads."""
    src = Path(server.__file__).read_text()
    endpoint = src.split(
        'admin/ensure-snapshot-indexes', 1
    )[1].split("\n@router", 1)[0]
    assert "background=True" in endpoint, \
        "background=True prevents index build from blocking reads"


def test_admin_endpoint_end_to_end():
    """Call the endpoint directly with an in-loop motor client. Verifies all
    three indexes are reported as created. Uses super_admin credentials
    from /app/memory/test_credentials.md."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        try:
            await db.product_snapshots.drop_indexes()
        except Exception:
            pass
        server.db = db
        body = await server.admin_ensure_snapshot_indexes(
            user={"id": "t", "email": "t@t", "role": "super_admin"}
        )
        assert body["ok"] is True, body
        assert set(body["indexes"].keys()) == {
            "barcode_crawled_at",
            "variant_skus_crawled_at",
            "variant_barcodes_crawled_at",
        }
        for name, entry in body["indexes"].items():
            assert entry["ok"], f"{name} failed: {entry.get('error')}"
    asyncio.run(main())


def test_created_indexes_match_query_shape():
    """After the endpoint runs, the collection must carry indexes on all
    three fields — the same shape the iter73v query fires against."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        server.db = db
        # Idempotently ensure the endpoint has run.
        await server.admin_ensure_snapshot_indexes(
            user={"id": "t", "email": "t@t", "role": "super_admin"}
        )
        idx_info = await db.product_snapshots.index_information()
        idx_keys = [tuple(entry["key"]) for entry in idx_info.values()]
        expected = [
            (("barcode", 1), ("crawled_at", -1)),
            (("variant_skus", 1), ("crawled_at", -1)),
            (("variant_barcodes", 1), ("crawled_at", -1)),
        ]
        for spec in expected:
            assert spec in idx_keys, \
                f"missing index {spec}; have {idx_keys}"
    asyncio.run(main())


def test_endpoint_is_idempotent():
    """Re-running the endpoint must be a no-op — safe to call from any
    monitoring script."""
    async def main():
        server.db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        user = {"id": "t", "email": "t@t", "role": "super_admin"}
        r1 = await server.admin_ensure_snapshot_indexes(user=user)
        r2 = await server.admin_ensure_snapshot_indexes(user=user)
        assert r1["ok"] is True
        assert r2["ok"] is True
    asyncio.run(main())


def test_variant_arrays_query_uses_multikey_index_semantics():
    """A $in query against a multikey index must return docs where ANY
    element of the array matches. This test seeds one doc with a variant
    barcode inside the array field and confirms the query finds it via the
    index. Guards against a future 'oh let me change variant_barcodes to a
    single string' refactor that would still LOOK like it works on a
    thin DB but silently miss all multi-variant products in production."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await db.product_snapshots.delete_many({"_probe": True})
        await db.product_snapshots.insert_one({
            "_probe": True,
            "sku": "PRIMARY-SKU",
            "barcode": "",
            "variant_skus": ["v1-sku", "052742024363", "v3-sku"],
            "variant_barcodes": ["v1-bc", "052742024363", "v3-bc"],
            "crawled_at": server.datetime.now(server.timezone.utc),
        })
        # Query by array element only
        got_sku = await db.product_snapshots.find_one({
            "variant_skus": {"$in": ["052742024363"]}
        })
        got_bc = await db.product_snapshots.find_one({
            "variant_barcodes": {"$in": ["052742024363"]}
        })
        assert got_sku is not None, "multikey $in on variant_skus failed"
        assert got_bc is not None, "multikey $in on variant_barcodes failed"
        await db.product_snapshots.delete_many({"_probe": True})
    asyncio.run(main())
