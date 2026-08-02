"""iter73h — Top Brands sanity: no more "Unknown" bucket dominating the
ranking, Arabic/English brand variants merged, dead rows dropped.

Client screenshot (Aug 2 2026) showed "Unknown" at 77.6% market share with
38,957 units — impossible when the brand is literally the "we couldn't
identify anything" bucket. Root cause: the ingest-time `extract_brand`
matches a hardcoded 34-brand list; 93% of products had empty brand and
landed in one big "Unknown" pile.

The fix is a READ-TIME brand normaliser that:
  1. Prefers the row's existing brand tag when non-empty.
  2. Runs KNOWN_BRANDS scan (now ~85 brands with Arabic/English variants).
  3. Falls back to the first Latin token of the English name — the
     packaging convention that "Applaws Cat Dry Food" starts with the
     brand name.
  4. Canonicalises Arabic + English variants into ONE bucket so
     `رويال كانين` and `Royal Canin` don't split.
  5. Rows whose brand STILL can't be resolved are DROPPED from Top Brands,
     never rendered as "Unknown".

These tests are pure code shape + logic — no live DB — so they run in every
environment.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import crawlers as _cr


# ── canonical_brand ────────────────────────────────────────────────────────
def test_canonical_brand_merges_arabic_and_english():
    """Royal Canin and رويال كانين must map to the SAME canonical name so
    they don't split across two rows on Top Brands."""
    assert _cr.canonical_brand("Royal Canin") == "Royal Canin"
    assert _cr.canonical_brand("رويال كانين") == "Royal Canin"
    assert _cr.canonical_brand("hills") == "Hill's"
    assert _cr.canonical_brand("Hill's") == "Hill's"
    assert _cr.canonical_brand("هيلز") == "Hill's"
    assert _cr.canonical_brand("APPLAWS") == "Applaws"
    assert _cr.canonical_brand("أبلاوز") == "Applaws"


def test_canonical_brand_blank_returns_none():
    """None / empty / whitespace-only inputs must return None so callers
    can filter them out — NEVER return a truthy 'Unknown' string."""
    assert _cr.canonical_brand("") is None
    assert _cr.canonical_brand(None) is None
    assert _cr.canonical_brand("   ") is None


def test_canonical_brand_unknown_brand_passes_through():
    """A genuinely-unknown brand tag (not in the canonical map) should
    still return the raw string so it shows up as its own bucket rather
    than being lost. The caller drops None but keeps real strings."""
    assert _cr.canonical_brand("SomeObscureBrand") == "SomeObscureBrand"
    assert _cr.canonical_brand("  Trimmed  ") == "Trimmed"


# ── extract_brand_smart ────────────────────────────────────────────────────
def test_extract_brand_smart_uses_existing_first():
    """If the row already carries a brand tag, honour it (canonicalised)."""
    assert _cr.extract_brand_smart("", "", existing="Royal Canin") == "Royal Canin"
    assert _cr.extract_brand_smart("طعام قطط", "", existing="royal canin") == "Royal Canin"


def test_extract_brand_smart_falls_back_to_english_leading_token():
    """The known-brand scan finds Applaws in the name — no fallback needed."""
    got = _cr.extract_brand_smart(
        "", "Applaws Cat Dry Food with Chicken for Adults", existing="")
    assert got == "Applaws"


def test_extract_brand_smart_ignores_generic_leading_words():
    """Names starting with generic descriptors ('The', 'Cat', 'Premium')
    must NOT return that word as a brand — otherwise every 'Cat Food'
    product would land under a spurious 'Cat' brand."""
    for name in ("Cat Food Salmon 400g",
                 "Premium Dog Treats",
                 "The Best Kitten Kibble",
                 "Dry Food for Adult Cats"):
        got = _cr.extract_brand_smart("", name)
        assert got is None or got not in ("Cat", "Premium", "The", "Dry"), \
            f"generic leading token was returned as brand for {name!r}: got {got!r}"


def test_extract_brand_smart_returns_none_when_nothing_resolvable():
    """A product with no name AND no existing tag has no brand — must
    return None so it drops OUT of the Top Brands ranking entirely.
    NEVER return 'Unknown'."""
    got = _cr.extract_brand_smart("", "", existing="")
    assert got is None
    got2 = _cr.extract_brand_smart(None, None, existing=None)
    assert got2 is None


def test_extract_brand_smart_handles_arabic_names():
    """Arabic-only names must run through the KNOWN_BRANDS scan (which
    contains Arabic aliases) and NOT trip the leading-token fallback (it
    intentionally only fires on Latin-first names)."""
    got = _cr.extract_brand_smart("طعام قطط رويال كانين للبالغين", "")
    assert got == "Royal Canin"
    got2 = _cr.extract_brand_smart("هيلز غذاء", "")
    assert got2 == "Hill's"


def test_extract_brand_smart_prefers_two_token_alias_when_available():
    """'Blue Buffalo' and 'Cat Chow' are 2-token brand aliases — the
    fallback tries the 2-token form BEFORE settling on the single leading
    token, so we get the correct canonical name."""
    assert _cr.extract_brand_smart(
        "", "Blue Buffalo Wilderness Duck Adult") == "Blue Buffalo"


# ── endpoint wiring: Top Brands aggregation ────────────────────────────────
def test_top_brands_aggregation_drops_unknown_bucket():
    """The Insights aggregation must never emit an 'Unknown' brand row."""
    src = (BACKEND / "server.py").read_text()
    # locate the Top Brands block
    a = src.index("# iter73h — Top Brands aggregation")
    b = src.index("total_brand_revenue = sum", a)
    body = src[a:b]
    # look for the SPECIFIC anti-pattern: `... or "Unknown"` used as a bucket key
    assert 'or "Unknown"' not in body and "or 'Unknown'" not in body, \
        "aggregation still buckets missing-brand rows as 'Unknown'"
    assert "extract_brand_smart" in body, \
        "aggregation must call extract_brand_smart, not `p.get('brand') or 'Unknown'`"
    assert "if not canonical:" in body and "continue" in body, \
        "rows with no resolvable brand must be DROPPED, not bucketed"


def test_top_brands_aggregation_drops_zero_activity_rows():
    """Rows with units==0 AND revenue==0 must be dropped from the ranking,
    otherwise long-tail catalog products crowd out the real ranking."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("# iter73h — Top Brands aggregation")
    b = src.index("total_brand_revenue = sum", a)
    body = src[a:b]
    assert "brand_acc = {b: v for b, v in brand_acc.items()" in body
    assert '(v["units"] or 0) > 0' in body and '(v["revenue"] or 0) > 0' in body, \
        "dead-row filter (units>0 OR revenue>0) is missing"


def test_market_share_normalises_across_kept_brands_only():
    """After Unknown / zero rows are dropped, the DISPLAYED brands' shares
    must add up to 100% — the denominator is the kept-brand revenue sum,
    not the full-catalog total."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("# iter73h — Top Brands aggregation")
    # market_share_pct uses total_brand_revenue which is computed AFTER
    # brand_acc is filtered to non-empty entries.
    b = src.index("top_brands = sorted(", a)
    body = src[a:b]
    # brand_acc filter comes before the total is computed
    i_filter = body.find("brand_acc = {b: v for b, v in brand_acc.items()")
    i_total = body.find("total_brand_revenue = sum")
    assert 0 <= i_filter < i_total, \
        "market share denominator must be computed AFTER the dead-row filter"
