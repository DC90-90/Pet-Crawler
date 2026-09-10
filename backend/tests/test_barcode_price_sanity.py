"""iter53 — a shared EAN across pack sizes is not proof of sameness.

An EAN identifies a TRADE ITEM, and manufacturers routinely print the unit
barcode on the multipack too. So one EAN legitimately covers a single 400g tin
(~8 SAR, Zarafa) and a 24-tin carton (~208 SAR, our catalogue). Barcode equality
is still "correct" and still pairs two products that are not substitutes:

  5011792007325  ours 208.00  vs Zarafa 8.10   -> +2468%
  5011792007622  ours ~200    vs Zarafa 7.99   -> +2400%
  8034105423817  ours ~200    vs Zarafa 6.99   -> +2700%

Rule: a >=6x price gap makes the BARCODE unreliable for that pair. The match
then needs positive corroboration of the same pack size — an explicit pack count
on both sides, or independently-worded but strongly similar names. Absent that,
it is dropped.

6x sits far outside retail discounting: a 74%-off sale is 3.85x and 80% off is
5x, so the Royal Canin 118-vs-466 case never reaches the check.
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
os.environ["DB_NAME"] = "test_barcode_sanity"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_barcode_sanity"
import matcher as M  # noqa: E402
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
USER = {"id": "t", "email": "t@t", "role": "super_admin"}
OWN = "own-store-id"

# the live Zarafa cluster: (sku, our carton price, Zarafa single price, name)
CLUSTER = [
    ("5011792007325", 208.00, 8.10, "Butcher's Delicious Wet Cat Food Venison in Jelly 400g"),
    ("5011792007622", 200.00, 7.99, "Butcher's Delicious Wet Cat Food Chicken in Jelly 400g"),
    ("8034105423817", 200.00, 6.99, "Almo Nature HFC Natural Wet Cat Food Chicken 70g"),
]
RC = "3182550402217"


# ── the rule itself ──────────────────────────────────────────────────────────
def test_shared_barcode_across_pack_sizes_is_rejected():
    for sku, ours, theirs, name in CLUSTER:
        ok, why = M.barcode_price_sane(ours, theirs, name, name)
        assert ok is False, (sku, why)
        assert why.startswith("shared_barcode_price_ratio_"), why


def test_rule_is_symmetric():
    """Which side is cheaper must not matter."""
    for sku, ours, theirs, name in CLUSTER:
        a = M.barcode_price_sane(ours, theirs, name, name)
        b = M.barcode_price_sane(theirs, ours, name, name)
        assert a == b, (sku, a, b)


def test_genuine_deep_discounts_are_never_touched():
    """The Royal Canin real sale and its neighbours sit below the threshold."""
    n = "Royal Canin Medium Adult 15kg"
    for label, hi, lo in [("74% off (the live sale)", 466.0, 118.0),
                          ("80% off", 466.0, 93.2),
                          ("83% off — just under 6x", 466.0, 78.0)]:
        ok, why = M.barcode_price_sane(hi, lo, n, n)
        assert ok is True, (label, max(hi, lo) / min(hi, lo), why)
        assert why is None
    # and the ratio that defines the boundary
    assert M.BARCODE_PRICE_RATIO_MAX == 6.0
    assert M.barcode_price_sane(600.0, 100.0, n, n)[0] is False   # exactly 6x
    assert M.barcode_price_sane(599.0, 100.0, n, n)[0] is True    # just under


def test_corroboration_keeps_a_wide_gap_when_pack_sizes_agree():
    ok, why = M.barcode_price_sane(208.0, 30.0, "Beso 24 Pieces*400g",
                                   "Beso Cat Food 24 Pieces*400g")
    assert ok is True and why == "pack_qty_agrees"
    # disagreeing explicit packs get no corroboration
    ok, why = M.barcode_price_sane(208.0, 30.0, "Beso 24 Pieces*400g", "Beso 6 Pieces*400g")
    assert ok is False, why


def test_corroboration_by_independent_similar_names():
    ok, why = M.barcode_price_sane(700.0, 100.0, "Acana Wild Coast Dog 11.4kg",
                                   "Acana Wild Coast Dog Food 11.4kg")
    assert ok is True and why == "name_corroborated"
    # unrelated names corroborate nothing
    assert M.barcode_price_sane(700.0, 100.0, "Acana Wild Coast Dog 11.4kg",
                                "Whiskas Tuna Pouch 85g")[0] is False


def test_identical_names_do_not_corroborate():
    """db.products holds ONE row per SKU shared by every store, so a
    competitor's name is often our own catalogue string echoed back. Identical
    strings are the same document, not two sources agreeing."""
    n = "Butcher's Delicious Wet Cat Food Venison in Jelly 400g"
    assert M._names_are_independent(n, n) is False
    assert M._names_are_independent(n, n.replace("Delicious ", "")) is True
    assert M.barcode_price_sane(208.0, 8.10, n, n)[0] is False


def test_explicit_pack_qty_distinguishes_unstated_from_single():
    """_extract_pack_qty returns 1 for a silent name; corroboration must not
    read two silences as agreement."""
    assert M._pack_qty_explicit("Butcher's Wet Cat Food 400g") is None
    assert M._extract_pack_qty("Butcher's Wet Cat Food 400g") == 1
    assert M._pack_qty_explicit("Beso 24 Pieces*400g") == 24
    # two silent names, 25x apart -> NOT corroborated
    assert M.barcode_price_sane(208.0, 8.10, "Butcher's 400g", "Butcher's 400g")[0] is False


def test_missing_or_zero_prices_are_not_judged():
    n = "Some Product 400g"
    for a, b in [(0, 8.1), (208.0, 0), (None, 8.1), (208.0, None), ("x", 8.1)]:
        assert M.barcode_price_sane(a, b, n, n)[0] is True


# ── the matcher path ─────────────────────────────────────────────────────────
class _FakeCur:
    def __init__(self, docs=()):
        self._d = list(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._d:
            raise StopAsyncIteration
        return self._d.pop(0)


class _FakeColl:
    def __init__(self, docs=()):
        self._docs = docs

    def find(self, *a, **k):
        return _FakeCur(self._docs)


class _FakeDB:
    def __init__(self, confirmed=()):
        self._confirmed = confirmed

    def __getattr__(self, n):
        if n == "product_matches":
            return _FakeColl(self._confirmed)
        return _FakeColl()


def _match(my, snaps, products, confirmed=()):
    return asyncio.run(M.match_my_product(_FakeDB(confirmed), my, snaps, products, "own"))


def test_barcode_match_dropped_for_the_zarafa_cluster():
    for sku, ours, theirs, name in CLUSTER:
        my = {"sku": sku, "barcode": sku, "name_ar": "", "name_en": name, "price": ours}
        snaps = [{"sku": sku, "store_id": "zarafa", "store_name": "Zarafa", "price": theirs}]
        prods = {sku: {"sku": sku, "name_ar": "", "name_en": name}}
        assert _match(my, snaps, prods) == [], sku


def test_real_sale_still_matches_through_the_barcode_path():
    name = "Royal Canin Medium Adult 15kg"
    my = {"sku": RC, "barcode": RC, "name_ar": "", "name_en": name, "price": 466.0}
    snaps = [{"sku": RC, "store_id": "aleef", "store_name": "Aleef", "price": 118.0}]
    prods = {RC: {"sku": RC, "name_ar": "", "name_en": name}}
    out = _match(my, snaps, prods)
    assert len(out) == 1, out
    assert out[0]["match_method"] == "barcode" and out[0]["confidence"] == 99
    assert out[0]["competitor_price"] == 118.0


def test_manually_confirmed_matches_are_exempt():
    """A human decision outranks the heuristic."""
    sku, ours, theirs, name = CLUSTER[0]
    my = {"sku": sku, "barcode": sku, "name_ar": "", "name_en": name, "price": ours}
    snaps = [{"sku": sku, "store_id": "zarafa", "store_name": "Zarafa", "price": theirs}]
    prods = {sku: {"sku": sku, "name_ar": "", "name_en": name}}
    out = _match(my, snaps, prods, confirmed=[{"competitor_sku": sku}])
    assert len(out) == 1 and out[0]["confidence"] == 100, out


def test_earlier_guards_still_apply():
    """iter51's pack guard must keep rejecting a stated 24-pack vs a single even
    when the price gap is small enough that iter53 never fires."""
    my = {"sku": "8015912514257", "barcode": "8015912514257", "name_ar": "",
          "name_en": "Beso Cat Wet Food 24 Pieces*400g", "price": 160.8}
    snaps = [{"sku": "8015912514257", "store_id": "z", "store_name": "Z", "price": 120.0}]
    prods = {"8015912514257": {"sku": "8015912514257", "name_ar": "",
                               "name_en": "Beso Cat Wet Food 400g"}}
    assert max(160.8, 120.0) / min(160.8, 120.0) < M.BARCODE_PRICE_RATIO_MAX
    assert _match(my, snaps, prods) == []


# ── the Scanner ──────────────────────────────────────────────────────────────
class _Agg:
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


def _snap(sku, store, price, at):
    return {"id": f"{sku}-{store}-{price}", "sku": sku, "store_id": store,
            "store_name": {"own-store-id": "Pets Houses", "zarafa": "Zarafa",
                           "aleef": "Aleef", "petsy": "Petsy"}[store],
            "price": price, "qty_available": 5, "in_stock": True,
            "confidence_score": 99, "crawled_at": at}


def test_scanner_gap_over_300_drops_to_zero_for_the_cluster():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        for c in ("stores", "my_products", "products", "product_snapshots"):
            await db[c].delete_many({})
        await db.stores.insert_many([
            {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com", "is_own_store": True},
            {"id": "zarafa", "name": "Zarafa", "domain": "zarafaksa.com"},
            {"id": "aleef", "name": "Aleef", "domain": "aleef.com"},
        ])
        now = server.datetime.now(server.timezone.utc)
        mine, prods, snaps = [], [], []
        for sku, ours, theirs, name in CLUSTER:
            # iter77 — `ours` is the shelf (inc-VAT) price: tag the basis so the
            # Scanner's VAT resolver takes it as-is instead of grossing it.
            mine.append({"sku": sku, "name_en": name, "name_ar": "", "price": ours,
                         "price_basis": "storefront_inc_vat"})
            prods.append({"id": f"p-{sku}", "sku": sku, "name_ar": "", "name_en": name})
            snaps += [_snap(sku, OWN, ours, now),
                      _snap(sku, "zarafa", theirs, now),      # the colliding tin
                      _snap(sku, "aleef", ours, now)]         # a real carton rival
        # a genuine deep discount that must survive
        rc_name = "Royal Canin Medium Adult 15kg"
        mine.append({"sku": RC, "name_en": rc_name, "name_ar": "", "price": 466.0,
                     "price_basis": "storefront_inc_vat"})
        prods.append({"id": "p-rc", "sku": RC, "name_ar": "", "name_en": rc_name})
        snaps += [_snap(RC, OWN, 466.0, now), _snap(RC, "aleef", 118.0, now),
                  _snap(RC, "zarafa", 431.0, now)]
        await db.my_products.insert_many(mine)
        await db.products.insert_many(prods)
        await db.product_snapshots.insert_many(snaps)
        server.db = db

        out = await _scan()

        # BEFORE this change every cluster SKU showed a +2400%-ish row
        assert [o for o in out["opportunities"] if o["gap_pct"] > 300] == [], \
            [(o["sku"], o["gap_pct"]) for o in out["opportunities"] if o["gap_pct"] > 300]
        assert out["summary"]["barcode_unreliable"] == 3, out["summary"]
        flagged = {f["sku"] for f in out["summary"]["barcode_unreliable_sample"]}
        assert flagged == {c[0] for c in CLUSTER}, flagged
        for f in out["summary"]["barcode_unreliable_sample"]:
            assert f["store_name"] == "Zarafa" and f["reason"].startswith(
                "shared_barcode_price_ratio_")

        # the cluster still has a real market low from the carton rival
        for sku, ours, _t, _n in CLUSTER:
            row = next((o for o in out["opportunities"] if o["sku"] == sku), None)
            assert row is None or row["market_lowest"] == ours, (sku, row)

        # the Royal Canin sale is untouched and still sets the low
        rc = next(o for o in out["opportunities"] if o["sku"] == RC and o["store_id"] == OWN)
        assert rc["market_lowest"] == 118.0
        assert rc["gap_pct"] == round((466.0 - 118.0) / 118.0 * 100, 1)
    asyncio.run(main())


def test_scanner_skips_sku_when_every_competitor_is_unreliable():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        for c in ("stores", "my_products", "products", "product_snapshots"):
            await db[c].delete_many({})
        await db.stores.insert_many([
            {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com", "is_own_store": True},
            {"id": "zarafa", "name": "Zarafa", "domain": "zarafaksa.com"},
            {"id": "aleef", "name": "Aleef", "domain": "aleef.com"},
        ])
        now = server.datetime.now(server.timezone.utc)
        sku, ours, theirs, name = CLUSTER[0]
        await db.my_products.insert_one({"sku": sku, "name_en": name, "name_ar": "",
                                         "price": ours, "price_basis": "storefront_inc_vat"})
        await db.products.insert_one({"id": "p", "sku": sku, "name_ar": "", "name_en": name})
        await db.product_snapshots.insert_many([
            _snap(sku, OWN, ours, now),
            _snap(sku, "zarafa", theirs, now),
            _snap(sku, "aleef", 7.5, now),      # a second colliding tin
        ])
        server.db = db
        out = await _scan()
        # no trustworthy competitor price left -> no market low, no row at all
        assert not any(o["sku"] == sku for o in out["opportunities"])
        assert out["summary"]["barcode_unreliable"] == 2
    asyncio.run(main())


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f()
    print("PASS: iter53 barcode price sanity")
