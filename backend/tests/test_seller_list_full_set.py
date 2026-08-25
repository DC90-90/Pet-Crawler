"""iter60 — "Stores Carrying" must list every store the matcher already linked.

Reported symptom: products a dozen of the 11 tracked stores sell were showing
1-2 sellers. It is not a crawl gap and not a matching gap — the snapshots exist
and product_matches links them. The product-detail endpoint threw them away at
render time:

    db.product_snapshots.find({"sku": sku, "crawled_at": {"$gte": now - 30d}})

Two filters, both invisible to the client:

  exact SKU string   product_matches was never read. A competitor matched on
                     barcode, or on any key other than a byte-identical SKU
                     string, was matched and then dropped. Zarafa is a Salla
                     store and publishes merchant-internal SKUs, so essentially
                     none of its rows survived.
  30-day cliff       a store crawled 31 days ago did not appear as stale, it
                     disappeared — "we have not looked recently" rendered as
                     "nobody else carries this".

The fix widens what is FETCHED, not what is TRUSTED: rows admitted through
product_matches are re-checked against the iter51/52 pack guard, so a single
400g tin still cannot be listed as a seller of a 24-tin carton.
"""
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_seller_set"
import server  # noqa: E402
import seller_set  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
USER = {"id": "t", "email": "t@t", "role": "super_admin"}
OWN = "own-store-id"
ZARAFA = "zarafa-store-id"

# The two production cases. Our side carries the GTIN as the SKU; Zarafa carries
# its own Salla product code, which is why exact-string matching never saw it.
HILLS = "052742059518"
HILLS_ZARAFA_SKU = "SL-88213"
RC = "3182550702263"
RC_ZARAFA_SKU = "SL-40917"

# Five-seller case: four competitors, only one of which shares our SKU string.
FIVE = "FIVE-SELLER-SKU"

# Pack-collision case: a single tin matched to our 24-tin carton by a shared
# barcode. iter51/52 keep it out; this fix must not let it back in.
CARTON = "5011792007325"


def _now():
    return server.datetime.now(server.timezone.utc)


async def _reset(db):
    for c in ("stores", "my_products", "products", "product_snapshots", "product_matches"):
        await db[c].delete_many({})


def _snap(sku, store_id, store_name, price, *, age_days=1, qty=10,
          in_stock=True, conf=95, tier=1, url=None, idx=0):
    return {
        "id": f"snap-{store_id}-{sku}-{idx}",
        "sku": sku, "store_id": store_id, "store_name": store_name,
        "price": price, "qty_available": qty, "in_stock": in_stock,
        "confidence_score": conf, "source_tier": tier,
        "product_url": url or f"https://example.com/p/{sku}",
        "crawled_at": _now() - timedelta(days=age_days),
    }


def _match(my_sku, comp_sku, store_id):
    return {"id": f"m-{my_sku}-{store_id}", "my_sku": my_sku,
            "competitor_sku": comp_sku, "competitor_store_id": store_id,
            "confidence": 95, "match_method": "barcode"}


