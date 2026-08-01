"""
Daleel — Product Matching Engine v4
2-level waterfall: Barcode → SKU
Name-based matching has been REMOVED (Feb 2026, by user request).
CRITICAL: A wrong match is worse than no match.
"""
import re, logging
from typing import Optional
from datetime import datetime, timezone, timedelta

from core.utils import canonical_barcode

# iter22 (Jul 2026): candidate snapshots for matching are bounded to this
# window. Nothing older should influence a match, and the bound is what lets
# the lookup aggregation survive production scale (~1M+ snapshot docs).
MATCH_WINDOW_DAYS = 14

logger = logging.getLogger(__name__)

# ── Stop words ──────────────────────────────────────────────
AR_STOPS = set("في من على إلى عن مع هذا هذه ذلك تلك هو هي هم لا ان أن و ب ال لل كل ما".split())
EN_STOPS = set("the a an and or for with from to in of is at by on it its this that".split())
ALL_STOPS = AR_STOPS | EN_STOPS | {"", "-", "–", "/", "|", ",", ".", "(", ")", "[", "]"}

# ── Patterns ────────────────────────────────────────────────
WEIGHT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(kg|g|gm|gr|grams?|كجم|جم|جرام|ml|l|liter|litre|oz|lb|lbs|كغ|مل|لتر)', re.IGNORECASE)
NUMERIC_BARCODE_RE = re.compile(r'^\d{8,14}$')

# Pack/bundle patterns
PACK_RE = re.compile(r'(?:pack\s*(?:of\s*)?|carton\s*(?:for\s*)?|box\s*(?:of\s*)?|set\s*(?:of\s*)?|bundle\s*(?:of\s*)?|×\s*)(\d+)', re.IGNORECASE)
PACK_AR_RE = re.compile(r'(?:علبة|عبوة|كرتون|عدد|طقم|مجموعة)\s*(\d+)', re.IGNORECASE)

# iter51 — COUNT-FIRST pack descriptors. Everything above expects
# "<keyword> N" ("pack of 24", "علبة 24"), but real catalogue names put the
# count first and never use a keyword at all:
#
#   "Beso Cat Wet Food ... 24 Pieces*400g"   -> 24
#   "Kit Cat Wet Food ... 24 Pieces*70g"     -> 24
#   "... 24 Pcs" / "24 x 400g" / "24*70g" / "24-pack" / "24 قطعة"
#
# Those all parsed as qty=1 (a single unit), so a 24-count carton compared
# clean against a single tin of the same EAN and the pack guard never fired.
# The `×` branch in PACK_RE could not help: it needs U+00D7 specifically AND
# expects the digits AFTER the sign, so even "24×400g" missed.
#
# Anchored on a number so brand names can't false-fire ("One Piece" has no
# leading digit). The multiplier branch requires a WEIGHT unit after the
# second number, so dimensions like "40 x 60 cm" are not read as a 40-pack.
PACK_COUNT_FIRST_RE = re.compile(
    r'(?<!\d)(\d{1,3})\s*(?:'
    r'[-\s]*(?:pieces?|pcs?|packs?|units?|tins?|cans?|sachets?|pouches?)\b'
    r'|[x×*]\s*\d+(?:\.\d+)?\s*(?:kg|g|gm|gr|ml|l|كجم|جم|جرام|مل|لتر)\b'
    r')', re.IGNORECASE)
PACK_COUNT_FIRST_AR_RE = re.compile(
    r'(?<!\d)(\d{1,3})\s*(?:قطعة|قطع|حبة|حبات|كيس|أكياس|ظرف|أظرف)')
# the reversed multiplier: "400g x 24", "1.5kg*6"
PACK_UNIT_FIRST_RE = re.compile(
    r'\d+(?:\.\d+)?\s*(?:kg|g|gm|gr|ml|l|كجم|جم|جرام|مل|لتر)\s*[x×*]\s*(\d{1,3})(?!\d)',
    re.IGNORECASE)

