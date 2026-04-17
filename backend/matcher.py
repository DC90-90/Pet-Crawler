"""
Daleel Pets — Product Matching Engine
4-level waterfall: Barcode → SKU → Name → Description
CRITICAL: A wrong match is worse than no match.
"""
import re, logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Arabic/English stop words ───────────────────────────────
AR_STOPS = set("في من على إلى عن مع هذا هذه ذلك تلك هو هي هم لا ان أن و ب ال لل كل ما".split())
EN_STOPS = set("the a an and or for with from to in of is at by on it its this that".split())
ALL_STOPS = AR_STOPS | EN_STOPS | {"", "-", "–", "/", "|", ",", ".", "(", ")", "[", "]"}

# Weight/size pattern
WEIGHT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(kg|g|gm|gr|grams?|كجم|جم|جرام|ml|l|liter|litre|oz|lb|lbs|كغ|مل|لتر)', re.IGNORECASE)
NUMERIC_BARCODE_RE = re.compile(r'^\d{8,14}$')


def _is_valid_barcode(val: str) -> bool:
    if not val:
        return False
    return bool(NUMERIC_BARCODE_RE.match(str(val).strip()))


def _tokenize(text: str) -> list:
    if not text:
        return []
    text = re.sub(r'[^\w\s\d\.\-]', ' ', str(text).lower())
    tokens = text.split()
    return [t for t in tokens if t not in ALL_STOPS and len(t) > 1]


def _extract_weight_token(text: str) -> Optional[str]:
    m = WEIGHT_RE.search(str(text))
    if m:
        num = m.group(1)
        unit = m.group(2).lower()
        # Normalize to grams
        if unit in ('kg', 'كجم', 'كغ'):
            return f"{float(num)*1000}g"
        if unit in ('g', 'gm', 'gr', 'gram', 'grams', 'جم', 'جرام'):
            return f"{float(num)}g"
        return f"{num}{unit}"
    return None


def _weights_conflict(w1: Optional[str], w2: Optional[str]) -> bool:
    if not w1 or not w2:
        return False
    try:
        n1 = float(re.search(r'[\d.]+', w1).group())
        n2 = float(re.search(r'[\d.]+', w2).group())
        if n1 == 0 or n2 == 0:
            return False
        ratio = max(n1, n2) / min(n1, n2)
        return ratio > 1.3
    except Exception:
        return False


