"""Mahally direct crawler + barcode enrichment (Jul 2026).

Why this exists: 93% of our crawled Salla products land in db.products with an
empty `barcode` — Salla's public JSON doesn't expose barcodes. Mahally (a Salla
aggregator at mahally.com) embeds the full product JSON in its SSR HTML for
every product it lists, including `barcode`, `sku`, `mpn`, and `gtin` fields
directly from the underlying Salla merchant record. Recon confirmed:
  • Next.js App Router SSR (Cloudflare) — plain httpx GETs work, no proxy/JS
  • Every /ar/products/{store_id}/{product_id}/ page embeds a JSON blob with
    `"barcode":"5411860811044","sku":"...","mpn":...,"gtin":...`
  • Store identity fully exposed via `store.domain` / `store.username` (the
    Salla merchant subdomain), so we can attribute Mahally products back to
    stores we already track.

This module is READ-ONLY against Mahally, and by default DRY-RUN against our
own database. The `enrich_barcodes_from_mahally()` function only writes when
`dry_run=False`, and the matcher rules are DELIBERATELY strict (RapidFuzz ratio
≥ 92, brand token exact match, size/weight tokens exact match) because a wrong
barcode creates a false 99-confidence match that poisons the matcher — per the
project's iter21 postmortem, false 99s are worse than no matches at all.
"""

import asyncio
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import httpx
from rapidfuzz import fuzz

logger = logging.getLogger("mahally")

MAHALLY_BASE = "https://mahally.com"
PETS_BROWSE_ROOTS = [
    "/ar/browse/الحيوانات-الأليفة-و-مستلزماتها/",
]

# Standard desktop UA + Arabic-preferred Accept-Language (Mahally serves the
# same SSR HTML to both, but Arabic gets the Arabic name fields populated).
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.9",
}

# Extracts (store_id, product_id) from href links on the browse pages.
_PRODUCT_HREF_RE = re.compile(r'href="/ar/products/(\d+)/(\d+)/[^"]*"')

# Matches the anchor "product_id":<pid> inside the escaped RSC stream.
# Mahally emits the JSON with backslash-escaped quotes (\"key\":value) because
# it's serialized inside a JS string literal for the RSC push. We normalize by
# unescaping before extraction — that's cheaper and more robust than trying to
# balance nested JSON objects with regex.


def _unescape_rsc(html: str) -> str:
    """Undo JS-string escaping so ``\\"key\\":value`` becomes ``"key":value``.

    We don't attempt full JSON parsing — the RSC stream contains multiple
    concatenated payloads, some with intentional syntax errors that would
    break json.loads. Field-level regex extraction on the unescaped text is
    both faster and immune to those boundary issues.
    """
    return (
        html.replace('\\"', '"')
            .replace("\\/", "/")
            .replace("\\\\", "\\")
            .replace("\\u0026", "&")
    )


def extract_product_hrefs(html: str) -> list[tuple[int, int]]:
    """Return unique ``(store_id, product_id)`` pairs from a browse page HTML."""
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for m in _PRODUCT_HREF_RE.finditer(html):
        pair = (int(m.group(1)), int(m.group(2)))
        if pair in seen:
            continue
        seen.add(pair)
        out.append(pair)
    return out


# Field extractors, all bounded so we never scan the whole 400 KB document.
_BARCODE_RE = re.compile(r'"barcode"\s*:\s*(?:null|"([^"]{0,60})")')
_SKU_RE = re.compile(r'"sku"\s*:\s*(?:null|"([^"]{0,120})")')
_MPN_RE = re.compile(r'"mpn"\s*:\s*(?:null|"([^"]{0,120})")')
_GTIN_RE = re.compile(r'"gtin"\s*:\s*(?:null|"([^"]{0,60})")')
_UPDATED_AT_RE = re.compile(r'"updated_at"\s*:\s*"([0-9\- :T]+)"')
_STORE_NAME_RE = re.compile(r'"store"\s*:\s*\{\s*"id"\s*:\s*\d+\s*,\s*"name"\s*:\s*"([^"]{1,200})"')
_STORE_USERNAME_RE = re.compile(r'"username"\s*:\s*"([a-zA-Z0-9._-]{2,80})"')
_STORE_DOMAIN_RE = re.compile(r'"domain"\s*:\s*"(https?://[^"]{4,200})"')
_PRODUCT_NAME_JSONLD_RE = re.compile(
    r'"@type"\s*:\s*"Product"\s*,\s*"name"\s*:\s*"([^"]{1,400})"'
)