# Every pattern that yields an explicit pack COUNT, in precedence order.
#
# The count-first patterns MUST be tried before PACK_RE. PACK_RE's bare
# `×\s*(\d+)` branch takes the number AFTER the sign, which in the very common
# "N×M<unit>" form is the UNIT SIZE, not the count: it read "24×400g" as a
# 400-pack. The count-first patterns anchor on the number before the sign and
# require a weight unit after it, so they resolve that shape correctly and
# PACK_RE still catches the keyword forms ("pack of 6", "Carton 24", "×24").
PACK_QTY_PATTERNS = (PACK_COUNT_FIRST_RE, PACK_COUNT_FIRST_AR_RE,
                     PACK_UNIT_FIRST_RE, PACK_RE, PACK_AR_RE)
PACK_KEYWORDS = {"pack", "carton", "box", "set", "bundle", "علبة", "كرتون", "عدد", "طقم"}
# Token boundary regex used by _has_pack_indicator. Splits on whitespace and
# common punctuation. We deliberately exclude letter characters so compound
# Arabic words like "متعددة" (= "multiple") stay as one token instead of
# being split around an embedded "عدد" substring. See iter20 bug fix.
PACK_TOKEN_SPLIT_RE = re.compile(r'[\s\-_/|,.;:()\[\]×]+')

# SKU suffix patterns
SKU_BUNDLE_SUFFIXES = ("pack", "carton", "box", "set", "bundle", "pcs", "multi")

# Known brand list (English + Arabic transliterations) — used to enforce brand match in name fallback
KNOWN_BRANDS_LOWER = [
    "royal canin", "رويال كانين", "whiskas", "ويسكاس", "pedigree", "بيدقري",
    "purina", "بورينا", "hill's", "hills", "هيلز", "n&d", "orijen", "اوريجن", "acana", "اكانا",
    "friskies", "فريسكيز", "me-o", "مي-او", "kong", "كونغ", "furminator", "فرمينيتور",
    "frontline", "فرونت لاين", "versele-laga", "فيرسيل", "catit", "oxbow", "tetra",
    "virbac", "ever clean", "josera", "brit", "schesir", "gimcat", "trixie", "beaphar",
    "perfect fit", "sheba", "fancy feast", "iams", "wellness", "natural balance",
    "advance", "applaws", "cesar", "felix", "almo nature", "arden grange",
]


def _is_valid_barcode(val: str) -> bool:
    if not val:
        return False
    return bool(NUMERIC_BARCODE_RE.match(str(val).strip()))


def _is_numeric_sku(val: str) -> bool:
    """Treat numeric SKU (8-14 digits) as a barcode/EAN candidate."""
    return _is_valid_barcode(val)


# ── iter61: canonical barcode keys ──────────────────────────
# Level 1 used to intersect RAW strings:
#     {"052742059518"} & {"52742059518"} == set()
# — the same GTIN written as UPC-A and as EAN, and the exact pair iter47 was
# written to fix. iter47's normalization lived in crawlers.py and was reachable
# only from the own-store price-resolution path, so the matcher never saw it.
# Here the same helper canonicalises BOTH sides to GTIN-14 before comparing.
#
# This widens the KEY SPACE only. Every downstream guard is untouched:
# _pack_compatible, _weights_reject and barcode_price_sane all still run on each
# surviving candidate, so a 6x price gap with no pack corroboration is still
# rejected exactly as in iter53.
def _barcode_key_set(barcodes=(), skus=()):
    """Comparable keys for one side of a candidate pair.

    The two argument groups are deliberately NOT treated the same:

    barcodes  a barcode/gtin/mpn FIELD. Suffix variants are expected here — the
              own catalogue carries "9003579308936carton" for a case pack that
              shares the unit EAN (iter45) — so the leading 8-14 digit run is
              canonicalised even when the whole string is not numeric.
    skus      a SKU FIELD. Only admitted when the WHOLE string is a valid
              barcode, which is the pre-existing _is_numeric_sku gate. A
              merchant SKU like "12345678-BLK" must NOT be read as a GTIN with a
              suffix, or every store's internal numbering becomes a key.

    The 8-digit floor keeps short numeric SKUs ("15", "4021") out entirely, so
    canonicalisation cannot collide two unrelated small-numbered products.
    """
    keys = set()
    for v in barcodes:
        s = str(v or "").strip()
        if not s:
            continue
        if _is_valid_barcode(s):
            keys.add(s.lower())
        k = canonical_barcode(s)        # tolerates a trailing variant suffix
        if k:
            keys.add(k)
    for v in skus:
        s = str(v or "").strip()
        if _is_valid_barcode(s):        # whole string, no suffix tolerance
            keys.add(s.lower())
            keys.add(canonical_barcode(s))
    return keys


