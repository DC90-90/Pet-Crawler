"""Product-level market view (16 Oct 2026): market size and my share per
product only when every seller is measured, my price against the lowest and the
median, ledger sales read for one product's offers, and a cohort memo key that
repeats on a plain Motor database."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import catalog_views  # noqa: E402
import ledger_sales  # noqa: E402
import price_cohort  # noqa: E402


def test_market_share_needs_every_seller_measured():
    full = catalog_views.market_share({"units": 2, "revenue": 200}, [{"units": 6, "revenue": 540}, {"units": 0, "revenue": 0}])
    assert full["market_revenue_est"] == 740 and full["market_units_est"] == 8
    assert full["market_share_pct"] == 27.0 and full["market_unit_share_pct"] == 25.0
    assert full["has_market_share"] and full["market_share_unavailable_reason"] is None

    # A competitor we cannot see: market size covers the measured sellers, no share.
    partial = catalog_views.market_share({"units": 2, "revenue": 200}, [{"units": 6, "revenue": 540}, None])
    assert partial["market_revenue_est"] == 740 and partial["market_size_complete"] is False
    assert partial["market_share_pct"] is None
    assert partial["market_share_unavailable_reason"] == "competitor_sales_unmeasured"

    assert catalog_views.market_share(None, [{"units": 1, "revenue": 9}])["market_share_unavailable_reason"] == "own_sales_unmeasured"
    nobody = catalog_views.market_share({"units": 0, "revenue": 0}, [{"units": 0, "revenue": 0}])
    assert nobody["market_share_pct"] is None and nobody["market_share_unavailable_reason"] == "no_sales_in_window"
    # The only seller who sold owns the market.
    assert catalog_views.market_share({"units": 3, "revenue": 90}, [])["market_share_pct"] == 100.0


def test_price_position_against_lowest_and_median():
    pos = catalog_views.price_position(110, [100, 120, 130])
    assert pos["rank"] == 2 and pos["of"] == 4
    assert pos["vs_lowest_pct"] == 10.0 and pos["vs_median_pct"] == -8.3 and pos["market_median"] == 120
    tied = catalog_views.price_position(100, [100, 120])
    assert tied["rank"] == 1 and tied["vs_lowest_pct"] == 0.0 and tied["vs_median_pct"] == -9.1
    assert catalog_views.price_position(None, [100]) is None and catalog_views.price_position(100, []) is None
    assert catalog_views.discount_pct(80, 100) == 20.0 and catalog_views.discount_pct(100, 100) is None


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    url = os.environ.get("DALEEL_TEST_MONGO_URL") or os.environ.get("MONGO_URL") or "mongodb://127.0.0.1:27017"
    return AsyncIOMotorClient(url, serverSelectionTimeoutMS=3000)[f"test_market_view_{uuid.uuid4().hex[:10]}"]


def test_offer_sales_reads_one_products_offers_with_measured_zeros():
    db = _db()

    async def run():
        try:
            await db.ledger_sales_meta.insert_one({"_id": "current", "build": "b1", "groups": []})
            await db.ledger_sales_daily.insert_many([
                {"build": "b1", "store_id": "a", "offer_id": "oa", "sku": "x", "date": "2026-10-10", "units": 2, "revenue": 20.0, "source": "stock_depletion"},
                {"build": "b1", "store_id": "a", "offer_id": "oa", "sku": "x", "date": "2026-10-11", "units": 1, "revenue": 10.0, "source": "stock_depletion"},
                {"build": "b1", "store_id": "a", "offer_id": "oa", "sku": "x", "date": "2026-09-01", "units": 9, "revenue": 90.0, "source": "stock_depletion"},
                {"build": "old", "store_id": "a", "offer_id": "oa", "sku": "x", "date": "2026-10-10", "units": 50, "revenue": 500.0, "source": "stock_depletion"},
                {"build": "b1", "store_id": "own", "offer_id": None, "sku": "MY-1", "date": "2026-10-10", "units": 4, "revenue": 40.0, "source": "stock_depletion"},
                {"build": "b1", "store_id": "c", "offer_id": "oc", "sku": "x", "date": "2026-10-10", "units": 7, "revenue": 70.0, "source": "sold_counter_diff"}])
            await db.ledger_sales_observed.insert_one(
                {"build": "b1", "store_id": "b", "offer_id": "ob", "sku": "x", "dates": ["2026-10-09", "2026-10-10"],
                 "first": "2026-10-09", "last": "2026-10-10", "source": "stock_depletion"})
            start = datetime(2026, 10, 1, tzinfo=timezone.utc)
            end = datetime(2026, 10, 15, tzinfo=timezone.utc)
            out = await ledger_sales.offer_sales(db, [("a", "oa"), ("b", "ob"), ("own", "MY-1"), ("z", "oz")], start, end)
            assert out[("a", "oa")]["units"] == 3 and out[("a", "oa")]["revenue"] == 30.0
            assert out[("a", "oa")]["by_day"] == {"2026-10-10": 2, "2026-10-11": 1}
            assert out[("b", "ob")]["units"] == 0 and out[("b", "ob")]["days_measured"] == 2   # measured, sold nothing
            assert out[("own", "MY-1")]["units"] == 4                                           # keyed by SKU without an offer id
            assert ("z", "oz") not in out and ("c", "oc") not in out                            # unmeasured / not asked for
        finally:
            await db.client.drop_database(db.name)
    asyncio.run(run())


def test_cohort_memo_key_repeats_on_a_motor_database(monkeypatch):
    price_cohort.reset_cohort_memo()
    db = _db()
    calls = []

    async def fake_build(*args):
        calls.append(1)
        return {"A": {"sellers": []}}
    monkeypatch.setattr(price_cohort, "_build_cohorts", fake_build)

    async def run():
        rows = [{"sku": "A"}]
        await price_cohort.build_cohorts(db, rows, "own", lambda r: 10.0)
        await price_cohort.build_cohorts(db, rows, "own", lambda r: 10.0)
    asyncio.run(run())
    # `db.raw` on Motor is a collection named "raw"; keying on it never repeated.
    assert len(calls) == 1


def test_zid_and_salla_images_are_read():
    import observation_contract as oc
    zid = {"images": [{"id": "x", "image": {"full_size": "https://m/f.webp", "medium": "https://m/m.webp"}}]}
    assert oc.image_url(zid) == "https://m/m.webp"
    assert oc.image_url({"images": [{"url": "https://s/a.jpg"}]}) == "https://s/a.jpg"
    assert oc.image_url({"img_url": "https://own/a.jpg"}) == "https://own/a.jpg"
    assert oc.image_url({"images": [{"image": {}}], "img_url": {"bad": 1}}) == ""


def test_category_facets_from_store_category_and_name():
    import category_map as cm
    assert cm.facets("Cat Sand", "رمل قطط بيسو") == {"facet_animal": "cat", "facet_type": "litter"}
    assert cm.facets(None, "رون رون طعام رطب للقطط تونة وسمك أبيض") == {"facet_animal": "cat", "facet_type": "wet_food"}
    assert cm.facets("Canary", "طعام كناري")["facet_animal"] == "bird"
    assert cm.facets(None, "لعبة للكلاب والقطط")["facet_animal"] is None        # both animals: no single tab
    assert cm.facets(None, "Applaws chicken can")["facet_type"] == "wet_food"
    assert cm.facets(None, "canary seed")["facet_type"] is None                    # "can" is not a prefix match
    rows = [{"facet_animal": "cat", "facet_type": "litter"}, {"facet_animal": None, "facet_type": "toys"}]
    assert cm.facet_counts(rows) == {"animal": {"cat": 1, "other": 1}, "type": {"litter": 1, "toys": 1}}
    assert cm.facet_filter(rows, animal="other") == rows[1:]


def test_competitor_rows_once_per_store_and_honest_unmeasured_reasons():
    """Client report (20 Oct 2026): a product all 4 competitors had run out of
    showed "7 stores not compared" (each store's old offer listed again) and
    blamed the own store for "publishing neither stock nor sales counts"."""
    cohort = {"sellers": [], "excluded": [
        {"store_id": "z", "store_name": "Zarafa", "price": 19.12, "excluded_reason": "out_of_stock", "crawled_at": "2026-10-20T01:30"},
        {"store_id": "z", "store_name": "Zarafa", "price": 19.12, "excluded_reason": "legacy_or_unverified_offer", "crawled_at": "2026-10-09T02:45"},
        {"store_id": "h", "store_name": "Hamtaro", "price": 19.55, "excluded_reason": "out_of_stock", "crawled_at": "2026-10-20T03:46"},
        {"store_id": "h", "store_name": "Hamtaro", "price": 19.55, "excluded_reason": "legacy_or_unverified_offer", "crawled_at": "2026-10-08T01:58"}]}
    rows = catalog_views.current_excluded(cohort)
    assert [r["store_name"] for r in rows] == ["Zarafa", "Hamtaro"] and all(r["excluded_reason"] == "out_of_stock" for r in rows)
    oos = catalog_views.out_of_stock_competitors(cohort)
    assert [(r["store_name"], r["last_price"]) for r in oos] == [("Zarafa", 19.12), ("Hamtaro", 19.55)]
    assert catalog_views._oos_fields(cohort) == {"oos_competitors": 2, "oos_competitor_min_price": 19.12, "oos_competitor_max_price": 19.55}
    # A store with a live offer lists no excluded row.
    assert catalog_views.current_excluded({**cohort, "sellers": [{"store_id": "z", "price": 18.0}]})[0]["store_name"] == "Hamtaro"
    assert catalog_views.unmeasured_reason({"in_stock": False, "is_own_store": True}, "zid") == "out_of_stock"
    assert catalog_views.unmeasured_reason({"in_stock": True, "qty_available": 5}, "zid") == "no_stock_movement"
    assert catalog_views.unmeasured_reason({"in_stock": True}, "salla") == "not_published"


def test_same_pack_written_as_count_times_unit_weight_matches():
    """GimCat 20 g vs Hamtaro/Petsy "4×5 g", Wanpy 70 g vs "5×14 غ" — same
    barcode, same total, refused by the pack guard (client, 20 Oct 2026)."""
    from matcher import _pack_compatible as ok
    assert ok("جيم كات مكافآت أعواد للقطط بالدجاج 20 جم", "جيم كات مكافئات 4×5جرام بالدجاج")
    assert ok("وانبي مكافاة كريمية للقطط بالدجاج 70جم", "مكافآت دجاج للقطط 5×14 غ وانبي")
    assert ok("Wanpy Creamy Lickable Treats Chicken - 70G", "Wanpy Creamy Cat Treats - 5 Pieces*14g")
    assert ok("Beso cat litter 20 kg", "Beso cat litter 2 x 10 kg")
    # Different totals stay apart: a single against its multipack.
    assert not ok("جيم كات أعواد 5 جم", "جيم كات مكافئات 4×5جرام")
    assert not ok("Royal Canin pouch 85g", "Royal Canin pouch 12 x 85g")
    assert not ok("Beso cat litter 10 kg", "Beso cat litter 2 x 10 kg")


def test_both_multipacks_with_equal_totals_match():
    from matcher import _pack_compatible as ok
    assert ok("ترولي مكافآت كريمية للقطط سالمون 5×14 غم", "مكافآت سالمون للقطط 5×14 غ ترولي")
    assert not ok("Royal Canin pouch 12 x 85g", "Royal Canin pouch 6 x 85g")
