"""iter58 — the four Discounts endpoints, which all failed in production.

Root causes were NOT uniform:

  top-pct / top-amount / timeline   $sort + $group over 90 days of snapshots
      with no allowDiskUse -> QueryExceededMemoryLimitNoDiskUseAllowed (292)
      -> unhandled -> 500. Same failure as iter22's _build_competitor_lookups
      and insights/data-freshness.

  aggression   never hit the memory limit ($group _id:None emits one doc). It
      looped over every active store issuing an aggregate AND a
      count_documents each — ~22 sequential 90-day scans awaited one at a time.
      That is why it HUNG instead of 500-ing.

  top-* (latent)   $first omits a field entirely when it is absent from the
      winning document, so ONE row missing original_price / price / store_name
      killed the endpoint with a KeyError or a TypeError on
      `original_price - price`.

FerretDB cannot run these pipelines ($first / $avg / $max / $dateToString are
unimplemented), so the aggregation stages are stubbed where needed and the
Python that consumes them — which is where the crashes actually lived — is
exercised for real.
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
os.environ["DB_NAME"] = "test_discounts_ep"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_discounts_ep"
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
U = {"id": "t", "email": "t@t", "role": "super_admin"}
ZID, SALLA = "zid-store", "salla-store"
SKU_Z, SKU_S = "8901234567890", "8909999999999"


# ── stub only the $-operator stages; everything else is the real DB ──────────
class _Agg:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, n=None):
        return list(self.rows)[:n] if n else list(self.rows)


class _Coll:
    def __init__(self, real, plans):
        self._r, self._plans = real, plans

    def __getattr__(self, n):
        return getattr(self._r, n)

    def aggregate(self, pipeline, **kw):
        # the fix under test: every discount pipeline must ask for disk spill
        assert kw.get("allowDiskUse") is True, f"allowDiskUse missing: {pipeline[:1]}"
        for matcher, rows in self._plans:
            if matcher(pipeline):
                return _Agg(rows)
        return _Agg([])


class _DB:
    def __init__(self, real, plans):
        self._r, self._plans = real, plans

    def __getitem__(self, n):
        return self._r[n]

    def __getattr__(self, n):
        v = getattr(self._r, n)
        return _Coll(v, self._plans) if n == "product_snapshots" else v


def _n_groups(p):
    return sum(1 for s in p if "$group" in s)


def _is_pair_group(p):
    # NOTE: dict equality ignores key order, so {"sku","store_id"} also matches
    # aggression's FIRST $group. Disambiguate on stage count — the top-*
    # pipelines have exactly one $group, aggression's discount pass has two.
    return _n_groups(p) == 1 and any(
        "$group" in s and s["$group"]["_id"] == {"sku": "$sku", "store_id": "$store_id"}
        for s in p)


def _is_week_group(p):
    return any("$project" in s and "week" in s["$project"] for s in p)


def _is_disc_group(p):
    return _n_groups(p) == 2


def _is_total_group(p):
    return _n_groups(p) == 1 and any(
        "$group" in s and s["$group"]["_id"] == "$store_id" for s in p)


async def _seed(db):
    for c in ("stores", "products", "product_snapshots", "sku_sales_daily"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": ZID, "name": "Aleef", "domain": "aleef.com", "platform": "zid", "is_active": True},
        {"id": SALLA, "name": "Zarafa", "domain": "zarafaksa.com", "platform": "salla",
         "is_active": True},
    ])
    await db.products.insert_many([
        {"id": "pz", "sku": SKU_Z, "name_ar": "رويال كانين", "name_en": "Royal Canin Adult 15kg",
         "category": "dog_food", "image_url": "http://x/z.jpg"},
        {"id": "ps", "sku": SKU_S, "name_ar": "ويسكاس", "name_en": "Whiskas Tuna 400g",
         "category": "cat_food", "image_url": "http://x/s.jpg"},
    ])
    now = server.datetime.now(server.timezone.utc)
    snaps = []
    # Zid product: NO discount for 10 days, then discounted from day -6 onward.
    # The history reconstruction must land on that exact first discounted row.
    for d in range(10, 6, -1):
        snaps.append({"id": f"z-full-{d}", "store_id": ZID, "store_name": "Aleef", "sku": SKU_Z,
                      "price": 466.0, "original_price": 466.0, "discount_pct": 0,
                      "confidence_score": 95, "crawled_at": now - server.timedelta(days=d)})
    for d in range(6, -1, -1):
        snaps.append({"id": f"z-disc-{d}", "store_id": ZID, "store_name": "Aleef", "sku": SKU_Z,
                      "price": 349.50, "original_price": 466.0, "discount_pct": 25,
                      "confidence_score": 95, "crawled_at": now - server.timedelta(days=d)})
    # Salla product: discounted throughout
    for d in range(4, -1, -1):
        snaps.append({"id": f"s-disc-{d}", "store_id": SALLA, "store_name": "Zarafa", "sku": SKU_S,
                      "price": 7.50, "original_price": 10.0, "discount_pct": 25,
                      "confidence_score": 95, "crawled_at": now - server.timedelta(days=d)})
    await db.product_snapshots.insert_many(snaps)
    # Zid sold-counter movement DURING the discount only
    for d in range(6, -1, -1):
        day = server._metric_day_str(now - server.timedelta(days=d))
        await db.sku_sales_daily.insert_one({
            "store_id": ZID, "sku": SKU_Z, "date": day, "units_sold": 3, "rev_sold": 1048.5,
            "units_qty": 0, "rev_qty": 0.0, "qty_drop": 0})
    server.db = db
    return now


def _pair_rows(now):
    """What the latest-per-(sku,store) $group emits for the seeded data."""
    return [
        {"_id": {"sku": SKU_Z, "store_id": ZID}, "sku": SKU_Z, "store_id": ZID,
         "store_name": "Aleef", "price": 349.50, "original_price": 466.0,
         "discount_pct": 25, "crawled_at": now},
        {"_id": {"sku": SKU_S, "store_id": SALLA}, "sku": SKU_S, "store_id": SALLA,
         "store_name": "Zarafa", "price": 7.50, "original_price": 10.0,
         "discount_pct": 25, "crawled_at": now},
    ]


# ── 1. all four return 200 with real data ───────────────────────────────────
def test_all_four_endpoints_return_data():
    async def main():
        real = AsyncIOMotorClient(MONGO)[_TEST_DB]
        now = await _seed(real)
        plans = [
            (_is_pair_group, _pair_rows(now)),
            (_is_week_group, [
                {"_id": {"store": "Aleef", "week": "2026-W30"}, "count": 7, "avg_depth": 25.0},
                {"_id": {"store": "Zarafa", "week": "2026-W30"}, "count": 5, "avg_depth": 25.0}]),
            (_is_disc_group, [
                {"_id": ZID, "products_on_discount": 1, "avg_depth": 25.0, "max_disc": 25,
                 "discounted_rows": 7},
                {"_id": SALLA, "products_on_discount": 1, "avg_depth": 25.0, "max_disc": 25,
                 "discounted_rows": 5}]),
            (_is_total_group, [{"_id": ZID, "rows": 11}, {"_id": SALLA, "rows": 5}]),
        ]
        server.db = _DB(real, plans)

        pct = await server.top_discounts_pct.__wrapped__(
            days=90, store_id=None, category=None, limit=30, user=U)
        amt = await server.top_discounts_amount.__wrapped__(
            days=90, store_id=None, category=None, limit=30, user=U)
        tl = await server.discount_timeline.__wrapped__(user=U)
        ag = await server.discount_aggression.__wrapped__(user=U)

        assert len(pct) == 2, pct
        assert len(amt) == 2, amt
        assert tl["stores"] == ["Aleef", "Zarafa"] and len(tl["timeline"]) == 1
        assert len(ag) == 2, ag
        server.db = real
    asyncio.run(main())


# ── 2. the client's columns, on a known discounted product ──────────────────
def test_known_product_columns_are_correct():
    async def main():
        real = AsyncIOMotorClient(MONGO)[_TEST_DB]
        now = await _seed(real)
        server.db = _DB(real, [(_is_pair_group, _pair_rows(now))])
        rows = await server.top_discounts_pct.__wrapped__(
            days=90, store_id=None, category=None, limit=30, user=U)
        z = next(r for r in rows if r["sku"] == SKU_Z)

        assert z["store_name"] == "Aleef"
        assert z["name_en"] == "Royal Canin Adult 15kg"
        assert z["original_price"] == 466.0
        assert z["sale_price"] == 349.50
        assert z["discount_amount_sar"] == 116.5           # 466.00 - 349.50
        assert z["discount_pct"] == 25
        assert z["category"] == "dog_food"
        # back-compat aliases the existing UI reads
        assert z["price"] == z["sale_price"] and z["savings_sar"] == z["discount_amount_sar"]
        server.db = real
    asyncio.run(main())


# ── 3. discount history start date == first snapshot where price dropped ────
def test_history_start_matches_first_discounted_snapshot():
    async def main():
        real = AsyncIOMotorClient(MONGO)[_TEST_DB]
        now = await _seed(real)
        server.db = _DB(real, [(_is_pair_group, _pair_rows(now))])
        rows = await server.top_discounts_pct.__wrapped__(
            days=90, store_id=None, category=None, limit=30, user=U)
        z = next(r for r in rows if r["sku"] == SKU_Z)

        # seeded: full price d-10..d-7, discounted d-6..d-0 -> start is d-6.
        # Compare against what the DB actually STORED: MongoDB truncates
        # datetimes to millisecond precision, so recomputing `now - 6d` in
        # Python differs in the microsecond field.
        first = await real.product_snapshots.find_one({"id": "z-disc-6"},
                                                      {"_id": 0, "crawled_at": 1})
        expect = server._aware(first["crawled_at"]).isoformat()
        assert z["discount_started_at"] == expect, (z["discount_started_at"], expect)
        assert z["days_on_discount"] == 6, z["days_on_discount"]
        assert z["discount_ongoing"] is True
        # the run does NOT reach the window edge — earlier full-price rows exist
        assert z["duration_is_lower_bound"] is True
        server.db = real
    asyncio.run(main())


def test_history_run_stops_at_the_price_returning_to_full():
    """A discount that ENDED must not be reported as ongoing."""
    async def main():
        real = AsyncIOMotorClient(MONGO)[_TEST_DB]
        now = await _seed(real)
        # newest Zid snapshot back at full price -> the run is over
        await real.product_snapshots.insert_one({
            "id": "z-back", "store_id": ZID, "store_name": "Aleef", "sku": SKU_Z,
            "price": 466.0, "original_price": 466.0, "discount_pct": 0,
            "confidence_score": 95, "crawled_at": now + server.timedelta(hours=1)})
        server.db = _DB(real, [(_is_pair_group, _pair_rows(now))])
        rows = await server.top_discounts_pct.__wrapped__(
            days=90, store_id=None, category=None, limit=30, user=U)
        z = next(r for r in rows if r["sku"] == SKU_Z)
        assert z["discount_ongoing"] is False and z["discount_started_at"] is None
        assert z["days_on_discount"] == 0
        server.db = real
    asyncio.run(main())


# ── 4. sold-qty: measured for Zid, "not measurable" for Salla ───────────────
def test_sold_during_discount_is_measured_for_zid_and_null_for_salla():
    async def main():
        real = AsyncIOMotorClient(MONGO)[_TEST_DB]
        now = await _seed(real)
        server.db = _DB(real, [(_is_pair_group, _pair_rows(now))])
        rows = await server.top_discounts_pct.__wrapped__(
            days=90, store_id=None, category=None, limit=30, user=U)
        z = next(r for r in rows if r["sku"] == SKU_Z)
        s = next(r for r in rows if r["sku"] == SKU_S)

        # 7 days x 3 units, all inside the discount run
        assert z["sold_during_discount"] == 21, z
        assert z["sold_during_discount_status"] == "measured"
        assert z["platform"] == "zid"

        # Salla: NO number, and an explicit reason — never a fabricated figure
        assert s["sold_during_discount"] is None, s
        assert s["sold_during_discount_status"] == "not_measurable"
        assert "sold-count" in (s["sold_during_discount_note"] or "")
        assert s["platform"] == "salla"
        server.db = real
    asyncio.run(main())


# ── 5. aggression returns products-on-discount and average depth ────────────
def test_aggression_reports_product_count_and_depth_without_n_plus_one():
    async def main():
        real = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(real)
        calls = {"n": 0}

        class _CountingColl(_Coll):
            def aggregate(self, pipeline, **kw):
                calls["n"] += 1
                return super().aggregate(pipeline, **kw)

        class _CountingDB(_DB):
            def __getattr__(self, n):
                v = getattr(self._r, n)
                return _CountingColl(v, self._plans) if n == "product_snapshots" else v

        server.db = _CountingDB(real, [
            (_is_disc_group, [
                {"_id": ZID, "products_on_discount": 12, "avg_depth": 22.4, "max_disc": 40,
                 "discounted_rows": 120},
                {"_id": SALLA, "products_on_discount": 30, "avg_depth": 31.2, "max_disc": 60,
                 "discounted_rows": 300}]),
            (_is_total_group, [{"_id": ZID, "rows": 600}, {"_id": SALLA, "rows": 500}]),
        ])
        ag = await server.discount_aggression.__wrapped__(user=U)

        # TWO aggregations total, not two per store — the hang fix
        assert calls["n"] == 2, calls
        by = {r["store"]: r for r in ag}
        assert by["Aleef"]["products_on_discount"] == 12
        assert by["Aleef"]["avg_depth"] == 22.4
        assert by["Aleef"]["frequency"] == 20.0            # 120 / 600
        assert by["Zarafa"]["products_on_discount"] == 30
        assert by["Zarafa"]["avg_depth"] == 31.2
        assert by["Zarafa"]["score"] >= by["Aleef"]["score"]
        assert ag[0]["label"] == "Most Aggressive"
        server.db = real
    asyncio.run(main())


# ── the latent $first defect ────────────────────────────────────────────────
def test_malformed_rows_no_longer_take_the_endpoint_down():
    """$first omits an absent field, so one bad row used to 500 the endpoint."""
    async def main():
        real = AsyncIOMotorClient(MONGO)[_TEST_DB]
        now = await _seed(real)
        broken = [
            {"sku": SKU_Z, "store_id": ZID, "store_name": "Aleef", "price": 349.5,
             "original_price": None, "discount_pct": 25, "crawled_at": now},
            {"sku": SKU_Z, "store_id": ZID, "price": 349.5, "discount_pct": 25,
             "crawled_at": now},                                  # no original_price, no store_name
            {"sku": SKU_S, "store_id": SALLA, "store_name": "Zarafa", "price": None,
             "original_price": 10.0, "discount_pct": 25, "crawled_at": now},
            {"sku": SKU_S, "store_id": SALLA, "store_name": "Zarafa", "price": 7.5,
             "original_price": 10.0, "discount_pct": 25, "crawled_at": now},   # the good one
        ]
        server.db = _DB(real, [(_is_pair_group, broken)])
        pct = await server.top_discounts_pct.__wrapped__(
            days=90, store_id=None, category=None, limit=30, user=U)
        assert len(pct) == 4, pct
        assert [r["discount_amount_sar"] for r in pct] == [None, None, None, 2.5]
        assert pct[1]["store_name"] == ""            # absent -> empty, not KeyError

        # top-amount ranks by SAR and must simply drop the unrankable rows
        amt = await server.top_discounts_amount.__wrapped__(
            days=90, store_id=None, category=None, limit=30, user=U)
        assert len(amt) == 1 and amt[0]["discount_amount_sar"] == 2.5, amt
        server.db = real
    asyncio.run(main())


def test_window_is_bounded_and_category_filter_applies():
    async def main():
        real = AsyncIOMotorClient(MONGO)[_TEST_DB]
        now = await _seed(real)
        server.db = _DB(real, [(_is_pair_group, _pair_rows(now))])
        # a caller asking for 3650 days is clamped to the 90-day bound
        rows = await server.top_discounts_pct.__wrapped__(
            days=3650, store_id=None, category=None, limit=30, user=U)
        assert len(rows) == 2
        assert server._DISCOUNT_MAX_DAYS == 90
        # category filter runs AFTER enrichment, on the joined product category
        only_dog = await server.top_discounts_pct.__wrapped__(
            days=90, store_id=None, category="dog_food", limit=30, user=U)
        assert [r["sku"] for r in only_dog] == [SKU_Z], only_dog
        server.db = real
    asyncio.run(main())


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
    print("PASS: iter58 discounts endpoints")
