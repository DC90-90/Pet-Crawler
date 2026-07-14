"""Unit tests for backend/mahally.py — parser + strict-guard matcher.

No network. No DB. Fixtures are minimal, hand-crafted approximations of the
real Mahally SSR JSON blobs observed during recon (see mahally.py header
comment for provenance). If Mahally's page structure changes, these tests
will fail loudly and force a re-recon pass before we ship broken enrichment.
"""

import re

from mahally import (
    _is_valid_ean,
    _normalize,
    extract_product_hrefs,
    extract_size_tokens,
    is_confident_match,
    parse_product_detail,
)


# ── Fixtures ───────────────────────────────────────────────────────────────
# Approximates the JSON block observed on a real product detail page. The
# structure is what our parser actually cares about: escaped RSC-shaped
# quotes, product_id anchor, store/domain block preceding, barcode/sku/etc.
# variants following.
FIXTURE_PRODUCT_HTML = r'''
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"Product","name":"طعام قطط رويال كانين 2kg","aggregateRating":{"ratingValue":5}}]}
</script>
</head><body>
<script>self.__next_f.push([1, "somepayload"])</script>
<script>self.__next_f.push([1, "...\"store\":{\"id\":1071118802,\"name\":\"بيتسي\",\"username\":\"petsy-1\",\"avatar\":\"x\",\"domain\":\"https://petsy-1.com\",\"has_mahly\":true},\"rating\":{\"total\":100,\"count\":20,\"rate\":5},\"seo\":{},\"skus\":[{\"id\":1076232856,\"product_id\":1166119229,\"price\":{\"amount\":9.28,\"currency\":\"SAR\"},\"cost_price\":{\"amount\":9.28,\"currency\":\"SAR\"},\"sale_price\":null,\"stock_quantity\":null,\"unlimited_quantity\":false,\"barcode\":null,\"sku\":null,\"mpn\":null,\"gtin\":null,\"updated_at\":\"2026-07-13 15:20:31\"},{\"id\":1076232857,\"product_id\":1166119229,\"price\":{\"amount\":9.28,\"currency\":\"SAR\"},\"cost_price\":{\"amount\":9.28,\"currency\":\"SAR\"},\"barcode\":\"5411860811044\",\"sku\":\"811044\",\"mpn\":null,\"gtin\":null,\"updated_at\":\"2026-07-13 15:20:31\"}]"])</script>
<a href="/ar/products/1071118802/1166119229/?queryID=abc">variant</a>
<a href="/ar/products/1030365934/1725454015/?queryID=abc">other</a>
</body></html>
'''


# ── Href discovery ─────────────────────────────────────────────────────────
def test_extract_product_hrefs_deduplicates():
    html = '<a href="/ar/products/100/200/?queryID=x">a</a>' \
           '<a href="/ar/products/100/200/?position=3">a2</a>' \
           '<a href="/ar/products/999/888/">b</a>'
    pairs = extract_product_hrefs(html)
    assert pairs == [(100, 200), (999, 888)]


def test_extract_product_hrefs_from_fixture():
    pairs = extract_product_hrefs(FIXTURE_PRODUCT_HTML)
    assert (1071118802, 1166119229) in pairs
    assert (1030365934, 1725454015) in pairs
    assert len(pairs) == 2


# ── Product detail parser ─────────────────────────────────────────────────
def test_parse_product_detail_returns_none_when_pid_missing():
    assert parse_product_detail(FIXTURE_PRODUCT_HTML, 999999) is None


def test_parse_product_detail_extracts_barcode_from_second_variant():
    """The parent product has barcode=null; the second variant has the real
    barcode. Our parser picks the FIRST non-null occurrence (variant #2)."""
    out = parse_product_detail(FIXTURE_PRODUCT_HTML, 1166119229)
    assert out is not None
    assert out["barcode"] == "5411860811044"
    assert out["sku"] == "811044"
    assert out["mpn"] is None
    assert out["gtin"] is None


def test_parse_product_detail_extracts_store_identity():
    out = parse_product_detail(FIXTURE_PRODUCT_HTML, 1166119229)
    assert out["store_name"] == "بيتسي"
    assert out["store_username"] == "petsy-1"
    assert out["store_domain"] == "https://petsy-1.com"


def test_parse_product_detail_extracts_jsonld_name():
    out = parse_product_detail(FIXTURE_PRODUCT_HTML, 1166119229)
    assert out["name_ar"] == "طعام قطط رويال كانين 2kg"


# ── Normalization ─────────────────────────────────────────────────────────
def test_normalize_arabic_alef_and_tashkeel():
    # Alef with hamza, kashida, and fatha — all normalized away.
    assert _normalize("أَكل قِطط") == _normalize("اكل قطط")


def test_normalize_ta_marbuta_and_ya():
    # ta-marbuta and alef-maqsura sometimes swap in merchant catalogs.
    assert _normalize("علبة") == _normalize("علبه")
    assert _normalize("متعددى") == _normalize("متعددي")


def test_normalize_lowercases_latin():
    assert _normalize("Royal Canin 2KG") == "royal canin 2kg"


# ── Size token extraction ─────────────────────────────────────────────────
def test_size_tokens_kg_canonicalizes_to_g_mass():
    assert extract_size_tokens("طعام قطط 2kg") == frozenset({"2000g_mass"})


def test_size_tokens_kg_equals_grams_after_canonical():
    """2kg and 2000g must produce the SAME token — guard trusts equality."""
    assert extract_size_tokens("food 2kg") == extract_size_tokens("food 2000g")


