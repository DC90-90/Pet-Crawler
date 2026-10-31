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


def test_catalogue_groups_every_store_by_barcode_and_marks_mine(monkeypatch):
    import asyncio
    import snapshot_reads
    import uuid
    from datetime import datetime, timedelta, timezone
    from motor.motor_asyncio import AsyncIOMotorClient

    windows, real = [], snapshot_reads.complete_latest

    async def spy(db, pipeline):
        span = pipeline[0]["$match"]["crawled_at"]
        windows.append(span["$lt"] - span["$gte"])
        return await real(db, pipeline)
    monkeypatch.setattr(snapshot_reads, "complete_latest", spy)

    async def run():
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
        db = client[f"test_key_brands_{uuid.uuid4().hex[:8]}"]
        try:
            now = datetime.now(timezone.utc)
            await db.stores.insert_many([{"id": "own", "name": "Pets houses", "is_own_store": True},
                                         {"id": "z", "name": "Zarafa"}, {"id": "l", "name": "Lana Pets"},
                                         {"id": "off", "name": "Closed", "is_active": False}])
            await db.my_products.insert_many([
                {"sku": "8595602581757", "name_ar": "كارني لوف 2 كجم", "price": 60.0},
                {"sku": "8595602581900", "name_en": "Schesir Tuna 85g", "price": 7.0},      # nobody else sells it
                {"sku": "3182550702362", "name_en": "Royal Canin Kitten", "price": 41.0}])  # not a key brand

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
                snap("z", "z4", "Carnilove old", 9.0, barcode="", ago=30),
                # filed under Carnilove by the store; the name does not say it
                {**snap("l", "l2", "طعام قطط بالبط 400 جم", 20.0, barcode=""), "brand": "Carnilove"}])
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
    assert items["gtin:08595602581900"]["own_sells"] and items["gtin:08595602581900"]["competitors"] == 0
    assert items["offer:l2"]["brand"] == "Carnilove"                                          # found by the store's brand
    assert len(out["items"]) == 4                     # no Royal Canin, no closed store, nothing older than the window
    assert {b["brand"]: b["items"] for b in out["brands"]}["Carnilove"] == 2
    assert windows and max(windows) <= timedelta(days=1)   # each read is one store, one day (10 s limit)


def test_a_store_brand_tag_naming_a_key_brand_labels_the_offer():
    from observation_contract import normalize_offer
    row = normalize_offer({"id": 7, "name": "طعام قطط بالبط 2 كجم", "brand": {"name": "LifeCat"}, "price": 30,
                           "currency": "SAR"}, "Zarafa")
    assert row["brand"] == "Life Cat" and row["brand_source"] == "key_brand_name"
    other = normalize_offer({"id": 8, "name": "Cat food", "brand": {"name": "Whiskas"}, "price": 9, "currency": "SAR"}, "Z")
    assert other["brand"] == "Whiskas" and other["brand_source"] == "store_supplied"


def test_the_sweep_stamps_the_brand_page_brand_on_items_already_caught():
    import asyncio
    import crawlers

    class Resp:
        def __init__(self, body, status=200):
            self.status_code, self._body = status, body

        def json(self):
            return self._body

    class Client:
        async def get(self, url, params=None):
            if url.endswith("/brands"):
                return Resp({"data": [{"id": 11, "name": "Carnilove"}, {"id": 12, "name": "Royal Canin"}], "cursor": {}})
            if params and params.get("source") == "brands":
                return Resp({"data": [{"id": 1, "name": "طعام قطط بالبط"}, {"id": 2, "name": "Carnilove Salmon"}], "cursor": {}})
            return Resp({"data": [{"id": 3, "name": "Royal Canin Kitten"}], "cursor": {}})   # search: off-brand only

    crawlers.SALLA_SWEEP_PAUSE = (0, 0)
    caught = [{"id": 1, "name": "طعام قطط بالبط"}]
    seen, log = {1}, {"endpoints_tried": []}
    added = asyncio.run(crawlers._salla_key_brand_sweep({"name": "S"}, Client(), seen, caught, log))
    assert caught[0]["brand"] == {"name": "Carnilove"}            # already caught, now labelled
    assert added == {"Carnilove": 1} and [c["id"] for c in caught] == [1, 2]
    # Every brand page is read (Royal Canin too); the key brand, read first, names the item.
    assert "brand_pages=2" in log["endpoints_tried"][-1]["error"]
    assert caught[0]["_brand_page"] == "Carnilove"