async def _seed(db):
    await _reset(db)
    await db.stores.insert_many([
        {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com",
         "platform": "zid", "is_own_store": True},
        {"id": ZARAFA, "name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla"},
        {"id": "comp-b", "name": "Petsy", "domain": "petsysa.com", "platform": "zid"},
        {"id": "comp-c", "name": "Aleef", "domain": "aleef.com", "platform": "zid"},
        {"id": "comp-d", "name": "Hobba", "domain": "hobba.sa", "platform": "salla"},
    ])
    await db.products.insert_many([
        {"sku": HILLS, "name_en": "Hills GI Biome Cat 1.5kg", "name_ar": "هيلز جي اي بايوم",
         "barcode": HILLS, "category": "cat_food", "brand": "Hills"},
        {"sku": HILLS_ZARAFA_SKU, "name_en": "Hills Gastrointestinal Biome Cat Food 1.5kg",
         "name_ar": "هيلز", "category": "cat_food", "brand": "Hills"},
        {"sku": RC, "name_en": "Royal Canin Sensible 33 Cat 2kg", "name_ar": "رويال كانين سنسيبل",
         "barcode": RC, "category": "cat_food", "brand": "Royal Canin"},
        {"sku": RC_ZARAFA_SKU, "name_en": "Royal Canin Sensible 33 Adult Cat 2kg",
         "name_ar": "رويال كانين", "category": "cat_food", "brand": "Royal Canin"},
        {"sku": FIVE, "name_en": "Test Product 400g", "name_ar": "منتج", "category": "cat_food"},
        {"sku": "FIVE-B", "name_en": "Test Product 400g", "name_ar": "منتج"},
        {"sku": "FIVE-C", "name_en": "Test Product 400g", "name_ar": "منتج"},
        {"sku": CARTON, "name_en": "Butcher's Venison in Jelly 400g Pack of 24",
         "name_ar": "بوتشرز", "barcode": CARTON, "category": "cat_food"},
        {"sku": "SINGLE-TIN", "name_en": "Butcher's Venison in Jelly 400g single tin",
         "name_ar": "بوتشرز"},
    ])
    # price_basis="storefront_inc_vat" isolates this suite from iter73p's
    # legacy-basis VAT gross-up (a bare row with no basis is treated as ex-VAT
    # and grossed × 1.15). These fixture prices already reflect the shopper-
    # facing figure; the suite's concern is the pack-size / seller-list logic,
    # not VAT resolution.
    await db.my_products.insert_many([
        {"sku": HILLS, "price": 170.0, "name_en": "Hills GI Biome Cat 1.5kg",
         "price_basis": "storefront_inc_vat"},
        {"sku": RC, "price": 129.0, "name_en": "Royal Canin Sensible 33 Cat 2kg",
         "price_basis": "storefront_inc_vat"},
        {"sku": FIVE, "price": 100.0, "name_en": "Test Product 400g",
         "price_basis": "storefront_inc_vat"},
        {"sku": CARTON, "price": 208.0, "name_en": "Butcher's Venison in Jelly 400g Pack of 24",
         "price_basis": "storefront_inc_vat"},
    ])

    snaps = []
    # ── Case 1: Hills. Us + Zarafa under a different SKU string.
    snaps.append(_snap(HILLS, OWN, "Pets Houses", 170.0))
    snaps.append(_snap(HILLS_ZARAFA_SKU, ZARAFA, "Zarafa", 163.0))
    # ── Case 2: Royal Canin. Same shape.
    snaps.append(_snap(RC, OWN, "Pets Houses", 129.0))
    snaps.append(_snap(RC_ZARAFA_SKU, ZARAFA, "Zarafa", 118.0))
    # ── Five sellers: one shares our SKU, three are matched under their own.
    snaps.append(_snap(FIVE, OWN, "Pets Houses", 100.0))
    snaps.append(_snap(FIVE, "comp-b", "Petsy", 95.0))          # exact SKU
    snaps.append(_snap("FIVE-B", ZARAFA, "Zarafa", 92.0))       # matched
    snaps.append(_snap("FIVE-C", "comp-c", "Aleef", 105.0))     # matched
    # OOS + stale: carried, but out of stock and last seen 40 days ago.
    snaps.append(_snap("FIVE-C", "comp-d", "Hobba", 110.0,
                       age_days=40, qty=0, in_stock=False))
    # ── Pack collision: a single tin matched to our 24-carton.
    snaps.append(_snap(CARTON, OWN, "Pets Houses", 208.0))
    snaps.append(_snap("SINGLE-TIN", ZARAFA, "Zarafa", 8.10))
    await db.product_snapshots.insert_many(snaps)

    await db.product_matches.insert_many([
        _match(HILLS, HILLS_ZARAFA_SKU, ZARAFA),
        _match(RC, RC_ZARAFA_SKU, ZARAFA),
        _match(FIVE, FIVE, "comp-b"),
        _match(FIVE, "FIVE-B", ZARAFA),
        _match(FIVE, "FIVE-C", "comp-c"),
        _match(FIVE, "FIVE-C", "comp-d"),
        _match(CARTON, "SINGLE-TIN", ZARAFA),
    ])
    server.db = db
    return db


async def _full(sku, days=30):
    return await server.get_product_full(sku, days=days, user=USER)


async def _before(db, sku, days=30):
    """The pre-iter60 seller list, reproduced verbatim, so before/after is
    measured rather than asserted."""
    since = _now() - timedelta(days=days)
    rows = await db.product_snapshots.find(
        {"sku": sku, "crawled_at": {"$gte": since}}, {"_id": 0}).to_list(5000)
    return {r["store_id"] for r in rows}


