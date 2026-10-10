"""Cross-store category mapping (10 Oct 2026): exact after Arabic
normalisation, synonym groups, token overlap; animals never cross; unmapped
stays visible."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import category_map as cm  # noqa: E402

CANON = ["القطط", "الكلاب", "طعام جاف", "طعام رطب", "رمل القطط", "مكافآت", "الطيور", "اكسسوارات"]


def test_normalize_unifies_arabic_variants_and_case():
    assert cm.normalize("القِطَط") == cm.normalize("القطط")
    assert cm.normalize("طعام رطبة") == cm.normalize("طعام رطبه")
    assert cm.normalize("أكل القطط") == cm.normalize("اكل القطط")
    assert cm.normalize("Cat Food") == "cat food"


def test_exact_match_after_normalisation():
    assert cm.best_match("القِطَط", CANON) == ("exact", "القطط")


def test_synonym_groups_map_english_and_arabic_spellings():
    assert cm.best_match("Cat Food", CANON)[1] == "القطط"
    assert cm.best_match("Dry Food", CANON)[1] == "طعام جاف"
    assert cm.best_match("معلبات", CANON)[1] == "طعام رطب"
    assert cm.best_match("Cat Litter", CANON)[1] in ("رمل القطط", "القطط")
    assert cm.best_match("Treats", CANON)[1] == "مكافآت"
    assert cm.best_match("عصافير", CANON)[1] == "الطيور"


def test_animals_never_cross():
    assert cm.best_match("Dog Food", ["القطط"]) == ("unmapped", None)
    assert cm.best_match("طعام كلاب جاف", ["القطط", "الكلاب"])[1] == "الكلاب"


def test_unrelated_names_stay_unmapped():
    assert cm.best_match("Gift Cards", CANON) == ("unmapped", None)
    assert cm.best_match("", CANON) == ("unmapped", None)


def test_map_resolution_order_and_unmapped_label():
    rows = [{"store_id": "s1", "store_category": "Feline Stuff", "canonical": "القطط", "method": "reviewed"}]
    m = cm.CategoryMap(CANON, rows, own_store_id="own")
    assert m.resolve("s1", [{"name": "feline stuff"}]) == ("القطط", "reviewed", "feline stuff")
    assert m.resolve("s1", [{"name": "Dog Food"}])[:2] == ("الكلاب", "synonym")
    assert m.resolve("own", [{"name": "أي شيء"}]) == ("أي شيء", "canonical", "أي شيء")
    assert m.label("s2", [{"name": "Gift Cards"}]) == ("unmapped: Gift Cards", "unmapped")
    assert m.label("s2", []) == ("", "none")
    assert m.unmapped_seen == {("s2", "Gift Cards"): 1}


def test_first_mappable_tag_wins_over_merchandising_noise():
    m = cm.CategoryMap(CANON, [], own_store_id="own")
    assert m.resolve("s3", [{"name": "Offers"}, {"name": "Wet Food"}])[0] == "طعام رطب"