def _first_non_null(pattern: re.Pattern, text: str, start: int, window: int) -> Optional[str]:
    """First non-empty capture of *pattern* within ``text[start:start+window]``.

    Skips ``null`` occurrences (pattern's group captures are None when null was
    matched) — that way we pick up the first VARIANT that actually has a
    value, ignoring the parent's null value.
    """
    end = start + window
    for m in pattern.finditer(text, start, end):
        val = m.group(1)
        if val:
            return val.strip()
    return None


def parse_product_detail(html: str, target_pid: int) -> Optional[dict]:
    """Parse a Mahally product detail page.

    Returns a dict with keys: ``product_id``, ``store_id``, ``name_ar``,
    ``barcode``, ``sku``, ``mpn``, ``gtin``, ``store_name``, ``store_domain``,
    ``store_username``, ``updated_at``. Returns ``None`` if the target
    product_id anchor can't be located (page structure changed or product no
    longer exists).
    """
    unesc = _unescape_rsc(html)

    # Locate the primary product anchor. Skip the sku[].product_id occurrences
    # by preferring the FIRST "product_id":<pid> whose immediate context is
    # NOT preceded by "skus":[{ — but in practice the parent product_id shows
    # up before any variant, so the first hit is correct.
    anchor = unesc.find(f'"product_id":{target_pid}')
    if anchor < 0:
        return None

    # Store context lives BEFORE the anchor (see recon: store.domain at ~-880
    # rel offset). Product-specific data lives AFTER the anchor.
    store_window_start = max(0, anchor - 4000)

    store_name = _first_non_null(_STORE_NAME_RE, unesc, store_window_start, 4000)
    store_domain = _first_non_null(_STORE_DOMAIN_RE, unesc, store_window_start, 4000)
    store_username = _first_non_null(_STORE_USERNAME_RE, unesc, store_window_start, 4000)

    # JSON-LD product name is authoritative — it's the SEO-facing name and
    # matches what the shopper sees. Present ONCE per page in a script tag.
    name_ar = None
    m = _PRODUCT_NAME_JSONLD_RE.search(unesc)
    if m:
        name_ar = m.group(1).strip()

    # Product identifiers — search forward from the anchor (variants sit
    # AFTER the parent product_id in the JSON stream).
    barcode = _first_non_null(_BARCODE_RE, unesc, anchor, 6000)
    sku = _first_non_null(_SKU_RE, unesc, anchor, 6000)
    mpn = _first_non_null(_MPN_RE, unesc, anchor, 6000)
    gtin = _first_non_null(_GTIN_RE, unesc, anchor, 6000)
    updated_at = _first_non_null(_UPDATED_AT_RE, unesc, anchor, 6000)

    return {
        "product_id": target_pid,
        "name_ar": name_ar,
        "barcode": barcode,
        "sku": sku,
        "mpn": mpn,
        "gtin": gtin,
        "store_name": store_name,
        "store_domain": store_domain,
        "store_username": store_username,
        "updated_at": updated_at,
    }


# ── Normalization + fuzzy match with strict guards ─────────────────────────

# Arabic diacritics (tashkeel) to strip during normalization.
_ARABIC_DIACRITICS = "".join([
    "\u064B", "\u064C", "\u064D", "\u064E", "\u064F", "\u0650",
    "\u0651", "\u0652", "\u0653", "\u0654", "\u0655", "\u0670",
])
_ARABIC_LETTERS_NORMALIZE = str.maketrans({
    # Alef variants → bare alef
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    # ya' variants
    "ى": "ي", "ئ": "ي",
    # ta' marbuta → ha' (many merchants write it interchangeably)
    "ة": "ه",
    # tatweel (kashida)
    "ـ": "",
})
_ARABIC_DIACRITIC_TABLE = str.maketrans("", "", _ARABIC_DIACRITICS)


