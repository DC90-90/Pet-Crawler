"""
Daleel — Multi-tier Crawler Module
Tier 1: JSON API endpoints (Salla/Shopify/Zid)
Tier 2: Playwright XHR interception
Tier 3: Playwright + BeautifulSoup HTML extraction
"""
import os
import re
import uuid
import time
import asyncio
import logging
import itertools
import httpx
from datetime import datetime, timezone

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")
logger = logging.getLogger(__name__)

# ── Webshare Residential Proxy (Saudi Arabia) ───────────────
# Rotating residential proxy used ONLY for stores that have `use_proxy=True`
# on their store document. Bandwidth is finite (50 GB/month) so the rotation
# helper is intentionally gated by the per-store flag at the caller.
_PROXY_USERNAMES = (
    [u.strip() for u in os.getenv("PROXY_USERNAMES", "").split(",") if u.strip()]
    if os.getenv("PROXY_USERNAMES")
    else []
)
_PROXY_ITER = itertools.cycle(_PROXY_USERNAMES) if _PROXY_USERNAMES else None
_PROXY_PWD = os.getenv("PROXY_PASSWORD", "")
_PROXY_HOST = os.getenv("PROXY_HOST", "p.webshare.io")
_PROXY_PORT = os.getenv("PROXY_PORT", "80")


def get_proxy_credentials():
    """Return (username, password, host, port) tuple for the next rotation slot,
    or None if proxies aren't configured. Username rotates round-robin."""
    if not _PROXY_ITER:
        return None
    user = next(_PROXY_ITER)
    return (user, _PROXY_PWD, _PROXY_HOST, _PROXY_PORT)


def get_proxy_url():
    """Return a full proxy URL (`http://user:pass@host:port`) or None."""
    creds = get_proxy_credentials()
    if not creds:
        return None
    user, pwd, host, port = creds
    return f"http://{user}:{pwd}@{host}:{port}"


def playwright_proxy_config(user, pwd, host, port):
    """Build the dict Playwright's `chromium.launch(proxy=...)` expects."""
    return {"server": f"http://{host}:{port}", "username": user, "password": pwd}


async def record_proxy_usage(db, store, bytes_estimate):
    """Best-effort bandwidth tracking. Never raises."""
    try:
        await db.proxy_usage.insert_one({
            "crawled_at": datetime.now(timezone.utc),
            "store_id": store.get("id", ""),
            "store_domain": store.get("domain", ""),
            "bytes_estimate": int(bytes_estimate or 0),
        })
    except Exception as e:
        logger.warning(f"[Proxy] usage record failed: {e}")

# ── Constants ────────────────────────────────────────────────
KNOWN_BRANDS = [
    "Royal Canin", "رويال كانين", "Whiskas", "ويسكاس", "Pedigree", "بيدقري",
    "Purina", "بورينا", "Hills", "هيلز", "N&D", "Orijen", "اوريجن", "Acana", "اكانا",
    "Friskies", "فريسكيز", "Me-O", "مي-او", "Kong", "كونغ", "FURminator", "فرمينيتور",
    "Frontline", "فرونت لاين", "Versele-Laga", "فيرسيل", "Catit", "Oxbow", "Tetra",
    "Virbac", "Ever Clean", "Josera", "Brit", "Schesir", "Gimcat", "Trixie", "Beaphar",
]

XHR_PATTERNS = ["/api/", "/products", "/collection", "product-list", "catalog", "items", "inventory"]
STORE_PAGES = ["/products", "/shop", "/collection/all", "/store", "/"]

SELECTOR_PROFILES = {
    "salla": {
        "card": [".product-card", ".product-item", "[data-product]", ".s-product-card-entry"],
        "name": [".product-card__title", ".product-name", "h3", "h2", ".s-product-card-entry__title"],
        "price": [".product-price", ".price", "[data-price]", ".s-product-card-entry__price"],
        "orig": [".product-price--compare", ".compare-price", "s", "del"],
        "image": ["img.product-card__image", ".product-image img", "img"],
    },
    "zid": {
        "card": [".product-item", ".zid-product", ".product-card"],
        "name": [".item-title", ".product-title", "h3"],
        "price": [".item-price", ".product-price", ".price-current"],
        "orig": [".item-price-old", ".price-old", "del"],
        "image": [".item-image img", ".product-img img", "img"],
    },
    "shopify": {
        "card": [".product-card", ".grid-product", "[data-product-card]"],
        "name": [".product-card__title", ".grid-product__title", "h3"],
        "price": [".product-card__price", ".grid-product__price", ".price"],
        "orig": [".price--compare", "del", "s"],
        "image": ["img.product-card__image", ".grid-product__image-wrap img", "img"],
    },
}


# ── Product Field Extractors ─────────────────────────────────
def extract_brand(name):
    name_lower = name.lower()
    for b in KNOWN_BRANDS:
        if b.lower() in name_lower:
            return b
    return ""


def guess_category(name):
    n = name.lower()
    food_keywords = ["طعام", "غذاء", "food", "دراي", "ويت", "علف", "كيبل", "معلب"]
    if any(w in n for w in food_keywords):
        if any(w in n for w in ["قط", "كات", "cat"]):
            return "cat_food"
        if any(w in n for w in ["كلب", "كلاب", "dog"]):
            return "dog_food"
        if any(w in n for w in ["طير", "طيور", "ببغاء", "bird"]):
            return "bird_food"
        if any(w in n for w in ["سمك", "أسماك", "fish"]):
            return "fish_food"
        return "pet_food"
    if any(w in n for w in ["رمل", "لتر", "litter", "فضلات", "تراب"]):
        return "litter"
    if any(w in n for w in ["لعب", "toy", "ألعاب", "كونغ"]):
        return "toys"
    if any(w in n for w in ["شامبو", "فرشاة", "shampoo", "brush", "groom", "عناية", "مقص", "تنظيف"]):
        return "grooming"
    if any(w in n for w in ["بيطر", "vet", "دواء", "علاج", "فيتامين", "مكمل", "برغوث"]):
        return "healthcare"
    return "accessories"


# ── Food subcategory classifier (iter36) ─────────────────────
# Splits cat_food / dog_food into dry / wet / treats. Same hybrid inputs as the
# rest of the extraction pipeline: the product NAME plus the store's own
# category tags (Salla/Zid `categories[]` names) when the payload carries them.
# QUALITY OVER COVERAGE: a product that doesn't match confidently — or matches
# both wet AND dry (variety packs) — stays generic cat_food / dog_food.
FOOD_SUBCATEGORY_PARENTS = ("cat_food", "dog_food")
FOOD_SUBCATEGORIES = ("cat_food_dry", "cat_food_wet", "cat_treats",
                      "dog_food_dry", "dog_food_wet", "dog_treats")

# NOTE deliberate omissions: "can" (matches Royal CANin), bare "treat" is
# checked specially so "treatment" (healthcare wording) never classifies food.
_TREAT_KEYWORDS = ["مكافأة", "مكافآت", "مكافات", "تريتس", "تريت", "سناك",
                   "snack", "biscuit", "بسكويت", "chew", "مضغ", "stick", "ستيك", "أعواد"]
_WET_KEYWORDS = ["رطب", "معلب", "ويت فود", "wet", "canned", "pouch", "باوتش",
                 "jelly", "جيلي", "بالجيلي", "gravy", "مرق", "شوربة", "soup",
                 "mousse", "pate", "باتيه"]
_DRY_KEYWORDS = ["جاف", "دراي", "dry", "kibble", "كيبل"]


def classify_food_subcategory(parent_category, *texts):
    """Return one of FOOD_SUBCATEGORIES, or None to keep the generic parent.

    Precedence: treats first (a chicken-stick "in gravy" is still a treat),
    then wet vs dry — and a product matching BOTH wet and dry keywords is a
    variety pack we refuse to guess on."""
    if parent_category not in FOOD_SUBCATEGORY_PARENTS:
        return None
    t = " ".join(str(x) for x in texts if x).lower()
    if not t:
        return None
    prefix = "cat" if parent_category == "cat_food" else "dog"
    is_treat = any(k in t for k in _TREAT_KEYWORDS) or ("treat" in t and "treatment" not in t)
    if is_treat:
        return f"{prefix}_treats"
    wet = any(k in t for k in _WET_KEYWORDS)
    dry = any(k in t for k in _DRY_KEYWORDS)
    if wet and dry:
        return None                       # mixed/variety pack — don't guess
    if wet:
        return f"{prefix}_food_wet"
    if dry:
        return f"{prefix}_food_dry"
    return None


def extract_store_category_names(raw):
    """Join the store's own category tag names (Salla: [{name: str}], Zid:
    [{name: {ar, en}}]) into one text blob for the subcategory classifier."""
    names = []
    cats = raw.get("categories")
    if isinstance(cats, list):
        for c in cats:
            if isinstance(c, dict):
                nm = c.get("name")
                if isinstance(nm, dict):
                    names.extend(str(v) for v in nm.values() if v)
                elif nm:
                    names.append(str(nm))
            elif isinstance(c, str):
                names.append(c)
    return " ".join(names)


def guess_animal(name):
    n = name.lower()
    if any(w in n for w in ["قط", "كات", "cat", "هر"]):
        return "cat"
    if any(w in n for w in ["كلب", "كلاب", "dog"]):
        return "dog"
    if any(w in n for w in ["طير", "طيور", "ببغاء", "bird", "كناري"]):
        return "bird"
    if any(w in n for w in ["سمك", "أسماك", "fish"]):
        return "fish"
    if any(w in n for w in ["زواحف", "reptile"]):
        return "reptile"
    if any(w in n for w in ["أرنب", "هامستر", "rabbit", "hamster"]):
        return "small"
    return "other"


def extract_weight(name):
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:كجم|كيلو|kg)', name.lower())
    if m:
        return float(m.group(1))
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:جرام|غرام|g)\b', name.lower())
    if m:
        return float(m.group(1)) / 1000
    return 0


def _extract_price_from_text(text):
    if not text:
        return 0
    nums = re.findall(r'[\d,]+\.?\d*', text.replace(",", ""))
    return float(nums[0]) if nums else 0


