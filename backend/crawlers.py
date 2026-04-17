"""
Daleel Pets — Multi-tier Crawler Module
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

    qty = int(raw.get("quantity", raw.get("stock_quantity", raw.get("qty", 0))) or 0)

    in_stock = raw.get("status") in ("sale", "active") or raw.get("is_available", raw.get("availability", qty > 0))

    imgs = raw.get("images", raw.get("image", []))
    img_url = ""
    if isinstance(imgs, list) and imgs:
        img_url = imgs[0].get("url", imgs[0].get("src", "")) if isinstance(imgs[0], dict) else str(imgs[0])
    elif isinstance(imgs, dict):
        img_url = imgs.get("url", imgs.get("src", ""))

    return {
        "name_ar": name_ar,
        "sku": sku_raw,
        "price": price,
        "original_price": original_price,
        "qty": max(0, qty),
        "in_stock": bool(in_stock),
        "img_url": img_url,
    }


async def process_crawled_products(db, store, all_raw, now, tier=1, confidence=95):
    """Process raw product data from any crawler tier into products + snapshots."""
    new_count = 0
    snap_count = 0
    for raw in all_raw:
        norm = _normalize_raw_product(raw, store["name"])

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
                "first_seen_at": now.isoformat(),
            })
            new_count += 1
        else:
            pid = existing["id"]
            if norm["img_url"] and not existing.get("image_url"):
                await db.products.update_one({"id": pid}, {"$set": {"image_url": norm["img_url"]}})

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
        # Zid page-number pagination
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
            )
            page = await ctx.new_page()
            intercepted = []
            page.on("response", _build_xhr_response_handler(intercepted))

            attempts, page_loaded = await _playwright_navigate_and_scroll(page, base)
            crawl_log["endpoints_tried"] = attempts
            await browser.close()

            if intercepted:
                best = max(intercepted, key=lambda x: x["count"])
                captured_products = best["items"]
                winning_pattern = best["url"]
                for ep in crawl_log["endpoints_tried"]:
                    ep["products"] = best["count"]
                crawl_log["endpoint_used"] = winning_pattern

    except ImportError:
        crawl_log["error"] = "Playwright not installed"
    except Exception as e:
        crawl_log["error"] = f"Tier 2 error: {str(e)[:200]}"

    now = datetime.now(timezone.utc)
    crawl_log["duration_secs"] = round(time.time() - start_time, 1)

    if captured_products and len(captured_products) >= 5:
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


# ── Waterfall Orchestrator ───────────────────────────────────
async def crawl_store_waterfall(db, store):
    """Run the 3-tier waterfall crawler for a store, with optional Tier 4 supplement."""
    platform = store.get("platform", "").lower()
    # Tier 1: JSON endpoints
    if platform in ("salla", "shopify", "zid"):
        result = await crawl_salla_tier1(db, store)
        if result.get("tier_used"):
            # Tier 4: Authenticated supplement (runs after success if configured)
            await _try_tier4_supplement(db, store, result)
            return result
    # Tier 2: XHR interception
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
