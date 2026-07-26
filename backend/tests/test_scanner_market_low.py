"""iter50 — Price Scanner market low must come from COMPETITORS only.

Production bug: for most products the Scanner's `market_lowest` was exactly
1/1.15 of the real lowest seller price.

  Hills          min 147.83  x1.15 = 170.00  = the real low
  Intersand      min  97.41  x1.15 = 112.02  = the real low
  Lindo          min  24.35  x1.15 =  28.00  = the real low
  Signor Gatto   min  28.88            28.88 = the real low   (already correct)

Root cause: the Scanner folded OUR OWN store into min()/mean(). Own-store
snapshots are written from the Zid Merchant API's ex-VAT price, while every
competitor snapshot is the inc-VAT storefront shelf price. So whenever our
under-stated price was the lowest raw number it became "the market low", and
every derived figure — gap %, overpriced count, revenue uplift, and the
"lower to X to become cheapest" advice — inherited the 15% error. Signor Gatto
looked right only because a competitor genuinely undercut even our ex-VAT price,
so the min came from a competitor and was already inc-VAT.

`own_id` was resolved at the top of the endpoint and never used.

This fixes the AGGREGATION only. Own-store snapshots are still stored ex-VAT
(Defect 1, crawlers.py:2163) — deliberately out of scope here.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_scanner_low")
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
USER = {"id": "t", "email": "t@t", "role": "super_admin"}
OWN = "own-store-id"

# (sku, our price, cheapest competitor, dearest competitor)
# `ours` and `low` are the REAL production numbers. The dearest competitor is
# fixture padding, priced far enough above the low that every SKU always yields
# at least one opportunity row — otherwise `market_lowest` would be
# unobservable on exactly the SKUs where the fix stops us being flagged.
CASES = [
    ("HILLS-GI-15",   147.83, 170.00, 199.00),
    ("INTERSAND-6",    97.41, 112.02, 139.00),
    ("LINDO-400",      24.35,  28.00,  35.00),
    ("SIGNOR-GATTO",   33.21,  28.88,  36.00),   # control: competitor is cheapest
]


def _comps(case):
    return [case[2], case[3]]


async def _seed(db):
    for c in ("stores", "my_products", "products", "product_snapshots"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com",
         "platform": "zid", "is_own_store": True},
        {"id": "comp-a", "name": "Aleef", "domain": "aleef.com", "platform": "zid"},
        {"id": "comp-b", "name": "Petsy", "domain": "petsysa.com", "platform": "zid"},
    ])
    now = server.datetime.now(server.timezone.utc)
    snaps, mine, prods = [], [], []
    for case in CASES:
        sku, ours, comps = case[0], case[1], _comps(case)
        mine.append({"sku": sku, "price": ours, "sync_source": "zid_api"})
        prods.append({"id": f"p-{sku}", "sku": sku, "name_ar": sku, "name_en": sku,
                      "category": "cat_food"})
        snaps.append({"id": f"s-{sku}-own", "sku": sku, "store_id": OWN,
                      "store_name": "Pets Houses", "price": ours, "qty_available": 5,
                      "in_stock": True, "confidence_score": 99, "crawled_at": now})
        for i, cp in enumerate(comps):
            sid = ("comp-a", "comp-b")[i]
            snaps.append({"id": f"s-{sku}-{sid}", "sku": sku, "store_id": sid,
                          "store_name": {"comp-a": "Aleef", "comp-b": "Petsy"}[sid],
                          "price": cp, "qty_available": 3, "in_stock": True,
                          "confidence_score": 99, "crawled_at": now})
    await db.my_products.insert_many(mine)
    await db.products.insert_many(prods)
    await db.product_snapshots.insert_many(snaps)
    server.db = db


class _Agg:
    """Stands in for the endpoint's $group pipeline.

    The sandbox runs FerretDB, which has not implemented the `$first`
    accumulator the Scanner's pipeline is built on. That pipeline is NOT part of
    this change — only the min/mean computed from its output is — so it is
    reproduced here in Python (latest snapshot per sku+store, same $match
    filters) and the real loop under test consumes the identical rows."""

    def __init__(self, coll, pipeline):
        self._coll, self._p = coll, pipeline

    async def to_list(self, n):
        match = self._p[0]["$match"]
        skus = set(match["sku"]["$in"])
        since = match["crawled_at"]["$gte"]
        floor = match["confidence_score"]["$gte"]
        latest = {}
        async for s in self._coll.find({}, {"_id": 0}):
            if s.get("sku") not in skus or (s.get("confidence_score") or 0) < floor:
                continue
            ca = s.get("crawled_at")
            if ca is None:
                continue
            # the driver hands back naive datetimes; `since` is tz-aware
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=server.timezone.utc)
            if ca < since:
                continue
            key = (s["sku"], s["store_id"])
            if key not in latest or ca > latest[key]["crawled_at"]:
                s = {**s, "crawled_at": ca}
                latest[key] = s
        return list(latest.values())


class _AggColl:
    def __init__(self, coll):
        self._c = coll

    def __getattr__(self, name):
        return getattr(self._c, name)

    def aggregate(self, pipeline, **kw):
        return _Agg(self._c, pipeline)


class _AggDB:
    def __init__(self, real):
        self._real = real

    def __getitem__(self, name):
        c = self._real[name]
        return _AggColl(c) if name == "product_snapshots" else c

    def __getattr__(self, name):
        v = getattr(self._real, name)
        return _AggColl(v) if name == "product_snapshots" else v


async def _scan():
    # the endpoint is wrapped in @ttl_cache(60); call the undecorated function
    fn = getattr(server.price_opportunities, "__wrapped__", server.price_opportunities)
    real, server.db = server.db, _AggDB(server.db)
    try:
        return await fn(days=14, user=USER)
    finally:
        server.db = real


def _ours(out, sku):
    return next((o for o in out["opportunities"]
                 if o["sku"] == sku and o["store_id"] == OWN), None)


def test_market_low_is_the_lowest_competitor_not_our_own_price():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        out = await _scan()
        lows = {}
        for o in out["opportunities"]:
            lows.setdefault(o["sku"], o["market_lowest"])
        for case in CASES:
            sku, ours, low = case[0], case[1], case[2]
            assert lows.get(sku) == low, (sku, lows.get(sku), low)
            # our own (ex-VAT) price is never the reported market low
            assert lows[sku] != ours, sku
            assert lows[sku] == min(_comps(case)), sku
    asyncio.run(main())


def test_the_three_ex_vat_cases_now_report_the_inc_vat_low():
    """Hills / Intersand / Lindo: the old low was exactly our_price, i.e.
    real_low / 1.15. The new low is the real inc-VAT competitor price."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        out = await _scan()
        for case in CASES[:3]:
            sku, ours, real_low = case[0], case[1], case[2]
            row = _ours(out, sku)
            # we are BELOW the competitor low, so we are not overpriced at all
            assert row is None, (sku, row)
            # the arithmetic that identified the bug
            assert abs(ours * 1.15 - real_low) < 0.02, sku
            # and we are credited as undercutting the market
            assert any(u["sku"] == sku and u["store_name"] == "Pets Houses"
                       for u in out["undercut"]), sku
    asyncio.run(main())


