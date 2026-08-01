"""iter72 — the "My Stock" column must never lie.

Client report: products they do NOT sell were showing "HIGH" stock. Two
fabrication paths caused it:

  1. `_my_products_dataset` carried a market-aggregate `stock_signal`
     (max qty across COMPETITOR snapshots) on every row, and the frontends
     rendered it in the My Stock column via `my_stock_signal || stock_signal`
     / a MEDIUM tone fallback.
  2. Rows with no snapshot history at all got a hardcoded
     `"stock_signal": "MEDIUM"` from the metrics-default dict.

The contract now:
  * NOT in my_products (exact SKU or canonical GTIN-14 barcode — nothing
    fuzzy) → `my_stock_status="not_in_catalog"`, `my_stock_signal=None`.
    Never a level, no matter what competitors stock.
  * In my catalog with real quantity/in_stock → level from THAT data only.
  * In my catalog with both fields missing → `my_stock_status="unknown"`,
    signal None — rendered "—", never an invented MEDIUM and never a
    fabricated OOS from treating missing quantity as zero.
"""
import asyncio
import inspect
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_my_stock")
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
USER = {"id": "t", "email": "t@t", "role": "super_admin"}
OWN = "own-store-id"
NOW = datetime.now(timezone.utc)
FRONTEND = Path(__file__).parent.parent.parent / "frontend" / "src"


def _snap(sku, store_id, price, qty=500, in_stock=True, age_days=1):
    return {"id": f"s-{store_id}-{sku}", "sku": sku, "store_id": store_id,
            "store_name": store_id, "price": price, "in_stock": in_stock,
            "qty_available": qty, "confidence_score": 95, "source_tier": 1,
            "crawled_at": NOW - timedelta(days=age_days)}


def _my(sku, barcode, qty, in_stock, price=100.0):
    return {"sku": sku, "barcode": barcode, "price": price, "sale_price": None,
            "quantity": qty, "in_stock": in_stock,
            "name_ar": "منتج", "name_en": f"Product {sku}",
            "is_own_store": True, "store_id": OWN,
            "last_synced_at": (NOW - timedelta(hours=2)).isoformat()}


async def _seed(db, my_products, products, snapshots):
    for c in ("stores", "my_products", "products", "product_snapshots",
              "product_matches", "dashboard_cache", "own_store_orders"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com",
         "platform": "zid", "is_own_store": True},
        {"id": "comp", "name": "Competitor", "domain": "comp.example", "platform": "salla"},
    ])
    if my_products:
        await db.my_products.insert_many(my_products)
    if products:
        await db.products.insert_many(products)
    if snapshots:
        await db.product_snapshots.insert_many(snapshots)
    server.db = db
    return db


def _db():
    return AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]


async def _market_dataset(db):
    return await server._my_products_dataset(
        db, 30, None, None, None, None, None, None, False)


# ── (a) market row absent from my catalog → never a level ───────────────────

def test_market_row_not_in_catalog_never_gets_a_level():
    async def main():
        db = await _seed(
            _db(),
            my_products=[_my("MINE-1", "6291041500213", 50, True)],
            products=[
                {"sku": "MINE-1", "barcode": "6291041500213", "name_ar": "لي", "name_en": "Mine"},
                # market-only product; competitor stocks it HEAVILY (qty 500)
                {"sku": "MKT-1", "barcode": "0052742059518", "name_ar": "سوق", "name_en": "Market only"},
            ],
            snapshots=[_snap("MKT-1", "comp", 80.0, qty=500, in_stock=True),
                       _snap("MINE-1", "comp", 90.0, qty=500, in_stock=True)],
        )
        ds = await _market_dataset(db)
        row = next(r for r in ds["rows"] if r["sku"] == "MKT-1")
        assert row["my_stock_status"] == "not_in_catalog"
        assert row["my_stock_signal"] is None            # never HIGH/MEDIUM/LOW/OOS
        # the competitor's qty=500 must not leak into any my-stock field
        assert row.get("my_quantity") is None

        # and the Sales-Insights projection carries the same verdict
        out = await server._insights_sales_compute(
            db, 30, None, None, None, "revenue_desc", USER)
        mkt = next(p for p in out["products"] if p["sku"] == "MKT-1")
        assert mkt["my_stock_status"] == "not_in_catalog"
        assert mkt["my_stock_signal"] is None
    asyncio.run(main())


# ── (b) in-catalog level comes from MY real quantity, not the market ────────

def test_in_catalog_level_comes_from_real_quantity():
    async def main():
        db = await _seed(
            _db(),
            my_products=[
                _my("HI", "6291041500213", 50, True),    # 50  -> HIGH
                _my("LO", "6291041500220", 5, True),     # 5   -> LOW
                _my("OUT", "6291041500237", 0, False),   # OOS
            ],
            products=[
                {"sku": "HI", "barcode": "6291041500213", "name_ar": "أ", "name_en": "Hi"},
                {"sku": "LO", "barcode": "6291041500220", "name_ar": "ب", "name_en": "Lo"},
                {"sku": "OUT", "barcode": "6291041500237", "name_ar": "ج", "name_en": "Out"},
            ],
            # competitor snapshots deliberately contradict my inventory
            snapshots=[_snap("HI", "comp", 90.0, qty=0, in_stock=False),
                       _snap("LO", "comp", 90.0, qty=500, in_stock=True),
                       _snap("OUT", "comp", 90.0, qty=500, in_stock=True)],
        )
        ds = await _market_dataset(db)
        by_sku = {r["sku"]: r for r in ds["rows"]}
        assert by_sku["HI"]["my_stock_signal"] == "HIGH"
        assert by_sku["LO"]["my_stock_signal"] == "LOW"
        assert by_sku["OUT"]["my_stock_signal"] == "OOS"
        for sku in ("HI", "LO", "OUT"):
            assert by_sku[sku]["my_stock_status"] == "ok"
    asyncio.run(main())