# ── Crawl Log Builder ────────────────────────────────────────
def _make_crawl_log(store, tier_attempted):
    return {
        "id": str(uuid.uuid4()),
        "store_id": store["id"],
        "store_name": store["name"],
        "tier_attempted": tier_attempted,
        "tier_used": None,
        "http_status": None,
        "products_found": 0,
        "products_new": 0,
        "products_updated": 0,
        "snapshots_created": 0,
        "error": None,
        "endpoint_used": None,
        "endpoints_tried": [],
        "duration_secs": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }


async def _finalize_crawl_log(db, crawl_log, store_id):
    """Save crawl log to DB and update store metadata."""
    crawl_log["completed_at"] = datetime.now(timezone.utc).isoformat()
    await db.crawl_logs.insert_one(crawl_log)
    await db.stores.update_one({"id": store_id}, {"$set": {
        "last_crawled_at": crawl_log["completed_at"],
        "last_crawl_tier": crawl_log["tier_used"],
        "last_crawl_status": "success" if crawl_log["tier_used"] else "failed",
        "last_crawl_error": crawl_log["error"],
        "last_crawl_products": crawl_log["products_found"],
        "last_crawl_endpoint": crawl_log.get("endpoint_used"),
    }})


# ── Raw Product Normalizer ───────────────────────────────────
def _absolutize_url(raw_url, store_domain):
    """Turn a raw URL value (full URL, path, or slug) into an absolute https URL on the store's domain."""
    if not raw_url or not store_domain:
        return ""
    s = str(raw_url).strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("/"):
        return f"https://{store_domain}{s}"
    # Treat as slug — Salla/Zid both expose products under /products/{slug}
    return f"https://{store_domain}/products/{s}"


