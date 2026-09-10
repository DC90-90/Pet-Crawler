"""iter52 — evidence-based pack/unit variant exclusion from the Scanner low.

Production: SKU 5011792007325 "Butcher's Delicious Wet Cat Food Venison in Jelly
400g" showed market_lowest 8.10 against market_avg 108.05 over 3 sellers, our
price 208 -> +2467%. Reconstructing from those aggregates (avg is
competitor-only since iter50, num_sellers counts all stores):

    us 208.00 | competitor 208.00 (a carton) | competitor 8.10 (a single tin)

208/24 = 8.67 per tin, so the 8.10 listing is a single unit of a 24-pack. Both
names say only "400g", so iter51's pack-count guard cannot see it.

The rule implemented here is deliberately NOT "drop the lowest price". A single
consistent low price is a genuine sale and MUST survive — a false low is visible
and correctable, a hidden competitor discount is not. Exclusion requires
EVIDENCE: the same store, in the same crawl run, publishing two prices for one
SKU that differ by >=4x. Anything else is kept and flagged.

The same-run scoping is what separates two concurrent LISTINGS from one price
CHANGING over time — a store discounting 466 -> 118 also spans 4x across a
14-day window, and must not be touched.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_pack_variants"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_pack_variants"
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
USER = {"id": "t", "email": "t@t", "role": "super_admin"}
OWN = "own-store-id"

BUTCHERS = "5011792007325"
RC = "3182550402217"


class _Agg:
    """FerretDB has no `$first` accumulator; the endpoint's $group pipeline is
    unchanged by iter52 and is reproduced here (latest snapshot per sku+store).
    Critically it collapses a store's MULTIPLE listings under one SKU into one
    row — which is exactly why the variant evidence has to be recovered from the
    raw snapshots."""

    def __init__(self, coll, pipeline):
        self._coll, self._p = coll, pipeline

    async def to_list(self, n):
        m = self._p[0]["$match"]
        skus, since, floor = set(m["sku"]["$in"]), m["crawled_at"]["$gte"], m["confidence_score"]["$gte"]
        latest = {}
        async for s in self._coll.find({}, {"_id": 0}):
            if s.get("sku") not in skus or (s.get("confidence_score") or 0) < floor:
                continue
            ca = s.get("crawled_at")
            if ca is None:
                continue
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=server.timezone.utc)
            if ca < since:
                continue
            k = (s["sku"], s["store_id"])
            if k not in latest or ca > latest[k]["crawled_at"]:
                latest[k] = {**s, "crawled_at": ca}
        return list(latest.values())


class _AggColl:
    def __init__(self, c):
        self._c = c

    def __getattr__(self, n):
        return getattr(self._c, n)

    def aggregate(self, pipeline, **kw):
        return _Agg(self._c, pipeline)


class _AggDB:
    def __init__(self, real):
        self._real = real

    def __getitem__(self, n):
        c = self._real[n]
        return _AggColl(c) if n == "product_snapshots" else c

    def __getattr__(self, n):
        v = getattr(self._real, n)
        return _AggColl(v) if n == "product_snapshots" else v


async def _scan():
    fn = getattr(server.price_opportunities, "__wrapped__", server.price_opportunities)
    real, server.db = server.db, _AggDB(server.db)
    try:
        return await fn(days=14, user=USER)
    finally:
        server.db = real


async def _base(db):
    for c in ("stores", "my_products", "products", "product_snapshots"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com", "is_own_store": True},
        {"id": "zarafa", "name": "Zarafa", "domain": "zarafaksa.com"},
        {"id": "aleef", "name": "Aleef", "domain": "aleef.com"},
        {"id": "petsy", "name": "Petsy", "domain": "petsysa.com"},
    ])
    server.db = db


def _snap(sku, store, price, at, sid=None):
    return {"id": f"{sku}-{store}-{price}-{at.isoformat()}", "sku": sku, "store_id": store,
            "store_name": {"own-store-id": "Pets Houses", "zarafa": "Zarafa",
                           "aleef": "Aleef", "petsy": "Petsy"}[store],
            "price": price, "qty_available": 5, "in_stock": True,
            "confidence_score": 99, "crawled_at": at}


def _row(out, sku):
    return next((o for o in out["opportunities"]
                 if o["sku"] == sku and o["store_id"] == OWN), None)


# ── the live case ────────────────────────────────────────────────────────────
def test_butchers_variant_is_excluded_from_the_market_low():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _base(db)
        now = server.datetime.now(server.timezone.utc)
        await db.my_products.insert_one(
            {"sku": BUTCHERS, "name_en": "Butcher's Wet Cat Food Venison in Jelly 400g",
             # iter77 — the Scanner reads our price through the shared VAT
             # resolver now; the tag says "this number is already the shelf
             # price" so it is not grossed by 1.15.
             "name_ar": "", "price": 208.0, "price_basis": "storefront_inc_vat"})
        await db.products.insert_one(
            {"id": "p1", "sku": BUTCHERS, "name_ar": "",
             "name_en": "Butcher's Wet Cat Food Venison in Jelly 400g"})
        await db.product_snapshots.insert_many([
            _snap(BUTCHERS, OWN, 208.0, now),
            _snap(BUTCHERS, "aleef", 208.0, now),
            # Zarafa lists BOTH the tin and the carton under one SKU, same run
            _snap(BUTCHERS, "zarafa", 8.10, now),
            _snap(BUTCHERS, "zarafa", 208.0, now),
        ])
        out = await _scan()

        v = out["summary"]["suspected_pack_mismatch_sample"]
        assert out["summary"]["suspected_pack_mismatch"] == 1, out["summary"]
        assert v[0]["sku"] == BUTCHERS and v[0]["excluded_price"] == 8.10
        assert v[0]["store_name"] == "Zarafa" and v[0]["store_price_used"] == 208.0
        assert v[0]["reason"] == "suspected_pack_mismatch"

        # the 8.10 no longer sets the market low; Zarafa still competes at 208
        row = _row(out, BUTCHERS)
        assert row is None, f"we are level with the market, not overpriced: {row}"
        # nothing above +300% survives for this SKU
        assert not [o for o in out["opportunities"]
                    if o["sku"] == BUTCHERS and o["gap_pct"] > 300]
    asyncio.run(main())


def test_variant_detector_returns_the_evidence():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _base(db)
        now = server.datetime.now(server.timezone.utc)
        await db.product_snapshots.insert_many([
            _snap(BUTCHERS, "zarafa", 8.10, now),
            _snap(BUTCHERS, "zarafa", 104.0, now),
            _snap(BUTCHERS, "zarafa", 208.0, now),
            _snap(BUTCHERS, "aleef", 208.0, now),
        ])
        since = now - server.timedelta(days=14)
        got = await server._detect_pack_variants(db, {BUTCHERS}, since)
        # only the sub-25% listing is a variant; the 12-pack at 104 is kept
        assert got[(BUTCHERS, "zarafa")] == {"excluded": [8.10], "effective": 104.0}
        # a store with one listing is never flagged
        assert (BUTCHERS, "aleef") not in got
    asyncio.run(main())


# ── the thing that must NOT happen ───────────────────────────────────────────
def test_genuine_single_store_discount_is_never_excluded():
    """Royal Canin 118 on sale from 466 — one consistent price per crawl. It is
    a real competitor discount and must stay in the market low."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _base(db)
        now = server.datetime.now(server.timezone.utc)
        old = now - server.timedelta(days=3)
        await db.my_products.insert_one(
            {"sku": RC, "name_en": "Royal Canin Medium Adult 15kg", "name_ar": "",
             "price": 466.0, "price_basis": "storefront_inc_vat"})
        await db.products.insert_one(
            {"id": "p2", "sku": RC, "name_ar": "", "name_en": "Royal Canin Medium Adult 15kg"})
        await db.product_snapshots.insert_many([
            _snap(RC, OWN, 466.0, now),
            # Aleef: 466 three days ago, 118 now — a 74% cut ACROSS RUNS, which
            # spans >4x and must not be read as a variant collision
            _snap(RC, "aleef", 466.0, old),
            _snap(RC, "aleef", 118.0, now),
            _snap(RC, "petsy", 431.0, now),
        ])
        out = await _scan()

        assert out["summary"]["suspected_pack_mismatch"] == 0, \
            out["summary"]["suspected_pack_mismatch_sample"]
        row = _row(out, RC)
        assert row is not None, "we ARE overpriced against a real 118 discount"
        assert row["market_lowest"] == 118.0, row
        assert row["gap_pct"] == round((466.0 - 118.0) / 118.0 * 100, 1)

        # the detector itself sees no evidence, even though the window spans 4x
        since = now - server.timedelta(days=14)
        assert await server._detect_pack_variants(db, {RC}, since) == {}
    asyncio.run(main())


