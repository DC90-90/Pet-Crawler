"""iter73 — Zarafa (and other newer Salla themes) link their categories as
`/{locale}/{slug-or-dash}/c{id}` (e.g. `/ar/-/c622249111`) instead of the
legacy `/categories/{id}` shape. The old category-discovery selector only
matched the legacy shape, so it returned ZERO categories on Zarafa's homepage.
That silently killed the entire storefront-categories walk (no cats → no API
calls → 0 products captured → whole store went dark). Result: SKU
5060122491365 (Applaws Chicken 400 g) and the rest of Zarafa's catalog were
absent from Daleel's Price Intel, even though the client could see the
product live on zarafaksa.com.

The fix widens the discovery regex to match BOTH shapes. These tests are pure
JS-string / no-network so they run in every environment:

  * legacy `/categories/{id}` still matches (no regression).
  * new `/c{id}` (as seen on Zarafa) is now captured.
  * junk paths that only happen to contain `c<digits>` (e.g. `/cart`, or a
    product path like `/some-product-name-2c123`) are NOT captured — the
    boundary rules require a slash before `/c` and end-of-segment right after.
"""
import re
from pathlib import Path

CRAWLERS = Path(__file__).resolve().parents[1] / "crawlers.py"


def _js_source():
    src = CRAWLERS.read_text(encoding="utf-8")
    assert "_discover_salla_category_ids" in src, "helper renamed / missing"
    return src


# Python mirror of the JS regexes so tests exercise the SAME shapes the
# browser evaluates. Keep the patterns in lock-step with the JS strings in
# crawlers.py — if one changes, update both here.
_LEGACY = re.compile(r"categories\/(\d+)")
_NEW    = re.compile(r"\/c(\d{6,})(?:$|[\/?#])")


def _extract_cat_ids(hrefs):
    out = []
    for h in hrefs:
        for pat in (_LEGACY, _NEW):
            m = pat.search(h)
            if m:
                if m.group(1) not in out:
                    out.append(m.group(1))
                break
    return out


def test_source_has_both_patterns_in_discover_helper():
    """Guard against a future refactor accidentally reverting to legacy-only."""
    src = _js_source()
    # find the _discover_salla_category_ids body — verify both regexes present.
    start = src.index("async def _discover_salla_category_ids")
    end = src.index("\nasync def ", start + 1)
    body = src[start:end]
    assert "categories\\\\/(\\\\d+)" in body, "legacy /categories/{id} regex missing"
    assert "\\/c(\\\\d{6,})" in body, "new /c{id} regex missing"


def test_source_has_both_patterns_in_subcategory_walker():
    """The subcategory-discovery evaluate() inside the storefront walk uses
    the SAME extraction rules — both regexes must live there too."""
    src = _js_source()
    # find the /ar/redirect/categories/{cid} loop inside the storefront crawler
    # and grab the enclosing evaluate() body.
    marker = "for cid in top_cat_ids[:60]:"
    i = src.index(marker)
    body = src[i:i + 2500]
    assert "categories\\\\/(\\\\d+)" in body, "subcategory legacy regex missing"
    assert "\\/c(\\\\d{6,})" in body, "subcategory new regex missing"


def test_legacy_categories_urls_still_match():
    hrefs = [
        "https://example.com/ar/redirect/categories/123456",
        "https://example.com/en/categories/999",
        "/categories/42",
    ]
    ids = _extract_cat_ids(hrefs)
    assert ids == ["123456", "999", "42"]


def test_zarafa_c_id_urls_now_match():
    hrefs = [
        "https://zarafaksa.com/ar/-/c806316219",     # Cats / all
        "https://zarafaksa.com/ar/-/c622249111",     # طعام جاف (dry food)
        "https://zarafaksa.com/ar/-/c1995694992",    # طعام رطب (wet food)
        "https://zarafaksa.com/en/some-slug/c1272966940",   # English + slug
        "https://zarafaksa.com/ar/-/c622249111?page=2",     # query string
    ]
    ids = _extract_cat_ids(hrefs)
    assert ids == ["806316219", "622249111", "1995694992", "1272966940"]
    # trailing ?page=2 form still matches the same id (dedup)


def test_mixed_page_yields_full_set_dedup():
    hrefs = [
        "/categories/42",
        "https://zarafaksa.com/ar/-/c42",           # <-- 2 digits, MUST NOT match (min 6)
        "https://zarafaksa.com/ar/-/c806316219",
        "/categories/42",                            # duplicate
    ]
    ids = _extract_cat_ids(hrefs)
    # `c42` too short (< 6 digits) — correctly rejected as noise
    assert ids == ["42", "806316219"]


def test_junk_paths_are_not_matched_as_categories():
    """Avoid grabbing product slugs / cart links / random tails that
    happen to contain `c<digits>` mid-word."""
    hrefs = [
        "https://zarafaksa.com/ar/cart",                        # /cart — no id
        "https://zarafaksa.com/ar/latest-products",             # nothing numeric
        "https://zarafaksa.com/ar/some-product-name-2c123456",  # `c123456` NOT after slash
        "https://zarafaksa.com/ar/blog/page-698418654",         # pageId, not category
        "javascript:void(0)",
    ]
    ids = _extract_cat_ids(hrefs)
    assert ids == []


def test_category_id_boundary_end_of_segment():
    """`/c{id}` must terminate at end-of-segment (`/`, `?`, `#`, or EOL) — a
    trailing letter/digit means it's NOT a category id."""
    hrefs = [
        "https://zarafaksa.com/ar/-/c806316219abc",   # trailing letters — reject
        "https://zarafaksa.com/ar/-/c806316219/",     # trailing slash — accept
        "https://zarafaksa.com/ar/-/c806316219#top",  # trailing hash — accept
    ]
    ids = _extract_cat_ids(hrefs)
    assert ids == ["806316219"]  # dedup after the two accepted matches