async def match_my_product(db, my_product: dict, comp_snapshots: list = None, comp_products: dict = None, own_store_id: str = None) -> list:
    """
    Run 4-level matching waterfall for a single my_product against all competitor products.
    Returns list of matches sorted by confidence desc.
    Accepts pre-built lookup tables for batch performance.
    """
    matches = []
    my_sku = str(my_product.get("sku", "")).strip()
    my_barcode = str(my_product.get("barcode", "")).strip()
    my_name_ar = str(my_product.get("name_ar", ""))
    my_name_en = str(my_product.get("name_en", ""))
    my_desc_ar = str(my_product.get("description_ar", ""))
    my_weight = _extract_weight_token(my_name_en) or _extract_weight_token(my_name_ar)

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

    # ── LEVEL 1: Barcode/EAN ────────────────────────────────
    if _is_valid_barcode(my_barcode):
        for snap in comp_snapshots:
            c_sku = str(snap["sku"]).strip()
            if c_sku in blacklist:
                continue
            c_prod = comp_products.get(c_sku, {})
            # Check barcode fields
            c_barcode = str(c_prod.get("barcode", "")).strip()
            c_gtin = str(c_prod.get("gtin", "")).strip()
            c_mpn = str(c_prod.get("mpn", "")).strip()
            # Also check if competitor SKU IS the barcode
            barcode_candidates = [c_barcode, c_gtin, c_mpn, c_sku]
            for candidate in barcode_candidates:
                if _is_valid_barcode(candidate) and candidate == my_barcode:
                    if c_sku in confirmed:
                        conf = 100
                    else:
                        conf = 99
                    weight_mismatch = _weights_conflict(
                        my_weight,
                        _extract_weight_token(c_prod.get("name_en", "") or c_prod.get("name_ar", ""))
                    )
                    matches.append(_build_match(
                        my_product, snap, c_prod, conf, "barcode", weight_mismatch
                    ))
                    matched_skus.add(c_sku)
                    break

    if matched_skus:
        return _dedupe_matches(matches)

    # ── LEVEL 2: SKU Match ──────────────────────────────────
    for snap in comp_snapshots:
        c_sku = str(snap["sku"]).strip()
        if c_sku in blacklist or c_sku in matched_skus:
            continue
        # Exact my_sku == competitor_sku
        if my_sku and c_sku and my_sku == c_sku:
            conf = 100 if c_sku in confirmed else 95
            c_prod = comp_products.get(c_sku, {})
            weight_mismatch = _weights_conflict(
                my_weight,
                _extract_weight_token(c_prod.get("name_en", "") or c_prod.get("name_ar", ""))
            )
            matches.append(_build_match(my_product, snap, c_prod, conf, "sku", weight_mismatch))
            matched_skus.add(c_sku)
            continue
        # My barcode vs competitor SKU (Zid stores use barcode as SKU)
        if _is_valid_barcode(my_barcode) and my_barcode == c_sku:
            conf = 100 if c_sku in confirmed else 95
            c_prod = comp_products.get(c_sku, {})
            weight_mismatch = _weights_conflict(
                my_weight,
                _extract_weight_token(c_prod.get("name_en", "") or c_prod.get("name_ar", ""))
            )
            matches.append(_build_match(my_product, snap, c_prod, conf, "sku_barcode", weight_mismatch))
            matched_skus.add(c_sku)

    if matched_skus:
        return _dedupe_matches(matches)

    # ── LEVEL 3: Name Matching ──────────────────────────────
    my_tokens_ar = _tokenize(my_name_ar)
    my_tokens_en = _tokenize(my_name_en)
    my_all_tokens = set(my_tokens_ar + my_tokens_en)

    if len(my_all_tokens) >= 3:
        for snap in comp_snapshots:
            c_sku = str(snap["sku"]).strip()
            if c_sku in blacklist or c_sku in matched_skus:
                continue
            c_prod = comp_products.get(c_sku, {})
            c_name_ar = str(c_prod.get("name_ar", ""))
            c_name_en = str(c_prod.get("name_en", ""))
            c_tokens = set(_tokenize(c_name_ar) + _tokenize(c_name_en))

            if len(c_tokens) < 3:
                continue

            common = my_all_tokens & c_tokens
            n_common = len(common)

            if n_common < 3:
                continue

            # Require at least 60% overlap of the SMALLER token set
            smaller = min(len(my_all_tokens), len(c_tokens))
            overlap_ratio = n_common / smaller if smaller > 0 else 0
            if overlap_ratio < 0.5:
                continue

            # Check weight conflict → reject
            c_weight = _extract_weight_token(c_name_en) or _extract_weight_token(c_name_ar)
            if _weights_conflict(my_weight, c_weight):
                continue

            # Price sanity: reject if price difference >500% (almost certainly wrong match)
            my_price = float(my_product.get("sale_price") or my_product.get("price") or 0)
            comp_price = float(snap.get("price", 0))
            if my_price > 0 and comp_price > 0:
                ratio = max(my_price, comp_price) / min(my_price, comp_price)
                if ratio > 6:
                    continue

            if n_common >= 5:
                conf = 85
            elif n_common >= 4:
                conf = 80
            else:
                conf = 70

            if c_sku in confirmed:
                conf = 100

            matches.append(_build_match(my_product, snap, c_prod, conf, f"name_{n_common}tok", False))
            matched_skus.add(c_sku)

    if matched_skus:
        return _dedupe_matches(matches)

    # ── LEVEL 4: Description Fallback — DISABLED ─────────────
    # Description matching produces too many false positives with generic pet product descriptions.
    # Keeping only Levels 1-3 for data quality. Level 4 can be re-enabled with stricter token extraction.

    return _dedupe_matches(matches)


def _build_match(my_prod, snap, comp_prod, confidence, method, weight_mismatch, needs_review=False):
    my_price = float(my_prod.get("sale_price") or my_prod.get("price") or 0)
    comp_price = float(snap.get("price", 0))
    diff_sar = round(comp_price - my_price, 2)
    diff_pct = round((diff_sar / my_price) * 100, 1) if my_price > 0 else 0

    flags = []
    if weight_mismatch:
        flags.append("SIZE_MISMATCH")
    if abs(diff_pct) > 40:
        flags.append("SUSPICIOUS_PRICE")
    if needs_review:
        flags.append("NEEDS_REVIEW")

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
                # Check if already confirmed
                existing = await db.product_matches.find_one({
                    "my_sku": my_sku,
                    "competitor_sku": m["competitor_sku"],
                    "competitor_store_id": m["competitor_store_id"],
                    "manually_confirmed": True,
                })
                if existing:
                    continue  # Don't overwrite confirmed matches
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