def _price_amount(f):
    """Dict-aware price coercion — Salla prices are {amount, currency} objects,
    Zid prices are plain numbers, legacy feeds may send strings."""
    if isinstance(f, dict):
        f = f.get("amount")
    try:
        return float(f or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_raw_product(raw, store_name):
    """Normalize a single raw product dict from any source into a standard form."""
    name_ar = raw.get("name", raw.get("title", ""))

    sku_raw = raw.get("sku") or raw.get("mpn") or f"S-{store_name[:2].upper()}-{raw.get('id', uuid.uuid4().hex[:6])}"

    # Price extraction happens AFTER barcode/variant selection below (iter35):
    # when the barcode we key on comes from a skus[] variant, that variant's
    # price fields — not the product root's — describe the item we track.

    # Stock quantity parsing (Feb 2026 micro-fixes):
    # - Salla returns quantity as STRING ("50") and uses unlimited_quantity flag
    # - Zid returns quantity as int|null and uses is_infinite flag
    # Handle both inline since this function is platform-agnostic.
    if raw.get("unlimited_quantity") or raw.get("is_infinite"):
        qty = 999
    else:
        try:
            qty = max(0, int(float(str(raw.get("quantity") or raw.get("stock_quantity") or raw.get("qty") or 0))))
        except (ValueError, TypeError):
            qty = 0

    # Capture cumulative sales counter (Salla: sales_count, Zid: sold_count, legacy Salla: sold_products_count)
    sold_count = int(
        raw.get("sales_count")
        or raw.get("sold_count")
        or raw.get("sold_products_count")
        or raw.get("total_sold")
        or raw.get("orders_count")
        or 0
    )

    # in_stock detection — handle multiple platform conventions defensively
    explicit_avail = raw.get("is_available")
    if explicit_avail is None:
        explicit_avail = raw.get("availability")
    status_val = str(raw.get("status", "")).lower()

    if explicit_avail is True or explicit_avail in ("yes", "available", "in_stock"):
        in_stock = True
    elif explicit_avail is False or explicit_avail in ("no", "unavailable", "out_of_stock", "sold_out"):
        in_stock = False
    elif status_val in ("sale", "active", "available", "published", "visible"):
        in_stock = True  # Active product on storefront → treat as in-stock unless explicitly unavailable
    elif status_val in ("draft", "hidden", "deleted", "out", "out_of_stock", "sold_out"):
        in_stock = False
    else:
        in_stock = qty > 0  # Last-resort fallback

    imgs = raw.get("images", raw.get("image", []))
    img_url = ""
    if isinstance(imgs, list) and imgs:
        first = imgs[0]
        if isinstance(first, dict):
            # Modern Salla: {url, src}; Legacy Salla: {image: {full_size, original}}
            img_url = (
                first.get("url")
                or first.get("src")
                or (first.get("image", {}).get("full_size") if isinstance(first.get("image"), dict) else "")
                or (first.get("image", {}).get("original") if isinstance(first.get("image"), dict) else "")
                or ""
            )
        else:
            img_url = str(first)
    elif isinstance(imgs, dict):
        img_url = imgs.get("url", imgs.get("src", ""))

    # Storefront product URL (Feb 2026): prefer Salla's `urls.customer` over the generic
    # `url` field, since `url` may be the admin URL or short link.
    urls_obj = raw.get("urls") or {}
    product_url = ""
    if isinstance(urls_obj, dict):
        product_url = urls_obj.get("customer") or urls_obj.get("store") or urls_obj.get("url") or ""
    if not product_url:
        product_url = (
            raw.get("url")
            or raw.get("html_url")
            or raw.get("permalink")
            or raw.get("product_url")
            or raw.get("link")
            or raw.get("page_url")
            or raw.get("product_page_url")
            or ""
        )
    product_url = str(product_url or "").strip()

    # Barcode extraction (Feb 2026): Salla often puts valid EANs on variants
    # (raw.skus[].barcode/gtin/mpn), not on the product root. Iterate variants first.
    _EAN_RE = re.compile(r"^\d{8,14}$")
    barcode = ""
    from_variant = False
    matched_variant = None       # iter35 — the variant the barcode came from
    variants = raw.get("skus")
    if isinstance(variants, list):
        for v in variants:
            if not isinstance(v, dict):
                continue
            for key in ("barcode", "gtin", "mpn"):
                cand = str(v.get(key) or "").strip()
                if _EAN_RE.match(cand):
                    barcode = cand
                    from_variant = True
                    matched_variant = v
                    break
            if barcode:
                break
    if not barcode:
        for key in ("gtin", "mpn", "barcode", "ean", "upc"):
            cand = str(raw.get(key) or "").strip()
            if _EAN_RE.match(cand):
                barcode = cand
                break
    logger.info(
        f"normalize_salla barcode_source={'variant' if from_variant else 'root' if barcode else 'none'} sku={sku_raw}"
    )

    # ── Effective / original / sale price (iter35 rewrite) ──────────────────
    # Root-only extraction systematically overstated Salla prices: Salla defines
    # sales PER VARIANT (skus[].price is the variant's CURRENT price,
    # skus[].regular_price the pre-sale price), and the root sale_price is often
    # {amount: 0} while a variant is on sale. Confirmed case: Lana Pets Brit
    # Care 7kg showed 279 (root/regular) instead of the live 237.02 (variant
    # sale). Rules:
    #   • price source = the variant the barcode was taken from (when it carries
    #     a usable price), else the product root — barcode and price must
    #     describe the SAME item.
    #   • effective price = source price, or sale_price when 0 < sale < price
    #     (Zid convention: price=regular, sale_price=effective).
    #   • original_price = regular_price when it's higher (Salla convention:
    #     price is ALREADY the discounted price, regular_price holds the
    #     pre-sale price) else the pre-swap price — making discount_pct real.
    #   • sale_price is returned (and now persisted) whenever a genuine
    #     discount exists, so capture regressions are visible in our own data.
    src = matched_variant if (matched_variant and _price_amount(matched_variant.get("price")) > 0) else raw
    base_price = _price_amount(src.get("price"))
    sale_price = _price_amount(src.get("sale_price"))
    if sale_price <= 0 and src is raw:
        # promotion.price (legacy Salla) and special_price (Mowkly) fallbacks —
        # (raw.get("promotion") or {}) also fixes the AttributeError when the
        # API returns promotion: null.
        sale_price = _price_amount((raw.get("promotion") or {}).get("price"))
        if sale_price <= 0:
            sale_price = _price_amount(raw.get("special_price"))
    regular_price = _price_amount(src.get("regular_price"))

    price = base_price
    if 0 < sale_price < price:
        price = sale_price
    original_price = price
    for cand in (regular_price, base_price):
        if cand > original_price:
            original_price = cand
    # Feb 2026: stock signal observability — tells us when unlimited flags fired
    _plat = "salla" if "unlimited_quantity" in raw else ("zid" if "is_infinite" in raw else "unknown")
    logger.info(
        f"stock_normalize platform={_plat} sku={sku_raw} qty={qty} "
        f"unlimited={bool(raw.get('unlimited_quantity') or raw.get('is_infinite'))}"
    )

    return {
        "name_ar": name_ar,
        "sku": sku_raw,
        "barcode": barcode,
        # iter35 — a real discount exists iff the sale price sits below the
        # original; equal-to-price sale fields (Salla mirrors price into
        # sale_price on sale items) are not a discount signal by themselves.
        "sale_price": float(sale_price) if 0 < sale_price < original_price else None,
        "price": price,
        "original_price": original_price,
        "qty": max(0, qty),
        "sold_count": max(0, sold_count),
        "in_stock": bool(in_stock),
        "img_url": img_url,
        "product_url": product_url,
    }


async def process_crawled_products(db, store, all_raw, now, tier=1, confidence=95):
    """Process raw product data from any crawler tier into products + snapshots."""
    new_count = 0
    snap_count = 0
    store_domain = store.get("domain", "")
    for raw in all_raw:
        norm = _normalize_raw_product(raw, store["name"])
        product_url = _absolutize_url(norm.get("product_url"), store_domain)

        existing = await db.products.find_one({"sku": norm["sku"]})
        # iter36 — hybrid classifier input: product name + the store's own
        # category tag names (when the raw payload carries them).
        store_cats = extract_store_category_names(raw)
        if not existing:
            pid = str(uuid.uuid4())
            category = guess_category(norm["name_ar"])
            await db.products.insert_one({
                "id": pid, "sku": norm["sku"],
                "name_ar": norm["name_ar"], "name_en": norm["name_ar"],
                "brand": extract_brand(norm["name_ar"]),
                "category": category,
                # additive: parent category stays; None = confidently generic
                "subcategory": classify_food_subcategory(category, norm["name_ar"], store_cats),
                "animal_type": guess_animal(norm["name_ar"]),
                "weight_kg": extract_weight(norm["name_ar"]),
                "image_url": norm["img_url"],
                "product_url": product_url,
                "first_seen_at": now.isoformat(),
            })
            new_count += 1
        else:
            pid = existing["id"]
            patch = {}
            if norm["img_url"] and not existing.get("image_url"):
                patch["image_url"] = norm["img_url"]
            if product_url and not existing.get("product_url"):
                patch["product_url"] = product_url
            if "subcategory" not in existing:
                # iter36 — one-shot enrichment of pre-existing products (the
                # startup backfill covers products no crawl revisits).
                patch["subcategory"] = classify_food_subcategory(
                    existing.get("category"), existing.get("name_ar"), existing.get("name_en"), store_cats)
            if patch:
                await db.products.update_one({"id": pid}, {"$set": patch})

        disc_pct = round((1 - norm["price"] / norm["original_price"]) * 100) if norm["original_price"] > norm["price"] > 0 else 0
        await db.product_snapshots.insert_one({
            "id": str(uuid.uuid4()),
            "product_id": pid,
            "store_id": store["id"],
            "store_name": store["name"],
            "sku": norm["sku"],
            "price": round(norm["price"], 2),
            "original_price": round(norm["original_price"], 2),
            # iter35 — persist the captured sale price so a future capture
            # regression is DETECTABLE from our own data (a store whose
            # discounted share collapses to ~0% is a red flag).
            "sale_price": round(norm["sale_price"], 2) if norm.get("sale_price") else None,
            "discount_pct": max(0, disc_pct),
            "in_stock": norm["in_stock"],
            "qty_available": norm["qty"],
            "sold_count": norm["sold_count"],
            "product_url": product_url,
            "source_tier": tier,
            "confidence_score": confidence,
            "crawled_at": now,
        })
        snap_count += 1

    return new_count, snap_count


# ── Tier 1: JSON API Endpoints ───────────────────────────────
def _build_salla_endpoints(base, cached_endpoint, platform="salla"):
    if platform == "zid":
        endpoints = [
            {"url": f"{base}/api/v1/products", "params": {"page": 1}, "tag": "/api/v1/products", "pagination": "page"},
        ]
    else:
        # Salla stores use /en/api/v1/products with cursor pagination
        # Also try Zid-style page pagination as fallback (some stores are misclassified)
        endpoints = [
            {"url": f"{base}/en/api/v1/products", "params": {}, "tag": "/en/api/v1/products", "pagination": "cursor"},
            {"url": f"{base}/api/v1/products", "params": {"page": 1}, "tag": "/api/v1/products", "pagination": "page"},
        ]
    if cached_endpoint:
        matching = [e for e in endpoints if e["tag"] == cached_endpoint]
        others = [e for e in endpoints if e["tag"] != cached_endpoint]
        endpoints = matching + others
    return endpoints


async def _try_single_endpoint(http, ep, crawl_log):
    """Try a single JSON endpoint. Returns (items_list, endpoint_dict) or ([], None)."""
    attempt = {"endpoint": ep["tag"], "status": None, "products": 0, "error": None}
    try:
        resp = await http.get(ep["url"], params=ep.get("params"))
        attempt["status"] = resp.status_code
        if resp.status_code != 200:
            attempt["error"] = f"HTTP {resp.status_code}"
            crawl_log["endpoints_tried"].append(attempt)
            return [], None
        try:
            body = resp.json()
        except Exception:
            attempt["error"] = "Non-JSON response"
            crawl_log["endpoints_tried"].append(attempt)
            return [], None
        items = body.get("data", body.get("products", body.get("results", [])))
        # Handle nested legacy Salla schema: { "data": { "products": { "data": [...], "current_page": 1 } } }
        if isinstance(items, dict):
            inner_products = items.get("products")
            if isinstance(inner_products, dict) and isinstance(inner_products.get("data"), list):
                # Stash pagination metadata for the legacy paginator
                ep["_legacy_pagination"] = {
                    "current_page": inner_products.get("current_page", 1),
                    "last_page": inner_products.get("last_page"),
                    "next_page_url": inner_products.get("next_page_url"),
                }
                items = inner_products["data"]
            elif isinstance(items.get("data"), list):
                items = items["data"]
        if isinstance(items, list) and len(items) >= 3:
            attempt["products"] = len(items)
            # Store cursor info for Salla cursor pagination
            cursor = body.get("cursor")
            if cursor and isinstance(cursor, dict):
                ep["_cursor_next"] = cursor.get("next")
            crawl_log["endpoints_tried"].append(attempt)
            return items, ep
        attempt["products"] = len(items) if isinstance(items, list) else 0
        attempt["error"] = f"Only {attempt['products']} products (need 3+)"
    except httpx.TimeoutException:
        attempt["status"] = 0
        attempt["error"] = "Timeout"
    except Exception as e:
        attempt["status"] = 0
        attempt["error"] = str(e)[:100]
    crawl_log["endpoints_tried"].append(attempt)
    return [], None


async def _paginate_endpoint(http, ep, initial_items):
    """Paginate through remaining pages. Supports Salla cursor and Zid page-number pagination."""
    all_items = list(initial_items)
    pagination = ep.get("pagination", "page")

    if pagination == "cursor":
        # Salla cursor-based: GET cursor.next directly as a complete URL until null
        # Fix: Salla cursor.next may drop /en/ prefix, causing 400 "deprecated" errors.
        # Detect and re-insert the /en/ prefix when the initial request used it.
        initial_path = ep.get("tag", "")
        needs_en_prefix = initial_path.startswith("/en/")
        next_url = ep.get("_cursor_next")
        pages_fetched = 1
        while next_url and pages_fetched < 200:
            try:
                # Fix cursor URL: re-insert /en/ if the working endpoint used it
                fetch_url = next_url
                if needs_en_prefix and "/en/api/" not in next_url and "/api/" in next_url:
                    fetch_url = next_url.replace("/api/", "/en/api/", 1)
                r = await http.get(fetch_url)
                if r.status_code != 200:
                    break
                body = r.json()
                more = body.get("data", body.get("products", body.get("results", [])))
                if not more:
                    break
                all_items.extend(more)
                pages_fetched += 1
                cursor = body.get("cursor")
                next_url = cursor.get("next") if cursor and isinstance(cursor, dict) else None
                logger.info(f"[Pagination] Page {pages_fetched}: +{len(more)} items (total: {len(all_items)}), has_next={next_url is not None}")
            except Exception as exc:
                logger.warning(f"[Pagination] Exception on page {pages_fetched+1}: {exc}")
                break
        logger.info(f"[Pagination] Done: {len(all_items)} total across {pages_fetched} pages")
    else:
        # Zid page-number pagination + legacy Salla page-number pagination
        page = 2
        while page <= 200:
            params = dict(ep.get("params", {}))
            params["page"] = page
            try:
                r = await http.get(ep["url"], params=params)
                if r.status_code != 200:
                    break
                body = r.json()
                more = body.get("data", body.get("products", body.get("results", [])))
                # Legacy Salla nested envelope: { data: { products: { data: [...] } } }
                if isinstance(more, dict):
                    inner = more.get("products")
                    if isinstance(inner, dict) and isinstance(inner.get("data"), list):
                        more = inner["data"]
                    elif isinstance(more.get("data"), list):
                        more = more["data"]
                if not more:
                    break
                all_items.extend(more)
                page += 1
                if len(more) < 20:
                    break
            except Exception:
                break

    return all_items


async def crawl_salla_tier1(db, store):
    """Tier 1: Try Salla/Zid public JSON endpoints. Cache working endpoint."""
    base = f"https://{store['domain']}"
    platform = store.get("platform", "salla").lower()
    endpoints = _build_salla_endpoints(base, store.get("working_endpoint"), platform=platform)
    crawl_log = _make_crawl_log(store, tier_attempted=1)

    all_raw = []
    winning_endpoint = None

    httpx_kwargs = {
        "timeout": 15.0,
        "follow_redirects": True,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html, */*",
        },
    }
    proxy_url = None
    if store.get("use_proxy"):
        creds = get_proxy_credentials()
        if creds:
            u, p, h, port = creds
            proxy_url = f"http://{u}:{p}@{h}:{port}"
            httpx_kwargs["proxy"] = proxy_url
            logger.info(f"[Proxy] store={store.get('domain')} tier=1 using proxy_user={u}")

    try:
        async with httpx.AsyncClient(**httpx_kwargs) as http:
            for ep in endpoints:
                items, matched_ep = await _try_single_endpoint(http, ep, crawl_log)
                if matched_ep:
                    all_raw = await _paginate_endpoint(http, matched_ep, items)
                    winning_endpoint = matched_ep
                    break
    except Exception as e:
        crawl_log["error"] = str(e)[:300]

    now = datetime.now(timezone.utc)
    if all_raw and winning_endpoint:
        crawl_log["tier_used"] = 1
        crawl_log["http_status"] = 200
        crawl_log["endpoint_used"] = winning_endpoint["tag"]
        crawl_log["products_found"] = len(all_raw)
        await db.stores.update_one({"id": store["id"]}, {"$set": {"working_endpoint": winning_endpoint["tag"]}})
        new_count, snap_count = await process_crawled_products(db, store, all_raw, now)
        crawl_log["products_new"] = new_count
        crawl_log["products_updated"] = len(all_raw) - new_count
        crawl_log["snapshots_created"] = snap_count
    else:
        last_attempt = crawl_log["endpoints_tried"][-1] if crawl_log["endpoints_tried"] else {}
        crawl_log["http_status"] = last_attempt.get("status", 0)
        crawl_log["error"] = f"Tier 1 exhausted — all {len(endpoints)} endpoints failed. Escalating to Tier 2. Last: {last_attempt.get('error', 'unknown')}"
        crawl_log["endpoint_used"] = "none — tier 2 stub"

    await _finalize_crawl_log(db, crawl_log, store["id"])
    logger.info(f"Tier1 {store['name']}: used={crawl_log['tier_used']}, found={crawl_log['products_found']}, ep={crawl_log.get('endpoint_used')}")
    return crawl_log


# ── Tier 2: XHR Interception ─────────────────────────────────
async def _playwright_navigate_and_scroll(page, base):
    """Navigate to a store page, scroll to load lazy content. Returns list of endpoint attempts."""
    attempts = []
    for path in STORE_PAGES:
        target = f"{base}{path}"
        try:
            resp = await page.goto(target, wait_until="networkidle", timeout=20000)
            if resp and resp.status < 400:
                attempts.append({"endpoint": path, "status": resp.status, "products": 0, "error": None})
                await page.wait_for_timeout(3000)
                for _ in range(3):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1500)
                await page.wait_for_timeout(4000)
                return attempts, True
            attempts.append({"endpoint": path, "status": resp.status if resp else 0, "products": 0, "error": f"HTTP {resp.status if resp else 'none'}"})
        except Exception as e:
            attempts.append({"endpoint": path, "status": 0, "products": 0, "error": str(e)[:80]})
    return attempts, False


def _build_xhr_response_handler(intercepted_list):
    """Build a Playwright response handler that captures JSON product payloads."""
    async def handle_response(response):
        url = response.url
        ct = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        if not any(p in url.lower() for p in XHR_PATTERNS):
            return
        try:
            body = await response.json()
            items = []
            if isinstance(body, list):
                items = body
            elif isinstance(body, dict):
                for key in ["data", "products", "items", "results", "collection"]:
                    if key in body and isinstance(body[key], list):
                        items = body[key]
                        break
            if items and len(items) >= 1:
                intercepted_list.append({"url": url, "items": items, "count": len(items)})
        except Exception:
            pass
    return handle_response


async def crawl_tier2_xhr(db, store):
    """Tier 2: Use Playwright to intercept XHR/fetch calls from storefront JS."""
    start_time = time.time()
    base = f"https://{store['domain']}"
    crawl_log = _make_crawl_log(store, tier_attempted=2)

    captured_products = []
    winning_pattern = None

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            if store.get("use_proxy"):
                creds = get_proxy_credentials()
                if creds:
                    user, pwd, host, port = creds
                    launch_kwargs["proxy"] = playwright_proxy_config(user, pwd, host, port)
                    logger.info(f"[Proxy] store={store.get('domain')} tier=2 using proxy_user={user}")
            browser = await pw.chromium.launch(**launch_kwargs)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="ar-SA",
                extra_http_headers={
                    "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.8",
                    "Accept": "application/json, text/html, */*",
                },
            )
            page = await ctx.new_page()
            intercepted = []
            page.on("response", _build_xhr_response_handler(intercepted))

            # For Salla stores, try direct API via Playwright (bypasses Cloudflare JS challenge)
            platform = store.get("platform", "").lower()
            if platform == "salla":
                salla_api_urls = [f"{base}/en/api/v1/products", f"{base}/api/v1/products"]
                for api_url in salla_api_urls:
                    try:
                        resp = await page.goto(api_url, wait_until="domcontentloaded", timeout=20000)
                        if resp and resp.status == 200:
                            content = await page.content()
                            if '"data"' in content and '"cursor"' in content:
                                import json as _json
                                # Extract JSON from page body
                                body_text = await page.inner_text("body")
                                body = _json.loads(body_text)
                                items = body.get("data", [])
                                if items and len(items) >= 1:
                                    # Follow cursor pagination within Playwright context
                                    all_items = list(items)
                                    cursor = body.get("cursor", {})
                                    next_url = cursor.get("next") if cursor else None
                                    initial_tag = "/en/api/v1/products" if "/en/" in api_url else "/api/v1/products"
                                    needs_en = "/en/" in api_url
                                    pages = 1
                                    while next_url and pages < 200:
                                        fetch_url = next_url
                                        if needs_en and "/en/api/" not in next_url and "/api/" in next_url:
                                            fetch_url = next_url.replace("/api/", "/en/api/", 1)
                                        try:
                                            resp2 = await page.goto(fetch_url, wait_until="domcontentloaded", timeout=15000)
                                            if not resp2 or resp2.status != 200:
                                                break
                                            body_text2 = await page.inner_text("body")
                                            body2 = _json.loads(body_text2)
                                            more = body2.get("data", [])
                                            if not more:
                                                break
                                            all_items.extend(more)
                                            pages += 1
                                            cursor2 = body2.get("cursor", {})
                                            next_url = cursor2.get("next") if cursor2 else None
                                        except Exception:
                                            break
                                    captured_products = all_items
                                    winning_pattern = api_url
                                    crawl_log["endpoints_tried"].append({"endpoint": initial_tag, "status": 200, "products": len(all_items), "error": None})
                                    logger.info(f"Tier2 {store['name']}: Salla API via Playwright — {len(all_items)} products across {pages} pages")
                                    break
                    except Exception:
                        continue

            # Fall back to standard XHR interception if no products yet
            if not captured_products:
                attempts, page_loaded = await _playwright_navigate_and_scroll(page, base)
                crawl_log["endpoints_tried"].extend(attempts)

                if intercepted:
                    best = max(intercepted, key=lambda x: x["count"])
                    captured_products = best["items"]
                    winning_pattern = best["url"]
                    for ep in crawl_log["endpoints_tried"]:
                        ep["products"] = best["count"]
                    crawl_log["endpoint_used"] = winning_pattern

            await browser.close()

    except ImportError:
        crawl_log["error"] = "Playwright not installed"
    except Exception as e:
        crawl_log["error"] = f"Tier 2 error: {str(e)[:200]}"

    now = datetime.now(timezone.utc)
    crawl_log["duration_secs"] = round(time.time() - start_time, 1)

    if captured_products and len(captured_products) >= 1:
        crawl_log["tier_used"] = 2
        crawl_log["http_status"] = 200
        crawl_log["products_found"] = len(captured_products)
        new_c, snap_c = await process_crawled_products(db, store, captured_products, now, tier=2, confidence=88)
        crawl_log["products_new"] = new_c
        crawl_log["products_updated"] = len(captured_products) - new_c
        crawl_log["snapshots_created"] = snap_c
        if winning_pattern:
            await db.stores.update_one({"id": store["id"]}, {"$set": {"working_xhr_pattern": winning_pattern}})
    else:
        count = len(captured_products) if captured_products else 0
        if not crawl_log["error"]:
            crawl_log["error"] = f"Tier 2 insufficient — captured {count} products (need 5+). Escalating to Tier 3"

    await _finalize_crawl_log(db, crawl_log, store["id"])
    logger.info(f"Tier2 {store['name']}: used={crawl_log['tier_used']}, found={crawl_log['products_found']}, dur={crawl_log['duration_secs']}s")
    return crawl_log


