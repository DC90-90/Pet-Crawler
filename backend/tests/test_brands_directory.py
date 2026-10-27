"""Every product gets a brand when any store's evidence names one (27 Oct 2026:
"Felyn Go Smart Cat Litter Box" showed brand "—" in Products I don't sell)."""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import brands  # noqa: E402


def setup_function(_):
    brands.install({"06287050381356": "Felyn Go", "08859601044294": "Pramy"}, ["Felyn Go", "Pramy", "Royal Canin", "Meow"])


def test_order_key_brand_then_barcode_then_name_then_tag():
    assert brands.brand_for("كيت كات بيوريه", None, ["06287050381356"]) == ("Kit Cat", "key_brand_name")
    assert brands.brand_for("صندوق رمل ذكي", None, ["6287050381356"]) == ("Felyn Go", "same_barcode")
    assert brands.brand_for(None, "Felyn Go Smart Cat Litter Box", [])[0] == "Felyn Go"
    assert brands.brand_for(None, "royal canin kitten 2kg", [])[0] == "Royal Canin"     # case and canonical name
    assert brands.brand_for(None, "Some Unknown Toy", [], existing="Zolux") == ("Zolux", "store_tag")
    assert brands.brand_for(None, "Some Unknown Toy", []) == (None, None)


def test_names_match_whole_words_only():
    assert brands.brand_for(None, "Homeowner dog bed", [])[0] is None      # "Meow" inside a word is not a brand
    assert brands.brand_for(None, "Meow cat treats", [])[0] == "Meow"


def test_product_words_are_never_brands():
    brands.install({}, ["Cat", "Food", "قطط", "No Brand", "AB"])
    assert brands.brand_for(None, "Cat food bowl", []) == (None, None)
    assert brands.brand_for(None, "x", [], existing="Other") == (None, None)


def test_refresh_builds_from_store_given_brands():
    from motor.motor_asyncio import AsyncIOMotorClient

    async def run():
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
        db = client[f"test_brands_{uuid.uuid4().hex[:8]}"]
        try:
            await db.products.insert_many([
                {"brand": "Felyn Go", "brand_source": "store_supplied", "barcode": "6287050381356"},
                {"brand": "Felyn Go", "brand_source": "store_supplied", "sku": "6287050381363"},
                {"brand": "Guess", "brand_source": None, "barcode": "5000000000005"},          # name guess: not evidence
                {"brand": "Cat", "brand_source": "store_supplied", "barcode": "5000000000012"}])  # product word
            return await brands.refresh(db)
        finally:
            await client.drop_database(db.name)
            client.close()
    out = asyncio.run(run())
    assert out["barcodes"] == 2
    assert brands.brand_for("منتج", None, ["6287050381363"]) == ("Felyn Go", "same_barcode")
    assert brands.brand_for(None, "x", ["5000000000005"]) == (None, None)


def test_a_brand_only_moves_up_the_evidence():
    from crawlers import _brand_upgrade
    store = {"brand": "Felyn Go", "brand_source": "store_supplied"}
    assert _brand_upgrade({"brand": "", "brand_source": None}, store)
    assert _brand_upgrade({"brand": "Almo", "brand_source": "store_supplied"}, store)
    assert not _brand_upgrade({"brand": "Kit Cat", "brand_source": "key_brand_name"}, store)
    assert not _brand_upgrade({"brand": "X", "brand_source": "reviewed"}, {"brand": "Y", "brand_source": "key_brand_name"})
    assert not _brand_upgrade({"brand": "Felyn Go", "brand_source": None}, {"brand": "Felyn Go", "brand_source": "store_supplied"})
    assert not _brand_upgrade({"brand": "", "brand_source": None}, {"brand": "Z", "brand_source": None})
