"""
Regression tests for the iter20 _has_pack_indicator word-boundary fix.

Bug: matcher.py:_has_pack_indicator() used naive substring matching, which
silently false-fired on words containing PACK_KEYWORDS as substrings.

The 4 collision classes we identified on live preview:
  - "عدد" (number) inside "متعدد الألوان" (= multi-colored)         [23 products]
  - "box"          inside "Subscription Box" / "Cat Meal Box"         [23 products]
  - "pack"         inside "Backpack" / "package"                      [ 9 products]
  - "كرتون"        inside "كرتونية" (= cardboard-made adjective)     [ 4 products]
  Total: 58 products silently misclassified as multipacks.

Misclassification suppresses Level-1 (barcode) matching for those products,
because the matcher skips Level 1 when my_is_bundle is True. So Beaphar
8711231124985 ("بيفار فيتامينات متعددة...") had 6 real competitor stores
but only 1 product_matches row (a Level-2 SKU match).

Fix: tokenize on whitespace + punctuation, check keyword membership at the
token level. Compound words stay as one token.

These tests pin BOTH that the false positives are removed AND that the
true positives are preserved.
"""
from matcher import _has_pack_indicator, _is_bundle_sku


# ── True positives must still fire (regression-protect the legitimate path) ──


def test_pack_of_n_english_still_detected():
    assert _has_pack_indicator("Reflex Pack of 6 canned food") is True
    assert _has_pack_indicator("Royal Canin set of 12") is True
    assert _has_pack_indicator("Hill's Bundle pack 24") is True


def test_carton_phrase_still_detected():
    assert _has_pack_indicator("Carton of 24 dental sticks") is True
    assert _has_pack_indicator("Box of 12 cans") is True


def test_arabic_pack_word_still_detected():
    # "علبة 12" = "box of 12" — legitimate multipack phrasing
    assert _has_pack_indicator("علبة 12 قطعة") is True
    assert _has_pack_indicator("كرتون 24 علبة") is True
    assert _has_pack_indicator("طقم 6 أوعية") is True


def test_pack_at_token_boundary_with_punctuation():
    # Hyphens and slashes are token separators too
    assert _has_pack_indicator("Royal-Canin-pack-of-6") is True
    assert _has_pack_indicator("treats|pack|24") is True
    assert _has_pack_indicator("canned food (pack 12)") is True


# ── False positives must NOT fire (the actual bug fix) ──


def test_arabic_multi_colored_does_not_false_fire():
    """The Beaphar bug: 'متعددة' contains 'عدد' as substring but is NOT
    a multipack — it means 'multiple/multi'.
    """
    assert _has_pack_indicator("بيفار فيتامينات متعددة مع التورين 50جم") is False
    assert _has_pack_indicator("متعدد الألوان") is False
    # The 2.4% catalogue-fraction trigger word
    assert _has_pack_indicator("ريفلكس طعام جاف متعدد الألوان") is False


def test_english_substring_box_does_not_false_fire():
    """'Pack' / 'Box' inside compound words like 'Backpack' must not trigger
    as substring matches. Standalone 'Box' tokens (e.g. 'Subscription Box')
    DO still trigger — that's intentional, conservative behavior since the
    matcher treats unknown-count multipack as a separate bucket. We only
    fix the SUBSTRING-COLLISION bug, not the standalone semantics.
    """
    # Substring collisions — must NOT fire
    assert _has_pack_indicator("Nobleza Backpack for pets") is False, (
        "'Backpack' contains 'pack' as substring but is a single product"
    )
    assert _has_pack_indicator("food package single") is False, (
        "'package' contains 'pack' as substring but means single packaging"
    )
    # Standalone token — STILL fires (conservative; PACK_RE will catch the
    # explicit 'Box of N' form elsewhere). We don't change this semantic.
    assert _has_pack_indicator("Ultimate Monthly Subscription Box") is True


def test_english_substring_pack_does_not_false_fire():
    """'Pack' inside 'Backpack' / 'package' must not trigger via substring."""
    assert _has_pack_indicator("Nobleza Backpack for pets") is False
    assert _has_pack_indicator("food package single") is False
    # Standalone 'pack' still fires (intended)
    assert _has_pack_indicator("Adult Cat Pack everything") is True


def test_arabic_carton_adjective_does_not_false_fire():
    """'كرتونية' = 'made of cardboard' (adjective). The product is a single
    cardboard scratcher, not a multipack carton.
    """
    assert _has_pack_indicator("تريكسي خداشة كرتونية مع الكاتنيب للقطط") is False
    assert _has_pack_indicator("خداشة كرتونية مع كرات والكاتنيب") is False


def test_empty_and_none_inputs():
    assert _has_pack_indicator("") is False
    assert _has_pack_indicator(None) is False


# ── End-to-end: the canonical Beaphar regression ──


def test_beaphar_name_no_longer_flagged_as_bundle():
    """The exact my_product.name_ar + name_en that triggered the production
    bug. After the fix, this must NOT be flagged as a multipack so the
    matcher's Level-1 barcode path can run on it.
    """
    name_full = "بيفار فيتامينات متعددة مع التورين 50جم Beaphar Multi-vitamin with Taurin - 50g"
    assert _has_pack_indicator(name_full) is False, (
        "Beaphar name must not be flagged as multipack — this is the "
        "exact regression that suppressed 6 of its barcode matches."
    )
    # And the SKU itself isn't a bundle SKU either
    assert _is_bundle_sku("8711231124985") is False