def test_signor_gatto_case_is_unchanged():
    """The control: a competitor genuinely holds the low, so the market low was
    already correct and must stay exactly as it was — including our gap."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        out = await _scan()
        row = _ours(out, "SIGNOR-GATTO")
        assert row is not None, "we ARE overpriced against a real competitor low"
        assert row["market_lowest"] == 28.88
        assert row["my_price"] == 33.21
        # 33.21 vs 28.88 -> +15.0%
        assert row["gap_pct"] == round((33.21 - 28.88) / 28.88 * 100, 1) == 15.0
        # market_avg is competitor-only too: mean of the two competitors,
        # with our 33.21 excluded
        assert row["market_avg"] == round((28.88 + 36.00) / 2, 2)
    asyncio.run(main())


def test_overpriced_count_drops_to_exclude_self_comparisons():
    """The headline number: products that were only ever "overpriced" against
    our own ex-VAT price must fall out of the count."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        out = await _scan()

        # OUR rows: only Signor Gatto, where a real competitor is cheaper
        own_rows = [o for o in out["opportunities"] if o["store_id"] == OWN]
        assert [o["sku"] for o in own_rows] == ["SIGNOR-GATTO"], own_rows

        # every reported low is a competitor price, on every row
        for o in out["opportunities"]:
            case = next(c for c in CASES if c[0] == o["sku"])
            assert o["market_lowest"] == min(_comps(case)), o

        # uplift is computed off the competitor low
        row = _ours(out, "SIGNOR-GATTO")
        assert row["revenue_uplift"] == round((33.21 - 28.88) * 3, 2)

        assert out["summary"]["total_overpriced"] == len(out["opportunities"])
        assert out["summary"]["overpriced_count"] == out["summary"]["total_overpriced"]
    asyncio.run(main())