def test_coverage_row_counts_and_explains_every_missing_item():
    listed = {"1": {"brand": "Kit Cat", "name": "a"}, "2": {"brand": "Kit Cat", "name": "b"},
              "3": {"brand": "Beso", "name": "c"}}
    row = kb.coverage_row(listed, seen={"1"}, known={"1", "2"})
    assert row["store_lists"] == 3 and row["in_daleel"] == 1
    assert row["brands"]["Kit Cat"]["missing"][0]["why"] == "seen before, not this week"
    assert row["brands"]["Beso"]["missing"][0]["why"] == "never collected"


def test_zarafa_skus_carry_the_barcode_before_the_store_number():
    """27 Oct 2026: Zarafa lists Taste of the Wild as "74198612383-341666817"
    (UPC 074198612383); the client saw these as "not sold by me"."""
    from observation_contract import sku_gtin, normalize_offer
    from price_cohort import identity_keys
    assert sku_gtin("74198612383-341666817") == "00074198612383"
    for risky in ("9003579308936-6", "9003579308936-12", "12345678-BLK", "074198614301SandF",
                  "74198612383-1234", "1234567890123-1234567", "", None):
        assert sku_gtin(risky) is None, risky                 # pack tails, merchant codes, bad check digit
    assert identity_keys({"sku": "74198612383-341666817", "barcode": ""}) == {"00074198612383"}
    assert identity_keys({"sku": "074198612383"}) == identity_keys({"sku": "74198612383-341666817"})
    row = normalize_offer({"id": 1, "name": "Taste Of The Wild Cat Dry Food", "sku": "74198612383-341666817",
                           "price": 87, "currency": "SAR"}, "Zarafa")
    from observation_contract import gtin
    assert gtin(row["barcode"]) == "00074198612383"


def test_a_competitor_offer_joins_my_product_through_the_matcher(monkeypatch):
    import asyncio
    import uuid
    from datetime import datetime, timedelta, timezone
    from motor.motor_asyncio import AsyncIOMotorClient

    async def fake_matches(db, own_price_fn, own_id):
        return {"zarafa-offer": "MY-TOTW"}                     # matched by name/confirmed, no barcode
    monkeypatch.setattr(kb, "_own_matches", fake_matches)

    async def run():
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
        db = client[f"test_kb_match_{uuid.uuid4().hex[:8]}"]
        try:
            now = datetime.now(timezone.utc)
            await db.stores.insert_many([{"id": "own", "name": "Pets houses", "is_own_store": True},
                                         {"id": "z", "name": "Zarafa"}])
            await db.my_products.insert_one({"sku": "MY-TOTW", "name_ar": "تيست اوف ذا وايلد قطط", "price": 95.0})
            await db.product_snapshots.insert_one({
                "observation_version": 2, "is_synthetic": False, "store_id": "z", "offer_id": "zarafa-offer",
                "sku": "ZR-1", "barcode": "", "name_en": "Taste Of The Wild Cat Dry Food", "price": 87.0,
                "in_stock": True, "crawled_at": now - timedelta(hours=3)})
            return await kb.catalogue(db, own_price_fn=lambda p: p.get("price"))
        finally:
            await client.drop_database(db.name)
            client.close()

    out = asyncio.run(run())
    assert len(out["items"]) == 1
    item = out["items"][0]
    assert item["own_sells"] and item["own_price"] == 95.0 and item["cheapest_store"] == "Zarafa"
    assert item["name_ar"] == "تيست اوف ذا وايلد قطط"          # my own name leads the row