# ── Tier 3: HTML Extraction ──────────────────────────────────
def _extract_products_from_html(html_content, platform):
    """Extract products from rendered HTML using platform-specific CSS selectors."""
    from bs4 import BeautifulSoup
    import json

    soup = BeautifulSoup(html_content, "html.parser")
    profiles_to_try = [SELECTOR_PROFILES.get(platform, {})] + [v for k, v in SELECTOR_PROFILES.items() if k != platform]
    products = []

    for profile in profiles_to_try:
        if not profile.get("card"):
            continue
        for card_sel in profile["card"]:
            cards = soup.select(card_sel)
            if len(cards) < 3:
                continue
            for card in cards:
                name = _select_first_text(card, profile.get("name", ["h3"]))
                if not name:
                    continue
                price = _select_first_price(card, profile.get("price", [".price"]))
                orig_price = _select_first_price(card, profile.get("orig", ["del"]))
                if orig_price <= price:
                    orig_price = price
                img = _select_first_attr(card, profile.get("image", ["img"]), "src", "data-src")
                products.append({
                    "name": name, "price": price,
                    "sale_price": price if price < orig_price else 0,
                    "original_price": orig_price,
                    "image": {"url": img}, "quantity": 0, "status": "sale",
                })
            if products:
                break
        if products:
            break

    # JSON-LD fallback
    if len(products) < 5:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                ld = json.loads(script.string)
                items = ld if isinstance(ld, list) else ld.get("itemListElement", [])
                for item in items:
                    prod = item.get("item", item)
                    if prod.get("@type") == "Product":
                        offer = prod.get("offers", {})
                        products.append({
                            "name": prod.get("name", ""),
                            "price": float(offer.get("price", 0)),
                            "quantity": 0, "status": "sale",
                            "image": {"url": prod.get("image", "")},
                        })
            except Exception:
                pass

    return products


def _select_first_text(card, selectors):
    for sel in selectors:
        el = card.select_one(sel)
        if el:
            return el.get_text(strip=True)
    return ""


def _select_first_price(card, selectors):
    for sel in selectors:
        el = card.select_one(sel)
        if el:
            return _extract_price_from_text(el.get_text(strip=True))
    return 0


def _select_first_attr(card, selectors, *attrs):
    for sel in selectors:
        el = card.select_one(sel)
        if el:
            for attr in attrs:
                val = el.get(attr, "")
                if val:
                    return val
    return ""