def test_wild_outlier_without_variant_evidence_is_kept_and_flagged():
    """iter52 policy: when in doubt, KEEP — a lone deep discount with no
    same-store spread stays in the comparison and is surfaced.

    iter53 NARROWED this: past a 6x gap on a shared EAN, an uncorroborated low is
    dropped as a barcode collision.

    iter78 narrows it AGAIN, on the client's report that a rival's single sachet
    at 4.30 was faking a +445% gap against their 23.45 multipack. A price that
    sits far below the cluster the OTHER sellers and our own price form is now
    excluded from the market low — 3x when three or more prices corroborate,
    5x when only two do. 91 against 431/440/466 is 4.8x on three references, so
    the "keep and flag" band no longer covers it. What still keeps it: evidence
    that the store CUT its price (see the discount escape below).
    """
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _base(db)
        now = server.datetime.now(server.timezone.utc)
        await db.my_products.insert_one(
            {"sku": RC, "name_en": "Royal Canin Medium Adult 15kg", "name_ar": "",
             "price": 466.0, "price_basis": "storefront_inc_vat"})
        await db.products.insert_one(
            {"id": "p3", "sku": RC, "name_ar": "", "name_en": "Royal Canin Medium Adult 15kg"})
        await db.product_snapshots.insert_many([
            _snap(RC, OWN, 466.0, now),
            # 5.1x below us and 4.8x below the cluster — under iter53's 6x cut,
            # so iter53 keeps it and iter78 is what decides
            _snap(RC, "aleef", 91.0, now),
            _snap(RC, "petsy", 431.0, now),
            _snap(RC, "zarafa", 440.0, now),
        ])
        out = await _scan()

        assert out["summary"]["suspected_pack_mismatch"] == 0
        assert out["summary"]["barcode_unreliable"] == 0, out["summary"]
        assert out["summary"]["low_outliers_excluded"] == 1, out["summary"]
        k = out["summary"]["low_outliers_excluded_sample"][0]
        assert k["sku"] == RC and k["price"] == 91.0
        assert k["references"] == 3 and k["needed"] == 3.0 and k["ratio"] == 4.84
        # excluded means excluded: with 91 gone the low is 431, which puts us
        # 8.1% above the market — under the 10% floor, so no row at all
        assert _row(out, RC) is None
        # prove the low really moved to 431 by pricing ourselves above the floor
        await db.my_products.update_one({"sku": RC}, {"$set": {"price": 600.0}})
        assert _row(await _scan(), RC)["market_lowest"] == 431.0
        await db.my_products.update_one({"sku": RC}, {"$set": {"price": 466.0}})

        # ...and past 6x iter53's shared-barcode rule takes over first
        await db.product_snapshots.update_one({"sku": RC, "store_id": "aleef"},
                                              {"$set": {"price": 20.0}})
        out2 = await _scan()
        assert out2["summary"]["barcode_unreliable"] == 1, out2["summary"]
        assert out2["summary"]["barcode_unreliable_sample"][0]["excluded_price"] == 20.0
        # with the collision gone the low is 431, putting us 8.1% above it —
        # under the 10% reporting floor, so no opportunity row at all
        assert _row(out2, RC) is None
    asyncio.run(main())