# ── (c) in-catalog with missing data → unknown, not MEDIUM, not OOS ─────────

def test_in_catalog_missing_data_is_unknown_not_a_default_level():
    async def main():
        db = await _seed(
            _db(),
            my_products=[_my("NODATA", "6291041500213", None, None)],
            products=[{"sku": "NODATA", "barcode": "6291041500213",
                       "name_ar": "؟", "name_en": "No data"}],
            snapshots=[_snap("NODATA", "comp", 90.0, qty=500, in_stock=True)],
        )
        ds = await _market_dataset(db)
        row = next(r for r in ds["rows"] if r["sku"] == "NODATA")
        assert row["my_stock_signal"] is None
        assert row["my_stock_status"] == "unknown"
    asyncio.run(main())


def test_no_snapshot_history_row_has_no_invented_market_signal():
    """The old metrics-default dict hardcoded stock_signal="MEDIUM" for
    own-catalog rows with zero snapshot history. Now: market signal unknown
    (None), while MY stock still resolves from my_products."""
    async def main():
        db = await _seed(
            _db(),
            my_products=[_my("FRESH", "6291041500213", 50, True)],
            products=[{"sku": "FRESH", "barcode": "6291041500213",
                       "name_ar": "جديد", "name_en": "Fresh"}],
            snapshots=[],                                # no history at all
        )
        ds = await server._my_products_dataset(
            db, 30, None, None, None, None, None, None, True)
        row = next(r for r in ds["rows"] if r["sku"] == "FRESH")
        assert row["stock_signal"] is None               # not "MEDIUM"
        assert row["my_stock_signal"] == "HIGH"          # my real qty=50
        assert row["my_stock_status"] == "ok"
    asyncio.run(main())


# ── membership is exact: canonical barcode counts, nothing fuzzy ────────────

def test_barcode_identity_membership_is_exact_not_fuzzy():
    async def main():
        db = await _seed(
            _db(),
            my_products=[_my("MY-SKU", "6291041500213", 5, True)],
            products=[
                # same trade item under a competitor SKU: leading zero differs,
                # canonical GTIN-14 equal -> IN my catalog, stock from MY doc
                {"sku": "COMP-SKU", "barcode": "06291041500213",
                 "name_ar": "نفس", "name_en": "Same item, comp sku"},
                # similar name, different barcode -> NOT mine (no name fuzz)
                {"sku": "LOOKALIKE", "barcode": "6291041500442",
                 "name_ar": "منتج", "name_en": "Product MY-SKU lookalike"},
            ],
            snapshots=[_snap("COMP-SKU", "comp", 90.0, qty=500, in_stock=True),
                       _snap("LOOKALIKE", "comp", 90.0, qty=500, in_stock=True)],
        )
        ds = await _market_dataset(db)
        by_sku = {r["sku"]: r for r in ds["rows"]}
        same = by_sku["COMP-SKU"]
        assert same["my_stock_status"] == "ok"
        assert same["my_stock_signal"] == "LOW"          # MY qty=5, not comp's 500
        look = by_sku["LOOKALIKE"]
        assert look["my_stock_status"] == "not_in_catalog"
        assert look["my_stock_signal"] is None
    asyncio.run(main())


# ── (d) source-level fence: no hardcoded stock-level constants remain ───────

def test_no_hardcoded_stock_level_constants_in_display_paths():
    for fn in (server._my_products_dataset, server._insights_sales_compute,
               server.export_csv):
        src = inspect.getsource(fn)
        for lvl in ('"MEDIUM"', "'MEDIUM'", '"HIGH"', "'HIGH'", '"LOW"', "'LOW'"):
            assert lvl not in src, f"hardcoded stock level {lvl} in {fn.__name__}"

    mypage = (FRONTEND / "pages" / "MyProductsPage.jsx").read_text(encoding="utf-8")
    assert "p.my_stock_signal || p.stock_signal" not in mypage, \
        "My Products must not fall back to the market stock_signal"
    assert 'data-testid="stock-not-in-catalog"' in mypage

    si = (FRONTEND / "components" / "SalesInsights.jsx").read_text(encoding="utf-8")
    assert "|| STOCK_TONE.MEDIUM" not in si, \
        "Sales Insights must not dress unknown stock up as MEDIUM"
    assert "p.stock_signal" not in si, \
        "Sales Insights stock column must read my_stock fields only"
    assert 'data-testid="stock-not-in-catalog"' in si
    assert "غير موجود في متجري" in si and "غير موجود في متجري" in mypage


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception:
            bad += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(fns) - bad}/{len(fns)} passed")
    sys.exit(1 if bad else 0)
