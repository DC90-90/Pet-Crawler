"""Store-supplied categories are captured verbatim; merchandising buckets never
become a product's category (10 Oct 2026, category-share groundwork)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "test_store_categories")
os.environ.setdefault("ENCRYPTION_KEY", "")

import crawlers  # noqa: E402


def test_zid_categories_are_structured_rows_in_feed_order():
    raw = {"categories": [
        {"id": 182958, "name": "طعام رطب", "slug": "cat-wet-food", "parent_id": None},
        {"id": 397691, "name": "عروض", "slug": "offers", "parent_id": None},
        {"id": 1515418, "name": {"ar": "اكانا", "en": "Acana"}, "slug": "اكانا", "parent_id": 1515416},
    ]}
    rows = crawlers.extract_store_categories(raw)
    assert [r["name"] for r in rows] == ["طعام رطب", "عروض", "اكانا"]
    assert rows[0] == {"id": "182958", "name": "طعام رطب", "slug": "cat-wet-food", "parent_id": None}
    assert rows[2]["parent_id"] == "1515416"


def test_salla_single_category_object_is_captured():
    rows = crawlers.extract_store_categories({"category": {"name": "الصحة والجمال للقطط", "url": None}})
    assert rows == [{"id": None, "name": "الصحة والجمال للقطط", "slug": None, "parent_id": None}]


def test_missing_or_malformed_categories_yield_nothing():
    assert crawlers.extract_store_categories({}) == []
    assert crawlers.extract_store_categories({"categories": None, "category": ""}) == []
    assert crawlers.extract_store_categories({"categories": [{"id": 1}, 42, {"name": {"ar": ""}}]}) == []


def test_primary_category_skips_merchandising_buckets():
    rows = crawlers.extract_store_categories({"categories": [
        {"id": 1, "name": "عروض", "slug": "offers"},
        {"id": 2, "name": "الأكثر مبيعا", "slug": "best-sellers"},
        {"id": 3, "name": "طعام جاف", "slug": "dry-food"},
    ]})
    assert crawlers.primary_store_category(rows) == "طعام جاف"


def test_primary_category_is_empty_when_only_buckets_exist():
    rows = crawlers.extract_store_categories({"categories": [{"id": 1, "name": "Offers", "slug": "offers"}]})
    assert crawlers.primary_store_category(rows) == ""
    assert crawlers.primary_store_category([]) == ""