async def crawl_tier3_html(db, store):
    """Tier 3: Playwright renders page, BeautifulSoup extracts with CSS selectors."""
    start_time = time.time()
    base = f"https://{store['domain']}"
    platform = store.get("platform", "custom").lower()
    crawl_log = _make_crawl_log(store, tier_attempted=3)
    html_content = None

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            if store.get("use_proxy"):
                creds = get_proxy_credentials()
                if creds:
                    user, pwd, host, port = creds
                    launch_kwargs["proxy"] = playwright_proxy_config(user, pwd, host, port)
                    logger.info(f"[Proxy] store={store.get('domain')} tier=3 using proxy_user={user}")
            browser = await pw.chromium.launch(**launch_kwargs)
            ctx = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", locale="ar-SA")
            page = await ctx.new_page()
            for path in STORE_PAGES:
                try:
                    resp = await page.goto(f"{base}{path}", wait_until="networkidle", timeout=20000)
                    if resp and resp.status < 400:
                        crawl_log["endpoints_tried"].append({"endpoint": path, "status": resp.status, "products": 0, "error": None})
                        for _ in range(3):
                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            await page.wait_for_timeout(1500)
                        await page.wait_for_timeout(2000)
                        html_content = await page.content()
                        crawl_log["endpoint_used"] = path
                        break
                    else:
                        crawl_log["endpoints_tried"].append({"endpoint": path, "status": resp.status if resp else 0, "products": 0, "error": f"HTTP {resp.status if resp else 'none'}"})
                except Exception as e:
                    crawl_log["endpoints_tried"].append({"endpoint": path, "status": 0, "products": 0, "error": str(e)[:80]})
            await browser.close()
    except Exception as e:
        crawl_log["error"] = f"Tier 3 browser error: {str(e)[:200]}"

    products_extracted = []
    if html_content:
        products_extracted = _extract_products_from_html(html_content, platform)

    now = datetime.now(timezone.utc)
    crawl_log["duration_secs"] = round(time.time() - start_time, 1)

    if products_extracted and len(products_extracted) >= 3:
        crawl_log["tier_used"] = 3
        crawl_log["http_status"] = 200
        crawl_log["products_found"] = len(products_extracted)
        new_c, snap_c = await process_crawled_products(db, store, products_extracted, now, tier=3, confidence=75)
        crawl_log["products_new"] = new_c
        crawl_log["products_updated"] = len(products_extracted) - new_c
        crawl_log["snapshots_created"] = snap_c
    else:
        if not crawl_log["error"]:
            crawl_log["error"] = f"Tier 3 extracted {len(products_extracted)} products — all tiers exhausted"

    await _finalize_crawl_log(db, crawl_log, store["id"])
    logger.info(f"Tier3 {store['name']}: used={crawl_log['tier_used']}, found={crawl_log['products_found']}, dur={crawl_log['duration_secs']}s")
    return crawl_log


async def _discover_salla_category_ids(page, base):
    """Click into menus/dropdowns to expand nested subcategories, then extract all category IDs."""
    try:
        await page.goto(f"{base}/", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2500)
        # Hover-trigger dropdown menus to load their child links into DOM
        try:
            await page.evaluate("""
                () => {
                  document.querySelectorAll('a, button, [class*="menu"], [class*="nav"]').forEach(el => {
                    el.dispatchEvent(new MouseEvent('mouseenter', {bubbles:true}));
                    el.dispatchEvent(new MouseEvent('mouseover', {bubbles:true}));
                  });
                }
            """)
            await page.wait_for_timeout(800)
        except Exception:
            pass

        # Visit each category page to discover its subcategories (nested-only on page-load)
        ids = await page.evaluate("""
            () => {
              const out = new Set();
              document.querySelectorAll('a[href*="/categories/"], a[href*="/redirect/categories/"]').forEach(a => {
                const m = a.href.match(/categories\\/(\\d+)/);
                if (m) out.add(m[1]);
              });
              return Array.from(out);
            }
        """)
        return list(dict.fromkeys(ids))
    except Exception:
        return []


async def _capture_salla_store_identifier(page, base):
    """Visit storefront and capture the `store-identifier` header from the first XHR call to api.salla.dev.
    Falls back to visiting a known category route if the homepage doesn't trigger any API calls quickly.
    Also tries reading the meta tag / window.Salla object on the page as a last resort.
    """
    sid_holder = {"value": None}

    def on_request(req):
        if sid_holder["value"]:
            return
        if "api.salla.dev/store/v1" in req.url:
            sid = req.headers.get("store-identifier")
            if sid:
                sid_holder["value"] = sid

    page.on("request", on_request)

    async def _wait_and_scroll(timeout_ms):
        elapsed = 0
        while elapsed < timeout_ms and not sid_holder["value"]:
            await page.wait_for_timeout(700)
            elapsed += 700
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight); window.scrollTo(0, 0)")
            except Exception:
                pass

    # Pass 1 — homepage
    try:
        await page.goto(f"{base}/", wait_until="domcontentloaded", timeout=25000)
        await _wait_and_scroll(7000)
    except Exception:
        pass

    if sid_holder["value"]:
        return sid_holder["value"]

    # Pass 2 — try reading window.Salla / meta tags directly
    try:
        sid_from_dom = await page.evaluate("""
            () => {
              try {
                if (window.Salla && window.Salla.config && window.Salla.config.store && window.Salla.config.store.id) {
                  return String(window.Salla.config.store.id);
                }
                if (window.salla && window.salla.config && window.salla.config.store && window.salla.config.store.id) {
                  return String(window.salla.config.store.id);
                }
                const meta = document.querySelector('meta[name="store-id"], meta[property="store-id"], meta[name="salla-store-id"]');
                if (meta) return meta.getAttribute('content');
                // Look for store id embedded in the page HTML/scripts
                const html = document.documentElement.outerHTML;
                const m = html.match(/"store_id"\\s*:\\s*"?(\\d{5,})"?/i)
                       || html.match(/store-identifier['"\\s:=]+(\\d{5,})/i)
                       || html.match(/storeId['"\\s:=]+(\\d{5,})/i);
                if (m) return m[1];
                return null;
              } catch (e) { return null; }
            }
        """)
        if sid_from_dom:
            return str(sid_from_dom)
    except Exception:
        pass

    # Pass 3 — visit a category route (often has more aggressive XHR than homepage)
    try:
        # Try common category-list routes
        for path in ["/ar/categories", "/categories", "/ar/products", "/products"]:
            try:
                await page.goto(f"{base}{path}", wait_until="domcontentloaded", timeout=18000)
                await _wait_and_scroll(5000)
                if sid_holder["value"]:
                    return sid_holder["value"]
            except Exception:
                continue
    except Exception:
        pass

    return sid_holder["value"]


async def crawl_salla_storefront_categories(db, store, target_min_products=300, max_categories=200, max_pages_per_cat=200):
    """
    Direct-API crawler for Salla stores that disabled their public /api/v1/products endpoint.
    Strategy:
      1. Open storefront in Playwright once to:
         a. Capture the store's secret `store-identifier` header value
         b. Extract category IDs from menu (including nested via hover-trigger)
         c. Visit each top-level category to discover subcategory IDs
      2. Close browser. Use plain httpx with the captured `store-identifier` to walk
         `https://api.salla.dev/store/v1/products?source=categories&source_value[]={cat_id}` cursor pages.
      3. Deduplicate products by `id`.
    """
    start_time = time.time()
    base = f"https://{store['domain']}"
    crawl_log = _make_crawl_log(store, tier_attempted=2)
    crawl_log["endpoint_used"] = "salla_storefront_categories_direct"

    seen_ids = set()
    captured = []
    store_identifier = None
    cat_ids = []
    proxy_user_for_httpx = None

    # Phase 1 — Playwright: capture store-identifier + discover all categories (incl. nested)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            if store.get("use_proxy"):
                creds = get_proxy_credentials()
                if creds:
                    user, pwd, host, port = creds
                    launch_kwargs["proxy"] = playwright_proxy_config(user, pwd, host, port)
                    proxy_user_for_httpx = (user, pwd, host, port)
                    logger.info(f"[Proxy] store={store.get('domain')} tier=storefront_categories using proxy_user={user}")
            browser = await pw.chromium.launch(**launch_kwargs)
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="ar-SA",
            )
            page = await ctx.new_page()
            store_identifier = await _capture_salla_store_identifier(page, base)
            top_cat_ids = await _discover_salla_category_ids(page, base)
            logger.info(f"[StorefrontCategories] {store['name']}: store_identifier={store_identifier}, top categories={len(top_cat_ids)}")
            crawl_log["endpoints_tried"].append({"endpoint": "homepage", "status": 200, "products": 0, "error": f"store-id={store_identifier} top_cats={len(top_cat_ids)}"})

            # Visit each top category to discover subcategories
            sub_ids = set(top_cat_ids)
            for cid in top_cat_ids[:60]:
                try:
                    await page.goto(f"{base}/ar/redirect/categories/{cid}", wait_until="domcontentloaded", timeout=18000)
                    await page.wait_for_timeout(1500)
                    new_sub = await page.evaluate("""
                        () => {
                          const out = new Set();
                          document.querySelectorAll('a[href*="/categories/"], a[href*="/redirect/categories/"]').forEach(a => {
                            const m = a.href.match(/categories\\/(\\d+)/);
                            if (m) out.add(m[1]);
                          });
                          return Array.from(out);
                        }
                    """)
                    sub_ids.update(new_sub)
                except Exception:
                    pass
            cat_ids = list(sub_ids)[:max_categories]
            crawl_log["endpoints_tried"].append({"endpoint": "subcategory_discovery", "status": 200, "products": 0, "error": f"total_categories_discovered={len(cat_ids)}"})
            await browser.close()
    except ImportError:
        crawl_log["error"] = "Playwright not installed"
    except Exception as e:
        crawl_log["error"] = f"Storefront crawler discovery error: {str(e)[:200]}"

    if not store_identifier:
        crawl_log["error"] = (crawl_log.get("error") or "") + " | Failed to capture store-identifier"
        crawl_log["duration_secs"] = round(time.time() - start_time, 1)
        await _finalize_crawl_log(db, crawl_log, store["id"])
        return crawl_log

    # Phase 2 — direct API with store-identifier header + cursor pagination
    api_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ar",
        "x-requested-with": "XMLHttpRequest",
        "Referer": f"{base}/",
        "Origin": base,
        "store-identifier": store_identifier,
    }

    httpx_kwargs = {"timeout": 20.0, "headers": api_headers}
    bytes_consumed = 0
    if store.get("use_proxy") and proxy_user_for_httpx:
        u, p, h, port = proxy_user_for_httpx
        httpx_kwargs["proxy"] = f"http://{u}:{p}@{h}:{port}"
        logger.info(f"[Proxy] store={store.get('domain')} tier=storefront_categories_api using proxy_user={u}")

    async with httpx.AsyncClient(**httpx_kwargs) as client:
        for cid in cat_ids:
            url = f"https://api.salla.dev/store/v1/products?source=categories&source_value%5B%5D={cid}&limit=50"
            cat_count = 0
            for page_num in range(max_pages_per_cat):
                try:
                    r = await client.get(url)
                    bytes_consumed += len(r.content or b"")
                    if r.status_code != 200:
                        crawl_log["endpoints_tried"].append({"endpoint": f"cat={cid} p={page_num+1}", "status": r.status_code, "products": 0, "error": r.text[:100]})
                        break
                    body = r.json()
                    items = body.get("data") or []
                    new_added = 0
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        pid = it.get("id")
                        if pid is None or pid in seen_ids:
                            continue
                        seen_ids.add(pid)
                        captured.append(it)
                        new_added += 1
                    cat_count += new_added
                    next_url = (body.get("cursor") or {}).get("next")
                    if not next_url:
                        break
                    url = next_url
                except Exception as e:
                    crawl_log["endpoints_tried"].append({"endpoint": f"cat={cid} p={page_num+1}", "status": 0, "products": 0, "error": str(e)[:80]})
                    break
            if cat_count > 0:
                crawl_log["endpoints_tried"].append({"endpoint": f"category {cid}", "status": 200, "products": cat_count, "error": None})

    now = datetime.now(timezone.utc)
    crawl_log["duration_secs"] = round(time.time() - start_time, 1)

    if captured:
        crawl_log["tier_used"] = 2
        crawl_log["http_status"] = 200
        crawl_log["products_found"] = len(captured)
        new_c, snap_c = await process_crawled_products(db, store, captured, now, tier=2, confidence=88)
        crawl_log["products_new"] = new_c
        crawl_log["products_updated"] = len(captured) - new_c
        crawl_log["snapshots_created"] = snap_c
        await db.stores.update_one({"id": store["id"]}, {"$set": {
            "working_xhr_pattern": "salla_storefront_categories_direct",
            "salla_store_identifier": store_identifier,
        }})
    else:
        if not crawl_log.get("error"):
            crawl_log["error"] = "Storefront-categories captured 0 products"

    await _finalize_crawl_log(db, crawl_log, store["id"])
    if store.get("use_proxy") and bytes_consumed > 0:
        await record_proxy_usage(db, store, bytes_consumed)
        logger.info(f"[Proxy] usage store={store.get('domain')} bytes={bytes_consumed}")
    logger.info(f"[StorefrontCategories] {store['name']}: found={crawl_log['products_found']}, dur={crawl_log['duration_secs']}s, cats={len(cat_ids)}")
    return crawl_log