def test_a_listing_without_a_barcode_links_to_my_product_only_when_its_name_states_the_same_product():
    sig = kb.name_signature
    mine = [("beso-tuna-gravy-24", sig("Beso Tuna in Gravy - 85g - Carton for 24 pcs", "")),
            ("beso-tuna-gravy", sig("Beso Tuna in Gravy - 85g", "")),
            ("beso-tuna-jelly-24", sig("Beso Wet Food Tuna in Jelly - 85g - Carton for 24 pcs", "")),
            ("carni-kitten-6", sig("Carnilove Dry Food for Kittens Salmon & Turkey 6kg", "")),
            ("beso-chicken-7", sig("Beso Adult Cat Food Rich in Chicken - 7kg", "بيسو طعام جاف للقطط البالغة بالدجاج - 7 كغ"))]
    # Arabic against English, the pack and every flavour agreeing (31 Oct 2026 samples).
    assert kb.name_match(sig("شرائح التونة بالمرق طعام رطب للقطط ــ بيسو 85غ - كرتون 24 حبه"), mine) == "beso-tuna-gravy-24"
    assert kb.name_match(sig("شرائح التونة بالمرق طعام رطب للقطط ــ بيسو 85غ - حبه"), mine) == "beso-tuna-gravy"
    assert kb.name_match(sig("كارنيلوف طعام جاف للقطط الصغيرة من السلمون والديك الرومي - 6 كيلوجرام"), mine) == "carni-kitten-6"
    # Anything that differs leaves it unlinked.
    assert kb.name_match(sig("شرائح التونة والربيان بالمرق ــ بيسو 85غ - كرتون 24 حبه"), mine) is None   # + shrimp
    assert kb.name_match(sig("شرائح التونة بالمرق ــ بيسو 85غ - كرتون 12 حبه"), mine) is None             # 12, not 24
    assert kb.name_match(sig("شرائح التونة بالمرق ــ بيسو 400غ"), mine) is None                           # size
    assert kb.name_match(sig("بيسو طعام جاف للقطط البالغة مكس الدجاج مع اللحم - 7 كغ"), mine) is None       # + meat
    assert kb.name_match(sig("بيسو طعام للقطط"), mine) is None                                             # no size
    # Two of my products fit: no guess.
    twins = [("a", sig("Beso Pate Beef Adult 400g", "")), ("b", sig("Beso Pate Beef Adult - 400 g", ""))]
    assert kb.name_match(sig("باتيه اللحم البقري للقطط البالغة (400 جرام) ـــ بيسو"), twins) is None


def test_the_catalogue_marks_a_name_link_and_never_links_two_barcodes(monkeypatch):
    import asyncio
    import uuid
    from datetime import datetime, timedelta, timezone
    from motor.motor_asyncio import AsyncIOMotorClient

    async def run():
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
        db = client[f"test_key_brands_{uuid.uuid4().hex[:8]}"]
        try:
            now = datetime.now(timezone.utc) - timedelta(hours=2)
            await db.stores.insert_many([{"id": "own", "name": "Pets houses", "is_own_store": True},
                                         {"id": "h", "name": "Hobba"}])
            await db.my_products.insert_many([
                {"sku": "BESO-TG-85", "name_en": "Beso Tuna in Gravy - 85g", "price": 6.0},
                {"sku": "8681299500017", "barcode": "8681299500017", "name_en": "Beso Chicken in Gravy - 85g", "price": 6.0}])

            def snap(offer, name, barcode=""):
                return {"observation_version": 2, "is_synthetic": False, "store_id": "h", "offer_id": offer, "sku": offer,
                        "barcode": barcode, "name_ar": name, "price": 5.5, "in_stock": True, "crawled_at": now}
            await db.product_snapshots.insert_many([
                snap("h1", "شرائح التونة بالمرق طعام رطب للقطط ــ بيسو 85غ"),
                snap("h2", "شرائح الدجاج بالمرق طعام رطب للقطط ــ بيسو 85غ", barcode="8681299500024")])  # another barcode
            return await kb.catalogue(db, own_price_fn=lambda p: p.get("price"))
        finally:
            await client.drop_database(db.name)
            client.close()

    out = asyncio.run(run())
    tuna = next(i for i in out["items"] if (i["name_en"] or "").startswith("Beso Tuna"))
    assert tuna["own_sells"] and {o["store_name"]: o.get("match") for o in tuna["offers"]} == {"Hobba": "name", "Pets houses": None}
    other = next(i for i in out["items"] if i["key"] == "gtin:08681299500024")
    assert not other["own_sells"]                    # my product has a different barcode: a different product
