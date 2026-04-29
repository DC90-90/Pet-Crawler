"""
Daleel — Product Matching Engine v4
2-level waterfall: Barcode → SKU
Name-based matching has been REMOVED (Feb 2026, by user request).
CRITICAL: A wrong match is worse than no match.
"""
import re, logging
from typing import Optional
from datetime import datetime, timezone

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
PACK_AR_RE = re.compile(r'(?:علبة|كرتون|عدد|طقم|مجموعة)\s*(\d+)', re.IGNORECASE)
PACK_KEYWORDS = {"pack", "carton", "box", "set", "bundle", "علبة", "كرتون", "عدد", "طقم"}

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
    """Extract pack/bundle quantity from text. Returns 1 if single unit."""
    for pattern in [PACK_RE, PACK_AR_RE]:
        m = pattern.search(str(text))
        if m:
            return int(m.group(1))
    text_lower = str(text).lower()
    if any(kw in text_lower for kw in PACK_KEYWORDS):
        return -1  # Has pack keyword but unknown quantity
    return 1  # Single unit


def _is_bundle_sku(sku: str) -> bool:
    """Fix 3: Check if SKU has bundle/pack suffix."""
    sku_lower = str(sku).lower()
    return any(sku_lower.endswith(s) for s in SKU_BUNDLE_SUFFIXES)


def _has_pack_indicator(text: str) -> bool:
    """Check if text contains any pack/bundle indicator."""
    text_lower = str(text).lower()
    return bool(PACK_RE.search(text_lower) or PACK_AR_RE.search(text_lower) or
                any(kw in text_lower for kw in PACK_KEYWORDS))


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

    # Barcode candidates from MY product: explicit barcode + numeric SKU
    my_barcode_candidates = set()
    if _is_valid_barcode(my_barcode):
        my_barcode_candidates.add(my_barcode)
    if _is_numeric_sku(my_sku):
        my_barcode_candidates.add(my_sku)

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
    if my_barcode_candidates and not my_is_bundle:
        for snap in comp_snapshots:
            c_sku = str(snap["sku"]).strip()
            if c_sku in blacklist:
                continue
            c_prod = comp_products.get(c_sku, {})
            c_barcode = str(c_prod.get("barcode", "")).strip()
            c_gtin = str(c_prod.get("gtin", "")).strip()
            c_mpn = str(c_prod.get("mpn", "")).strip()
            comp_barcode_candidates = set()
            for v in (c_barcode, c_gtin, c_mpn, c_sku):
                if _is_valid_barcode(v):
                    comp_barcode_candidates.add(v)
            common_barcodes = my_barcode_candidates & comp_barcode_candidates
            if not common_barcodes:
                continue
            c_name = _get_comp_name(c_prod)
            # Pack compatibility
            if not _pack_compatible(my_name_full, c_name):
                continue
            # Weight strict — barcode matches still must have weight match (or both unknown)
            c_weight_g = _extract_weight_grams(c_name)
            if _weights_reject(my_weight_g, c_weight_g):
                continue
            # Price-ratio sanity for barcode matches: ≤ 2.0× (catches mis-tagged barcodes)
            my_price = float(my_product.get("sale_price") or my_product.get("price") or 0)
            comp_price = float(snap.get("price", 0))
            if my_price > 0 and comp_price > 0:
                ratio = max(my_price, comp_price) / min(my_price, comp_price)
                if ratio > 2.0:
                    continue
            conf = 100 if c_sku in confirmed else 99
            matches.append(_build_match(my_product, snap, c_prod, conf, "barcode"))
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

        # Price-ratio sanity for SKU matches: ≤ 1.5×
        my_price = float(my_product.get("sale_price") or my_product.get("price") or 0)
        comp_price = float(snap.get("price", 0))
        if my_price > 0 and comp_price > 0:
            ratio = max(my_price, comp_price) / min(my_price, comp_price)
            if ratio > 1.5:
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
    if abs(diff_pct) > 40:
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
    """Pre-build competitor snapshot and product lookups ONCE for batch matching."""
    pipeline = [
        {"$sort": {"crawled_at": -1}},
        {"$group": {
            "_id": {"sku": "$sku", "store_id": "$store_id"},
            "sku": {"$first": "$sku"},
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
    if own_store_id:
        pipeline.insert(0, {"$match": {"store_id": {"$ne": own_store_id}}})

    snapshots = await db.product_snapshots.aggregate(pipeline).to_list(100000)
    products = {}
    async for p in db.products.find({}, {"_id": 0}):
        products[p["sku"]] = p
    logger.info(f"[Matching] Built lookups: {len(snapshots)} snapshots, {len(products)} products")
    return snapshots, products


async def run_matching_for_all(db, progress_callback=None):
    """Run matching engine for ALL my_products. Returns summary stats."""
    my_products = await db.my_products.find({}, {"_id": 0}).to_list(5000)
    total = len(my_products)
    stats = {"total": total, "matched": 0, "unmatched": 0, "total_matches": 0}

    # Pre-build lookups ONCE
    own_store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1})
    own_store_id = own_store["id"] if own_store else None
    comp_snapshots, comp_products = await _build_competitor_lookups(db, own_store_id)

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