def test_product_with_no_competitor_is_skipped_entirely():
    """Our store alone carrying a SKU is not a market — it must not produce a
    market low, a gap, or an opportunity row."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        now = server.datetime.now(server.timezone.utc)
        await db.my_products.insert_one({"sku": "SOLO-1", "price": 50})
        await db.products.insert_one({"id": "p-solo", "sku": "SOLO-1", "name_ar": "solo"})
        # two own-store snapshots so the len(store_snaps) >= 2 gate can't be
        # what saves us — the competitor-only guard has to
        await db.product_snapshots.insert_many([
            {"id": "solo-1", "sku": "SOLO-1", "store_id": OWN, "store_name": "Pets Houses",
             "price": 50, "qty_available": 1, "in_stock": True, "confidence_score": 99,
             "crawled_at": now},
            {"id": "solo-2", "sku": "SOLO-1", "store_id": OWN, "store_name": "Pets Houses",
             "price": 900, "qty_available": 1, "in_stock": True, "confidence_score": 99,
             "crawled_at": now - server.timedelta(hours=1)},
        ])
        out = await _scan()
        assert not any(o["sku"] == "SOLO-1" for o in out["opportunities"])
        assert not any(w["sku"] == "SOLO-1" for w in out["well_positioned"])
        assert not any(u["sku"] == "SOLO-1" for u in out["undercut"])
    asyncio.run(main())


def test_competitor_only_low_is_used_when_we_are_the_expensive_one():
    """Sanity: raising our price above every competitor must produce a gap
    measured against the cheapest COMPETITOR, not against ourselves."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        await db.product_snapshots.update_one(
            {"id": "s-LINDO-400-own"}, {"$set": {"price": 60.0}})
        out = await _scan()
        row = _ours(out, "LINDO-400")
        assert row["market_lowest"] == 28.00                  # not 60.0, not 24.35
        assert row["gap_pct"] == round((60.0 - 28.0) / 28.0 * 100, 1)
        assert row["badge"] == "overpriced_risk"              # >= 25%
    asyncio.run(main())


if __name__ == "__main__":
    test_market_low_is_the_lowest_competitor_not_our_own_price()
    test_the_three_ex_vat_cases_now_report_the_inc_vat_low()
    test_signor_gatto_case_is_unchanged()
    test_overpriced_count_drops_to_exclude_self_comparisons()
    test_product_with_no_competitor_is_skipped_entirely()
    test_competitor_only_low_is_used_when_we_are_the_expensive_one()
    print("PASS: iter50 scanner competitor-only market low")