def _store_names(product):
    return {sp["store_name"] for sp in product["store_prices"]}


# ── The two production cases ────────────────────────────────────────────────

def test_hills_shows_zarafa_as_a_seller():
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        before = await _before(db, HILLS)
        assert before == {OWN}                             # 1 seller: only us
        out = await _full(HILLS)
        assert "Zarafa" in _store_names(out), out["store_prices"]
        z = next(sp for sp in out["store_prices"] if sp["store_name"] == "Zarafa")
        assert z["price"] == 163.0
        assert z["match_source"] == "matched"
        assert z["sku"] == HILLS_ZARAFA_SKU
        assert out["seller_count"] == 2
    asyncio.run(main())


def test_royal_canin_sensible_shows_zarafa_as_a_seller():
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        assert ZARAFA not in await _before(db, RC)
        out = await _full(RC)
        assert "Zarafa" in _store_names(out)
        z = next(sp for sp in out["store_prices"] if sp["store_name"] == "Zarafa")
        assert z["price"] == 118.0 and z["match_source"] == "matched"
    asyncio.run(main())


# ── The systemic case ───────────────────────────────────────────────────────

def test_product_matched_by_five_stores_shows_all_five():
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        before = await _before(db, FIVE)
        assert len(before) == 2, before                    # us + the one exact-SKU store
        out = await _full(FIVE)
        assert out["seller_count"] == 5, _store_names(out)
        assert _store_names(out) == {"Pets Houses", "Zarafa", "Petsy", "Aleef", "Hobba"}
    asyncio.run(main())


def test_cheapest_of_n_counts_the_same_sellers_the_table_lists():
    """Requirement 4 — the badge and the table must not disagree. The stale
    Hobba row is inside both or outside both, never one of each."""
    async def main():
        await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _full(FIVE)
        mp = out["market_position"]
        assert mp is not None
        assert mp["total_sellers"] == out["seller_count"] == 5
        assert mp["stale_sellers"] == 1                    # Hobba, 40 days old
        assert mp["min_price"] == 92.0                     # Zarafa, matched row
    asyncio.run(main())


# ── Shown-with-label, never dropped ─────────────────────────────────────────

def test_stale_seller_is_labelled_not_dropped():
    async def main():
        await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _full(FIVE)
        hobba = next(sp for sp in out["store_prices"] if sp["store_name"] == "Hobba")
        assert hobba["is_stale"] is True
        assert hobba["data_status"] == "stale"
        assert hobba["days_since_crawl"] >= 39
        assert hobba["price_as_of"]                        # a date the UI can print
        assert hobba["price"] == 110.0                     # the price is still there
    asyncio.run(main())


def test_out_of_stock_seller_is_labelled_not_dropped():
    async def main():
        await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _full(FIVE)
        hobba = next(sp for sp in out["store_prices"] if sp["store_name"] == "Hobba")
        assert hobba["stock_status"] == "OOS"
        assert hobba["is_oos"] is True
        assert out["seller_summary"]["oos"] == 1
        assert out["seller_summary"]["stale"] == 1
        assert out["seller_summary"]["live"] == 4
    asyncio.run(main())


def test_stale_qty_is_excluded_from_total_volume_but_the_seller_remains():
    async def main():
        await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _full(FIVE)
        assert out["total_volume"] == 40                   # 4 live stores x 10
        assert out["seller_count"] == 5
    asyncio.run(main())


def test_history_chart_stays_inside_the_requested_window():
    """The seller table is not bounded by `days`; the chart still is."""
    async def main():
        await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _full(FIVE, days=30)
        assert "Hobba" in _store_names(out)                # in the table
        assert "Hobba" not in out["history"]               # no 40-day-old line
    asyncio.run(main())


# ── Guards from iter51-53 stay in force ─────────────────────────────────────

def test_wrong_pack_size_match_is_still_excluded():
    async def main():
        await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        out = await _full(CARTON)
        assert "Zarafa" not in _store_names(out), out["store_prices"]
        assert out["seller_summary"]["excluded_wrong_match"] == 1
        assert out["price_range"]["min"] == 208.0          # no 8.10 false low
    asyncio.run(main())