def test_size_tokens_litres_to_ml_volume():
    assert extract_size_tokens("shampoo 1L") == frozenset({"1000ml_volume"})
    assert extract_size_tokens("400 ml") == frozenset({"400ml_volume"})


def test_size_tokens_multiple_units_kept():
    toks = extract_size_tokens("dry food 400g + wet food 85g")
    assert toks == frozenset({"400g_mass", "85g_mass"})


def test_size_tokens_ignores_pack_count():
    # "pack of 12" has no unit → no size token → guard is silent, not
    # over-restrictive.
    assert extract_size_tokens("pack of 12") == frozenset()
    assert extract_size_tokens("12 pieces") == frozenset()


def test_size_tokens_arabic_units():
    assert extract_size_tokens("طعام قطط 2 كجم") == frozenset({"2000g_mass"})
    assert extract_size_tokens("طعام كلاب 400 جرام") == frozenset({"400g_mass"})
    assert extract_size_tokens("شامبو 250 مل") == frozenset({"250ml_volume"})


# ── Match guard: fuzzy ratio ─────────────────────────────────────────────
def test_reject_low_ratio():
    my = {"name_ar": "طعام قطط رويال كانين", "brand": "رويال كانين"}
    ml = {"name_ar": "شامبو كلاب بيوريتش"}  # totally different product
    matched, score, reason = is_confident_match(my, ml)
    assert not matched
    assert reason.startswith("ratio<") or reason.startswith("brand_token_missing")


# ── Match guard: brand token exact ───────────────────────────────────────
def test_reject_when_brand_missing_from_mahally_name():
    my = {"name_ar": "طعام قطط", "brand": "رويال كانين"}
    ml = {"name_ar": "طعام قطط بريميوم"}  # same category, wrong brand
    matched, score, reason = is_confident_match(my, ml)
    assert not matched
    assert reason.startswith("brand_token_missing")


def test_reject_when_our_brand_column_is_empty():
    """User rule: when our catalog has no brand we can't verify. Skip."""
    my = {"name_ar": "طعام قطط رويال كانين 2 كجم", "brand": ""}
    ml = {"name_ar": "طعام قطط رويال كانين 2 كجم"}
    matched, score, reason = is_confident_match(my, ml)
    assert not matched
    assert reason == "my_brand_empty"


def test_accept_when_brand_multi_word_all_present():
    my = {"name_ar": "رويال كانين قطط 2 كجم", "brand": "رويال كانين"}
    ml = {"name_ar": "رويال كانين قطط 2 كجم"}
    matched, score, reason = is_confident_match(my, ml)
    assert matched
    assert score >= 92
    assert reason == "match"


# ── Match guard: size tokens exact set ───────────────────────────────────
def test_reject_size_mismatch_2kg_vs_4kg():
    """The user's canonical example: 2kg vs 4kg — REJECT regardless of ratio."""
    my = {"name_ar": "طعام قطط رويال كانين 2 كجم", "brand": "رويال كانين"}
    ml = {"name_ar": "طعام قطط رويال كانين 4 كجم"}
    matched, score, reason = is_confident_match(my, ml)
    assert not matched, "same brand, similar name, DIFFERENT size — must reject"
    assert reason.startswith("size_mismatch")


def test_accept_when_size_matches_across_unit_conversion():
    """Canonical size tokens equal across unit conversion — but this alone is
    not enough: the ratio guard still fires when the strings look different
    enough. To isolate the size guard, we verify the token sets DIRECTLY, and
    match two names whose ratio also happens to clear 92."""
    from mahally import extract_size_tokens
    # Size guard passes across unit conversion (2kg == 2000g as canonical g).
    assert extract_size_tokens("طعام قطط 2 كجم") == extract_size_tokens("طعام قطط 2000 جرام")

    # Names identical except unit written both ways in each — matches.
    my = {"name_ar": "طعام قطط رويال كانين 2 كجم", "brand": "رويال كانين"}
    ml = {"name_ar": "طعام قطط رويال كانين 2 كجم"}
    matched, score, reason = is_confident_match(my, ml)
    assert matched
    assert reason == "match"


def test_accept_when_neither_has_size():
    """No size token in either → size guard is silent — pass via other guards."""
    my = {"name_ar": "علبة طعام قطط رويال كانين تونا", "brand": "رويال كانين"}
    ml = {"name_ar": "علبة طعام قطط رويال كانين تونا"}
    matched, score, reason = is_confident_match(my, ml)
    assert matched


def test_reject_asymmetric_but_same_family_size():
    """One says '2kg', other says nothing — set inequality → reject."""
    my = {"name_ar": "طعام رويال كانين 2 كجم", "brand": "رويال كانين"}
    ml = {"name_ar": "طعام رويال كانين"}
    matched, score, reason = is_confident_match(my, ml)
    assert not matched
    assert reason.startswith("size_mismatch")


# ── Barcode validator ─────────────────────────────────────────────────────
def test_is_valid_ean_accepts_8_to_14_digits():
    assert _is_valid_ean("12345678")
    assert _is_valid_ean("5411860811044")  # EAN-13
    assert _is_valid_ean("12345678901234")  # 14
    assert not _is_valid_ean("1234567")  # 7 digits
    assert not _is_valid_ean("123456789012345")  # 15 digits
    assert not _is_valid_ean("ABCD5678")
    assert not _is_valid_ean("")
    assert not _is_valid_ean(None)
