"""Offline reproduction using the ZIP's actual matcher; no network or DB writes."""
import asyncio
import json
import sys
from pathlib import Path
import sys
ROOT = Path(sys.argv[1]).resolve()

sys.path.insert(0, str(ROOT / "backend"))
import matcher
import seller_set

class Cursor:
    def __init__(self, rows): self.rows = rows
    def __aiter__(self):
        async def generate():
            for row in self.rows: yield row
        return generate()

class Collection:
    def __init__(self, rows=()): self.rows = rows
    def find(self, query, projection=None):
        return Cursor([r for r in self.rows if all(r.get(k) == v for k, v in query.items())])

class DB:
    def __init__(self, confirmed=(), blacklist=()):
        self.product_matches = Collection(confirmed)
        self.match_blacklist = Collection(blacklist)

def snap(sku, store, price=100, barcode=None, **kwargs):
    return {"sku": sku, "store_id": store, "store_name": store, "price": price,
            "barcode": barcode, "confidence_score": 95, **kwargs}

MINE = {"sku": "ABC-01", "barcode": "3182550702263", "price": 100,
        "name_en": "Royal Canin Adult Cat Food 2kg"}

async def match(snaps, products, mine=None, db=None):
    return await matcher.match_my_product(db or DB(), mine or MINE, snaps, products, "own")

async def main():
    results = {}
    # An unrelated merchant product shares only an internal SKU; barcodes disagree.
    unrelated = {"sku": "ABC-01", "barcode": "052742059518", "name_en": "Hills Dog Food 2kg"}
    out = await match([snap("ABC-01", "competitor", barcode=unrelated["barcode"])], {"ABC-01": unrelated})
    results["conflicting_barcode_and_brand_still_sku_match"] = out
    assert len(out) == 1 and out[0]["confidence"] == 95

    # L2 deduplicates by SKU before store, dropping a genuine second retailer.
    out = await match([snap("ABC-01", "first"), snap("ABC-01", "second")],
                      {"ABC-01": {"name_en": MINE["name_en"]}})
    results["same_sku_two_stores_only_one_retained"] = [r["competitor_store_id"] for r in out]
    assert len(out) == 1

    # A barcode success causes a whole-product early return before checking L2.
    out = await match([snap("BARCODE-LINK", "barcode-store", barcode=MINE["barcode"]),
                       snap("ABC-01", "sku-store")],
                      {"BARCODE-LINK": {"name_en": MINE["name_en"]},
                       "ABC-01": {"name_en": MINE["name_en"]}})
    results["barcode_match_hides_other_store_sku_match"] = [r["competitor_store_id"] for r in out]
    assert results["barcode_match_hides_other_store_sku_match"] == ["barcode-store"]

    # Real per-store barcode disagrees; global product-row barcode still matches.
    out = await match([snap("C1", "competitor", barcode="052742059518")],
                      {"C1": {"barcode": MINE["barcode"], "name_en": MINE["name_en"]}})
    results["global_catalog_barcode_overrides_conflicting_store_observation"] = out
    assert len(out) == 1 and out[0]["confidence"] == 99

    # One pair's manual approval is applied to every retailer sharing its SKU.
    db = DB(confirmed=[{"my_sku": "ABC-01", "competitor_sku": "C1",
                        "competitor_store_id": "approved-store", "manually_confirmed": True}])
    out = await match([snap("C1", "unapproved-store", price=10, barcode=MINE["barcode"])],
                      {"C1": {"name_en": MINE["name_en"]}}, db=db)
    results["manual_confirmation_leaks_to_another_store"] = out
    assert len(out) == 1 and out[0]["confidence"] == 100

    # No input confidence floor in the actual matcher.
    out = await match([snap("C1", "low-quality-store", barcode=MINE["barcode"], confidence_score=1)],
                      {"C1": {"name_en": MINE["name_en"]}})
    results["snapshot_confidence_1_becomes_match_confidence_99"] = out
    assert len(out) == 1 and out[0]["confidence"] == 99

    # The report says variant arrays match; this version never reads them.
    out = await match([snap("C1", "variant-store", variant_barcodes=[MINE["barcode"]])],
                      {"C1": {"name_en": MINE["name_en"], "variant_barcodes": [MINE["barcode"]]}})
    results["variant_barcode_array_uses_parent_price"] = out
    assert len(out) == 1 and out[0]["competitor_price"] == 100

    # Failed extraction yields None; matcher crashes instead of quarantining it.
    try:
        await match([snap("C1", "missing-price-store", price=None, barcode=MINE["barcode"])],
                    {"C1": {"name_en": MINE["name_en"]}})
    except TypeError as exc:
        results["missing_price_crashes_matcher"] = type(exc).__name__ + ": " + str(exc)
    else:
        raise AssertionError("Expected crash on missing price")

    results["unknown_pack_asymmetry"] = {
        "single_vs_unknown_carton": matcher._pack_compatible("Wet food 400g", "Wet food 400g carton"),
        "unknown_carton_vs_single": matcher._pack_compatible("Wet food 400g carton", "Wet food 400g"),
    }
    assert results["unknown_pack_asymmetry"] == {
        "single_vs_unknown_carton": True, "unknown_carton_vs_single": False}
    results["detail_selector_unscoped_base_sku"] = seller_set.snapshot_or_clauses("ABC-01", {})
    results["six_day_old_price_status"] = seller_set.freshness_labels(
        matcher.datetime.now(matcher.timezone.utc) - matcher.timedelta(days=6))
    assert results["six_day_old_price_status"]["data_status"] == "live"
    print(json.dumps(results, indent=2, ensure_ascii=False, default=str))

if __name__ == "__main__": asyncio.run(main())