def _normalize(text: str) -> str:
    """Normalize Arabic + Latin text for fuzzy comparison.

    Lowercases, strips Arabic diacritics, normalizes alef/ya/ta-marbuta,
    collapses whitespace and non-alphanumerics. Deterministic.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = s.translate(_ARABIC_DIACRITIC_TABLE)
    s = s.translate(_ARABIC_LETTERS_NORMALIZE)
    s = s.lower()
    # Collapse anything that isn't a letter/digit to a single space.
    s = re.sub(r"[^\w\u0600-\u06FF]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Weight/volume/count tokens the guard must lock. Canonicalized to grams for
# mass and millilitres for volume so ``2kg`` matches ``2000g`` and ``1L``
# matches ``1000ml``.
_SIZE_UNIT_MAP = {
    "kg": ("mass", 1000.0), "kilo": ("mass", 1000.0), "kilos": ("mass", 1000.0),
    "كجم": ("mass", 1000.0), "كيلو": ("mass", 1000.0),
    "كيلوغرام": ("mass", 1000.0), "كيلوجرام": ("mass", 1000.0),
    "g": ("mass", 1.0), "gm": ("mass", 1.0), "gr": ("mass", 1.0),
    "gram": ("mass", 1.0), "grams": ("mass", 1.0),
    "جم": ("mass", 1.0), "غ": ("mass", 1.0),
    "جرام": ("mass", 1.0), "غرام": ("mass", 1.0),
    "mg": ("mass", 0.001), "ملغ": ("mass", 0.001),
    "l": ("volume", 1000.0), "liter": ("volume", 1000.0), "litre": ("volume", 1000.0),
    "ltr": ("volume", 1000.0), "لتر": ("volume", 1000.0), "ليتر": ("volume", 1000.0),
    "ml": ("volume", 1.0), "مل": ("volume", 1.0), "ميلي": ("volume", 1.0),
    "cl": ("volume", 10.0), "cc": ("volume", 1.0),
    "oz": ("mass", 28.3495),
}
_SIZE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(kg|kilos?|كيلو(?:غرام|جرام)?|كجم"
    r"|gm?|gr|grams?|جم|جرام|غرام|غ|mg|ملغ"
    r"|ml|مل|ميلي|l(?:iter|itre|tr)?|لتر|ليتر|cl|cc|oz)"
    r"(?![a-z\u0600-\u06FF])",  # unit boundary — avoid matching 'gram' inside a word
    re.IGNORECASE,
)


def extract_size_tokens(name: str) -> frozenset[str]:
    """Extract canonical size tokens (mass in grams, volume in millilitres).

    ``"طعام قطط 2kg"`` → ``{"2000g_mass"}``
    ``"400ml + 85g gift"`` → ``{"400ml_volume", "85g_mass"}``
    ``"pack of 12"`` → ``frozenset()``  (no unit → not size-locked)
    """
    tokens: set[str] = set()
    for m in _SIZE_RE.finditer(name):
        raw_num = m.group(1).replace(",", ".")
        try:
            num = float(raw_num)
        except ValueError:
            continue
        unit_lc = m.group(2).lower()
        family_scale = _SIZE_UNIT_MAP.get(unit_lc)
        if not family_scale:
            continue
        family, scale = family_scale
        canonical_value = num * scale
        # Trim to 3 decimals to avoid float noise; strip trailing zeros.
        # A 0.5 kg product = 500g_mass; 0.001kg = 1g_mass.
        rendered = f"{canonical_value:.3f}".rstrip("0").rstrip(".") or "0"
        base_unit = "g" if family == "mass" else "ml"
        tokens.add(f"{rendered}{base_unit}_{family}")
    return frozenset(tokens)


def is_confident_match(
    my_product: dict,
    mahally_product: dict,
    min_ratio: int = 92,
) -> tuple[bool, int, str]:
    """Strict three-guard match: name ratio ≥ min_ratio + brand token in both + size tokens equal.

    Returns ``(matched, score, reason)``. On reject, ``reason`` explains why
    so the dry-run report can surface high-scoring near-misses for review.
    """
    my_raw = (my_product.get("name_ar") or my_product.get("name_en") or "").strip()
    ml_raw = (mahally_product.get("name_ar") or "").strip()
    if not my_raw or not ml_raw:
        return False, 0, "empty_name"

    my_name = _normalize(my_raw)
    ml_name = _normalize(ml_raw)
    if not my_name or not ml_name:
        return False, 0, "empty_name_after_normalize"

    # Guard 1 — fuzzy name similarity. token_set_ratio is tolerant to word
    # order and duplication (common in Arabic product names that mix vendor
    # branding, size, and description into one line).
    score = int(fuzz.token_set_ratio(my_name, ml_name))
    if score < min_ratio:
        return False, score, f"ratio<{min_ratio}"

    # Guard 2 — brand token must be present in both names. We use our own
    # db.products.brand column as ground truth. If it's empty we CANNOT
    # verify the guard, so we bail out rather than risk a false match — the
    # user's rule ("brand token must match exactly") is a rejection of soft
    # inference here.
    my_brand_raw = (my_product.get("brand") or "").strip()
    if not my_brand_raw:
        return False, score, "my_brand_empty"

    my_brand = _normalize(my_brand_raw)
    if not my_brand:
        return False, score, "my_brand_empty_after_normalize"

    # Every token of our brand must appear in the Mahally name. A single
    # missing token → reject. This handles multi-word brands ("royal canin",
    # "رويال كانين") without letting a partial hit through.
    brand_tokens = [t for t in my_brand.split() if len(t) >= 2]
    if not brand_tokens:
        return False, score, "my_brand_tokens_too_short"
    for tok in brand_tokens:
        if tok not in ml_name:
            return False, score, f"brand_token_missing:{tok}"

    # Guard 3 — size/volume/mass tokens must be an EXACT set match. If our
    # product's name has "2kg" and Mahally's says "4kg", reject. If neither
    # name has a size token, that's fine (many products don't spec size in
    # the name — the fuzzy ratio + brand check remain the discriminators).
    my_sizes = extract_size_tokens(my_raw)
    ml_sizes = extract_size_tokens(ml_raw)
    if my_sizes != ml_sizes:
        return False, score, f"size_mismatch:{sorted(my_sizes)}!={sorted(ml_sizes)}"

    return True, score, "match"


# ── Discovery + fetch ──────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, path_or_url: str) -> Optional[str]:
    """GET one Mahally page; None on transport or non-2xx."""
    url = path_or_url if path_or_url.startswith("http") else (MAHALLY_BASE + path_or_url)
    try:
        r = await client.get(url, headers=_HEADERS, timeout=30.0, follow_redirects=True)
    except httpx.HTTPError as e:
        logger.warning(f"[Mahally] GET {url} failed: {type(e).__name__}: {e}")
        return None
    if r.status_code != 200:
        logger.warning(f"[Mahally] GET {url} -> {r.status_code}")
        return None
    return r.text


async def discover_pet_products(
    client: httpx.AsyncClient,
    max_products: int = 300,
) -> list[tuple[int, int]]:
    """Enumerate pet-category product hrefs (deduplicated) up to ``max_products``.

    Returns ordered ``(store_id, product_id)`` pairs. Depth is intentionally
    shallow: Mahally's browse root already exposes 100+ pet products per
    fetch, and additional depth would require reversing their Algolia
    infinite-scroll — out of scope for this build. Callers who need more
    coverage pass a bigger ``max_products`` and, in a future iteration, we can
    add subcategory + store-page walks.
    """
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for root in PETS_BROWSE_ROOTS:
        html = await _get(client, root)
        if not html:
            continue
        for sid, pid in extract_product_hrefs(html):
            if (sid, pid) in seen:
                continue
            seen.add((sid, pid))
            out.append((sid, pid))
            if len(out) >= max_products:
                return out
    return out


async def fetch_product_details(
    client: httpx.AsyncClient,
    pairs: list[tuple[int, int]],
    concurrency: int = 4,
) -> list[dict]:
    """Fetch and parse every ``(store_id, product_id)`` pair concurrently.

    Concurrency is deliberately modest (4 in-flight) to be a polite neighbor —
    Mahally is Cloudflare-fronted and a single crawler slamming their edge
    with 20 parallel requests would earn us a rate-limit block.
    """
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []

    async def one(sid: int, pid: int) -> None:
        async with sem:
            path = f"/ar/products/{sid}/{pid}/"
            html = await _get(client, path)
            if not html:
                return
            parsed = parse_product_detail(html, pid)
            if parsed is None:
                return
            parsed["store_id"] = sid
            parsed["source_url"] = MAHALLY_BASE + path
            results.append(parsed)

    await asyncio.gather(*(one(sid, pid) for sid, pid in pairs))
    return results


# ── Barcode enrichment (dry-run by default) ───────────────────────────────

async def enrich_barcodes_from_mahally(
    db,
    max_products: int = 300,
    min_ratio: int = 92,
    dry_run: bool = True,
) -> dict:
    """Discover Mahally pet products, match against ``db.products``, optionally write barcodes.

    Never writes when ``dry_run=True``. Always reports the same counters
    plus a sample of 20 confident matches (with scores) and 10 near-misses
    (ratio in [80, min_ratio) — visibility on what the guards rejected).
    """
    started = datetime.now(timezone.utc)

    async with httpx.AsyncClient() as client:
        pairs = await discover_pet_products(client, max_products=max_products)
        mahally_products = await fetch_product_details(client, pairs)

    with_barcode = [p for p in mahally_products if _is_valid_ean(p.get("barcode"))]

    # Pull our own catalog once — only rows where barcode is empty. The
    # projection is minimal because we may have thousands of rows.
    my_empty = await db.products.find(
        {"$or": [{"barcode": {"$exists": False}}, {"barcode": ""}, {"barcode": None}]},
        {"_id": 0, "sku": 1, "name_ar": 1, "name_en": 1, "brand": 1},
    ).to_list(50000)

    matches: list[dict] = []
    near_misses: list[dict] = []
    my_skus_touched: set[str] = set()
    conflicts: list[dict] = []

    for mp in with_barcode:
        best: Optional[dict] = None
        best_score = 0
        best_reason = ""
        for my in my_empty:
            if my.get("sku") in my_skus_touched:
                continue  # one Mahally barcode per our-sku, first wins
            matched, score, reason = is_confident_match(my, mp, min_ratio=min_ratio)
            if matched and score > best_score:
                best = my
                best_score = score
                best_reason = reason
            elif not matched and 80 <= score < min_ratio and len(near_misses) < 40:
                near_misses.append({
                    "my_sku": my.get("sku"),
                    "my_name_ar": my.get("name_ar"),
                    "my_brand": my.get("brand"),
                    "mahally_name_ar": mp.get("name_ar"),
                    "mahally_barcode": mp.get("barcode"),
                    "score": score,
                    "reason": reason,
                })
        if best and best.get("sku"):
            # Detect a barcode already claimed by ANOTHER row in db.products
            # (with a different SKU) — that's a conflict we surface but don't
            # write, even in a wet run.
            existing = await db.products.find_one(
                {"barcode": mp["barcode"]}, {"_id": 0, "sku": 1}
            )
            if existing and existing.get("sku") and existing["sku"] != best["sku"]:
                conflicts.append({
                    "mahally_barcode": mp["barcode"],
                    "existing_sku": existing["sku"],
                    "would_have_written_to_sku": best["sku"],
                })
                continue
            my_skus_touched.add(best["sku"])
            matches.append({
                "my_sku": best["sku"],
                "my_name_ar": best.get("name_ar"),
                "my_brand": best.get("brand"),
                "mahally_name_ar": mp.get("name_ar"),
                "mahally_barcode": mp["barcode"],
                "mahally_store_name": mp.get("store_name"),
                "mahally_store_domain": mp.get("store_domain"),
                "score": best_score,
                "source_url": mp.get("source_url"),
            })

    written = 0
    if not dry_run and matches:
        now = datetime.now(timezone.utc)
        for m in matches:
            res = await db.products.update_one(
                {"sku": m["my_sku"], "$or": [
                    {"barcode": {"$exists": False}}, {"barcode": ""}, {"barcode": None},
                ]},
                {"$set": {
                    "barcode": m["mahally_barcode"],
                    "barcode_source": "mahally",
                    "barcode_confidence": int(m["score"]),
                    "barcode_enriched_at": now,
                }},
            )
            if res.modified_count:
                written += 1

    duration = (datetime.now(timezone.utc) - started).total_seconds()

    return {
        "dry_run": dry_run,
        "started_at": started.isoformat(),
        "duration_secs": round(duration, 2),
        "mahally_products_discovered": len(mahally_products),
        "mahally_products_with_barcode": len(with_barcode),
        "my_products_with_empty_barcode": len(my_empty),
        "would_enrich": len(matches),
        "written": written,
        "conflicts": conflicts,
        "sample_matches": matches[:20],
        "sample_near_misses": near_misses[:10],
        "min_ratio": min_ratio,
    }


# Delegated barcode validator — same rule as matcher._is_valid_barcode (8–14
# digits) but locally defined so this module has no circular dependency on
# matcher.py, which imports from server.py at module load.
_NUMERIC_BARCODE_RE = re.compile(r"^\d{8,14}$")


def _is_valid_ean(val: Any) -> bool:
    if not val:
        return False
    return bool(_NUMERIC_BARCODE_RE.match(str(val).strip()))