def test_a_store_that_cut_its_own_price_keeps_its_deep_discount():
    """The discount escape. Same 91 as above, but this store was selling at 440
    earlier in the window — that is a clearance, which is exactly the competitor
    move worth seeing, not a pack collision."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _base(db)
        now = server.datetime.now(server.timezone.utc)
        old = now - server.timedelta(days=2)
        await db.my_products.insert_one(
            {"sku": RC, "name_en": "Royal Canin Medium Adult 15kg", "name_ar": "",
             "price": 466.0, "price_basis": "storefront_inc_vat"})
        await db.products.insert_one(
            {"id": "p3b", "sku": RC, "name_ar": "", "name_en": "Royal Canin Medium Adult 15kg"})
        await db.product_snapshots.insert_many([
            _snap(RC, OWN, 466.0, now),
            _snap(RC, "aleef", 440.0, old),          # the price it cut FROM
            _snap(RC, "aleef", 91.0, now),
            _snap(RC, "petsy", 431.0, now),
            _snap(RC, "zarafa", 440.0, now),
        ])
        out = await _scan()

        assert out["summary"]["low_outliers_excluded"] == 0, out["summary"]
        assert _row(out, RC)["market_lowest"] == 91.0
    asyncio.run(main())


def test_moderate_spreads_are_untouched():
    """A normal market spread must not trip either rule."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _base(db)
        now = server.datetime.now(server.timezone.utc)
        await db.my_products.insert_one(
            {"sku": RC, "name_en": "Royal Canin Medium Adult 15kg", "name_ar": "",
             "price": 466.0, "price_basis": "storefront_inc_vat"})
        await db.products.insert_one(
            {"id": "p4", "sku": RC, "name_ar": "", "name_en": "Royal Canin Medium Adult 15kg"})
        await db.product_snapshots.insert_many([
            _snap(RC, OWN, 466.0, now),
            _snap(RC, "aleef", 380.0, now),
            _snap(RC, "petsy", 431.0, now),
            # same store, two close prices in one run (size variants of similar
            # value) — a 1.13x spread is not a pack split
            _snap(RC, "zarafa", 440.0, now),
            _snap(RC, "zarafa", 390.0, now),
        ])
        out = await _scan()
        assert out["summary"]["suspected_pack_mismatch"] == 0
        assert out["summary"]["low_outliers_kept"] == 0
        assert _row(out, RC)["market_lowest"] == 380.0
    asyncio.run(main())


