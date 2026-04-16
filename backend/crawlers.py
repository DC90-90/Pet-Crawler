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
def _build_salla_endpoints(base, cached_endpoint):
    endpoints = [
        {"url": f"{base}/api/v2/products", "params": {"per_page": 50, "page": 1}, "tag": "/api/v2/products"},
        {"url": f"{base}/products.json", "params": {"limit": 250, "page": 1}, "tag": "/products.json"},
        {"url": f"{base}/api/store/products", "params": {"limit": 50, "page": 1}, "tag": "/api/store/products"},
        {"url": f"{base}/api/product/list", "params": {"per_page": 50, "page": 1}, "tag": "/api/product/list"},
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
        resp = await http.get(ep["url"], params=ep["params"])
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
        items = body.get("data", body.get("products", []))
        if isinstance(items, list) and len(items) >= 5:
            attempt["products"] = len(items)
            crawl_log["endpoints_tried"].append(attempt)
            return items, ep
        attempt["products"] = len(items) if isinstance(items, list) else 0
        attempt["error"] = f"Only {attempt['products']} products (need 5+)"
    except httpx.TimeoutException:
        attempt["status"] = 0
        attempt["error"] = "Timeout"
    except Exception as e:
        attempt["status"] = 0
        attempt["error"] = str(e)[:100]
    crawl_log["endpoints_tried"].append(attempt)
    return [], None


async def _paginate_endpoint(http, ep, initial_items):
    """Paginate through remaining pages of a working endpoint."""
    all_items = list(initial_items)
    page = 2
    limit_key = list(ep["params"].keys())[0]
    limit_val = ep["params"][limit_key]
    while page <= 20:
        params = {limit_key: limit_val, "page": page}
        r2 = await http.get(ep["url"], params=params)
        if r2.status_code != 200:
            break
        try:
            body2 = r2.json()
            more = body2.get("data", body2.get("products", []))
        except Exception:
            break
        if not more:
            break
        all_items.extend(more)
        page += 1
        if len(more) < limit_val:
            break
    return all_items


async def crawl_salla_tier1(db, store):
    """Tier 1: Try multiple Salla public JSON endpoints in sequence. Cache working endpoint."""
    base = f"https://{store['domain']}"
    endpoints = _build_salla_endpoints(base, store.get("working_endpoint"))
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
    """Run the 3-tier waterfall crawler for a store."""
    platform = store.get("platform", "").lower()
    # Tier 1: JSON endpoints
    if platform in ("salla", "shopify", "zid"):
        result = await crawl_salla_tier1(db, store)
        if result.get("tier_used"):
            return result
    # Tier 2: XHR interception
    result = await crawl_tier2_xhr(db, store)
    if result.get("tier_used"):
        return result
    # Tier 3: HTML scraping
    result = await crawl_tier3_html(db, store)
    return result