def _tokenize(text: str) -> list:
    if not text:
        return []
    text = re.sub(r'[^\w\s\d\.\-]', ' ', str(text).lower())
    tokens = text.split()
    return [t for t in tokens if t not in ALL_STOPS and len(t) > 1]


def _extract_brand(text: str) -> Optional[str]:
    """Return the canonical brand if the text contains a known brand, else None."""
    if not text:
        return None
    t = str(text).lower()
    for b in KNOWN_BRANDS_LOWER:
        if b in t:
            return b
    return None


def _extract_weight_grams(text: str) -> Optional[float]:
    """Extract weight from text, normalized to grams. Returns None if no weight found."""
    m = WEIGHT_RE.search(str(text))
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2).lower()
    if unit in ('kg', 'كجم', 'كغ'):
        return num * 1000
    if unit in ('g', 'gm', 'gr', 'gram', 'grams', 'جم', 'جرام'):
        return num
    if unit in ('ml', 'مل'):
        return num
    if unit in ('l', 'liter', 'litre', 'لتر'):
        return num * 1000
    if unit == 'oz':
        return num * 28.35
    if unit in ('lb', 'lbs'):
        return num * 453.59
    return num


def _extract_pack_qty(text: str) -> int:
    """Extract pack/bundle quantity from text. Returns 1 if single unit.

    NOTE on semantics (pre-existing, deliberately preserved): a name with no
    pack signal at all returns 1, i.e. "no descriptor" is read as "single".
    That is what makes the guard conservative — a 24-count carton compared
    against a competitor whose name says nothing is BLOCKED rather than
    assumed compatible. -1 is reserved for "pack keyword present, count
    unreadable".
    """
    for pattern in PACK_QTY_PATTERNS:
        m = pattern.search(str(text))
        if m:
            return int(m.group(1))
    # iter51 — TOKEN-level keyword test, matching _has_pack_indicator. This
    # function still used naive substring matching, so iter20's bug lived on
    # here: "متعدد الألوان" (multi-COLOURED) contains "عدد" and returned -1,
    # which _pack_compatible reads as "unknown multipack" and uses to block
    # every single-unit competitor. That mattered less while Level 1 gated on
    # _has_pack_indicator; now that _pack_compatible is the sole filter there,
    # the two must agree.
    tokens = [t for t in PACK_TOKEN_SPLIT_RE.split(str(text).lower()) if t]
    if any(t in PACK_KEYWORDS for t in tokens):
        return -1  # Has pack keyword but unknown quantity
    return 1  # Single unit


def _is_bundle_sku(sku: str) -> bool:
    """Fix 3: Check if SKU has bundle/pack suffix."""
    sku_lower = str(sku).lower()
    return any(sku_lower.endswith(s) for s in SKU_BUNDLE_SUFFIXES)


def _has_pack_indicator(text: str) -> bool:
    """Check if text contains any pack/bundle indicator.

    Bug fix (Feb 2026, iter20): the previous implementation used naive
    substring matching (`kw in text_lower`), which false-fired on Arabic
    words containing PACK_KEYWORDS as substrings — most notably "عدد"
    appearing inside "متعدد الألوان" (= "multi-colored", a color descriptor,
    NOT a multipack indicator). This affected 58 of 2,466 my_products
    (2.4%) — see test_matcher_pack_indicator.py for the exhaustive list.
    Suppressing barcode-level matching for those products silently masked
    real competitor links (e.g. Beaphar 8711231124985 had 0 matches because
    "متعددة" in the Arabic name false-triggered as a multipack).

    Fix: tokenize on whitespace and common punctuation, then check
    keyword membership at the TOKEN level. Compound words like "متعددة",
    "Backpack", "Subscription Box", "كرتونية" stay as one token and are
    not in PACK_KEYWORDS, so they don't false-fire. Legitimate multipack
    phrasing ("pack of 6", "علبة 12", "Carton 24") still matches because
    "pack" / "علبة" / "Carton" appear as standalone tokens.

    iter51 — also recognises the count-first descriptors ("24 Pieces*400g",
    "24 Pcs", "24 x 400g", "24 قطعة"), which carry no PACK_KEYWORDS token at
    all and so read as single units before this change.
    """
    text_lower = str(text).lower()
    if any(p.search(text_lower) for p in PACK_QTY_PATTERNS):
        return True
    tokens = [t for t in PACK_TOKEN_SPLIT_RE.split(text_lower) if t]
    return any(t in PACK_KEYWORDS for t in tokens)