def test_store_with_variants_still_competes_at_its_real_price():
    """Excluding the tin must not remove the store from the market — its carton
    price is a genuine competitor price and may even be the low."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _base(db)
        now = server.datetime.now(server.timezone.utc)
        await db.my_products.insert_one(
            {"sku": BUTCHERS, "name_en": "Butcher's 400g", "name_ar": "",
             "price": 208.0, "price_basis": "storefront_inc_vat"})
        await db.products.insert_one(
            {"id": "p5", "sku": BUTCHERS, "name_ar": "", "name_en": "Butcher's 400g"})
        await db.product_snapshots.insert_many([
            _snap(BUTCHERS, OWN, 208.0, now),
            _snap(BUTCHERS, "zarafa", 8.10, now),     # tin  -> excluded
            _snap(BUTCHERS, "zarafa", 180.0, now),    # carton, and the real low
            _snap(BUTCHERS, "aleef", 205.0, now),
        ])
        out = await _scan()
        row = _row(out, BUTCHERS)
        assert out["summary"]["suspected_pack_mismatch"] == 1
        assert row["market_lowest"] == 180.0, row      # Zarafa still wins on price
        assert row["gap_pct"] == round((208.0 - 180.0) / 180.0 * 100, 1)
    asyncio.run(main())


if __name__ == "__main__":
    test_butchers_variant_is_excluded_from_the_market_low()
    test_variant_detector_returns_the_evidence()
    test_genuine_single_store_discount_is_never_excluded()
    test_wild_outlier_without_variant_evidence_is_kept_and_flagged()
    test_moderate_spreads_are_untouched()
    test_store_with_variants_still_competes_at_its_real_price()
    print("PASS: iter52 pack-variant guard")
