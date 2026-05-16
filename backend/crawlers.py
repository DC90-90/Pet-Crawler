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
import logging
import httpx
from datetime import datetime, timezone

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")
logger = logging.getLogger(__name__)

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


def _normalize_raw_product(raw, store_name):
    """Normalize a single raw product dict from any source into a standard form."""
    name_ar = raw.get("name", raw.get("title", ""))

    sku_raw = raw.get("sku") or raw.get("mpn") or f"S-{store_name[:2].upper()}-{raw.get('id', uuid.uuid4().hex[:6])}"

    price_field = raw.get("price", 0)
    if isinstance(price_field, dict):
        price = float(price_field.get("amount", 0))
    else:
        price = float(price_field or 0)

    sale_field = raw.get("sale_price", raw.get("promotion", {}).get("price", 0))
    if isinstance(sale_field, dict):
        sale_price = float(sale_field.get("amount", 0))
    else:
        sale_price = float(sale_field or 0)

    original_price = price
    if 0 < sale_price < price:
        original_price = price
        price = sale_price

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
        "sale_price": float(sale_price) if 0 < sale_price < (price + sale_price) else None,
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
        if not existing:
            pid = str(uuid.uuid4())
            await db.products.insert_one({
                "id": pid, "sku": norm["sku"],
                "name_ar": norm["name_ar"], "name_en": norm["name_ar"],
                "brand": extract_brand(norm["name_ar"]),
                "category": guess_category(norm["name_ar"]),
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
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
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
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
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

    # Phase 1 — Playwright: capture store-identifier + discover all categories (incl. nested)
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
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

    async with httpx.AsyncClient(timeout=20.0, headers=api_headers) as client:
        for cid in cat_ids:
            url = f"https://api.salla.dev/store/v1/products?source=categories&source_value%5B%5D={cid}&limit=50"
            cat_count = 0
            for page_num in range(max_pages_per_cat):
                try:
                    r = await client.get(url)
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
    logger.info(f"[StorefrontCategories] {store['name']}: found={crawl_log['products_found']}, dur={crawl_log['duration_secs']}s, cats={len(cat_ids)}")
    return crawl_log


_NUMERIC_BARCODE_RE = re.compile(r"^\d{8,14}$")


def _is_valid_ean(val):
    return bool(val) and bool(_NUMERIC_BARCODE_RE.match(str(val).strip()))


async def sync_own_store_prices(db, store=None):
    """Sync prices/quantities from the user's own Zid store back into db.my_products.

    Strategy:
      1. Find the store flagged is_own_store=True (or use the one passed in).
      2. Crawl its public Tier-1 JSON endpoint (no Playwright — JSON only).
      3. For each crawled product, match against my_products by:
           Level 1 — barcode match (8-14 digit EAN)
           Level 2 — exact SKU match
         No name-based matching.
      4. Update ONLY: price, sale_price, quantity, in_stock, last_synced_at, sync_source.
         Never overwrite catalog metadata (names, images, categories, URLs).
      5. After sync, schedule run_matching_for_all() so Price Intel reflects the new prices.

    Returns: {"updated": int, "not_found": int, "crawled": int, "store": str, "synced_at": iso}
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

    # ── Tier-1 JSON crawl (no browser) ──
    base = f"https://{store['domain']}"
    platform = store.get("platform", "zid").lower()
    endpoints = _build_salla_endpoints(base, store.get("working_endpoint"), platform=platform)
    crawl_log = _make_crawl_log(store, tier_attempted=1)
    all_raw = []
    winning_endpoint = None
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

    crawled = len(all_raw)
    crawl_log["products_found"] = crawled
    if winning_endpoint:
        crawl_log["tier_used"] = 1
        crawl_log["endpoint_used"] = winning_endpoint["tag"]
        await db.stores.update_one({"id": store["id"]}, {"$set": {"working_endpoint": winning_endpoint["tag"]}})

    # ── Pre-build lookup tables of my_products by barcode + SKU ──
    my_by_sku, my_by_barcode = {}, {}
    async for mp in db.my_products.find({}, {"_id": 0, "sku": 1, "barcode": 1}):
        if mp.get("sku"):
            my_by_sku[str(mp["sku"]).strip()] = mp["sku"]
        if _is_valid_ean(mp.get("barcode")):
            my_by_barcode[str(mp["barcode"]).strip()] = mp["sku"]

    # ── Match + update ──
    updated, not_found = 0, 0
    sync_ts = datetime.now(timezone.utc).isoformat()
    UPDATE_FIELDS_NEVER_OVERWRITE = {  # noqa: F841 — documentation only
        "sku", "barcode", "name_ar", "name_en", "description_ar", "description_en",
        "categories_ar", "categories_en", "images", "product_page_url",
        "is_own_store", "store_id", "imported_at",
    }

    for raw in all_raw:
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
            not_found += 1
            continue

        update_doc = {
            "price": round(norm["price"], 2),
            "sale_price": round(norm["sale_price"], 2) if norm.get("sale_price") else None,
            "quantity": int(norm["qty"]),
            "in_stock": bool(norm["in_stock"]),
            "last_synced_at": sync_ts,
            "sync_source": "zid_crawler",
        }
        await db.my_products.update_one({"sku": target_sku}, {"$set": update_doc})
        updated += 1

    duration = (datetime.now(timezone.utc) - started_at).total_seconds()
    crawl_log["products_updated"] = updated
    crawl_log["products_new"] = 0  # never creates new my_products rows
    crawl_log["snapshots_created"] = 0
    if not all_raw:
        crawl_log["error"] = (crawl_log.get("error") or "") + " | own-store crawl returned 0 items"
    await _finalize_crawl_log(db, crawl_log, store["id"])

    # Persist sync stats on the store doc for /api/import/status
    await db.stores.update_one(
        {"id": store["id"]},
        {"$set": {
            "last_own_store_sync": sync_ts,
            "own_store_sync_updated": updated,
            "own_store_sync_not_found": not_found,
            "own_store_sync_crawled": crawled,
        }},
    )

    logger.info(f"[OwnSync] Done in {duration:.1f}s — crawled={crawled}, updated={updated}, not_found={not_found}")

    return {
        "store": store["name"],
        "domain": store.get("domain"),
        "crawled": crawled,
        "updated": updated,
        "not_found": not_found,
        "synced_at": sync_ts,
        "duration_seconds": round(duration, 1),
        # Mimic the standard crawl-log shape so /api/stores/{id}/crawl response stays consistent
        "tier_used": crawl_log.get("tier_used"),
        "http_status": 200 if winning_endpoint else 0,
        "products_found": crawled,
        "products_new": 0,
        "products_updated": updated,
        "snapshots_created": 0,
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