# iter53 — BARCODE RELIABILITY.
#
# An EAN identifies a TRADE ITEM, and manufacturers routinely print the unit
# barcode on the multipack too. So the same EAN legitimately appears on a single
# 400g tin (~8 SAR) and on a 24-tin carton (~208 SAR). Barcode equality is then
# still "correct" — and still pairs two products that are not substitutes,
# producing the +2400% gaps on the Zarafa cluster.
#
# Rule: a >=6x price gap on a barcode match makes the BARCODE unreliable for
# that pair, not the price wrong. The match then needs positive corroboration
# that the two are the same pack size; absent that, it is dropped.
#
# 6x is deliberately far outside retail discounting. A 74%-off sale is 3.85x;
# even 80% off is only 5x. Crossing 6x means an 83%+ discount, which is rarer
# than the pack-collision it is being confused with.
BARCODE_PRICE_RATIO_MAX = 6.0
_NAME_CORROBORATION_MIN = 0.75


def _pack_qty_explicit(text: str) -> Optional[int]:
    """Pack count ONLY when a real descriptor says so.

    _extract_pack_qty returns 1 for a name that says nothing about packaging,
    conflating "a single unit" with "unstated". That conflation is safe for
    _pack_compatible (it errs toward blocking) but useless as CORROBORATION:
    two silent names agreeing on "1" is absence of evidence, not evidence of
    agreement — and it is exactly the Butcher's shape, where both sides read
    "400g" and neither mentions the carton.
    """
    for pattern in PACK_QTY_PATTERNS:
        m = pattern.search(str(text))
        if m:
            return int(m.group(1))
    return None