_NUMERIC_BARCODE_RE = re.compile(r"^\d{8,14}$")


def _is_valid_ean(val):
    return bool(val) and bool(_NUMERIC_BARCODE_RE.match(str(val).strip()))


# Zid's Merchant API has exposed the cumulative sold counter under different
# names across API versions/plans; probe them in priority order. Capturing this
# is what powers the "My Revenue / Units Sold" KPIs via the estimator's
# sold_count_diff method — before Feb 2026 own-store snapshots hardcoded
# sold_count=0, which made own-store sales estimation structurally impossible.
ZID_SOLD_FIELD_CANDIDATES = ("sold_quantity", "sold_count", "sales_count", "total_sold", "sold")


def _extract_zid_sold_count(product: dict) -> int:
    """Best-effort extraction of the cumulative units-sold counter from a Zid
    Merchant API product payload. Returns 0 when absent or unparseable."""
    for key in ZID_SOLD_FIELD_CANDIDATES:
        val = product.get(key)
        if val is None:
            continue
        try:
            n = int(float(str(val).strip()))
        except (ValueError, TypeError):
            continue
        if n >= 0:
            return n
    return 0


def _own_sync_fallback_warning(zid_status: str):
    """Return a user-facing warning when the own-store sync unexpectedly fell
    back from the Zid Merchant API to the public crawl.

    `missing_token` returns None — creds simply aren't configured, which is a
    setup state, not a runtime failure. Any other non-ok status means creds ARE
    configured but the API path failed, which silently zeroes the own-store
    sales KPIs (no snapshots with sold counters get written) and must be
    surfaced on the dashboard.
    """
    if zid_status in ("ok", "missing_token", None):
        return None
    return (
        f"Own-store sync fell back to public crawl (Zid API status: {zid_status}). "
        "Own snapshots with sold counters are NOT being written — 'My Revenue' and "
        "'Units Sold' KPIs will stall until the Zid API connection is restored."
    )


async def _fetch_zid_api_catalog(db, store):
    """Fetch the full product catalogue from Zid's authenticated Merchant API.

    Uses the per-store Manager Token + Store-Id headers (no OAuth flow). Iterates
    `GET https://api.zid.sa/v1/products/?page=N&page_size=200` until `next` is null.
    Returns a list of raw product dicts in the SAME shape `_normalize_raw_product`
    consumes (sku, barcode, name_ar, name_en, price, qty, image, url) so the caller
    treats it identically to the public-crawl path.

    Returns ([], "missing_token") if creds are absent — caller falls back to public crawl.
    Returns ([], "auth_failed") on 4xx so caller can fall back.
    """
    token = os.environ.get("ZID_API_TOKEN")
    store_id = os.environ.get("ZID_STORE_ID")
    if not token or not store_id:
        return [], "missing_token"

    headers = {
        "Access-Token": token,
        "Store-Id": store_id,
        "Role": "Manager",
        "Accept-Language": "en",
        "Accept": "application/json",
    }
    out = []
    try:
        async with httpx.AsyncClient(base_url="https://api.zid.sa/v1", timeout=45.0) as http:
            page = 1
            while True:
                resp = await http.get(
                    "/products/",
                    params={"page": page, "page_size": 200},
                    headers=headers,
                )
                if resp.status_code in (401, 403):
                    logger.error(f"[OwnSync][Zid API] auth rejected status={resp.status_code}")
                    return [], "auth_failed"
                resp.raise_for_status()
                payload = resp.json()
                items = payload.get("results") or []
                for p in items:
                    name_obj = p.get("name") or {}
                    out.append({
                        "sku": str(p.get("sku") or "").strip(),
                        "barcode": str(p.get("barcode") or "").strip(),
                        "name_ar": name_obj.get("ar") or "",
                        "name_en": name_obj.get("en") or "",
                        "price": p.get("sale_price") or p.get("price") or 0,
                        "sale_price": p.get("sale_price"),
                        "qty_available": 0 if p.get("is_infinite") else (p.get("quantity") or 0),
                        "in_stock": bool(p.get("is_infinite")) or ((p.get("quantity") or 0) > 0),
                        # Cumulative units-sold counter — feeds the estimator's
                        # sold_count_diff method (works even for is_infinite
                        # products whose qty can never show depletion).
                        "sold_count": _extract_zid_sold_count(p),
                        "img_url": ((p.get("images") or [{}])[0] or {}).get("origin") or ((p.get("images") or [{}])[0] or {}).get("image") or "",
                        "product_url": p.get("html_url") or "",
                        "_zid_id": p.get("id"),
                        "_zid_is_infinite": bool(p.get("is_infinite")),
                    })
                if not payload.get("next"):
                    break
                page += 1
                # Brief breathing room between pages — well below Zid's published rate limits
                await asyncio.sleep(0.15)
                if page > 100:
                    logger.warning("[OwnSync][Zid API] hit 100-page safety cap")
                    break
    except httpx.HTTPError as e:
        logger.error(f"[OwnSync][Zid API] network error after {len(out)} products: {e}")
        return out, "partial" if out else "network_failed"
    logger.info(f"[OwnSync][Zid API] fetched {len(out)} products in {page} page(s)")
    return out, "ok"