def test_exact_sku_rows_are_never_re_filtered():
    """The guard applies only to rows the matcher admitted. A store publishing
    the identical SKU is the endpoint's pre-existing behaviour and must survive
    regardless of what its name says."""
    async def main():
        db = await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        await db.product_snapshots.insert_one(
            _snap(CARTON, "comp-b", "Petsy", 12.0, idx=9))
        out = await _full(CARTON)
        assert "Petsy" in _store_names(out)
    asyncio.run(main())


def test_the_two_seller_list_endpoints_agree():
    """/products/{sku} and /products/{sku}/full must not disagree about who
    carries the product — they are the same table rendered from two payloads."""
    async def main():
        await _seed(AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]])
        for sku in (HILLS, RC, FIVE, CARTON):
            short = await server.get_product(sku, user=USER)
            full = await _full(sku)
            assert _store_names(short) == _store_names(full), sku
            assert short["seller_count"] == full["seller_count"], sku
    asyncio.run(main())


# ── Pure helpers ────────────────────────────────────────────────────────────

def test_alias_clauses_are_scoped_to_the_owning_store():
    """An unscoped {"sku": {"$in": [...]}} would let a generic competitor SKU
    pull unrelated products in from every other store."""
    aliases = {"s1": {"A1"}, "s2": {"A2", "A3"}}
    clauses = seller_set.snapshot_or_clauses("HUB", aliases)
    assert clauses[0] == {"sku": "HUB"}
    assert {"store_id": "s1", "sku": {"$in": ["A1"]}} in clauses
    assert {"store_id": "s2", "sku": {"$in": ["A2", "A3"]}} in clauses
    assert all("store_id" in c for c in clauses[1:])
    # a reverse hop adds hub SKUs to the unscoped branch, and they are then not
    # repeated as per-store aliases
    multi = seller_set.snapshot_or_clauses(["HUB", "HUB2"], {"s1": {"HUB2", "A1"}})
    assert multi[0] == {"sku": {"$in": ["HUB", "HUB2"]}}
    assert multi[1] == {"store_id": "s1", "sku": {"$in": ["A1"]}}


def test_alias_map_merges_both_match_directions():
    rows = [
        {"my_sku": "HUB", "competitor_sku": "X", "competitor_store_id": "s1"},
        {"my_sku": "HUB2", "competitor_sku": "HUB", "competitor_store_id": "s2"},
        {"my_sku": "HUB", "competitor_sku": "Y", "competitor_store_id": "s1"},
    ]
    assert seller_set.alias_map_from_matches(rows, "HUB") == {
        "s1": {"X", "Y"}, "s2": {"HUB"}}
    assert seller_set.hub_skus_from_matches(rows, "HUB") == ["HUB2"]


def test_freshness_labels_never_drop_a_row():
    now = _now()
    fresh = seller_set.freshness_labels(now - timedelta(days=1), now)
    old = seller_set.freshness_labels(now - timedelta(days=40), now)
    unknown = seller_set.freshness_labels(None, now)
    assert fresh["data_status"] == "live" and fresh["is_stale"] is False
    assert old["data_status"] == "stale" and old["days_since_crawl"] == 40
    assert unknown["data_status"] == "unknown" and unknown["price_as_of"] is None


def test_pack_guard_keeps_a_pair_with_no_evidence():
    ok, _ = seller_set.pack_guard_ok("Butcher's 400g", "")
    assert ok is True
    ok, reason = seller_set.pack_guard_ok("Butcher's 400g Pack of 24", "Butcher's 400g tin")
    assert ok is False and reason == "pack_mismatch"
    ok, _ = seller_set.pack_guard_ok("Butcher's 400g Pack of 24", "Butchers carton of 24 400g")
    assert ok is True


def test_market_position_defaults_are_unchanged_for_other_callers():
    """iter60 loosens the filter only where the caller asks. my-products and
    insights must keep the 7-day / confidence>=85 contract."""
    now = _now()
    rows = [
        {"store_id": OWN, "price": 100.0, "confidence_score": 99, "crawled_at": now},
        {"store_id": "c1", "price": 90.0, "confidence_score": 95,
         "crawled_at": now - timedelta(days=40)},
    ]
    assert server.compute_market_position(rows, OWN) is None          # default: filtered
    loose = server.compute_market_position(rows, OWN, max_age_days=None, min_confidence=0)
    assert loose["total_sellers"] == 2 and loose["stale_sellers"] == 1


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
