"""The client's key brands are recognised in every store's names (21 Oct 2026)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import key_brands as kb  # noqa: E402


def test_every_key_brand_in_latin_and_arabic():
    cases = {
        "Kit Cat Purr Puree Cat Treats with Salmon- 4 Sachets*15g": "Kit Cat", "كيت كات بيوريه سلمون": "Kit Cat",
        "طعام جاف كارني لوف للقطط 2 كجم": "Carnilove", "Carnilove Salmon Adult 1.5kg": "Carnilove",
        "Life Cat Wet Food Tuna 85g": "Life Cat", "لايف كات تونة": "Life Cat",
        "Taste Of The Wild High Prairie": "Taste of the Wild", "Applaws Tin Tuna 70g": "Applaws",
        "ابلاوز تونة": "Applaws", "Schesir after dark": "Schesir", "GimCat Malt-Soft Extra": "GimCat",
        "جيم كات معجون": "GimCat", "Beso cat litter 10L": "Beso", "بيسو رمل قطط": "Beso",
        "Canvit Biotin 100g": "Canvit", "Farmina N&D Pumpkin Lamb": "Farmina", "ان اند دي قطط": "Farmina",
        "انترساند رمل": "Intersand", "Kitcat soya clump": "Kit Cat",
    }
    for name, brand in cases.items():
        assert kb.brand_in_name(name) == brand, name


def test_other_brands_and_words_are_not_key_brands():
    for name in ("Royal Canin Kitten 2kg", "Kitten food chicken", "Whiskas pouch", "", None):
        assert kb.brand_in_name(name) is None


def test_the_name_wins_over_a_wrong_store_tag():
    from crawlers import extract_brand_smart
    assert extract_brand_smart("", "Kit Cat Hairball Powder", existing="Almo") == "Kit Cat"


def test_items_group_by_barcode_else_by_offer():
    assert kb._group_key({"barcode": "8595602581757", "offer_id": "x"}) == "gtin:08595602581757"
    assert kb._group_key({"barcode": "", "sku": "ABC-1", "offer_id": "x"}) == "offer:x"


def test_the_search_terms_find_the_brand_they_search_for():
    for brand, terms in kb.SEARCH_TERMS.items():
        assert brand in kb.KEY_BRANDS
        for t in terms:
            if t != "N&D":
                assert kb.brand_in_name(t) == brand, t


def test_catalogue_groups_every_store_by_barcode_and_marks_mine():
    import asyncio
    import uuid
    from datetime import datetime, timedelta, timezone
    from motor.motor_asyncio import AsyncIOMotorClient

    async def run():
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
        db = client[f"test_key_brands_{uuid.uuid4().hex[:8]}"]
        try:
            now = datetime.now(timezone.utc)
            await db.stores.insert_many([{"id": "own", "name": "Pets houses", "is_own_store": True},
                                         {"id": "z", "name": "Zarafa"}, {"id": "l", "name": "Lana Pets"},
                                         {"id": "off", "name": "Closed", "is_active": False}])
            await db.products.insert_one({"store_id": "own", "sku": "8595602581757", "price": 60.0})

            def snap(store, offer, name, price, stock=True, barcode="8595602581757", ago=1):
                return {"observation_version": 2, "is_synthetic": False, "store_id": store, "offer_id": offer,
                        "sku": barcode, "barcode": barcode, "name_ar": name, "name_en": name, "price": price,
                        "in_stock": stock, "crawled_at": now - timedelta(days=ago)}
            await db.product_snapshots.insert_many([
                snap("z", "z1", "كارني لوف قطط 2 كجم", 55.0), snap("z", "z1", "كارني لوف قطط 2 كجم", 50.0, ago=3),
                snap("l", "l1", "Carnilove Cat 2kg", 52.0, stock=False),
                snap("own", "o1", "Carnilove Cat 2kg", 61.0),
                snap("z", "z2", "Royal Canin Kitten", 40.0, barcode="3182550702362"),
                snap("z", "z3", "Kit Cat Hairball 30x5g", 30.0, barcode=""),
                snap("off", "c1", "Carnilove Cat 2kg", 10.0),
                snap("z", "z4", "Carnilove old", 9.0, barcode="", ago=30)])
            return await kb.catalogue(db, own_price_fn=lambda p: p.get("price"))
        finally:
            await client.drop_database(db.name)
            client.close()

    out = asyncio.run(run())
    items = {i["key"]: i for i in out["items"]}
    carni = items["gtin:08595602581757"]
    assert carni["brand"] == "Carnilove" and carni["own_sells"] and carni["own_price"] == 60.0   # the shelf rule, not the snapshot
    assert {o["store_name"]: o["price"] for o in carni["offers"]} == {"Zarafa": 55.0, "Lana Pets": 52.0, "Pets houses": 60.0}
    assert carni["cheapest_store"] == "Zarafa" and carni["own_vs_cheapest_pct"] == 9.1     # Lana is out of stock
    assert any(i["brand"] == "Kit Cat" and not i["own_sells"] for i in out["items"])         # an item I don't sell
    assert len(out["items"]) == 2                     # no Royal Canin, no closed store, nothing older than the window
    assert {b["brand"]: b["items"] for b in out["brands"]}["Carnilove"] == 1
