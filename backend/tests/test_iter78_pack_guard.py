"""iter78 — PACK SIZE GUARD.

Client report: *"Stop a rival's single sachet being compared to my multipack, it
fakes a +445% gap"*. Two real shapes from their data:

  45g toothpaste   ours 23.45 · Mowkly 23.00 · Panda 4.30   -> low was 4.30 (+445%)
  15g Kit Cat stick ours 14.00 · Petsy 10.00 (3.5g single!) · Aleef 7.50 (3.5g)
                    · Panda 10.00 · Mowkly 10.50 · Caty 3.20 -> low was 3.20

`product_snapshots` has no product name, so the guard reads the seller's OWN
descriptor out of the storefront slug, and falls back to a corroborated-cluster
rule when the slug is silent.

The hard part is that slug generators MANGLE numbers, and every mangling below is
a real listing of the SAME product as ours — excluding them would move the market
low the wrong way and hide genuinely cheaper competitors:

  ours 4x15g  -> "…لكرات الشعر 415جرام"            (Hobba: 4x15 run together)
  ours 4x14g  -> "…للقطط 4-14جرام", "…414 جم"      (Mowkly, Hobba)
  ours 6x50g  -> "…In-Broth-6.50g…"                 (Petsy)
  ours 7.5kg  -> "…-75كج"                           (Hobba, and their OWN slug)
  ours 1.2L   -> "…-12-لتر"                         (Hobba, Caty)
  ours 1.2kg  -> "…-120-كجم"                        (Mowkly)
  ours 20kg   -> "…-23.6L-20-Kg-…"                  (Petsy: volume AND mass)

So the rule is EXPLICIT, UNAMBIGUOUS, UN-MANGLABLE evidence only.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["DB_NAME"] = "test_iter78_pack_guard"
# Snapshot: sibling test modules reassign DB_NAME at import, so a
# call-time read of the env var can point at ANOTHER suite's database.
_TEST_DB = "test_iter78_pack_guard"
import pack_guard as pg  # noqa: E402
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
USER = {"id": "t", "email": "t@t", "role": "super_admin"}
OWN = "own-store-id"


# ── 1. reading the seller's own descriptor out of a slug ─────────────────────
def test_a_dashed_decimal_is_a_decimal_not_a_pack_of_five():
    s = pg.slug_descriptor(
        "https://petsysa.com/products/Sticks-Atlantic-Salmon-3-5-g-Treats-For-Cats-Kit-Cat")
    assert "3.5g" in s
    assert pg.stated_weight_grams(s) == 3.5      # not 5.0


def test_a_two_digit_second_number_is_a_pack_multiplier():
    """"4-14g" is 4 x 14g, not a 4.14g product — the slug just lost the ×."""
    s = pg.slug_descriptor("https://mowkly.com/products/churu-chicken-cheese-4-14g")
    assert pg.stated_weight_grams(s) == 14.0
    assert pg.slug_pack_reject("Inaba Churu 4 x 14 g", 14.0, s) == (False, None)


def test_arabic_gram_and_kilo_abbreviations_are_understood():
    assert pg.stated_weight_grams(
        pg.slug_descriptor("https://caty-store.com/products/كتكات-اعواد-للقطط-15غ-1")) == 15.0
    assert pg.stated_weight_grams(
        pg.slug_descriptor("https://x.com/products/رمل-قطط-7-5-كغ")) == 7500.0


def test_a_slug_with_two_different_weights_is_ambiguous_not_evidence():
    s = pg.slug_descriptor(
        "https://petsysa.com/products/Cat-Litter-with-Baby-Powder-Scent-23.6L-20-Kg-Beso")
    assert pg.stated_weight_grams(s) is None
    assert pg.slug_pack_reject("Beso Cat Litter Baby Powder 20kg", 20000.0, s) == (False, None)


def test_an_opaque_slug_is_never_evidence():
    s = pg.slug_descriptor("https://hamtaro.sa/en/AzNoKRP")
    assert pg.stated_weight_grams(s) is None
    assert pg.slug_pack_reject("Kit Cat Sticks 15g", 15.0, s) == (False, None)
    assert pg.slug_pack_reject("Kit Cat Sticks 15g", 15.0, "") == (False, None)


# ── 2. what the guard rejects, and what it must NOT ──────────────────────────
KITCAT = "كت كات مكافأة اعواد للقطط السالمون 15جم Kit Cat Sticks 15g"


def test_the_single_sachet_is_rejected():
    for url in ("https://petsysa.com/products/Sticks-Atlantic-Salmon-3-5-g-Treats",
                "https://aleef.com/products/كت-كات-عصي-السلمون-3-5-جرام"):
        rej, why = pg.slug_pack_reject(KITCAT, 15.0, pg.slug_descriptor(url))
        assert rej and why == "slug_weight_3.5g_vs_ours_15g", url


def test_a_dropped_decimal_point_is_not_a_different_product():
    """The mangling that made the guard hide sellers 45% cheaper than us."""
    cases = [
        ("BioSand Cat Litter 7.5kg", 7500.0, "https://hobba.sa/products/رمل-قطط-تكتل-75-كجم"),
        ("Water fountain 1.2L", 1200.0, "https://caty-store.com/products/نافورة-شرب-12-لتر"),
        ("KitCat Dry Food Urinary 1.2kg", 1200.0,
         "https://mowkly.com/products/كت-كات-طعام-جاف-120-كجم"),
    ]
    for name, w, url in cases:
        assert pg.slug_pack_reject(name, w, pg.slug_descriptor(url)) == (False, None), url


def test_a_multipack_on_either_side_disables_the_weight_axis():
    """ours 4x15g vs "415جرام" — the same product, run together by the slug."""
    s = pg.slug_descriptor("https://hobba.sa/products/كت-كات-هريس-دجاج-لكرات-الشعر-415جرام")
    assert pg.stated_weight_grams(s) == 415.0
    assert pg.slug_pack_reject("KitCat Purr Puree chicken 4x15g", 15.0, s) == (False, None)


def test_an_explicit_pack_count_disagreement_is_rejected():
    s = pg.slug_descriptor("https://x.com/products/beso-wet-food-24-x-400g")
    rej, why = pg.slug_pack_reject("Beso Wet Food 6 x 400g", 400.0, s)
    assert rej and why == "slug_pack_qty_24_vs_ours_6"


def test_a_genuinely_different_size_is_still_rejected():
    s = pg.slug_descriptor("https://caty-store.com/products/كت-كات-رمل-كلاسيك-30-كجم")
    rej, why = pg.slug_pack_reject("KitCat MultiCat Sand 20kg", 20000.0, s)
    assert rej and "30000g_vs_ours_20000g" in why


# ── 3. the corroborated-cluster rule ─────────────────────────────────────────
def test_the_toothpaste_case_one_seller_against_us_and_one_other():
    out = pg.cluster_outliers([("mowkly", 23.0), ("panda", 4.3)], own_price=23.45)
    assert set(out) == {"panda"} and out["panda"]["ratio"] == 5.4


def test_the_kitcat_case_one_seller_against_a_six_price_cluster():
    out = pg.cluster_outliers(
        [("mowkly", 10.0), ("panda", 10.0), ("hobba", 10.5), ("hamtaro", 13.98),
         ("caty", 3.2)], own_price=14.0)
    assert set(out) == {"caty"}


def test_a_price_under_three_times_below_is_kept():
    """A 60% discount is a sale, not a pack collision — 3x is the line."""
    assert pg.cluster_outliers([("a", 10.0), ("b", 10.0), ("c", 4.0)], own_price=10.0) == {}


def test_one_reference_price_is_not_a_cluster():
    """Nothing corroborates the high side, so the low is left alone."""
    assert pg.cluster_outliers([("a", 30.0), ("b", 3.0)]) == {}
    assert pg.cluster_outliers([("b", 3.0)], own_price=30.0) == {}


def test_the_dearest_price_is_never_touched():
    out = pg.cluster_outliers([("a", 10.0), ("b", 10.0), ("dear", 90.0)], own_price=10.0)
    assert out == {}


# ── 4. end to end through the Scanner ────────────────────────────────────────
# (sku, our price, our name, [(store, price, slug)])
FIXTURE = [
    ("TOOTHPASTE-45G", 23.45,
     "فريش فريندز معجون اسنان للقطط 45جم Fresh Friends Toothpaste 45g", [
         ("mowkly", 23.0, "https://mowkly.com/products/فريش-فريندز-معجون-اسنان-45جرام"),
         ("panda", 4.3, "https://matjarpanda.com/products/fresh-friends-toothpaste-kit"),
     ]),
    ("KITCAT-15G", 14.0, KITCAT, [
        ("petsy", 10.0, "https://petsysa.com/products/Sticks-Atlantic-Salmon-3-5-g-Treats"),
        ("aleef", 7.5, "https://aleef.com/products/كت-كات-عصي-السلمون-3-5-جرام"),
        ("panda", 10.0, "https://matjarpanda.com/products/kit-cat-stick-atlantic-salmon"),
        ("mowkly", 10.5, "https://mowkly.com/products/كت-كات-اعواد-سلمون"),
        ("caty", 3.2, "https://caty-store.com/products/كتكات-اعواد-للقطط-15غ-1"),
    ]),
    ("LITTER-7-5KG", 46.0, "بايو ساند رمل قطط 7.5كج BioSand Cat Litter 7.5kg", [
        ("hobba", 64.4, "https://hobba.sa/products/بايو-ساند-رمل-تكتل-75-كجم"),
        ("mowkly", 45.99, "https://mowkly.com/products/رمل-بايو-ساند-معطر"),
    ]),
]
STORE_NAMES = {"petsy": "Petsy", "aleef": "Aleef", "panda": "Panda Store",
               "mowkly": "Mowkly", "caty": "Caty", "hobba": "Hobba"}


async def _seed(db):
    for c in ("stores", "my_products", "products", "product_snapshots",
              "sku_sales_daily", "own_store_orders"):
        await db[c].delete_many({})
    await db.stores.insert_many(
        [{"id": OWN, "name": "Pets Houses", "domain": "pets-houses.com",
          "platform": "zid", "is_own_store": True}] +
        [{"id": sid, "name": nm, "domain": f"{sid}.com", "platform": "salla"}
         for sid, nm in STORE_NAMES.items()])
    now = server.datetime.now(server.timezone.utc)
    snaps, mine, prods = [], [], []
    for sku, ours, name, sellers in FIXTURE:
        mine.append({"sku": sku, "price": ours, "name_ar": name, "name_en": name,
                     "price_basis": "storefront_inc_vat", "quantity": 4})
        prods.append({"id": f"p-{sku}", "sku": sku, "name_ar": name, "name_en": name,
                      "category": "cat_food"})
        snaps.append({"id": f"s-{sku}-own", "sku": sku, "store_id": OWN,
                      "store_name": "Pets Houses", "price": ours, "qty_available": 4,
                      "in_stock": True, "confidence_score": 99, "crawled_at": now})
        for sid, price, url in sellers:
            snaps.append({"id": f"s-{sku}-{sid}", "sku": sku, "store_id": sid,
                          "store_name": STORE_NAMES[sid], "price": price,
                          "qty_available": 3, "in_stock": True, "product_url": url,
                          "confidence_score": 99, "crawled_at": now})
    await db.my_products.insert_many(mine)
    await db.products.insert_many(prods)
    await db.product_snapshots.insert_many(snaps)
    server.db = db


class _Agg:
    """FerretDB has no `$first` accumulator, so the endpoint's $group is
    reproduced here (latest snapshot per sku+store, same $match filters) and the
    real loop under test consumes identical rows."""

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
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=server.timezone.utc)
            if ca < since:
                continue
            key = (s["sku"], s["store_id"])
            if key not in latest or ca > latest[key]["crawled_at"]:
                latest[key] = {**s, "crawled_at": ca}
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
    fn = getattr(server.price_opportunities, "__wrapped__", server.price_opportunities)
    real, server.db = server.db, _AggDB(server.db)
    try:
        return await fn(days=14, user=USER)
    finally:
        server.db = real


def _row(out, sku):
    return next((o for o in out["opportunities"] if o["sku"] == sku), None)


def test_end_to_end_the_two_reported_products_report_honest_gaps():
    async def main():
        db = AsyncIOMotorClient(MONGO)[_TEST_DB]
        await _seed(db)
        out = await _scan()
        s = out["summary"]

        # 1. the 445% toothpaste: Panda's 4.30 is 5.4x below us AND Mowkly, so it
        #    stops being "the market low" — and level with Mowkly we are simply
        #    not overpriced any more.
        assert _row(out, "TOOTHPASTE-45G") is None
        excluded = {(x["sku"], x["store_name"]) for x in s["low_outliers_excluded_sample"]}
        assert ("TOOTHPASTE-45G", "Panda Store") in excluded

        # 2. the Kit Cat sticks: the two 3.5g singles go on slug evidence, Caty's
        #    3.20 goes on the cluster rule, and the truthful low is 10.00.
        row = _row(out, "KITCAT-15G")
        assert row["market_lowest"] == 10.0 and row["gap_pct"] == 40.0
        assert row["lowest_store_name"] in ("Panda Store", "Mowkly")
        slugged = {(x["sku"], x["store_name"]) for x in s["slug_pack_mismatch_sample"]}
        assert {("KITCAT-15G", "Petsy"), ("KITCAT-15G", "Aleef")} <= slugged
        assert ("KITCAT-15G", "Caty") in excluded
        # the excluded sellers are gone from the sheet's seller list too, so the
        # chart cannot contradict the market low
        names = {x["store_name"] for x in row["sellers"]}
        assert names == {"Pets Houses", "Panda Store", "Mowkly"}
        assert min(x["price"] for x in row["sellers"]) == row["market_lowest"]

        # 3. the dropped-decimal litter: Hobba stays a real competitor
        assert not any(x["sku"] == "LITTER-7-5KG"
                       for x in s["slug_pack_mismatch_sample"] + s["low_outliers_excluded_sample"])
        assert _row(out, "LITTER-7-5KG") is None       # we are the cheaper one

        # nothing is dropped silently
        assert s["slug_pack_mismatch"] == 2 and s["low_outliers_excluded"] == 2
    asyncio.run(main())