async def sync_own_store_prices(db, store=None):
    """Sync prices/quantities from the user's own Zid store back into db.my_products.

    Strategy:
      1. Find the store flagged is_own_store=True (or use the one passed in).
      2. PREFER the authenticated Zid Merchant API (when ZID_API_TOKEN +
         ZID_STORE_ID are present). Falls back to public Tier-1 JSON crawl on
         auth failure or missing creds.
      3. For each crawled product, match against my_products by:
           Level 1 — barcode match (8-14 digit EAN)
           Level 2 — exact SKU match
         No name-based matching.
      4. Update ONLY: price, sale_price, quantity, in_stock, last_synced_at, sync_source.
         Never overwrite catalog metadata (names, images, categories, URLs).
      5. New SKUs are upserted into db.my_products with full metadata (auto-discovery).
      6. After sync, schedule run_matching_for_all() so Price Intel reflects the new prices.

    Returns: {"updated": int, "discovered": int, "archived": int, "not_found": int,
              "crawled": int, "store": str, "synced_at": iso, "source": "zid_api"|"public_crawl"}
    """
    if store is None:
        store = await db.stores.find_one({"is_own_store": True}, {"_id": 0})
    if not store:
        logger.warning("[OwnSync] No store flagged is_own_store=True — skipping sync")
        return {"updated": 0, "not_found": 0, "crawled": 0, "store": None,
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "error": "no_own_store_flagged"}

    started_at = datetime.now(timezone.utc)
    logger.info(f"[OwnSync] Starting price sync for {store['name']} ({store.get('domain')})")

    # ── Try Zid Merchant API first; fall back to public crawl on miss ──
    sync_source_label = None
    all_raw, zid_status = await _fetch_zid_api_catalog(db, store)
    winning_endpoint = None
    crawl_log = _make_crawl_log(store, tier_attempted=1)

    if zid_status == "ok" and all_raw:
        sync_source_label = "zid_api"
        winning_endpoint = {"tag": "zid_merchant_api"}
        crawl_log["tier_used"] = 0  # 0 = authenticated API (better than tier 1 public)
        crawl_log["endpoint_used"] = "https://api.zid.sa/v1/products/"
        await db.stores.update_one({"id": store["id"]}, {"$set": {"working_endpoint": "zid_merchant_api"}})
    else:
        if zid_status != "missing_token":
            logger.warning(f"[OwnSync] Zid API attempt → {zid_status}; falling back to public crawl")
        sync_source_label = "public_crawl"
        # ── Public Tier-1 JSON crawl (no browser) ──
        base = f"https://{store['domain']}"
        platform = store.get("platform", "zid").lower()
        endpoints = _build_salla_endpoints(base, store.get("working_endpoint"), platform=platform)
        all_raw = []
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/html, */*",
            }) as http:
                for ep in endpoints:
                    items, matched_ep = await _try_single_endpoint(http, ep, crawl_log)
                    if matched_ep:
                        all_raw = await _paginate_endpoint(http, matched_ep, items)
                        winning_endpoint = matched_ep
                        break
        except Exception as e:
            crawl_log["error"] = str(e)[:300]
            logger.error(f"[OwnSync] Crawl failed: {e}")

        if winning_endpoint:
            crawl_log["tier_used"] = 1
            crawl_log["endpoint_used"] = winning_endpoint["tag"]
            await db.stores.update_one({"id": store["id"]}, {"$set": {"working_endpoint": winning_endpoint["tag"]}})

    crawled = len(all_raw)
    crawl_log["products_found"] = crawled

    # ── Pre-build lookup tables of my_products by barcode + SKU ──
    my_by_sku, my_by_barcode = {}, {}
    async for mp in db.my_products.find({}, {"_id": 0, "sku": 1, "barcode": 1}):
        if mp.get("sku"):
            my_by_sku[str(mp["sku"]).strip()] = mp["sku"]
        if _is_valid_ean(mp.get("barcode")):
            my_by_barcode[str(mp["barcode"]).strip()] = mp["sku"]

    # ── Match + update ──
    updated, not_found, discovered = 0, 0, 0
    seen_skus = set()  # SKUs touched by THIS sync — used to mark presence flag
    sync_ts = datetime.now(timezone.utc).isoformat()
    UPDATE_FIELDS_NEVER_OVERWRITE = {  # noqa: F841 — documentation only
        "sku", "barcode", "name_ar", "name_en", "description_ar", "description_en",
        "categories_ar", "categories_en", "images", "product_page_url",
        "is_own_store", "store_id", "imported_at",
    }

    own_store_id = store.get("id")

    for raw in all_raw:
        # Zid API rows arrive pre-normalised (see _fetch_zid_api_catalog); the
        # public-crawl path needs _normalize_raw_product to reshape Salla/Zid
        # storefront JSON. Distinguish by the synthetic `_zid_id` marker.
        if raw.get("_zid_id"):
            norm = {
                "sku": raw.get("sku") or "",
                "barcode": raw.get("barcode") or "",
                "name_ar": raw.get("name_ar") or "",
                "name_en": raw.get("name_en") or "",
                "price": raw.get("price") or 0,
                "sale_price": raw.get("sale_price"),
                "qty": raw.get("qty_available") or 0,
                "in_stock": raw.get("in_stock", False),
                "img_url": raw.get("img_url", ""),
                "product_url": raw.get("product_url", ""),
            }
        else:
            norm = _normalize_raw_product(raw, store["name"])
        crawled_sku = str(norm["sku"]).strip()
        crawled_barcode = str(norm.get("barcode") or "").strip()

        target_sku = None
        # Level 1: barcode (EAN 8-14 digits)
        if _is_valid_ean(crawled_barcode) and crawled_barcode in my_by_barcode:
            target_sku = my_by_barcode[crawled_barcode]
        # Level 2: exact SKU match
        elif crawled_sku and crawled_sku in my_by_sku:
            target_sku = my_by_sku[crawled_sku]
        # Numeric-SKU-as-barcode fallback (some Zid stores put EAN in the SKU field)
        elif _is_valid_ean(crawled_sku) and crawled_sku in my_by_barcode:
            target_sku = my_by_barcode[crawled_sku]

        if not target_sku:
            # Feb 2026: previously this branch silently discarded the product.
            # New behaviour (per user request "auto-add new SKUs from store"):
            # upsert a fresh my_products row using all normalized metadata from
            # the Zid crawl. We never overwrite an existing row this way — the
            # `not_found` lookups above guarantee this SKU is genuinely new.
            new_doc = {
                "id": str(uuid.uuid4()),
                "sku": crawled_sku,
                "barcode": crawled_barcode or "",
                "name_ar": norm.get("name_ar", ""),
                "name_en": norm.get("name_en") or norm.get("name_ar", ""),
                "image_url": norm.get("img_url", ""),
                "product_url": norm.get("product_url", ""),
                "price": round(norm["price"], 2),
                "sale_price": round(norm["sale_price"], 2) if norm.get("sale_price") else None,
                "quantity": int(norm["qty"]),
                "in_stock": bool(norm["in_stock"]),
                "is_own_store": True,
                "store_id": own_store_id,
                "imported_at": sync_ts,
                "first_seen_on_store": sync_ts,
                "last_seen_on_store": sync_ts,
                "present_on_store": True,
                "last_synced_at": sync_ts,
                "sync_source": f"{sync_source_label}_auto_discovery",
                "discovered_via": sync_source_label,
            }
            await db.my_products.update_one(
                {"sku": crawled_sku},
                {"$setOnInsert": new_doc},
                upsert=True,
            )
            # Keep the in-memory lookups consistent for the rest of the loop
            my_by_sku[crawled_sku] = crawled_sku
            if _is_valid_ean(crawled_barcode):
                my_by_barcode[crawled_barcode] = crawled_sku
            seen_skus.add(crawled_sku)
            discovered += 1
            not_found += 1  # preserved for backwards-compat metric
            continue

        update_doc = {
            "price": round(norm["price"], 2),
            "sale_price": round(norm["sale_price"], 2) if norm.get("sale_price") else None,
            "quantity": int(norm["qty"]),
            "in_stock": bool(norm["in_stock"]),
            "last_synced_at": sync_ts,
            "sync_source": sync_source_label,
            "present_on_store": True,
            "last_seen_on_store": sync_ts,
        }
        await db.my_products.update_one({"sku": target_sku}, {"$set": update_doc})
        seen_skus.add(target_sku)
        updated += 1

    # ── Write through to db.products + db.product_snapshots (Zid API source only) ──
    # The My Products table joins on db.product_snapshots, so without this write
    # newly synced Zid products wouldn't appear until the next scheduled crawl
    # runs and inserts a snapshot. With Zid's API as our authoritative source,
    # we surface every product immediately via a synthetic source_tier=0 snapshot.
    snapshots_created = 0
    snapshots_deduped = 0
    if sync_source_label == "zid_api" and all_raw:
        # ── Change-only writes + daily heartbeat (iter24, Jul 2026) ──
        # The 6h sync + daily crawl job wrote ~5.2 snapshots/SKU/day, ~80% of
        # them byte-identical to the previous one. At 2,175 SKUs that's ~11.3k
        # rows/day of pure duplication — the volume that pushed the 30D/90D
        # dashboard windows past pod limits (Cloudflare 520). A snapshot is
        # now written only when (price, qty, sold_count, in_stock) changed
        # since the LAST snapshot written TODAY (UTC) — so the first sync of
        # each day always writes (daily heartbeat). Downstream contracts that
        # depend on a snapshot existing every day are preserved:
        #   • compute_market_position's 7-day seller-freshness cutoff
        #   • on_date single-day windows (every day has ≥1 own snapshot)
        #   • sales estimator: dropping snapshots whose price/qty/sold values
        #     are IDENTICAL to their predecessor cannot change positive-delta
        #     sums or sold-counter diffs (equal-adjacent values contribute 0).
        _today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        _todays_latest = {}
        async for _snap in db.product_snapshots.find(
            {"store_id": own_store_id, "crawled_at": {"$gte": _today_start}},
            {"_id": 0, "sku": 1, "price": 1, "qty_available": 1, "sold_count": 1, "in_stock": 1, "crawled_at": 1},
        ):
            _prev = _todays_latest.get(_snap["sku"])
            if _prev is None or _snap["crawled_at"] > _prev["crawled_at"]:
                _todays_latest[_snap["sku"]] = _snap

        snap_docs = []
        prod_upserts = []
        for raw in all_raw:
            sku = (raw.get("sku") or "").strip()
            if not sku:
                continue
            price = raw.get("price") or 0
            qty = raw.get("qty_available") or 0
            in_stock = bool(raw.get("in_stock")) if not raw.get("_zid_is_infinite") else True
            barcode = raw.get("barcode") or ""
            _prev = _todays_latest.get(sku)
            _snapshot_unchanged_today = _prev is not None and (
                round(float(_prev.get("price") or 0), 2) == round(float(price), 2)
                and int(_prev.get("qty_available") or 0) == int(qty)
                and int(_prev.get("sold_count") or 0) == int(raw.get("sold_count") or 0)
                and bool(_prev.get("in_stock")) == in_stock
            )
            # Upsert catalog row (idempotent — only sets if new, preserves history)
            prod_upserts.append({
                "sku": sku,
                "set_on_insert": {
                    "id": str(uuid.uuid4()),
                    "sku": sku,
                    "barcode": barcode,
                    "name_ar": raw.get("name_ar") or "",
                    "name_en": raw.get("name_en") or "",
                    "image_url": raw.get("img_url") or "",
                    "product_url": raw.get("product_url") or "",
                    "first_seen_at": sync_ts,
                    "category": "",
                    "animal_type": "",
                    "brand": "",
                },
            })
            if _snapshot_unchanged_today:
                snapshots_deduped += 1
                continue  # values unchanged since the last snapshot today — no new row
            snap_docs.append({
                "id": str(uuid.uuid4()),
                "store_id": own_store_id,
                "store_name": store["name"],
                "sku": sku,
                "price": round(price, 2),
                "original_price": round(price, 2),
                "discount_pct": 0,
                "in_stock": in_stock,
                "qty_available": int(qty),
                # Real cumulative sold counter from the Zid Merchant API (was
                # hardcoded 0 until Feb 2026, which zeroed all own-sales KPIs).
                "sold_count": int(raw.get("sold_count") or 0),
                "product_url": raw.get("product_url") or "",
                "source_tier": 0,  # 0 = authenticated API (best signal we have)
                "confidence_score": 99,
                "crawled_at": started_at,
            })
        # Bulk upsert catalog rows (only sets on insert; never overwrites)
        for up in prod_upserts:
            await db.products.update_one({"sku": up["sku"]}, {"$setOnInsert": up["set_on_insert"]}, upsert=True)
        # Bulk insert snapshots
        if snap_docs:
            await db.product_snapshots.insert_many(snap_docs)
            snapshots_created = len(snap_docs)

    # ── Mark every my_products row NOT seen in this crawl as archived ──
    # Soft-archive only: row + history are preserved, but `present_on_store=False`
    # lets the UI badge them as "Removed from store" without filtering them out.
    archived = 0
    if all_raw:  # safety: skip archival if the crawl returned nothing (likely upstream block)
        res = await db.my_products.update_many(
            {"sku": {"$nin": list(seen_skus)}},
            {"$set": {"present_on_store": False, "last_archive_check": sync_ts}},
        )
        archived = res.modified_count or 0

    duration = (datetime.now(timezone.utc) - started_at).total_seconds()
    crawl_log["products_updated"] = updated
    crawl_log["products_new"] = discovered
    crawl_log["snapshots_created"] = snapshots_created
    crawl_log["snapshots_deduped"] = snapshots_deduped  # change-only writes (iter24)
    if not all_raw:
        crawl_log["error"] = (crawl_log.get("error") or "") + " | own-store crawl returned 0 items"
    await _finalize_crawl_log(db, crawl_log, store["id"])

    # Fallback alert (Feb 2026): creds configured but the Zid API path failed —
    # own snapshots (and their sold counters) are not being written, which
    # silently zeroes the My Revenue / Units Sold KPIs. Surface it everywhere.
    sync_warning = _own_sync_fallback_warning(zid_status) if sync_source_label == "public_crawl" else None
    if sync_warning:
        logger.warning(f"[OwnSync] {sync_warning}")

    # Persist sync stats on the store doc for /api/import/status
    await db.stores.update_one(
        {"id": store["id"]},
        {"$set": {
            "last_own_store_sync": sync_ts,
            "own_store_sync_updated": updated,
            "own_store_sync_not_found": not_found,
            "own_store_sync_crawled": crawled,
            "own_store_sync_discovered": discovered,
            "own_store_sync_archived": archived,
            "own_store_sync_source": sync_source_label,
            "own_store_sync_warning": sync_warning or "",
        }},
    )

    logger.info(
        f"[OwnSync] Done in {duration:.1f}s — crawled={crawled}, updated={updated}, "
        f"discovered={discovered}, archived={archived}, not_found={not_found}"
    )

    return {
        "store": store["name"],
        "domain": store.get("domain"),
        "source": sync_source_label,
        "zid_status": zid_status,
        "warning": sync_warning,
        "crawled": crawled,
        "updated": updated,
        "discovered": discovered,
        "archived": archived,
        "not_found": not_found,
        "synced_at": sync_ts,
        "duration_seconds": round(duration, 1),
        # Mimic the standard crawl-log shape so /api/stores/{id}/crawl response stays consistent
        "tier_used": crawl_log.get("tier_used"),
        "http_status": 200 if winning_endpoint else 0,
        "products_found": crawled,
        "products_new": discovered,
        "products_updated": updated,
        "snapshots_created": snapshots_created,
        "error": crawl_log.get("error"),
        "completed_at": sync_ts,
        "duration_secs": round(duration, 1),
        "is_own_store_sync": True,
    }


# ── Waterfall Orchestrator ───────────────────────────────────
async def crawl_store_waterfall(db, store):
    """Run the multi-tier waterfall crawler for a store, with optional Tier 4 supplement.

    Special-case: own store (is_own_store=True) is sync'd into my_products via
    sync_own_store_prices() instead of going through the competitor snapshot pipeline.
    """
    if store.get("is_own_store"):
        return await sync_own_store_prices(db, store=store)

    platform = store.get("platform", "").lower()
    tier1_only = bool(store.get("tier1_only"))
    storefront_strategy = bool(store.get("use_storefront_categories"))

    # Tier 1: JSON endpoints (skipped if store has explicitly disabled the API)
    if platform in ("salla", "shopify", "zid") and not storefront_strategy:
        result = await crawl_salla_tier1(db, store)
        if result.get("tier_used"):
            # Tier 4: Authenticated supplement (runs after success if configured)
            await _try_tier4_supplement(db, store, result)
            return result
        if tier1_only:
            # Skip Playwright-based Tiers 2/3 (e.g., on hosts without Chromium)
            result["error"] = (result.get("error") or "") + " | tier1_only=True: Tier 2/3 browser tiers skipped."
            return result

    # Tier 2.5 (Storefront categories) — for stores that disabled their public API
    if storefront_strategy:
        result = await crawl_salla_storefront_categories(db, store)
        if result.get("tier_used"):
            await _try_tier4_supplement(db, store, result)
            return result

    # Tier 2: XHR interception (homepage scroll)
    result = await crawl_tier2_xhr(db, store)
    if result.get("tier_used"):
        await _try_tier4_supplement(db, store, result)
        return result
    # Tier 3: HTML scraping
    result = await crawl_tier3_html(db, store)
    await _try_tier4_supplement(db, store, result)
    return result


async def _try_tier4_supplement(db, store, base_result):
    """Run Tier 4 authenticated crawl as a supplement if credentials are configured and session is active."""
    store_id = store.get("id")
    if not store_id:
        return
    # Refresh store data to get latest tier4 fields
    s = await db.stores.find_one({"id": store_id}, {"_id": 0})
    if not s:
        return
    session_status = s.get("tier4_session_status", "not_configured")
    if session_status != "active" or not s.get("tier4_session_cookies"):
        return
    # Check session expiry
    session_expiry = s.get("tier4_session_expiry")
    if session_expiry:
        exp = session_expiry if isinstance(session_expiry, datetime) else datetime.fromisoformat(str(session_expiry))
        if hasattr(exp, 'tzinfo') and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            await db.stores.update_one({"id": store_id}, {"$set": {"tier4_session_status": "expired"}})
            return
    try:
        from server import decrypt_value
        cookies_enc = s["tier4_session_cookies"]
        cookies_str = decrypt_value(cookies_enc)
        import ast
        cookies = ast.literal_eval(cookies_str)
    except Exception as exc:
        logger.warning(f"[T4 Crawl] Cannot decrypt cookies for {store.get('name')}: {type(exc).__name__}")
        return
    try:
        await crawl_tier4_authenticated(db, store, cookies)
    except Exception as exc:
        logger.warning(f"[T4 Crawl] Error for {store.get('name')}: {type(exc).__name__}: {exc}")


async def crawl_tier4_authenticated(db, store, cookies):
    """Tier 4: Authenticated crawl — captures extra data points available only when logged in."""
    from playwright.async_api import async_playwright
    store_id = store["id"]
    store_name = store.get("name", "")
    base_url = store.get("base_url") or f"https://{store['domain']}"
    platform = store.get("platform", "").lower()
    now = datetime.now(timezone.utc)
    logger.info(f"[T4 Crawl] Starting authenticated crawl for {store_name}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="ar-SA",
        )
        # Inject saved session cookies
        for c in cookies:
            try:
                await context.add_cookies([c])
            except Exception:
                pass
        page = await context.new_page()
        t4_snapshots = []
        # Navigate to product listing pages
        product_urls = [f"{base_url}/products", f"{base_url}/shop", f"{base_url}/collection/all"]
        for purl in product_urls:
            try:
                resp = await page.goto(purl, wait_until="domcontentloaded", timeout=15000)
                if resp and resp.status < 400:
                    break
            except Exception:
                continue
        await page.wait_for_timeout(3000)
        # Extract authenticated data from product cards on the page
        cards = await page.query_selector_all(".product-card, .product-item, [data-product], .product-entry, .product")
        for card in cards[:50]:
            try:
                snapshot = await _extract_tier4_data(card, page, platform)
                if snapshot:
                    snapshot["store_id"] = store_id
                    snapshot["store_name"] = store_name
                    snapshot["source_tier"] = 4
                    snapshot["confidence_score"] = 96
                    snapshot["tier4_authenticated"] = True
                    snapshot["crawled_at"] = now
                    snapshot["id"] = str(uuid.uuid4())
                    t4_snapshots.append(snapshot)
            except Exception:
                continue
        if t4_snapshots:
            await db.product_snapshots.insert_many(t4_snapshots)
            logger.info(f"[T4 Crawl] {store_name}: {len(t4_snapshots)} authenticated snapshots created")
        await db.stores.update_one({"id": store_id}, {"$set": {"tier4_last_auth_crawl": now.isoformat()}})
        await browser.close()
    return {"tier4_snapshots": len(t4_snapshots)}


async def _extract_tier4_data(card, page, platform):
    """Extract authenticated-only data points from a product card element."""
    data = {}
    # Try to get product name/SKU for matching
    name_el = await card.query_selector(".product-title, .product-name, h3, h4, [data-product-title]")
    if name_el:
        data["name"] = (await name_el.inner_text()).strip()
    # Member price
    member_el = await card.query_selector(".member-price, .loyalty-price, [data-member-price], .special-price")
    if member_el:
        text = await member_el.inner_text()
        price = _extract_price_from_card_text(text)
        if price:
            data["tier4_member_price"] = price
    # Regular price
    price_el = await card.query_selector(".price, [data-price], .product-price")
    if price_el:
        text = await price_el.inner_text()
        price = _extract_price_from_card_text(text)
        if price:
            data["price"] = price
    # Flash sale
    flash_el = await card.query_selector(".flash-sale, .countdown, [data-flash], .sale-badge")
    if flash_el:
        data["tier4_flash_sale"] = True
        flash_price_el = await card.query_selector(".flash-price, .sale-price")
        if flash_price_el:
            text = await flash_price_el.inner_text()
            fp = _extract_price_from_card_text(text)
            if fp:
                data["tier4_flash_price"] = fp
    # Exact stock
    stock_el = await card.query_selector(".stock-count, [data-quantity], .availability")
    if stock_el:
        text = await stock_el.inner_text()
        import re as _re
        nums = _re.findall(r'\d+', text)
        if nums:
            data["tier4_qty_exact"] = int(nums[0])
    # In stock
    data["in_stock"] = True
    oos_el = await card.query_selector(".out-of-stock, .sold-out, [data-oos]")
    if oos_el:
        data["in_stock"] = False
    if not data.get("name") and not data.get("price"):
        return None
    return data


def _extract_price_from_card_text(text):
    """Extract numeric price from text like '199.99 ر.س' or 'SAR 199'."""
    import re as _re
    nums = _re.findall(r'[\d,]+\.?\d*', text.replace(',', ''))
    if nums:
        try:
            return float(nums[0])
        except ValueError:
            pass
    return None
