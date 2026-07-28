"""iter61 — the matcher must normalise barcodes the way iter47 does.

Production: Zarafa matches on some products (Signor Gatto) and is absent from
others (Hills GI Biome 052742059518, RC Sensible 3182550702263) despite selling
them. Not a crawl gap, not a display filter — a MATCH failure.

Two defects, both in the barcode key space:

1. Level 1 intersected RAW strings::

       {"052742059518"} & {"52742059518"} == set()

   The same GTIN written as UPC-A and as EAN. That is precisely the pair iter47
   was written to fix, but iter47's normalization lived in crawlers.py and was
   reachable only from the own-store price-resolution path. The matcher never
   called it. Same defect class, different cost: iter47 cost price accuracy,
   this costs SELLER COVERAGE — a real competitor drops off the product.

2. The competitor side had no barcode to compare against at all.
   _normalize_raw_product has extracted one since iter35 (variant-aware, from
   skus[].barcode/gtin/mpn) and BOTH write sites dropped it, so Level 1 could
   only fire when a store happened to type a bare EAN into its SKU field. Salla
   stores publish merchant-internal SKUs, which is why Zarafa mostly missed.

The fix widens the KEY SPACE only. Every guard from iter51-53 still runs on each
surviving candidate, and the tests at the bottom pin that: a 6x price gap with
no pack corroboration is still rejected, a 24-pack still cannot match a single
tin, and short numeric SKUs are still not barcode candidates.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_matcher_norm")
import crawlers  # noqa: E402
import matcher  # noqa: E402
from core.utils import canonical_barcode  # noqa: E402

HILLS_OURS = "052742059518"      # UPC-A, leading zero
HILLS_THEIRS = "52742059518"     # same GTIN, zero dropped
RC = "3182550702263"


def _snap(sku, store_id="zarafa", price=163.0, barcode=None):
    s = {"sku": sku, "store_id": store_id, "store_name": "Zarafa",
         "price": price, "qty_available": 5, "in_stock": True,
         "source_tier": 1, "crawled_at": None}
    if barcode is not None:
        s["barcode"] = barcode
    return s


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __aiter__(self):
        async def gen():
            for r in self._rows:
                yield r
        return gen()


class _FakeColl:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def find(self, *a, **k):
        return _FakeCursor(self._rows)

    async def find_one(self, *a, **k):
        return self._rows[0] if self._rows else None


class _FakeDB:
    """match_my_product only reads match_blacklist and product_matches when it
    is handed pre-built lookups, which every test here does."""
    match_blacklist = _FakeColl()
    product_matches = _FakeColl()


async def _match(my_product, snapshots, comp_products):
    return await matcher.match_my_product(
        _FakeDB(), my_product, comp_snapshots=snapshots,
        comp_products=comp_products, own_store_id="own")


# ── Case 1: Hills GI Biome ──────────────────────────────────────────────────

def test_hills_upca_vs_ean_now_links():
    """052742059518 (ours) vs 52742059518 (Zarafa) — the exact reported pair."""
    async def main():
        mine = {"sku": HILLS_OURS, "barcode": HILLS_OURS, "price": 170.0,
                "name_en": "Hills GI Biome Cat 1.5kg", "name_ar": "هيلز"}
        snaps = [_snap(HILLS_THEIRS)]
        prods = {HILLS_THEIRS: {"sku": HILLS_THEIRS,
                                "name_en": "Hills Gastrointestinal Biome Cat 1.5kg",
                                "name_ar": "هيلز"}}
        out = await _match(mine, snaps, prods)
        assert len(out) == 1, out
        assert out[0]["competitor_sku"] == HILLS_THEIRS
        assert out[0]["match_method"] == "barcode"          # contract unchanged
        assert out[0]["barcode_key"] == "gtin14"           # recovered by normalisation
    asyncio.run(main())


def test_hills_key_mismatch_is_exactly_the_leading_zero():
    """The mechanical reason the old matcher missed: raw sets are disjoint,
    GTIN-14 sets are not."""
    assert HILLS_OURS != HILLS_THEIRS
    assert {HILLS_OURS} & {HILLS_THEIRS} == set()
    assert canonical_barcode(HILLS_OURS) == canonical_barcode(HILLS_THEIRS) == "00052742059518"
    assert (matcher._barcode_key_set(barcodes=(HILLS_OURS,))
            & matcher._barcode_key_set(skus=(HILLS_THEIRS,)))


# ── Case 2: Royal Canin Sensible 33 ─────────────────────────────────────────

def test_rc_sensible_links_through_the_competitor_snapshot_barcode():
    """Zarafa publishes a Salla product code as its SKU, so the ONLY bridge is
    the barcode the crawler used to discard."""
    async def main():
        mine = {"sku": RC, "barcode": RC, "price": 129.0,
                "name_en": "Royal Canin Sensible 33 Cat 2kg", "name_ar": "رويال كانين"}
        snaps = [_snap("SL-40917", price=118.0, barcode=RC)]
        prods = {"SL-40917": {"sku": "SL-40917",
                              "name_en": "Royal Canin Sensible 33 Adult Cat 2kg",
                              "name_ar": "رويال كانين"}}
        out = await _match(mine, snaps, prods)
        assert len(out) == 1, out
        assert out[0]["competitor_sku"] == "SL-40917"
        assert out[0]["match_method"] == "barcode"
        assert out[0]["barcode_key"] == "literal"          # raw strings already agreed
    asyncio.run(main())


def test_without_the_persisted_barcode_the_same_pair_still_misses():
    """Pins WHY a re-crawl is required: normalisation alone cannot bridge a
    merchant-internal SKU. This is the pre-iter61 data shape."""
    async def main():
        mine = {"sku": RC, "barcode": RC, "price": 129.0,
                "name_en": "Royal Canin Sensible 33 Cat 2kg", "name_ar": "رويال"}
        snaps = [_snap("SL-40917", price=118.0)]            # no barcode captured
        prods = {"SL-40917": {"sku": "SL-40917", "name_en": "Royal Canin Sensible 33",
                              "name_ar": "رويال"}}
        assert await _match(mine, snaps, prods) == []
    asyncio.run(main())


def test_cross_match_works_in_both_directions():
    """our barcode vs their SKU, and our SKU vs their barcode."""
    async def main():
        their_sku_is_our_barcode = await _match(
            {"sku": "PH-991", "barcode": HILLS_OURS, "price": 170.0,
             "name_en": "Hills GI Biome 1.5kg", "name_ar": "هيلز"},
            [_snap(HILLS_THEIRS)],
            {HILLS_THEIRS: {"sku": HILLS_THEIRS, "name_en": "Hills GI Biome 1.5kg", "name_ar": "هيلز"}})
        assert len(their_sku_is_our_barcode) == 1

        our_sku_is_their_barcode = await _match(
            {"sku": HILLS_OURS, "barcode": "", "price": 170.0,
             "name_en": "Hills GI Biome 1.5kg", "name_ar": "هيلز"},
            [_snap("SL-88213", barcode=HILLS_THEIRS)],
            {"SL-88213": {"sku": "SL-88213", "name_en": "Hills GI Biome 1.5kg", "name_ar": "هيلز"}})
        assert len(our_sku_is_their_barcode) == 1
    asyncio.run(main())


# ── iter47 parity: one normalization, both paths ────────────────────────────

def test_matcher_and_crawler_agree_on_the_canonical_key():
    """Item 3 — the two paths must not have divergent normalisation."""
    for v in (HILLS_OURS, HILLS_THEIRS, RC, "9003579308936carton"):
        from_crawler = set(crawlers.barcode_keys(v))
        from_matcher = matcher._barcode_key_set(barcodes=(v,))
        assert canonical_barcode(v) in from_crawler
        assert canonical_barcode(v) in from_matcher
    assert crawlers.barcode_keys is not None      # still importable under the old name


def test_variant_suffix_is_canonicalised_from_a_barcode_field_only():
    """iter45's "…carton" suffix belongs to barcode fields. A merchant SKU with
    a suffix must NOT be read as a GTIN, or every store's internal numbering
    becomes a key."""
    assert matcher._barcode_key_set(barcodes=("9003579308936carton",)) == {"09003579308936"}
    assert matcher._barcode_key_set(skus=("9003579308936carton",)) == set()
    assert matcher._barcode_key_set(skus=("12345678-BLK",)) == set()


def test_short_numeric_skus_are_never_barcode_candidates():
    for short in ("15", "4021", "1234567"):
        assert matcher._barcode_key_set(skus=(short,)) == set(), short
        assert matcher._barcode_key_set(barcodes=(short,)) == set(), short


def test_distinct_eans_stay_distinct():
    a, b = "5011792007325", "5011792007326"
    assert not (matcher._barcode_key_set(barcodes=(a,)) & matcher._barcode_key_set(barcodes=(b,)))
    # 8 vs 9 digits: padding must not make these collide
    assert not (matcher._barcode_key_set(barcodes=("12345678",))
                & matcher._barcode_key_set(barcodes=("123456780",)))


# ── The crawler must stop discarding the barcode ────────────────────────────

class _RecordingColl:
    def __init__(self, existing=None):
        self.existing = existing
        self.inserted, self.updates = [], []

    async def find_one(self, *a, **k):
        return self.existing

    async def insert_one(self, doc):
        self.inserted.append(doc)

    async def update_one(self, q, upd):
        self.updates.append(upd.get("$set", {}))


class _RecordingDB:
    def __init__(self, existing=None):
        self.products = _RecordingColl(existing)
        self.product_snapshots = _RecordingColl()


RAW = {"id": 1694697895, "name": "Hills GI Biome Cat 1.5kg", "sku": "SL-88213",
       "price": {"amount": 163.0, "currency": "SAR"}, "quantity": 5,
       "skus": [{"barcode": HILLS_THEIRS, "price": {"amount": 163.0}}]}
STORE = {"id": "zarafa", "name": "Zarafa", "domain": "zarafaksa.com"}


def test_crawler_persists_the_competitor_barcode_to_both_collections():
    async def main():
        db = _RecordingDB(existing=None)
        now = matcher.datetime.now(matcher.timezone.utc)
        assert crawlers._normalize_raw_product(RAW, "Zarafa")["barcode"] == HILLS_THEIRS
        await crawlers.process_crawled_products(db, STORE, [RAW], now)
        assert db.products.inserted[0]["barcode"] == HILLS_THEIRS
        assert db.product_snapshots.inserted[0]["barcode"] == HILLS_THEIRS
    asyncio.run(main())


def test_crawler_backfills_the_barcode_onto_an_existing_product_row():
    async def main():
        db = _RecordingDB(existing={"id": "p1", "sku": "SL-88213", "subcategory": None})
        now = matcher.datetime.now(matcher.timezone.utc)
        await crawlers.process_crawled_products(db, STORE, [RAW], now)
        assert db.products.updates[0].get("barcode") == HILLS_THEIRS
    asyncio.run(main())


def test_crawler_never_overwrites_a_barcode_we_already_hold():
    async def main():
        db = _RecordingDB(existing={"id": "p1", "sku": "SL-88213",
                                    "barcode": "9999999999999", "subcategory": None})
        now = matcher.datetime.now(matcher.timezone.utc)
        await crawlers.process_crawled_products(db, STORE, [RAW], now)
        assert all("barcode" not in u for u in db.products.updates)
    asyncio.run(main())


# ── The iter51-53 guards are NOT weakened ───────────────────────────────────

def test_six_times_price_gap_still_blocks_a_normalised_match():
    """iter53 — the widened key space must not become a way around the guard."""
    async def main():
        mine = {"sku": "5011792007325", "barcode": "5011792007325", "price": 208.0,
                "name_en": "Butcher's Venison in Jelly 400g", "name_ar": "بوتشرز"}
        snaps = [_snap("05011792007325", price=8.10)]       # 25x gap, same GTIN
        prods = {"05011792007325": {"sku": "05011792007325",
                                    "name_en": "Butcher's Venison Jelly 400g tin",
                                    "name_ar": "بوتشرز علبة"}}
        assert await _match(mine, snaps, prods) == []
    asyncio.run(main())


def test_pack_mismatch_still_blocks_a_normalised_match():
    """iter51/52 — a carton and a single tin share the unit EAN."""
    async def main():
        mine = {"sku": "5011792007325", "barcode": "5011792007325", "price": 208.0,
                "name_en": "Butcher's Venison in Jelly 400g Pack of 24", "name_ar": "بوتشرز"}
        snaps = [_snap("05011792007325", price=190.0)]      # <6x, so only pack can block
        prods = {"05011792007325": {"sku": "05011792007325",
                                    "name_en": "Butcher's Venison in Jelly 400g single tin",
                                    "name_ar": "بوتشرز"}}
        assert await _match(mine, snaps, prods) == []
    asyncio.run(main())


def test_weight_mismatch_still_blocks_a_normalised_match():
    async def main():
        mine = {"sku": "3182550702263", "barcode": "3182550702263", "price": 129.0,
                "name_en": "Royal Canin Sensible 33 Cat 2kg", "name_ar": "رويال"}
        snaps = [_snap("03182550702263", price=129.0)]
        prods = {"03182550702263": {"sku": "03182550702263",
                                    "name_en": "Royal Canin Sensible 33 Cat 10kg",
                                    "name_ar": "رويال"}}
        assert await _match(mine, snaps, prods) == []
    asyncio.run(main())


def test_a_legitimate_four_times_discount_still_matches():
    """The iter53 control case: 118 vs 466 is ~4x, under the 6x threshold, and
    must survive — hiding a real competitor discount is the worse error."""
    async def main():
        mine = {"sku": "3182550702263", "barcode": "3182550702263", "price": 466.0,
                "name_en": "Royal Canin Sensible 33 Cat 2kg", "name_ar": "رويال"}
        snaps = [_snap("03182550702263", price=118.0)]
        prods = {"03182550702263": {"sku": "03182550702263",
                                    "name_en": "Royal Canin Sensible 33 Adult Cat 2kg",
                                    "name_ar": "رويال كانين"}}
        assert len(await _match(mine, snaps, prods)) == 1
    asyncio.run(main())


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