def _name_similarity(a: str, b: str) -> float:
    """Jaccard overlap of significant tokens."""
    ta, tb = set(_tokenize(a)), set(_tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _names_are_independent(a: str, b: str) -> bool:
    """Whether two names carry independent information.

    db.products holds ONE row per SKU shared by every store, so a competitor's
    "name" for a colliding EAN is frequently our own catalogue string echoed
    back. Byte-identical names therefore corroborate nothing — they are the same
    document, not two sources agreeing.
    """
    na = " ".join(sorted(_tokenize(a)))
    nb = " ".join(sorted(_tokenize(b)))
    return bool(na) and bool(nb) and na != nb


def barcode_price_sane(my_price, comp_price, my_name, comp_name):
    """(ok, reason) for a barcode-matched pair.

    Symmetric in the two sides: which one is cheaper is irrelevant, only the
    magnitude of the gap matters.
    """
    try:
        p1, p2 = float(my_price or 0), float(comp_price or 0)
    except (TypeError, ValueError):
        return True, None
    if p1 <= 0 or p2 <= 0:
        return True, None                       # no price to judge on
    ratio = max(p1, p2) / min(p1, p2)
    if ratio < BARCODE_PRICE_RATIO_MAX:
        return True, None                       # normal discounting range

    q1, q2 = _pack_qty_explicit(my_name), _pack_qty_explicit(comp_name)
    if q1 is not None and q2 is not None:
        # both sides STATE a pack size: that settles it either way. A
        # disagreement is positive evidence of different products and must not
        # be overridden by name similarity — the names of a 24-pack and a
        # 6-pack of the same product are nearly identical by construction.
        if q1 == q2:
            return True, "pack_qty_agrees"
        return False, f"pack_qty_differs_{q1}_vs_{q2}"
    if (_names_are_independent(my_name, comp_name)
            and _name_similarity(my_name, comp_name) >= _NAME_CORROBORATION_MIN):
        return True, "name_corroborated"
    return False, f"shared_barcode_price_ratio_{ratio:.1f}x"


def _weights_reject(w1_g: Optional[float], w2_g: Optional[float]) -> bool:
    """Fix 2: Strict weight enforcement — reject if >10% difference."""
    if w1_g is None or w2_g is None:
        return False
    if w1_g == 0 or w2_g == 0:
        return False
    ratio = max(w1_g, w2_g) / min(w1_g, w2_g)
    return ratio > 1.10  # >10% difference = REJECT


def _pack_compatible(my_text: str, comp_text: str) -> bool:
    """Fix 1: Check if pack configurations are compatible."""
    my_qty = _extract_pack_qty(my_text)
    comp_qty = _extract_pack_qty(comp_text)

    # My product is a multi-pack
    if my_qty > 1 or my_qty == -1:
        # Competitor must also be a multi-pack with matching qty
        if comp_qty == 1:
            return False  # Single unit can never match multi-pack
        if my_qty > 1 and comp_qty > 1 and my_qty != comp_qty:
            return False  # Different pack sizes

    # Competitor is a multi-pack but I'm single
    if comp_qty > 1 and my_qty == 1:
        return False

    return True


async def match_my_product(db, my_product: dict, comp_snapshots: list = None, comp_products: dict = None, own_store_id: str = None) -> list:
    """Run 3-level matching waterfall for a single my_product."""
    matches = []
    my_sku = str(my_product.get("sku", "")).strip()
    my_barcode = str(my_product.get("barcode", "")).strip()
    my_name_ar = str(my_product.get("name_ar", ""))
    my_name_en = str(my_product.get("name_en", ""))
    my_name_full = f"{my_name_ar} {my_name_en}"
    my_weight_g = _extract_weight_grams(my_name_en) or _extract_weight_grams(my_name_ar)
    my_is_bundle = _is_bundle_sku(my_sku) or _has_pack_indicator(my_name_full)

    # Barcode candidates from MY product: explicit barcode + numeric SKU.
    # iter61 — both go through _barcode_key_set, which adds the GTIN-14 form.
    # The SKU is still admitted only when the whole string is a barcode, which
    # is what makes this a cross-match in both directions: our barcode can meet
    # their SKU and our SKU can meet their barcode.
    my_barcode_candidates = _barcode_key_set(barcodes=(my_barcode,), skus=(my_sku,))
    # lowercased to compare against the key set, which is lowercased throughout
    my_literal_candidates = {v.lower() for v in (my_barcode, my_sku) if _is_valid_barcode(v)}

    # Get blacklisted matches
    blacklist = set()
    async for bl in db.match_blacklist.find({"my_sku": my_sku}, {"_id": 0, "competitor_sku": 1}):
        blacklist.add(bl["competitor_sku"])

    # Get manually confirmed matches
    confirmed = {}
    async for cm in db.product_matches.find({"my_sku": my_sku, "manually_confirmed": True}, {"_id": 0, "competitor_sku": 1}):
        confirmed[cm["competitor_sku"]] = True

    if comp_snapshots is None or comp_products is None:
        own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
        own_store_id = own_store["id"] if own_store else None
        comp_snapshots, comp_products = await _build_competitor_lookups(db, own_store_id)

    matched_skus = set()

    def _get_comp_name(c_prod):
        return f"{c_prod.get('name_ar', '')} {c_prod.get('name_en', '')}"

    # ── LEVEL 1: Barcode/EAN ────────────────────────────────
    # Barcode match if EITHER my barcode-candidates intersect competitor barcode-candidates
    #
    # iter51 — this used to be `and not my_is_bundle`: a multipack was banned
    # from barcode matching WHOLESALE, because cartons share the unit EAN. With
    # pack counts now parsed on both sides, _pack_compatible below filters
    # per-candidate instead, which is strictly better:
    #   24-pack vs single  -> still blocked (a name with no descriptor reads
    #                         as qty 1, so unknown competitors stay blocked)
    #   24-pack vs 24-pack -> now MATCHES, where before the carton could not
    #                         barcode-match anything at all.
    if my_barcode_candidates:
        for snap in comp_snapshots:
            c_sku = str(snap["sku"]).strip()
            if c_sku in blacklist:
                continue
            c_prod = comp_products.get(c_sku, {})
            # iter61 — `snap.barcode` is the per-store observation. db.products
            # holds ONE row per SKU shared by every store (first writer wins),
            # so the snapshot is the only place a second store's barcode for the
            # same SKU string survives.
            comp_barcode_candidates = _barcode_key_set(
                barcodes=(snap.get("barcode"), c_prod.get("barcode"),
                          c_prod.get("gtin"), c_prod.get("mpn")),
                skus=(c_sku,))
            common_barcodes = my_barcode_candidates & comp_barcode_candidates
            if not common_barcodes:
                continue
            # Literal equality means the raw strings already agreed; anything
            # else was recovered by canonicalisation. Recorded as a SEPARATE
            # field rather than a new match_method value, so that the existing
            # `match_method == "barcode"` contract every downstream consumer
            # relies on is untouched, and the effect of this change is still
            # measurable in product_matches after a re-run.
            barcode_key = ("literal" if (my_literal_candidates & comp_barcode_candidates)
                           else "gtin14")
            c_name = _get_comp_name(c_prod)
            # Pack compatibility
            if not _pack_compatible(my_name_full, c_name):
                continue
            # Weight strict — barcode matches still must have weight match (or both unknown)
            c_weight_g = _extract_weight_grams(c_name)
            if _weights_reject(my_weight_g, c_weight_g):
                continue
            # iter21 (Feb 2026) — REMOVED the previous "price ratio > 2.0 →
            # skip" hard-reject for barcode matches. Rationale: barcode/EAN
            # equality is definitive proof of same-product (that's the whole
            # point of an international barcode). A price gap doesn't disprove
            # sameness — it usually means one side runs a deep discount or the
            # other side is at MRP. Aggressive user discounts (e.g. Carnilove
            # 2.93 SAR vs market 13–22 SAR) were being silently dropped from
            # product_matches, breaking Price Intel and Market Position for
            # every product they discounted. No new flag is added for L1
            # either — a mis-tagged barcode is a crawler ingestion bug to
            # fix at source, not a per-match annotation to spam every day.
            # iter53 — barcode reliability. The comment above is right that a
            # price gap does not disprove sameness for a TRUE barcode match, and
            # that hard-rejecting on ratio killed real discounts. This check is
            # narrower: it fires only past 6x — beyond any retail discount — and
            # even then only drops the pair when NOTHING corroborates that the
            # two are the same pack size. Manually confirmed matches are exempt.
            if c_sku not in confirmed:
                _ok, _why = barcode_price_sane(
                    my_product.get("sale_price") or my_product.get("price"),
                    snap.get("price"), my_name_full, c_name)
                if not _ok:
                    logger.info(
                        "[Matching] barcode match dropped my_sku=%s comp_sku=%s "
                        "store=%s reason=%s", my_sku, c_sku,
                        snap.get("store_name"), _why)
                    continue
            conf = 100 if c_sku in confirmed else 99
            m = _build_match(my_product, snap, c_prod, conf, "barcode")
            m["barcode_key"] = barcode_key
            matches.append(m)
            matched_skus.add(c_sku)

    if matched_skus:
        return _dedupe_matches(matches)

    # ── LEVEL 2: SKU Match ──────────────────────────────────
    for snap in comp_snapshots:
        c_sku = str(snap["sku"]).strip()
        if c_sku in blacklist or c_sku in matched_skus:
            continue
        c_prod = comp_products.get(c_sku, {})
        c_name = _get_comp_name(c_prod)

        matched = False
        # Exact SKU match
        if my_sku and c_sku and my_sku == c_sku:
            matched = True

        if not matched:
            continue

        # Bundle SKU → competitor must also be bundle
        if my_is_bundle and not _has_pack_indicator(c_name):
            continue

        # Pack compatibility
        if not _pack_compatible(my_name_full, c_name):
            continue

        # Strict weight
        c_weight_g = _extract_weight_grams(c_name)
        if _weights_reject(my_weight_g, c_weight_g):
            continue

        # iter21 (Feb 2026) — REPLACED the previous "price ratio > 1.5 →
        # skip" hard-reject with the existing SUSPICIOUS_PRICE flag surfaced
        # by _build_match (fires when abs(diff_pct) > 40%). SKU-string
        # equality is a weaker signal than barcode equality — SKUs are
        # proprietary strings, so a large price gap on a Level-2 match is
        # genuinely worth annotating. But we no longer HIDE the match:
        # user's real competitors land in product_matches, and the flag
        # gives the UI a subtle "review this" indicator.
        # iter53 — the Level-1 drop alone is not enough. These stores put the
        # EAN in the SKU field, so a pair rejected as a barcode collision falls
        # straight through to this exact-SKU path and matches anyway. Apply the
        # same check whenever the matched SKU IS a barcode; a proprietary SKU
        # string carries no trade-item ambiguity and is left alone.
        if c_sku not in confirmed and _is_valid_barcode(c_sku):
            _ok, _why = barcode_price_sane(
                my_product.get("sale_price") or my_product.get("price"),
                snap.get("price"), my_name_full, c_name)
            if not _ok:
                logger.info(
                    "[Matching] EAN-shaped SKU match dropped my_sku=%s comp_sku=%s "
                    "store=%s reason=%s", my_sku, c_sku, snap.get("store_name"), _why)
                continue
        conf = 100 if c_sku in confirmed else 95
        matches.append(_build_match(my_product, snap, c_prod, conf, "sku"))
        matched_skus.add(c_sku)

    if matched_skus:
        return _dedupe_matches(matches)

    # ── LEVEL 3: REMOVED (Feb 2026) ─────────────────────────
    # Name-based matching has been disabled per user request: too many false
    # positives (e.g., "Royal Canin SHN Mini Junior 4kg" being matched to
    # unrelated 209 SAR products with only 80% name overlap).
    # We now only match on Barcode/EAN (Level 1) or exact SKU (Level 2).
    return _dedupe_matches(matches)


def _build_match(my_prod, snap, comp_prod, confidence, method):
    my_price = float(my_prod.get("sale_price") or my_prod.get("price") or 0)
    comp_price = float(snap.get("price", 0))
    diff_sar = round(comp_price - my_price, 2)
    diff_pct = round((diff_sar / my_price) * 100, 1) if my_price > 0 else 0

    flags = []
    # iter21 (Feb 2026): SUSPICIOUS_PRICE flag fires only for Level-2 (SKU
    # string) matches. Barcode/EAN equality is definitive same-product
    # evidence, so a large price gap on a barcode match is legitimate
    # discount noise (aggressive user discount OR competitor at MRP), not
    # a data-quality signal. SKU-string equality is weaker so a >40% gap
    # is genuinely worth annotating for the user's review.
    if method == "sku" and abs(diff_pct) > 40:
        flags.append("SUSPICIOUS_PRICE")

    return {
        "my_sku": str(my_prod.get("sku", "")),
        "my_name_ar": my_prod.get("name_ar", ""),
        "my_name_en": my_prod.get("name_en", ""),
        "my_price": my_price,
        "competitor_sku": str(snap["sku"]),
        "competitor_name": comp_prod.get("name_ar", "") or comp_prod.get("name_en", ""),
        "competitor_store_id": snap["store_id"],
        "competitor_store_name": snap.get("store_name", ""),
        "competitor_price": comp_price,
        "competitor_original_price": float(snap.get("original_price", comp_price)),
        "competitor_in_stock": snap.get("in_stock", False),
        "competitor_qty": snap.get("qty_available", 0),
        "diff_sar": diff_sar,
        "diff_pct": diff_pct,
        "position": "cheaper" if diff_sar > 0 else ("equal" if diff_sar == 0 else "expensive"),
        "confidence": confidence,
        "match_method": method,
        "flags": flags,
        "crawled_at": snap.get("crawled_at"),
    }


def _dedupe_matches(matches):
    """Keep best match per competitor store (highest confidence)."""
    best = {}
    for m in matches:
        key = (m["competitor_sku"], m["competitor_store_id"])
        if key not in best or m["confidence"] > best[key]["confidence"]:
            best[key] = m
    return sorted(best.values(), key=lambda x: -x["confidence"])


async def _build_competitor_lookups(db, own_store_id):
    """Pre-build competitor snapshot and product lookups ONCE for batch matching.

    iter22 (Jul 2026) — PRODUCTION-SCALE FIX. The previous pipeline ran
    $sort + $group over the ENTIRE product_snapshots collection (no time
    bound, no allowDiskUse). At production volume (~1M+ docs) it exceeded
    MongoDB's 100MB in-memory stage limit and threw on every run — the
    matcher had zero successful production runs since 2026-04-17. Fix:
      1. $match bounds candidates to the last MATCH_WINDOW_DAYS days —
         the range on crawled_at also lets the $sort ride the
         (crawled_at, -1) index instead of sorting in memory.
      2. allowDiskUse=True as a spill safety net for the $group stage.
    Matching LOGIC is unchanged — same fields, same latest-per-(sku,store)
    contract via $sort desc + $first.
    """
    since = datetime.now(timezone.utc) - timedelta(days=MATCH_WINDOW_DAYS)
    match_stage = {"crawled_at": {"$gte": since}}
    if own_store_id:
        match_stage["store_id"] = {"$ne": own_store_id}
    pipeline = [
        {"$match": match_stage},
        {"$sort": {"crawled_at": -1}},
        {"$group": {
            "_id": {"sku": "$sku", "store_id": "$store_id"},
            "sku": {"$first": "$sku"},
            # iter61 — the per-store barcode observation, now that the crawler
            # persists it. Level 1 has no other source for a competitor's
            # barcode: db.products is shared across stores.
            "barcode": {"$first": "$barcode"},
            "store_id": {"$first": "$store_id"},
            "store_name": {"$first": "$store_name"},
            "price": {"$first": "$price"},
            "original_price": {"$first": "$original_price"},
            "in_stock": {"$first": "$in_stock"},
            "qty_available": {"$first": "$qty_available"},
            "source_tier": {"$first": "$source_tier"},
            "crawled_at": {"$first": "$crawled_at"},
        }},
    ]

    snapshots = await db.product_snapshots.aggregate(pipeline, allowDiskUse=True).to_list(100000)
    products = {}
    async for p in db.products.find({}, {"_id": 0}):
        products[p["sku"]] = p
    logger.info(f"[Matching] Built lookups: {len(snapshots)} snapshots, {len(products)} products")
    return snapshots, products


async def run_matching_for_all(db, progress_callback=None):
    """Run matching engine for ALL my_products. Returns summary stats."""
    # Hardening (Feb 2026): only run matching for items explicitly tagged as own-store.
    own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
    own_store_id = own_store["id"] if own_store else None

    mp_query = {"is_own_store": True}
    if own_store_id:
        mp_query["store_id"] = own_store_id

    my_products = await db.my_products.find(mp_query, {"_id": 0}).to_list(5000)
    # Fallback for legacy data with no flags — still match, but log a warning
    if not my_products:
        legacy = await db.my_products.find({}, {"_id": 0}).to_list(5000)
        if legacy:
            logger.warning(
                f"[Matching] No my_products tagged with is_own_store=True; "
                f"falling back to all {len(legacy)} my_products. Re-tag the catalog to silence this warning."
            )
        my_products = legacy
    total = len(my_products)
    stats = {"total": total, "matched": 0, "unmatched": 0, "total_matches": 0}

    # Pre-build lookups ONCE
    comp_snapshots, comp_products = await _build_competitor_lookups(db, own_store_id)

    # iter22 safety guard: an empty candidate pool means the crawlers have
    # produced NO snapshots inside the match window (stale/down/blocked).
    # Rebuilding against it would wipe every non-confirmed match. Abort loudly
    # instead — the error lands in sync_runs and the data-freshness alarm.
    if not comp_snapshots:
        raise RuntimeError(
            f"Refusing to rebuild product_matches: 0 competitor snapshots in the last "
            f"{MATCH_WINDOW_DAYS} days (crawlers stale or down). Existing matches left untouched."
        )

    for i, mp in enumerate(my_products):
        matches = await match_my_product(db, mp, comp_snapshots, comp_products, own_store_id)
        my_sku = str(mp.get("sku", ""))

        # Remove old non-confirmed matches
        await db.product_matches.delete_many({"my_sku": my_sku, "manually_confirmed": {"$ne": True}})

        if matches:
            stats["matched"] += 1
            stats["total_matches"] += len(matches)
            for m in matches:
                m["matched_at"] = datetime.now(timezone.utc).isoformat()
                m["manually_confirmed"] = False
                existing = await db.product_matches.find_one({
                    "my_sku": my_sku,
                    "competitor_sku": m["competitor_sku"],
                    "competitor_store_id": m["competitor_store_id"],
                    "manually_confirmed": True,
                })
                if existing:
                    continue
                await db.product_matches.update_one(
                    {"my_sku": my_sku, "competitor_sku": m["competitor_sku"], "competitor_store_id": m["competitor_store_id"]},
                    {"$set": m},
                    upsert=True,
                )
        else:
            stats["unmatched"] += 1

        if progress_callback and (i + 1) % 100 == 0:
            await progress_callback(i + 1, total)

    return stats
