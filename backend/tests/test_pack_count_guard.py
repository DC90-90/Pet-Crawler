"""iter51 — pack-COUNT guard: a carton and a single tin are different products.

Production: the Scanner flagged our multi-packs as +2000% overpriced because a
carton and a single piece share an EAN (and on some stores a SKU string), so
they were compared directly.

  Beso      "24 Pieces*400g"  SKU 8015912514257  ours 160.80 vs low  7.50  +2044%
  Kit Cat   "24 Pieces*70g"   SKU 8858772603095  ours 132.25 vs low  6.24  +2019%
  Butcher's "400g"            SKU 5011792007325  ours 208.00 vs low  8.10  +2468%

The pack guard never fired because PACK_RE only understands "<keyword> N"
("pack of 24", "علبة 24"). Every count-FIRST form — "24 Pieces*400g", "24 Pcs",
"24 x 400g", "24-pack", "24 قطعة" — parsed as qty 1, i.e. a single unit. The
`×` branch could not help either: it needs U+00D7 *and* the digits after the
sign, so even "24×400g" missed.

These are genuinely different products, so matching/comparison is BLOCKED —
prices are NOT normalised per unit.
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
os.environ["DB_NAME"] = "test_pack_guard"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_pack_guard"
import matcher as M  # noqa: E402
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
USER = {"id": "t", "email": "t@t", "role": "super_admin"}
OWN = "own-store-id"

# the three production SKUs: (sku, our carton name, our price, single-unit low)
LIVE = [
    ("8015912514257", "Beso Cat Wet Food Chicken 24 Pieces*400g", 160.80, 7.50),
    ("8858772603095", "Kit Cat Wet Food Tuna 24 Pieces*70g",      132.25, 6.24),
    ("5011792007325", "Butcher's Dog Wet Food Chicken 400g",      208.00, 8.10),
]


# ── parsing ──────────────────────────────────────────────────────────────────
def test_count_first_pack_descriptors_are_parsed():
    for text, qty in [
        ("24 Pieces*400g", 24), ("24 Pieces*70g", 24), ("24 Pcs", 24),
        ("24 pieces * 400 g", 24), ("24 x 400g", 24), ("24*70g", 24),
        ("24×400g", 24), ("24-pack", 24), ("24 pack", 24),
        ("6 sachets", 6), ("12 pouches", 12), ("4 tins", 4),
        ("24 قطعة", 24), ("12 حبة", 12), ("6 أكياس", 6),
        ("عبوة 24", 24), ("علبة 12", 12), ("pack of 6", 6), ("Carton 24", 24),
        ("400g x 24", 24), ("1.5kg*6", 6),
    ]:
        assert M._extract_pack_qty(text) == qty, (text, M._extract_pack_qty(text))
        assert M._has_pack_indicator(text) is True, text


def test_singles_and_non_pack_names_are_untouched():
    """A product with no pack descriptor must be unaffected — qty 1, no
    indicator — and must not be dragged in by a weight or a barcode."""
    for text in ["400g", "70g", "15kg", "1.5 kg", "Royal Canin Medium Adult 15kg",
                 "Butcher's Dog Wet Food Chicken 400g", "Hills GI Biome 1.5kg",
                 "One Piece Cat Toy", "40 x 60 cm Pet Bed", "8015912514257", ""]:
        assert M._extract_pack_qty(text) == 1, (text, M._extract_pack_qty(text))
        assert M._has_pack_indicator(text) is False, text

    # iter20 regression guard: COMPOUND words must not false-fire
    for text in ["متعدد الألوان", "Backpack Carrier", "كرتونية"]:
        assert M._has_pack_indicator(text) is False, text
    # ...but a STANDALONE keyword token still does, on main as here. iter20's
    # docstring cites "Subscription Box" as safe; it isn't — the splitter breaks
    # on whitespace, so "box" is its own token. Pre-existing, out of scope,
    # pinned so the behaviour is at least deliberate.
    assert M._has_pack_indicator("Subscription Box Toy") is True
    # ...and _extract_pack_qty now agrees with it (it used naive substring
    # matching, so "متعدد" returned -1 and blocked every single-unit competitor)
    assert M._extract_pack_qty("متعدد الألوان") == 1
    assert M._extract_pack_qty("Backpack Carrier") == 1


# ── the guard itself ─────────────────────────────────────────────────────────
def test_carton_does_not_match_single_but_carton_matches_carton():
    for _sku, carton, _p, _l in LIVE[:2]:
        single = carton.replace("24 Pieces*", "")
        assert M._extract_pack_qty(carton) == 24
        assert M._extract_pack_qty(single) == 1
        # 24-pack vs 1-piece -> BLOCKED
        assert M._pack_compatible(carton, single) is False, carton
        assert M._pack_compatible(single, carton) is False, carton
        # 24-pack vs 24-pack -> still matches
        assert M._pack_compatible(carton, carton) is True, carton
        # a differently-worded 24-pack still matches
        assert M._pack_compatible(carton, single + " Carton 24") is True, carton
    # two singles are unaffected
    assert M._pack_compatible("Butcher's 400g", "Butchers Chicken 400g") is True
    # both-unknown proceeds as before
    assert M._pack_compatible("Some Pack Thing", "Another Pack Thing") is True


# ── both match paths ─────────────────────────────────────────────────────────
class _FakeCur:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _FakeColl:
    def find(self, *a, **k):
        return _FakeCur()


class _FakeDB:
    def __getattr__(self, n):
        return _FakeColl()


def _match(my, snaps, products):
    return asyncio.run(M.match_my_product(_FakeDB(), my, snaps, products, "own"))


def test_barcode_path_respects_pack_count():
    """Shared EAN — the collision the guard exists for."""
    my = {"sku": "8015912514257", "barcode": "8015912514257",
          "name_ar": "", "name_en": "Beso Cat Wet Food 24 Pieces*400g", "price": 160.8}
    snaps = [{"sku": "8015912514257", "store_id": "zarafa", "price": 7.5}]
    single = {"8015912514257": {"sku": "8015912514257", "name_ar": "",
                                "name_en": "Beso Cat Wet Food 400g"}}
    assert _match(my, snaps, single) == [], "single piece must not match the carton"

    carton = {"8015912514257": {"sku": "8015912514257", "name_ar": "",
                                "name_en": "Beso Cat Wet Food 24 Pieces*400g"}}
    out = _match(my, snaps, carton)
    assert len(out) == 1 and out[0]["match_method"] == "barcode", out
    # regression: before iter51 a bundle was banned from Level 1 wholesale, so
    # this carton-to-carton match could not form at all
    assert out[0]["confidence"] == 99


def test_sku_path_respects_pack_count():
    """Shared SKU string (the Zarafa shape) — no barcode involved."""
    my = {"sku": "BESO-CHK", "barcode": "", "name_ar": "",
          "name_en": "Beso Cat Wet Food 24 Pieces*400g", "price": 160.8}
    snaps = [{"sku": "BESO-CHK", "store_id": "zarafa", "price": 7.5}]
    single = {"BESO-CHK": {"sku": "BESO-CHK", "name_ar": "",
                           "name_en": "Beso Cat Wet Food 400g"}}
    assert _match(my, snaps, single) == [], "single piece must not match via SKU"

    carton = {"BESO-CHK": {"sku": "BESO-CHK", "name_ar": "",
                           "name_en": "Beso Cat Wet Food 24 Pieces*400g"}}
    out = _match(my, snaps, carton)
    assert len(out) == 1 and out[0]["match_method"] == "sku", out


def test_products_without_pack_descriptors_still_match_normally():
    """No pack descriptor anywhere -> the guard is a no-op."""
    my = {"sku": "3182550402217", "barcode": "3182550402217", "name_ar": "",
          "name_en": "Royal Canin Medium Adult 15kg", "price": 466}
    snaps = [{"sku": "3182550402217", "store_id": "aleef", "price": 431.26}]
    prods = {"3182550402217": {"sku": "3182550402217", "name_ar": "",
                               "name_en": "Royal Canin Medium Adult 15kg"}}
    out = _match(my, snaps, prods)
    assert len(out) == 1 and out[0]["match_method"] == "barcode"


# ── Scanner ──────────────────────────────────────────────────────────────────
class _Agg:
    """FerretDB has no `$first` accumulator, so the endpoint's $group pipeline
    (unchanged by iter51) is reproduced here; the loop under test consumes
    identical rows."""

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


async def _seed_scanner(db, catalogue_name):
    """catalogue_name(sku, carton) -> the name db.products holds for that SKU.

    db.products is ONE row per SKU shared by every store (first writer wins), so
    this models the two possible worlds: the shared row holds the competitor's
    single-piece name, or it holds our own carton name.
    """
    for c in ("stores", "my_products", "products", "product_snapshots"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com", "is_own_store": True},
        {"id": "zarafa", "name": "Zarafa", "domain": "zarafaksa.com"},
        {"id": "comp-b", "name": "Petsy", "domain": "petsysa.com"},
    ])
    now = server.datetime.now(server.timezone.utc)
    mine, prods, snaps = [], [], []
    for sku, carton, ours, low in LIVE:
        mine.append({"sku": sku, "name_en": carton, "name_ar": "", "price": ours})
        prods.append({"id": f"p-{sku}", "sku": sku, "name_ar": "",
                      "name_en": catalogue_name(sku, carton), "category": "cat_food"})
        snaps += [
            {"id": f"{sku}-own", "sku": sku, "store_id": OWN, "store_name": "Pets Houses",
             "price": ours, "qty_available": 5, "in_stock": True,
             "confidence_score": 99, "crawled_at": now},
            {"id": f"{sku}-z", "sku": sku, "store_id": "zarafa", "store_name": "Zarafa",
             "price": low, "qty_available": 9, "in_stock": True,
             "confidence_score": 99, "crawled_at": now},
            {"id": f"{sku}-b", "sku": sku, "store_id": "comp-b", "store_name": "Petsy",
             "price": round(low * 1.2, 2), "qty_available": 4, "in_stock": True,
             "confidence_score": 99, "crawled_at": now},
        ]
    await db.my_products.insert_many(mine)
    await db.products.insert_many(prods)
    await db.product_snapshots.insert_many(snaps)
    server.db = db


async def _scan():
    fn = getattr(server.price_opportunities, "__wrapped__", server.price_opportunities)
    real, server.db = server.db, _AggDB(server.db)
    try:
        return await fn(days=14, user=USER)
    finally:
        server.db = real


def test_scanner_drops_the_three_live_skus_when_catalogue_holds_the_single_name():
    """The fixable world: db.products carries the competitor's single-piece
    name, so the mismatch is visible and all three SKUs are withheld."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        # Butcher's carton name has no descriptor either, so model it as the
        # catalogue holding the single name while OUR name says 24 Pieces
        await _seed_scanner(db, lambda sku, carton: carton.replace("24 Pieces*", "")
                            if "24 Pieces*" in carton else carton)
        out = await _scan()

        # Beso + Kit Cat: our 24-pack vs a catalogue single -> withheld
        for sku, _c, _p, _l in LIVE[:2]:
            assert not any(o["sku"] == sku for o in out["opportunities"]), sku
            assert sku in out["summary"]["pack_mismatch_sample"], sku
        assert out["summary"]["pack_mismatch_skipped"] == 2, out["summary"]

        # Butcher's: NEITHER name has a pack descriptor, so THIS guard cannot
        # distinguish them — that was the documented limit of a name-based rule.
        # iter53 closes it from the other side (a >=6x price gap on a shared EAN
        # with nothing corroborating sameness), so the row is gone too.
        assert not any(o["sku"] == "5011792007325" for o in out["opportunities"])
        assert "5011792007325" in {f["sku"] for f in
                                   out["summary"]["barcode_unreliable_sample"]}
        # nothing above +300% survives at all now
        assert [o["sku"] for o in out["opportunities"] if o["gap_pct"] > 300] == []
    asyncio.run(main())


