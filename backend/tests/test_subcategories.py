"""iter36 — food subcategory classifier (dry / wet / treats for cat & dog food).

Covers: keyword semantics (AR + EN), quality-over-coverage rules (ambiguity →
generic), the Royal CANin / "treatment" substring traps, store-category-tag
input, parent gating, additive backward compatibility (parent filters keep
matching), the crawler insert/patch paths, the startup backfill, trending
grouping, and the My Products / list filter routing. Plus a curated corpus of
realistic Saudi pet-store names that produces the distribution + samples for
the classifier sanity-check report.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DB_NAME", "test_subcategories")
from crawlers import (  # noqa: E402
    classify_food_subcategory, classify_food_subcategory_hybrid,
    extract_store_category_names, guess_category,
    process_crawled_products, FOOD_SUBCATEGORIES,
)
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
C = classify_food_subcategory


def test_dry_keywords():
    assert C("cat_food", "رويال كانين طعام قطط جاف للقطط البالغة 4 كجم") == "cat_food_dry"
    assert C("cat_food", "ME-O Adult Dry Food Tuna 7kg") == "cat_food_dry"
    assert C("dog_food", "دراي فود للكلاب من جوسيرا") == "dog_food_dry"
    assert C("dog_food", "Brit Premium kibble adult large breed") == "dog_food_dry"
    assert C("cat_food", "طعام كيبل للقطط الصغيرة") == "cat_food_dry"


def test_wet_keywords():
    assert C("cat_food", "شيبا طعام رطب للقطط بالدجاج") == "cat_food_wet"
    assert C("cat_food", "واو معلبات تونة للقطط 85 جرام") == "cat_food_wet"
    assert C("cat_food", "Applaws pouch chicken breast in jelly") == "cat_food_wet"
    assert C("cat_food", "قطع الدجاج في المرق للقطط") == "cat_food_wet"
    assert C("dog_food", "Pedigree canned adult beef 400g") == "dog_food_wet"
    assert C("dog_food", "طعام كلاب بالجيلي") == "dog_food_wet"
    assert C("cat_food", "Gourmet Gold mousse with tuna") == "cat_food_wet"
    assert C("cat_food", "باتيه القطط بالسلمون") == "cat_food_wet"


def test_treat_keywords():
    assert C("cat_food", "مكافآت القطط بالدجاج من تمبتيشنز") == "cat_treats"
    assert C("cat_food", "دريميز تريتس للقطط بالسلمون") == "cat_treats"
    assert C("dog_food", "سناك الكلاب أعواد المضغ بالبقر") == "dog_treats"
    assert C("dog_food", "Jerhigh chicken stick dog snack") == "dog_treats"
    assert C("dog_food", "Pedigree Dentastix daily chew") == "dog_treats"
    assert C("cat_food", "بسكويت مكافأة للقطط") == "cat_treats"


def test_treats_win_over_wet_and_dry():
    # a treat "in gravy" or a "dry biscuit" is still a treat
    assert C("cat_food", "تريتس قطط قطع دجاج في المرق") == "cat_treats"
    assert C("dog_food", "dry biscuit snack for dogs") == "dog_treats"


def test_wet_plus_dry_is_ambiguous_stays_generic():
    assert C("cat_food", "مجموعة طعام القطط جاف + رطب عرض توفير") is None
    assert C("cat_food", "Wet & Dry mixed feeding bundle") is None


def test_no_signal_stays_generic():
    assert C("cat_food", "رويال كانين بيرشن للقطط البالغة 2 كجم") is None
    assert C("dog_food", "طعام كلاب بروتين دجاج 3 كيلو") is None


def test_substring_traps():
    # Royal CANin must NOT read as "canned"
    assert C("cat_food", "Royal Canin Persian Adult 4kg") is None
    # "treatment" (hairball treatment food) must NOT read as a treat
    assert C("cat_food", "Hairball treatment adult formula") is None
    # but genuine "treats" beside "treatment"-free text works
    assert C("cat_food", "Salmon treats for adult cats") == "cat_treats"


def test_parent_gating_and_empty():
    assert C("litter", "رمل قطط جاف") is None            # not a food parent
    assert C("toys", "dry chew toy") is None
    assert C(None, "dry food") is None
    assert C("cat_food") is None
    assert C("cat_food", "", None) is None


def test_store_category_tags_help():
    # name alone is generic; the store's own tag disambiguates (hybrid input)
    raw_salla = {"categories": [{"name": "طعام رطب للقطط"}]}
    tags = extract_store_category_names(raw_salla)
    assert C("cat_food", "فيليكس بالدجاج 85g", tags) == "cat_food_wet"
    raw_zid = {"categories": [{"name": {"ar": "مكافآت", "en": "Treats"}}]}
    assert C("dog_food", "لو للكلاب", extract_store_category_names(raw_zid)) == "dog_treats"
    assert extract_store_category_names({}) == ""
    assert extract_store_category_names({"categories": None}) == ""


# ── iter39 fixes (validated against real-catalog samples) ────────────────────
def test_bowls_are_accessories_not_food():
    # the confirmed case: "صحن طعام" (food bowl) used to hit طعام → cat_food,
    # and بلاستيكي (plastic) contains ستيك → treats. Bowls now force accessories.
    assert guess_category("مودرنا صحن طعام بلاستيكي للقطط و الكلاب") == "accessories"
    assert guess_category("وعاء طعام مزدوج للكلاب") == "accessories"
    assert guess_category("Automatic pet feeder with food storage") == "accessories"
    assert guess_category("Stainless steel dog food bowl") == "accessories"
    assert guess_category("مغذية أوتوماتيكية للقطط") == "accessories"


def test_holistic_and_plastic_no_longer_read_as_steak():
    # ستيك is a substring of هوليستيك (holistic) and بلاستيكي (plastic) — the
    # confirmed cause of Solid Gold dry food landing in dog_treats.
    assert C("dog_food", "سوليد جولد هوليستيك بليندز طعام جاف للكلاب") == "dog_food_dry"
    assert C("cat_food", "طعام هوليستيك جاف للقطط") == "cat_food_dry"
    # standalone ستيك is still a treat word
    assert C("dog_food", "ستيك دجاج مجفف للكلاب") == "dog_treats"
    # sticker must not read as stick
    assert C("cat_food", "sticker gift with cat food") is None


def test_bundles_stay_generic():
    # the confirmed case: kitten box (food + litter + treats + toy) → cat_treats
    assert C("cat_food", "بكج للقطط الصغيرة مع طعام أكانا وحبيبات تدريب الحمّام ومكافآت تشورو ولعبة") is None
    assert C("cat_food", "عرض 1+1 طعام قطط رطب") is None
    assert C("dog_food", "Puppy starter package: kibble + treats") is None
    assert C("cat_food", "مجموعة تغذية القطط الشاملة") is None


def test_treat_names_reach_food_parents():
    # issue 4: treat names carry no generic food keyword and fell through
    # guess_category to accessories — never reaching the subcategorizer.
    assert guess_category("مكافآت تشورو للقطط بالتونة") == "cat_food"
    assert guess_category("سناك كلاب بالكبد المجفف") == "dog_food"
    assert guess_category("تريتس القطط بالسلمون") == "cat_food"
    # ...and then subcategorize as treats end-to-end
    cat = guess_category("مكافآت تشورو للقطط بالتونة")
    assert C(cat, "مكافآت تشورو للقطط بالتونة") == "cat_treats"


def test_hybrid_name_verdict_beats_store_tags():
    # an unambiguous form keyword in the NAME can never be overridden by a tag
    assert classify_food_subcategory_hybrid("dog_food", "طعام جاف للكلاب", "مكافآت") == "dog_food_dry"
    # bundle-marked names block tag input entirely
    assert classify_food_subcategory_hybrid("cat_food", "بكج طعام القطط", "طعام رطب") is None
    # tags still help when the name is inconclusive
    assert classify_food_subcategory_hybrid("cat_food", "فيليكس بالدجاج 85g", "طعام رطب") == "cat_food_wet"


def test_classifier_migration_v2():
    async def main():
        db = AsyncIOMotorClient(MONGO)["test_subcat_migration"]
        for c in ("products", "metric_rollup_meta"):
            await db[c].delete_many({})
        await db.products.insert_many([
            # issue 1: bowl mis-filed as food + treats (via بلاستيكي)
            {"id": "1", "sku": "B1", "name_ar": "مودرنا صحن طعام بلاستيكي للقطط و الكلاب",
             "name_en": "", "category": "cat_food", "subcategory": "cat_treats"},
            # issue 2: dry food mis-filed as treats (via هوليستيك)
            {"id": "2", "sku": "S1", "name_ar": "سوليد جولد هوليستيك بليندز طعام جاف للكلاب",
             "name_en": "", "category": "dog_food", "subcategory": "dog_treats"},
            # issue 3: bundle filed by smallest component
            {"id": "3", "sku": "P1", "name_ar": "بكج للقطط الصغيرة مع طعام أكانا ومكافآت تشورو ولعبة",
             "name_en": "", "category": "cat_food", "subcategory": "cat_treats"},
            # issue 4: treat-named product stuck in accessories
            {"id": "4", "sku": "T1", "name_ar": "مكافآت تشورو للقطط بالتونة",
             "name_en": "", "category": "accessories"},
            # hand-labeled product with keyword-less name must NOT move
            {"id": "5", "sku": "H1", "name_ar": "هيلز كيتن دجاج 2 كجم",
             "name_en": "Hills Kitten Chicken 2kg", "category": "cat_food", "subcategory": None},
            {"id": "6", "sku": "H2", "name_ar": "قفص نقل معدني",
             "name_en": "", "category": "accessories"},
        ])
        n = await server.backfill_food_subcategories(db)
        assert n >= 4, n
        docs = {p["sku"]: p async for p in db.products.find({}, {"_id": 0})}
        assert docs["B1"]["category"] == "accessories" and docs["B1"]["subcategory"] is None
        assert docs["S1"]["category"] == "dog_food" and docs["S1"]["subcategory"] == "dog_food_dry"
        assert docs["P1"]["category"] == "cat_food" and docs["P1"]["subcategory"] is None
        assert docs["T1"]["category"] == "cat_food" and docs["T1"]["subcategory"] == "cat_treats"
        assert docs["H1"]["category"] == "cat_food" and docs["H1"]["subcategory"] is None
        assert docs["H2"]["category"] == "accessories"
        # version marker set → second run is a no-op
        marker = await db.metric_rollup_meta.find_one({"_id": "classifier"})
        assert marker["version"] == server.CLASSIFIER_VERSION
        assert await server.backfill_food_subcategories(db) == 0
    asyncio.run(main())


# ── curated realistic corpus → the distribution/sample report ────────────────
CORPUS = [
    # (name, parent) — names mirror the real Saudi catalog style (AR/EN mixed)
    ("رويال كانين فيت كير طعام قطط جاف 4 كجم", "cat_food"),
    ("طعام قطط جاف من بونيتي بالتونة 7 كجم", "cat_food"),
    ("ME-O دراي فود كيتن 1.2 كجم", "cat_food"),
    ("جوسيرا طعام قطط جاف كيتن 2 كجم", "cat_food"),
    ("Brit Care Grain-Free Hair Care dry 7kg", "cat_food"),
    ("Taste of the Wild kibble cat 6.6kg", "cat_food"),
    ("شيبا معلبات دجاج 85 جرام", "cat_food"),
    ("فيليكس طعام رطب بالسلمون في الجيلي", "cat_food"),
    ("واو باوتش تونة وجمبري للقطط", "cat_food"),
    ("Applaws chicken breast in gravy pouch 70g", "cat_food"),
    ("Gourmet Gold mousse beef 85g", "cat_food"),
    ("معلب قطط بالدجاج والكبد 400 جرام", "cat_food"),
    ("Sheba pate salmon entree", "cat_food"),
    ("تمبتيشنز مكافآت القطط بالدجاج المشوي", "cat_food"),
    ("دريميز تريتس بالسلمون 60 جرام", "cat_food"),
    ("سناك القطط أعواد التونة", "cat_food"),
    ("Catit Creamy lickable treats 5x15g", "cat_food"),
    ("بسكويت مكافأة للقطط بالنعناع البري", "cat_food"),
    ("رويال كانين بيرشن أدلت 2 كجم", "cat_food"),                # generic (no form keyword)
    ("طعام القطط المعقمة 10 كجم", "cat_food"),                   # generic
    ("عرض القطط جاف + معلبات مشكل", "cat_food"),                 # ambiguous → generic
    ("رويال كانين ماكسي أدلت طعام كلاب جاف 15 كجم", "dog_food"),
    ("بيديجري دراي فود بقري للكلاب البالغة 10 كجم", "dog_food"),
    ("Josera kibble active dog 15kg", "dog_food"),
    ("بيديجري معلب لحم بقري للكلاب 400 جرام", "dog_food"),
    ("Cesar wet dog food chicken & rice", "dog_food"),
    ("طعام كلاب رطب بالدجاج في المرق", "dog_food"),
    ("Pedigree pouch adult beef in gravy", "dog_food"),
    ("دنتاستيكس أعواد مضغ يومية للكلاب المتوسطة", "dog_food"),
    ("Jerhigh chicken stick سناك كلاب", "dog_food"),
    ("مكافآت الكلاب بالكبد المجفف", "dog_food"),
    ("SmartBones chew bones mini 8pcs", "dog_food"),
    ("رويال كانين ميني بابي 2 كجم", "dog_food"),                  # generic
    ("طعام كلاب هايبوالرجينيك بالسمك", "dog_food"),               # generic
]


def _corpus_distribution():
    dist = {k: 0 for k in FOOD_SUBCATEGORIES}
    generic = {"cat_food": 0, "dog_food": 0}
    assigned = {}
    for name, parent in CORPUS:
        sub = C(parent, name)
        assigned[name] = sub or parent
        if sub:
            dist[sub] += 1
        else:
            generic[parent] += 1
    return dist, generic, assigned


def test_corpus_classification_sanity():
    dist, generic, assigned = _corpus_distribution()
    # every bucket must be non-empty and the known-generic rows must stay generic
    for k in FOOD_SUBCATEGORIES:
        assert dist[k] > 0, k
    assert assigned["رويال كانين بيرشن أدلت 2 كجم"] == "cat_food"
    assert assigned["عرض القطط جاف + معلبات مشكل"] == "cat_food"
    assert assigned["Brit Care Grain-Free Hair Care dry 7kg"] == "cat_food_dry"
    assert assigned["دنتاستيكس أعواد مضغ يومية للكلاب المتوسطة"] == "dog_treats"


def test_crawler_and_backfill_and_trending_integration():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        for c in ("products", "product_snapshots", "sku_sales_daily",
                  "metric_daily_rollups", "sku_store_coverage"):
            await db[c].delete_many({})
        store = {"id": "s1", "name": "TestStore", "domain": "t.example"}
        now = datetime.now(timezone.utc)

        # (a) new insert classifies (name + store tag hybrid)
        raw = {"id": 1, "sku": "K1", "name": "شيبا معلبات دجاج للقطط",
               "price": 10.0, "quantity": 5,
               "categories": [{"name": "طعام رطب"}]}
        await process_crawled_products(db, store, [raw], now)
        p = await db.products.find_one({"sku": "K1"}, {"_id": 0})
        assert p["category"] == "cat_food" and p["subcategory"] == "cat_food_wet", p

        # (b) pre-existing product without the field gets patched on recrawl
        await db.products.insert_one({"id": "x", "sku": "K2", "name_ar": "دراي فود قطط 4كجم",
                                      "name_en": "", "category": "cat_food"})
        raw2 = {"id": 2, "sku": "K2", "name": "دراي فود قطط 4كجم", "price": 20.0, "quantity": 2}
        await process_crawled_products(db, store, [raw2], now)
        p2 = await db.products.find_one({"sku": "K2"}, {"_id": 0})
        assert p2["subcategory"] == "cat_food_dry", p2

        # (c) startup backfill covers products no crawl revisits; None marks done
        await db.products.insert_one({"id": "y", "sku": "K3", "name_ar": "مكافآت كلاب بالكبد",
                                      "name_en": "", "category": "dog_food"})
        await db.products.insert_one({"id": "z", "sku": "K4", "name_ar": "رويال كانين بيرشن",
                                      "name_en": "", "category": "cat_food"})
        n = await server.backfill_food_subcategories(db)
        assert n == 2, n
        assert (await db.products.find_one({"sku": "K3"}))["subcategory"] == "dog_treats"
        k4 = await db.products.find_one({"sku": "K4"})
        assert "subcategory" in k4 and k4["subcategory"] is None      # generic, marked done
        assert await server.backfill_food_subcategories(db) == 0      # idempotent

        # (d) trending groups by subcategory-or-parent
        await db.sku_sales_daily.insert_many([
            {"_id": "s1|K1|d", "store_id": "s1", "sku": "K1", "date": "2099-01-01",
             "units_sold": 0, "rev_sold": 0.0, "units_qty": 0, "rev_qty": 0.0, "qty_drop": 7},
            {"_id": "s1|K4|d", "store_id": "s1", "sku": "K4", "date": "2099-01-01",
             "units_sold": 0, "rev_sold": 0.0, "units_qty": 0, "rev_qty": 0.0, "qty_drop": 3},
        ])
        server.db = db
        trending = await server._insights_trending_compute(db, 30)
        by_cat = {t["category"]: t["total_sales"] for t in trending}
        assert by_cat.get("cat_food_wet") == 7, by_cat        # K1 split out
        assert by_cat.get("cat_food") == 3, by_cat            # K4 stays generic parent
        labels = {t["category"]: t["category_label"] for t in trending}
        assert labels["cat_food_wet"] == "Wet Cat Food"

        # (e) filter routing: subcategory key filters subcategory; parent keeps
        # matching ALL its products (additive backward compatibility)
        subq = {"subcategory": "cat_food_wet"}
        assert await db.products.count_documents(subq) == 1
        assert await db.products.count_documents({"category": "cat_food"}) == 3
    asyncio.run(main())


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and name != "test_crawler_and_backfill_and_trending_integration":
            fn()
    dist, generic, assigned = _corpus_distribution()
    total = len(CORPUS)
    print("corpus distribution:")
    for k, v in {**dist, **generic}.items():
        print(f"  {k:15} {v:3}  ({100*v/total:.0f}%)")
    print("PASS: iter36 subcategory classifier")
