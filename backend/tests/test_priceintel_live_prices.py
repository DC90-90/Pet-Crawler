"""iter71 — Price Intel serves LIVE prices, never match-time frozen ones.

Client report: "prices in Price Intelligence still show prices without VAT —
same issue as before in other tabs." Root cause (both audit passes): the
dashboard and the detail sheet read product_matches.competitor_price — a price
FROZEN when the matcher ran. The VAT-basis fix landed AFTER many matches were
written, so Price Intel kept serving pre-VAT-era prices while My Products read
live snapshots. Same metric, different eras.

The fix: product_matches stays the match IDENTITY record; every price, diff
and gap classification now resolves at read time from the latest in-window
accepted snapshot — the exact My-Products rules — and a matched pair with no
valid in-window snapshot is SHOWN as stale/unavailable, never silently served
frozen.

Fixture shape mirrors the production era-split: match docs frozen at the
pre-VAT price (ex-VAT, e.g. 100.00), snapshots re-crawled after the VAT fix at
the inc-VAT shelf price (115.00).
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
os.environ["DB_NAME"] = "test_pi_live"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_pi_live"
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
USER = {"id": "t", "email": "t@t", "role": "super_admin"}
OWN = "own-store-id"
NOW = datetime.now(timezone.utc)


def _match(my_sku, comp_sku, store_id, store_name, frozen_price, conf=99,
           in_stock=True):
    return {"my_sku": my_sku, "competitor_sku": comp_sku,
            "competitor_store_id": store_id, "competitor_store_name": store_name,
            "competitor_price": frozen_price,          # the pre-VAT-era freeze
            "competitor_in_stock": in_stock,
            "my_price": 999.0,                         # frozen own price — must never surface
            "diff_sar": -1.0, "diff_pct": -1.0, "position": "cheaper",
            "confidence": conf, "match_method": "barcode", "flags": [],
            "crawled_at": NOW - timedelta(days=60)}


def _snap(sku, store_id, price, age_days=1, conf=95, in_stock=True):
    return {"id": f"s-{store_id}-{sku}-{age_days}", "sku": sku, "store_id": store_id,
            "store_name": store_id, "price": price, "in_stock": in_stock,
            "qty_available": 5, "confidence_score": conf, "source_tier": 1,
            "crawled_at": NOW - timedelta(days=age_days)}


async def _seed(db):
    for c in ("stores", "my_products", "products", "product_snapshots",
              "product_matches", "dashboard_cache"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com",
         "platform": "zid", "is_own_store": True},
        {"id": "zarafa", "name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla"},
        {"id": "aleef", "name": "Aleef", "domain": "aleef.com", "platform": "zid"},
    ])
    # my_products carries the resolve_own_price output (inc-VAT, iter54)
    await db.my_products.insert_many([
        # iter76 — price_basis is REQUIRED on a fixture that already carries an
        # inc-VAT price: iter73p treats a basis-less row as legacy ex-VAT and
        # grosses it by 1.15 (170 -> 195.5), which has nothing to do with what
        # this suite tests (live vs match-time-frozen prices).
        {"sku": "HILLS", "price": 170.0, "sale_price": None, "quantity": 5,
         "name_ar": "هيلز", "name_en": "Hills GI Biome", "barcode": "052742059518",
         "is_own_store": True, "store_id": OWN, "price_basis": "storefront_inc_vat",
         "last_synced_at": (NOW - timedelta(hours=2)).isoformat()},
        {"sku": "RC", "price": 129.0, "sale_price": None, "quantity": 3,
         "name_ar": "رويال", "name_en": "RC Sensible", "barcode": "3182550702263",
         "is_own_store": True, "store_id": OWN, "price_basis": "storefront_inc_vat",
         "last_synced_at": (NOW - timedelta(hours=2)).isoformat()},
    ])
    await db.products.insert_many([
        {"sku": "Z-HILLS", "name_ar": "هيلز", "name_en": "Hills", "barcode": "052742059518"},
        {"sku": "A-RC", "name_ar": "رويال", "name_en": "RC", "barcode": "3182550702263"},
    ])
    server.db = db
    return db


def _run(coro):
    return asyncio.run(coro)


# ── (a) frozen pre-VAT match price resolves to the fresh snapshot price ─────

def test_dashboard_serves_the_live_snapshot_price_not_the_frozen_one():
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[_TEST_DB])
        # match frozen at the pre-VAT 100.00; the store was re-crawled post-fix
        # at the inc-VAT 115.00 (and an older in-window 110.00 must lose to it)
        await db.product_matches.insert_one(_match("HILLS", "Z-HILLS", "zarafa", "Zarafa", 100.0))
        await db.product_snapshots.insert_many([
            _snap("Z-HILLS", "zarafa", 110.0, age_days=5),
            _snap("Z-HILLS", "zarafa", 115.0, age_days=1),      # latest in window
            _snap("Z-HILLS", "zarafa", 999.0, age_days=1, conf=60),  # below floor — ignored
        ])
        out = await server._price_intel_dashboard_compute(db)
        row = next(r for r in out["full_table"] if r["my_sku"] == "HILLS")
        assert row["cheapest_price"] == 115.0                   # live, inc-VAT
        assert row["cheapest_price"] != 100.0                   # the freeze is dead
        assert row["price_status"] == "live"
        assert row["diff_pct"] == round((170.0 - 115.0) / 115.0 * 100, 1)
        # classification recomputed from the RESOLVED price: 47.8% -> red
        red = [a for a in out["action_required"] if a["my_sku"] == "HILLS"]
        assert red and red[0]["severity"] == "red"
        assert out["summary"]["overpriced_red"] >= 1
    asyncio.run(main())


# ── (b) own price comes from my_products (resolve_own_price basis) ──────────

def test_own_price_is_live_never_the_frozen_match_value():
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[_TEST_DB])
        await db.product_matches.insert_one(_match("HILLS", "Z-HILLS", "zarafa", "Zarafa", 100.0))
        await db.product_snapshots.insert_one(_snap("Z-HILLS", "zarafa", 115.0))
        out = await server._price_intel_dashboard_compute(db)
        row = next(r for r in out["full_table"] if r["my_sku"] == "HILLS")
        assert row["my_price"] == 170.0                         # my_products (inc-VAT)
        assert row["my_price"] != 999.0                         # frozen my_price never surfaces

        # and the detail sheet agrees
        detail = await server.price_intel_product_detail("HILLS", user=USER)
        assert detail["market_summary"]["my_price"] == 170.0
        card = detail["competitors"][0]
        assert card["my_price"] == 170.0
        assert card["competitor_price"] == 115.0
        assert card["price_status"] == "live"
        assert card["diff_pct"] == round((115.0 - 170.0) / 170.0 * 100, 1)
    asyncio.run(main())


# ── (c) no in-window snapshot -> stale/unavailable, out of the buckets ──────

def test_match_without_in_window_snapshot_is_stale_and_uncounted():
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[_TEST_DB])
        await db.product_matches.insert_one(_match("HILLS", "Z-HILLS", "zarafa", "Zarafa", 100.0))
        # only snapshot is OUTSIDE the freshness window
        await db.product_snapshots.insert_one(
            _snap("Z-HILLS", "zarafa", 115.0, age_days=server.PRICE_INTEL_WINDOW_DAYS + 10))
        out = await server._price_intel_dashboard_compute(db)
        row = next(r for r in out["full_table"] if r["my_sku"] == "HILLS")
        # SHOWN — the match identity is real — but priced as unavailable
        assert row["price_status"] == "stale"
        assert row["cheapest_price"] is None and row["diff_pct"] is None
        assert row["sellers"] == 1
        # and excluded from every summary bucket
        assert not any(a["my_sku"] == "HILLS" for a in out["action_required"])
        assert not any(a["my_sku"] == "HILLS" for a in out["my_advantages"])
        assert out["summary"]["overpriced_red"] == 0
        assert out["summary"]["overpriced_yellow"] == 0
        assert out["summary"]["rows_without_live_price"] == 1

        # detail sheet: card shown, marked stale, out of the market summary
        detail = await server.price_intel_product_detail("HILLS", user=USER)
        card = detail["competitors"][0]
        assert card["price_status"] == "stale" and card["competitor_price"] is None
        assert detail["market_summary"]["sellers_count"] == 0
        assert detail["market_summary"]["matched_count"] == 1
        assert detail["market_summary"]["lowest_price"] == 0
    asyncio.run(main())


# ── (d) dashboard and My Products resolve to the SAME price ─────────────────

def test_dashboard_gap_agrees_with_my_products_for_the_same_pair():
    """The two pages use different sign conventions (diff_pct: positive =
    I'm overpriced; vs_my_price_pct: positive = I'm winning) but must resolve
    the SAME snapshot price — so each must be exactly derivable from the other
    through the shared cheapest price."""
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[_TEST_DB])
        await db.product_matches.insert_one(_match("HILLS", "Z-HILLS", "zarafa", "Zarafa", 100.0))
        await db.product_snapshots.insert_many([
            _snap("Z-HILLS", "zarafa", 115.0, age_days=1),
            _snap("Z-HILLS", "zarafa", 120.0, age_days=9),
        ])
        out = await server._price_intel_dashboard_compute(db)
        row = next(r for r in out["full_table"] if r["my_sku"] == "HILLS")

        ds = await server._my_products_dataset(
            db, server.PRICE_INTEL_WINDOW_DAYS, None, None, None, None, None, None, True)
        mp_row = next(p for p in ds["rows"] if p["sku"] == "HILLS")

        # the shared fact: both resolved the identical live price
        assert row["cheapest_price"] == mp_row["competitor_min_price"] == 115.0
        # and each page's percentage is derivable from it
        my = row["my_price"]
        assert row["diff_pct"] == round((my - 115.0) / 115.0 * 100, 1)
        assert mp_row["vs_my_price_pct"] == round((115.0 - my) / my * 100, 1)
    asyncio.run(main())


# ── the recompute path picks the new logic up (cache, task item 6) ──────────

def test_dashboard_cache_spec_recomputes_through_the_new_compute():
    assert any(base == "price-intel/dashboard" for base, _f in server._SINGLE_CACHE_SPECS)
    import inspect
    src = inspect.getsource(server._price_intel_dashboard_compute)
    assert "_resolve_match_prices" in src
    assert 'm["competitor_price"]' not in src and 'x["competitor_price"]' not in src, \
        "no frozen competitor_price read may remain in the dashboard compute"


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