def test_scanner_unaffected_when_pack_counts_agree():
    """Same pack count on both sides -> the Scanner behaves exactly as before."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed_scanner(db, lambda sku, carton: carton)   # catalogue == our name
        out = await _scan()
        assert out["summary"]["pack_mismatch_skipped"] == 0
        # Beso and Kit Cat state "24 Pieces*" on BOTH sides, so iter53's shared-
        # barcode check finds pack_qty_agrees and keeps their >6x lows. iter78
        # then removes them from the OTHER side: each low sits >5x below the
        # cluster our price and the second seller form, which is precisely the
        # collision the client reported as a +445% gap. Level with what is left,
        # we are not overpriced on either SKU.
        assert {o["sku"] for o in out["opportunities"]} == set()
        excluded = {f["sku"] for f in out["summary"]["low_outliers_excluded_sample"]}
        assert {"8015912514257", "8858772603095"} <= excluded
        # Butcher's states no pack count anywhere, so nothing corroborates its
        # 25x gap and iter53 drops it before iter78 ever sees it
        assert {f["sku"] for f in out["summary"]["barcode_unreliable_sample"]} \
            == {"5011792007325"}
    asyncio.run(main())


if __name__ == "__main__":
    test_count_first_pack_descriptors_are_parsed()
    test_singles_and_non_pack_names_are_untouched()
    test_carton_does_not_match_single_but_carton_matches_carton()
    test_barcode_path_respects_pack_count()
    test_sku_path_respects_pack_count()
    test_products_without_pack_descriptors_still_match_normally()
    test_scanner_drops_the_three_live_skus_when_catalogue_holds_the_single_name()
    test_scanner_unaffected_when_pack_counts_agree()
    print("PASS: iter51 pack-count guard")
