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
from datetime import datetime, timezone, timedelta

# iter61 — one definition of barcode canonicalisation, shared with matcher.py.
# Re-exported here so `crawlers.barcode_keys` keeps working.
from core.utils import _BARCODE_LEAD_RE, barcode_keys, canonical_barcode  # noqa: F401

# iter67 — the append-only daily ledger (Phase 1: written alongside the
# rollups from every persistence path; nothing reads it yet).
import ledger
from fetch_policy import (polite_get, host_saturated, SUPPLEMENT_ABORT_AFTER,  # noqa: F401
                          host_diagnostics)

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


# ── iter74 — proxy health gate + DIRECT fallback ─────────────────────────────
# Client-reported (production, urgent): every Salla store showed CRAWL STATUS
# "Failed — Tier 3 extracted 0 products, all tiers failed", while every Zid
# store showed Success. The failing set was EXACTLY `PROXY_STORES`: the Webshare
# residential subscription answers `402 Payment Required` on all 40 rotation
# usernames, so each tier died inside the proxy connect — never reaching the
# store. A dead proxy subscription must NOT mean "no data": the pod can reach
# these storefronts directly (verified: zarafaksa.com API returns 200), so the
# crawler now probes the proxy once, caches the verdict, and crawls DIRECT when
# the proxy is unusable — recording the fallback so ops can see it happened.
PROXY_PROBE_URL = "https://api.ipify.org?format=json"
PROXY_HEALTH_TTL_SECS = 900          # re-probe at most every 15 minutes
_PROXY_HEALTH = {"ok": None, "checked_at": 0.0, "reason": "", "exit_ip": None}


async def proxy_health(force=False):
    """(ok, reason) for the residential proxy. Cached; never raises."""
    now = time.time()
    if not force and _PROXY_HEALTH["checked_at"] and \
            now - _PROXY_HEALTH["checked_at"] < PROXY_HEALTH_TTL_SECS:
        return _PROXY_HEALTH["ok"], _PROXY_HEALTH["reason"]
    creds = get_proxy_credentials()
    if not creds:
        _PROXY_HEALTH.update(ok=False, checked_at=now, reason="not_configured")
        return False, "not_configured"
    u, p, h, port = creds
    try:
        async with httpx.AsyncClient(proxy=f"http://{u}:{p}@{h}:{port}",
                                     timeout=15.0) as c:
            r = await c.get(PROXY_PROBE_URL)
        ok = r.status_code == 200
        reason = "" if ok else f"http_{r.status_code}"
        _PROXY_HEALTH.update(ok=ok, checked_at=now, reason=reason,
                             exit_ip=(r.text[:60] if ok else None))
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)[:80]}"
        _PROXY_HEALTH.update(ok=False, checked_at=now, reason=reason, exit_ip=None)
        ok = False
    if not ok:
        logger.error("[Proxy] UNUSABLE (%s) — proxied stores will crawl DIRECT. "
                     "Top up / renew the Webshare subscription to restore "
                     "Saudi-exit crawling.", _PROXY_HEALTH["reason"])
    return _PROXY_HEALTH["ok"], _PROXY_HEALTH["reason"]


async def resolve_proxy_for(store, crawl_log=None, tier=""):
    """Proxy creds for this store, or None when it must go DIRECT."""
    if not store.get("use_proxy"):
        return None
    ok, reason = await proxy_health()
    if ok:
        return get_proxy_credentials()
    if isinstance(crawl_log, dict):
        crawl_log["proxy_status"] = f"unusable: {reason}"
        crawl_log.setdefault("proxy_fallback_tiers", []).append(str(tier))
    logger.warning("[Proxy] store=%s tier=%s → DIRECT fallback (%s)",
                   store.get("domain"), tier, reason)
    return None


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
    # iter73h — extended so the read-time normalizer resolves more product
    # names than the tiny original list did. These are the brands that
    # dominate our crawl footprint but were falling into "Unknown".
    "Applaws", "أبلاوز", "Sheba", "شيبا", "Felix", "فيليكس", "Cesar", "سيزار",
    "IAMS", "أيمز", "Eukanuba", "يوكانوبا", "Pro Plan", "برو بلان",
    "Advance", "أدفانس", "Farmina", "فارمينا", "Almo Nature", "المو ناتشر",
    "Bosch", "بوش", "Wellness", "ويلنس", "Taste of the Wild", "طيست اوف ذا ولد",
    "Nutro", "نيوترو", "Solid Gold", "سوليد قولد", "Merrick", "ميريك",
    "Fromm", "فروم", "Canidae", "كانيديا", "Zignature", "زيقنيتشر",
    "Chicken Soup", "شيكن سوب", "Nutrisource", "نيوتري سورس",
    "Whiskas", "Cat Chow", "كات تشاو", "Feliway", "فيلوي",
    "Bio Groom", "بايو قروم", "Furminator", "Sentry", "سنتري",
    "Hartz", "هارتز", "PetSafe", "بيت سيف", "Kaytee", "كايتي",
    "Petromax", "بيتروماكس", "Vitakraft", "فيتاكرافت",
    "Ziwi Peak", "زيوي بيك", "Zoetis", "زوتيس", "AATU", "اتو",
    "Prima Cat", "بريما كات", "Prima Dog", "بريما دوق",
    "Pro-Sense", "برو سنس", "Sanicat", "سانيكات", "Catsan", "كاتسان",
    "Fussie Cat", "فوسي كات", "Nulo", "نولو", "Instinct", "انستنكت",
    "Blue Buffalo", "بلو بافلو", "Wellness Core", "ويلنس كور",
    "Cesar", "Cats Best", "كات بست", "Marshall", "مارشال",
    "Zolux", "زولوكس", "Camon", "كامون", "Ferplast", "فيربلاست",
    "Savic", "سافيك", "Rotweiler", "روت وايلر", "Almo", "ألمو",
    "Josera", "Nature's Miracle", "معجزة الطبيعة",
    # KSA / Regional & Mahally-observed brands
    "Petex", "بتيكس", "Petex Pro", "Katze", "كاتزي",
    "Meow", "ميو", "Bark", "بارك", "PetTime", "بت تايم",
    "Petpourri", "بت بوري", "Mera", "ميرا", "Bewi Dog", "بيوي دوق",
    "MonPetit", "مون بتيت", "GimDog", "جيم دوق", "GimCat",
    "Sanabo", "سنابو", "Reptomin",
]

# iter73h — canonical brand map. Merges Arabic + English variants of the same
# brand into ONE display bucket so a product tagged "رويال كانين" (Ar) and
# another tagged "Royal Canin" (En) don't split the same brand across two
# rows on Top Brands. Keys are lowercase for case-insensitive matching.
CANONICAL_BRAND_MAP = {
    "royal canin": "Royal Canin", "رويال كانين": "Royal Canin",
    "whiskas": "Whiskas", "ويسكاس": "Whiskas",
    "pedigree": "Pedigree", "بيدقري": "Pedigree",
    "purina": "Purina", "بورينا": "Purina",
    "pro plan": "Pro Plan", "برو بلان": "Pro Plan",
    "hills": "Hill's", "هيلز": "Hill's", "hill's": "Hill's",
    "orijen": "Orijen", "اوريجن": "Orijen", "أوريجن": "Orijen",
    "acana": "Acana", "اكانا": "Acana", "أكانا": "Acana",
    "friskies": "Friskies", "فريسكيز": "Friskies",
    "me-o": "Me-O", "meo": "Me-O", "مي-او": "Me-O",
    "kong": "Kong", "كونغ": "Kong",
    "furminator": "FURminator", "فرمينيتور": "FURminator",
    "frontline": "Frontline", "فرونت لاين": "Frontline",
    "versele-laga": "Versele-Laga", "versele laga": "Versele-Laga", "فيرسيل": "Versele-Laga",
    "catit": "Catit", "oxbow": "Oxbow", "tetra": "Tetra",
    "virbac": "Virbac", "ever clean": "Ever Clean", "josera": "Josera",
    "brit": "Brit", "brit care": "Brit", "brit premium": "Brit",
    "schesir": "Schesir", "gimcat": "GimCat", "trixie": "Trixie",
    "beaphar": "Beaphar", "applaws": "Applaws", "أبلاوز": "Applaws",
    "sheba": "Sheba", "شيبا": "Sheba",
    "felix": "Felix", "فيليكس": "Felix",
    "cesar": "Cesar", "سيزار": "Cesar",
    "iams": "IAMS", "أيمز": "IAMS",
    "eukanuba": "Eukanuba", "يوكانوبا": "Eukanuba",
    "advance": "Advance", "أدفانس": "Advance",
    "farmina": "Farmina", "فارمينا": "Farmina", "n&d": "Farmina", "farmina n&d": "Farmina",
    "almo nature": "Almo Nature", "المو ناتشر": "Almo Nature", "almo": "Almo Nature",
    "bosch": "Bosch", "بوش": "Bosch",
    "wellness": "Wellness", "ويلنس": "Wellness", "wellness core": "Wellness",
    "taste of the wild": "Taste of the Wild", "طيست اوف ذا ولد": "Taste of the Wild",
    "nutro": "Nutro", "نيوترو": "Nutro",
    "solid gold": "Solid Gold", "سوليد قولد": "Solid Gold",
    "merrick": "Merrick", "ميريك": "Merrick",
    "fromm": "Fromm", "فروم": "Fromm",
    "canidae": "Canidae", "كانيديا": "Canidae",
    "zignature": "Zignature", "زيقنيتشر": "Zignature",
    "chicken soup": "Chicken Soup", "شيكن سوب": "Chicken Soup",
    "nutrisource": "NutriSource", "نيوتري سورس": "NutriSource",
    "cat chow": "Cat Chow", "كات تشاو": "Cat Chow",
    "feliway": "Feliway", "فيلوي": "Feliway",
    "sentry": "Sentry", "سنتري": "Sentry",
    "hartz": "Hartz", "هارتز": "Hartz",
    "petsafe": "PetSafe", "بيت سيف": "PetSafe",
    "kaytee": "Kaytee", "كايتي": "Kaytee",
    "vitakraft": "Vitakraft", "فيتاكرافت": "Vitakraft",
    "ziwi peak": "Ziwi Peak", "زيوي بيك": "Ziwi Peak",
    "aatu": "AATU", "اتو": "AATU",
    "sanicat": "Sanicat", "سانيكات": "Sanicat",
    "catsan": "Catsan", "كاتسان": "Catsan",
    "fussie cat": "Fussie Cat", "فوسي كات": "Fussie Cat",
    "nulo": "Nulo", "نولو": "Nulo",
    "instinct": "Instinct", "انستنكت": "Instinct",
    "blue buffalo": "Blue Buffalo", "بلو بافلو": "Blue Buffalo",
    "cats best": "Cats Best", "cat's best": "Cats Best", "كات بست": "Cats Best",
    "zolux": "Zolux", "زولوكس": "Zolux",
    "camon": "Camon", "كامون": "Camon",
    "ferplast": "Ferplast", "فيربلاست": "Ferplast",
    "savic": "Savic", "سافيك": "Savic",
    "mera": "Mera", "ميرا": "Mera",
    "bewi dog": "Bewi Dog", "بيوي دوق": "Bewi Dog",
    "gimdog": "GimDog", "جيم دوق": "GimDog",
}


def canonical_brand(raw):
    """iter73h — read-time brand normalisation.

    Turn a raw brand tag (from the ingest-time `extract_brand`, or a store's
    own field) into a display-ready canonical name. Handles Arabic/English
    variants of the same brand, common punctuation drift ("Hill's" vs
    "Hills"), and case. Returns None when the input is genuinely blank —
    callers filter these OUT of Top Brands so the client never sees an
    "Unknown" bucket dominating the ranking.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    if key in CANONICAL_BRAND_MAP:
        return CANONICAL_BRAND_MAP[key]
    # Second try: strip punctuation and re-look-up ("hill's" → "hills")
    stripped = "".join(c for c in key if c.isalnum() or c in " -")
    if stripped in CANONICAL_BRAND_MAP:
        return CANONICAL_BRAND_MAP[stripped]
    # Third: the raw value doesn't match a known canonical form. Return the
    # raw string trimmed so it still shows up as its own bucket rather than
    # falling into "Unknown" — callers apply an explicit `is None` filter,
    # NOT a truthiness test, so real brand strings pass through.
    return raw.strip()


def extract_brand_smart(name_ar, name_en, existing=None):
    """iter73h — smarter than the ingest-time `extract_brand`. Tries in order:

      1. an EXISTING non-empty brand tag on the product (from crawl)
      2. `extract_brand()` on the English name (KNOWN_BRANDS scan)
      3. `extract_brand()` on the Arabic name
      4. the first non-generic leading tokens of the English name — brands
         are typically the first word on the packshot ("Applaws Cat Dry
         Food" → "Applaws").

    Returns the canonical form via `canonical_brand()` or None if nothing
    lands. Never returns "Unknown".
    """
    if existing and str(existing).strip().lower() in CANONICAL_BRAND_MAP:
        c = canonical_brand(existing)
        if c:
            return c
    for nm in (name_en, name_ar):
        if not nm:
            continue
        got = extract_brand(nm)
        if got:
            return canonical_brand(got) or got
    return None  # Descriptive leading words are not verified brands.
    # Fallback: leading English word(s) heuristic. Only fires when the string
    # is Latin (avoiding false positives on Arabic-only names) and the token
    # doesn't sit on the "generic descriptor" blocklist.
    _GENERIC = {"the", "cat", "dog", "pet", "premium", "natural", "organic",
                "adult", "kitten", "puppy", "senior", "royal", "for", "food",
                "dry", "wet", "chicken", "beef", "salmon", "tuna", "lamb",
                "with", "gr", "kg", "grams", "kilogram", "flavor", "flavour",
                "treats", "snack", "biscuit", "biscuits", "and", "canned"}
    if name_en:
        # Take the first 1-2 alphabetic tokens as the candidate brand
        parts = [w for w in name_en.split() if any(c.isalpha() for c in w)]
        if parts and all(ord(c) < 128 for c in parts[0]):
            cand = parts[0].strip(".,-()[]{}").strip()
            if cand.lower() not in _GENERIC and len(cand) >= 2:
                # Prefer a two-token brand ("Blue Buffalo") when the second
                # token is Latin AND not generic
                if len(parts) > 1 and all(ord(c) < 128 for c in parts[1]):
                    two = f"{cand} {parts[1].strip(chr(46) + chr(44)).strip()}"
                    c2 = canonical_brand(two)
                    if c2 and c2 != two.strip():        # matched an alias
                        return c2
                return canonical_brand(cand) or cand
    return None

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


# iter39 — feeding accessories: these force `accessories` even when طعام/food
# appears in the name ("صحن طعام" = food bowl).
_BOWL_KEYWORDS = ["صحن", "صحون", "وعاء", "أوعية", "bowl", "feeder", "مغذية"]


def guess_category(name):
    n = name.lower()
    # iter39 — feeding ACCESSORIES win before food keywords: "صحن طعام" (food
    # bowl) contains طعام and used to classify bowls/feeders as food.
    if any(w in n for w in _BOWL_KEYWORDS):
        return "accessories"
    food_keywords = ["طعام", "غذاء", "food", "دراي", "ويت", "علف", "كيبل", "معلب"]
    # iter39 — treat names ("مكافآت تشورو", "سناك كلاب") often carry NO generic
    # food keyword and fell through to accessories, so they never reached the
    # food subcategorizer. A treat signal IS a food signal.
    if any(w in n for w in food_keywords) or _has_treat_signal(n):
        # iter40 — DOG signals win the parent decision (client rule: an explicit
        # للكلاب / كلاب / dog beats any stray cat token, and عظم chew-bones are
        # dog products). Zolux "عظمة مضغ ... للكلاب" was landing in cat_treats.
        if any(w in n for w in ["كلب", "كلاب", "dog", "عظمة", "عظم", "bone"]):
            return "dog_food"
        if any(w in n for w in ["قط", "كات", "cat"]):
            return "cat_food"
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

# NOTE deliberate omissions: "can" (matches Royal CANin). iter39 — the short/
# collision-prone tokens (ستيك inside هوليستيك "holistic" and بلاستيكي
# "plastic"; تريت inside تريتمنت; treat inside treatment; stick inside sticker)
# are WORD-BOUNDED via regex instead of substring-matched. That trap was the
# confirmed cause of "Solid Gold طعام جاف" landing in dog_treats.
_TREAT_SUBSTRINGS = ["مكافأة", "مكافآت", "مكافات", "تريتس", "سناك",
                     "snack", "biscuit", "بسكويت", "chew", "مضغ", "أعواد",
                     # iter40 — treat forms found missing during validation
                     "جيركي", "jerky", "دنتال", "ليكابل", "lickable"]
_TREAT_WORD_RE = re.compile(r"(?<!\w)(ستيك|تريت|sticks?|treats?)(?!\w)")
_WET_KEYWORDS = ["رطب", "معلب", "ويت فود", "wet", "canned", "pouch", "باوتش",
                 "jelly", "جيلي", "بالجيلي", "gravy", "مرق", "شوربة", "soup",
                 "mousse", "pate", "باتيه"]
_DRY_KEYWORDS = ["جاف", "دراي", "dry", "kibble", "كيبل"]
# iter39 — bundle/box/offer markers: multi-item packs (food + litter + treats
# + toy) were getting filed by their smallest component. Bundles stay generic.
_BUNDLE_MARKERS = ["بكج", "باكج", "باكيج", "bundle", "package", "combo",
                   "كومبو", "عرض", "عروض", "مجموعة", "+"]


def _has_treat_signal(t):
    return any(k in t for k in _TREAT_SUBSTRINGS) or bool(_TREAT_WORD_RE.search(t))


def _is_bundle(t):
    return any(m in t for m in _BUNDLE_MARKERS)


def classify_food_subcategory(parent_category, *texts):
    """Return one of FOOD_SUBCATEGORIES, or None to keep the generic parent.

    Precedence: bundle markers first (multi-item packs stay generic), then
    treats (a chicken-stick "in gravy" is still a treat), then wet vs dry —
    and a product matching BOTH wet and dry keywords is a variety pack we
    refuse to guess on."""
    if parent_category not in FOOD_SUBCATEGORY_PARENTS:
        return None
    t = " ".join(str(x) for x in texts if x).lower()
    if not t:
        return None
    if _is_bundle(t):
        return None
    prefix = "cat" if parent_category == "cat_food" else "dog"
    if _has_treat_signal(t):
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


def classify_food_subcategory_hybrid(parent_category, name, store_tags):
    """iter39 — precedence-safe hybrid: the product NAME's verdict always wins
    (an explicit form keyword in the name can never be overridden by a store
    tag, and a bundle-marked name blocks tag input entirely); store category
    tags are consulted only when the name alone is inconclusive."""
    primary = classify_food_subcategory(parent_category, name)
    if primary is not None or _is_bundle(str(name or "").lower()):
        return primary
    return classify_food_subcategory(parent_category, name, store_tags)


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
    from observation_contract import money
    text = str(text or "").replace("٫", ".").replace("٬", "")
    nums = re.findall(r'[\d]+(?:\.[\d]+)?', text)
    return money(nums[0]) if nums else None


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
    complete = bool(crawl_log.get("complete"))
    succeeded = crawl_log["tier_used"] is not None and not crawl_log.get("error")
    crawl_log["status"] = "complete" if succeeded and complete else "partial" if succeeded else "failed"
    await db.crawl_logs.insert_one(dict(crawl_log))
    await db.stores.update_one({"id": store_id}, {"$set": {
        "last_crawl_attempt_at": crawl_log["completed_at"],
        "last_crawl_tier": crawl_log["tier_used"],
        # iter75 — `tier_used == 0` means the AUTHENTICATED merchant API won
        # (own store, best possible source). `if crawl_log["tier_used"]` treated
        # that 0 as falsy, so "Pets Houses" was reported FAILED on the Stores
        # page after every successful 2233-product sync from api.zid.sa —
        # exactly the failure the client reported. Only None is a failure.
        "last_crawl_status": crawl_log["status"],
        "last_crawl_error": crawl_log["error"],
        "last_crawl_products": crawl_log["products_found"],
        "last_crawl_endpoint": crawl_log.get("endpoint_used"),
    }})
    if succeeded and complete:
        await db.stores.update_one({"id": store_id}, {"$set": {"last_successful_crawl_at": crawl_log["completed_at"], "last_crawled_at": crawl_log["completed_at"]}})


# ── iter73w soft-block guard ────────────────────────────────────────────────
# A "soft block" is a server response that LOOKS like a success (HTTP 200 with
# well-formed JSON) but carries no or drastically fewer products than the store
# has historically returned — the classic Salla/Cloudflare signature is HTTP
# 200 with `data: []`. Writing snapshots from a soft-blocked crawl pollutes
# the DB with a false "we lost the catalog" event that downstream surfaces
# (Stores Carrying, Discounts, Revenue) then treat as ground truth.
#
# Policy: compare the current crawl's product count to the MEDIAN of the last
# SOFT_BLOCK_SAMPLE_SIZE successful crawls in the past SOFT_BLOCK_LOOKBACK_DAYS
# days. If the current count is below SOFT_BLOCK_FLOOR_RATIO of that baseline
# AND the baseline itself is above SOFT_BLOCK_MIN_BASELINE (so we never punish
# a genuinely small catalog), refuse to persist and mark the crawl soft-blocked.
# The previous valid snapshot cohort is preserved untouched (no delete, no
# overwrite) — downstream reads keep serving the last known good state.
SOFT_BLOCK_MIN_BASELINE = 50    # baseline must be ≥ this to trigger the guard
SOFT_BLOCK_FLOOR_RATIO = 0.2    # current must be ≥ 20% of median baseline
SOFT_BLOCK_LOOKBACK_DAYS = 30
SOFT_BLOCK_SAMPLE_SIZE = 10     # median across last N successful crawls
SOFT_BLOCK_MIN_SAMPLES = 3      # < 3 history samples → guard passes through


async def _detect_soft_block(db, store, current_count, crawl_log):
    """Return (is_soft_blocked: bool, reason: str). Always populates
    crawl_log['soft_block'] with structured diagnostics.

    A crawl is flagged soft-blocked when it produced far fewer products than
    the store's own recent successful crawls — the signature of Salla (and
    the fronting CDN/WAF) returning HTTP 200 with an empty or truncated
    payload under rate-limiting. Stores without enough history (< 3 samples)
    OR whose baseline itself is below SOFT_BLOCK_MIN_BASELINE are always
    allowed through — the first crawl of a newly-onboarded store and small
    catalogs must never be punished.

    Fail-open: any detector error records the reason on the crawl_log and
    returns (False, "") — a broken guard must not cost a working store its
    snapshots.
    """
    diag = {"current_count": current_count, "samples": 0,
            "baseline_median": 0, "decision": "unknown"}
    crawl_log["soft_block"] = diag
    try:
        since = datetime.now(timezone.utc) - timedelta(days=SOFT_BLOCK_LOOKBACK_DAYS)
        history = await db.crawl_logs.find(
            {"store_id": store["id"],
             "tier_used": {"$ne": None},
             "products_found": {"$gt": 0},
             "soft_blocked": {"$ne": True},
             "completed_at": {"$gte": since.isoformat()}},
            {"_id": 0, "products_found": 1}
        ).sort("completed_at", -1).limit(SOFT_BLOCK_SAMPLE_SIZE).to_list(SOFT_BLOCK_SAMPLE_SIZE)
        counts = sorted(int(h.get("products_found") or 0) for h in history)
        diag["samples"] = len(counts)
        if len(counts) < SOFT_BLOCK_MIN_SAMPLES:
            diag["decision"] = "insufficient_history"
            return False, ""
        baseline = counts[len(counts) // 2]  # median
        diag["baseline_median"] = baseline
        if baseline < SOFT_BLOCK_MIN_BASELINE:
            diag["decision"] = "baseline_below_min"
            return False, ""
        floor = int(baseline * SOFT_BLOCK_FLOOR_RATIO)
        diag["floor"] = floor
        if current_count < floor:
            reason = (f"soft-block detected: current crawl produced {current_count} "
                      f"products but median of last {len(counts)} crawls is {baseline} "
                      f"(floor {floor} = {int(SOFT_BLOCK_FLOOR_RATIO * 100)}% of median). "
                      f"Refusing to persist — previous snapshots preserved.")
            diag["decision"] = "blocked"
            diag["reason"] = reason
            crawl_log["soft_blocked"] = True
            logger.warning(f"[SoftBlock] {store.get('name')}: {reason}")
            return True, reason
        diag["decision"] = "passed"
        return False, ""
    except Exception as exc:
        logger.warning(f"[SoftBlock] detector error for {store.get('name')}: "
                       f"{type(exc).__name__}: {exc}")
        diag["decision"] = "detector_error"
        diag["error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        return False, ""


def _apply_soft_block(crawl_log, current_count, endpoint_tag, reason):
    """Uniformly tag a soft-blocked crawl_log across tiers. Callers must skip
    both `process_crawled_products` and any barcode supplement — the crawl
    produced no persistable data, so the previous snapshot cohort stands."""
    crawl_log["tier_used"] = None
    crawl_log["http_status"] = 200
    crawl_log["products_found"] = current_count
    crawl_log["endpoint_used"] = f"{endpoint_tag} (soft-blocked)" if endpoint_tag else "soft-blocked"
    crawl_log["error"] = reason
    crawl_log["snapshots_created"] = 0
    crawl_log["soft_blocked"] = True


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
    from observation_contract import money
    # Compatibility arithmetic sentinel only; normalized offers preserve None.
    return money(f) or 0.0


# iter59 — cumulative units-sold counter, all platforms.
#
# Salla publishes it as `sold_quantity` at the product root — the number behind
# the storefront's "تم بيعه أكثر من N مرة" badge. Zid uses `sold_count`. The
# old extractor checked five names, none of them Salla's, so Salla always read
# 0 and those stores were reported "not measurable".
#
# ORDER MATTERS: sold_quantity first, so a payload carrying both (or carrying
# sold_count as a decoy zero) resolves to the Salla value.
SOLD_FIELD_CANDIDATES = ("sold_quantity", "sold_count", "sales_count",
                         "sold_products_count", "total_sold", "orders_count")

# The badge is BUCKETED above a ceiling — "أكثر من 1000" / "sold more than
# 1000 times" / "1000+". A capped value cannot be diffed: it stops moving while
# real sales continue, so a naive diff reports 0 velocity for the store's best
# sellers. Those readings are flagged and excluded from velocity rather than
# silently under-counting.
_SOLD_CAP_RE = re.compile(
    r"(?:\+\s*$)|(?:^\s*\+)|أكثر\s*من|اكثر\s*من|more\s+than|over\s+\d", re.IGNORECASE)


def _extract_sold_count(raw):
    """(units, capped) from any platform's cumulative sold counter.

    `capped` is driven by the RAW TEXT ("1000+", "أكثر من 1000"), not by the
    numeric value: flagging every exact 1000 would discard real data. A value
    genuinely pinned at a ceiling is self-limiting anyway — consecutive reads
    are equal, so the diff contributes 0 rather than a wrong number.
    """
    for key in SOLD_FIELD_CANDIDATES:
        val = raw.get(key)
        if val is None or val == "":
            continue
        s = str(val).strip()
        capped = bool(_SOLD_CAP_RE.search(s))
        digits = re.sub(r"[^\d.]", "", s)
        if not digits:
            continue
        try:
            return max(0, int(float(digits))), capped
        except (ValueError, TypeError):
            continue
    return None, False

# Module-scoped: 8-14 digit numeric-only string ⇒ candidate barcode. Kept at
# module scope so `_collect_variant_field_list` and any future extractor
# helper share the exact same predicate (iter73v).
_EAN_MATCH_RE = re.compile(r"^\d{8,14}$")



def _normalize_raw_product(raw, store_name):
    from observation_contract import normalize_offer
    return normalize_offer(raw, store_name)


def _retired_parent_normalizer(raw, store_name):
    """Normalize a single raw product dict from any source into a standard form."""
    name_ar = raw.get("name", raw.get("title", ""))

    # iter73u (Aug 8 2026) — client-reported: Zarafa's product "Hill's Science
    # Plan Cat Dry Food with Chicken for Kittens / 3KG" (SKU 052742024363 on
    # the storefront) was invisible on the product detail's "Stores Carrying"
    # list, though Hamtaro (raw sku 52742024363 at root) matched fine. Root
    # cause: Salla merchants who put the EAN into `skus[].sku` (variant
    # level) leave the ROOT `sku`/`mpn` fields empty. This extractor read
    # ONLY the root, so every such product got a synthetic `S-<store>-<id>`
    # SKU and their snapshot's `barcode` field stayed empty (variant-level
    # `sku` was never scanned as a barcode source either). With no barcode
    # AND a bogus synthetic SKU, the matcher's Level-1 barcode step had
    # nothing to intersect on and no product_matches row was ever created —
    # `_seller_snapshots` then hid the competitor from the UI.
    #
    # Fix: (1) fall back to `skus[].sku` for the primary SKU field, and
    # (2) treat a numeric `skus[].sku` as a barcode candidate (below).
    variant_sku = ""
    variants_scan = raw.get("skus")
    if isinstance(variants_scan, list):
        for _v in variants_scan:
            if isinstance(_v, dict) and _v.get("sku"):
                variant_sku = str(_v["sku"]).strip()
                if variant_sku:
                    break
    sku_raw = (raw.get("sku") or raw.get("mpn") or variant_sku
               or f"S-{store_name[:2].upper()}-{raw.get('id', uuid.uuid4().hex[:6])}")

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
    # iter59 — the tuple below never contained Salla's actual field name, so
    # every Salla product resolved to 0 and those stores were reported
    # "not measurable". The codebase already knew the right name: it sits first
    # in ZID_SOLD_FIELD_CANDIDATES, but that list was only ever used on the
    # own-store Zid Merchant path, never in this shared competitor extractor.
    sold_count, sold_capped = _extract_sold_count(raw)

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
    #
    # iter73u (Aug 8 2026) — also scan `skus[].sku`: many Salla merchants
    # (Zarafa confirmed 8 Aug) use the variant's SKU field to hold the EAN
    # itself (client stored "052742024363" as SKU). Without this, the
    # snapshot's barcode field stays empty even when a valid GTIN is
    # sitting one field away. `_EAN_RE.match` gates the value so a normal
    # merchant SKU string like "HL-CAT-3KG" is never mistaken for a
    # barcode.
    # `_EAN_RE` gates whether a numeric string can be treated as a barcode
    # (variant `sku` field, root sku, root gtin/mpn/etc.). Kept module-scoped
    # via the alias below so `_collect_variant_field_list` (helper defined
    # further down) can use the same regex.
    _EAN_RE = _EAN_MATCH_RE
    barcode = ""
    from_variant = False
    matched_variant = None       # iter35 — the variant the barcode came from
    variants = raw.get("skus")
    if isinstance(variants, list):
        for v in variants:
            if not isinstance(v, dict):
                continue
            for key in ("barcode", "gtin", "mpn", "sku"):
                cand = str(v.get(key) or "").strip()
                if _EAN_RE.match(cand):
                    barcode = cand
                    from_variant = True
                    matched_variant = v
                    break
            if barcode:
                break
    if not barcode:
        for key in ("gtin", "mpn", "barcode", "ean", "upc", "sku"):
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
        # iter59 — kept SEPARATE from sold_count so a bucketed badge reading is
        # never mistaken for an exact counter downstream.
        "sold_count_cumulative": max(0, sold_count),
        "sold_count_capped": bool(sold_capped),
        "in_stock": bool(in_stock),
        "img_url": img_url,
        "product_url": product_url,
        # iter73v (Aug 8 2026) — variant-aware matching. Collect EVERY
        # variant's SKU + barcode into two arrays. Matcher's Level-1
        # barcode step and `_seller_snapshots`' direct-key fallback query
        # against these arrays so a product with 3 variants each carrying
        # a distinct barcode is matched on ANY of them — not just the one
        # we happened to pick as primary. Empty strings dropped; identity
        # de-duped; primary sku/barcode always included so downstream
        # code that reads only `variant_barcodes` still sees the primary.
        "variant_skus": _collect_variant_field_list(raw, ("sku",), fallback=sku_raw),
        "variant_barcodes": _collect_variant_field_list(
            raw, ("barcode", "gtin", "mpn", "sku", "ean", "upc"),
            fallback=barcode, numeric_only=True),
    }


def _collect_variant_field_list(raw, keys, *, fallback="", numeric_only=False):
    """Collect every value on `raw.skus[].{keys}` and `raw.{keys}` roots.

    iter73v — used to build the parent snapshot's `variant_skus` and
    `variant_barcodes` arrays. The parent primary (the string that lives
    in `snap.sku` / `snap.barcode`) is always prepended so the array is
    strictly a superset. When `numeric_only=True`, values are filtered
    to the EAN-shaped regex — so `variant_barcodes` never accepts a
    "HL-CAT-3KG"-style SKU string, but `variant_skus` accepts anything.
    """
    seen = []
    dedupe = set()

    def _accept(val):
        s = str(val or "").strip()
        if not s or s in dedupe:
            return
        if numeric_only and not _EAN_MATCH_RE.match(s):
            return
        seen.append(s)
        dedupe.add(s)

    if fallback:
        _accept(fallback)
    variants = raw.get("skus")
    if isinstance(variants, list):
        for v in variants:
            if not isinstance(v, dict):
                continue
            for k in keys:
                _accept(v.get(k))
    for k in keys:
        _accept(raw.get(k))
    return seen


async def process_crawled_products(db, store, all_raw, now, tier=1, confidence=95):
    """Process raw product data from any crawler tier into products + snapshots."""
    new_count = 0
    snap_count = 0
    store_domain = store.get("domain", "")
    ledger_obs = []            # iter67 — one ledger observation per normalized item
    from observation_contract import expand_variants, stable_id
    expanded = [offer for listing in all_raw for offer in expand_variants({
        **listing, "_currency": store.get("currency", "SAR") if store.get("platform") in ("salla", "zid") else store.get("currency"),
        "_price_basis": "storefront_inc_vat" if tier in (1, 2, 3, 4) else listing.get("price_basis"),
    })]
    seen_offers = set()
    for raw in expanded:
        # Once a listing is known to be a parent, later incomplete responses
        # cannot revive its generic price/quantity as a specific child offer.
        if raw.get("_variant_id") == "root":
            listing_id = raw.get("_listing_id")
            known_child = await db.products.find_one({"store_id": store["id"], "listing_id": listing_id,
                "variant_id": {"$nin": [None, "root"]}}, {"_id": 0, "offer_id": 1})
            known_parent = await db.observation_quarantine.find_one({"store_id": store["id"], "listing_id": listing_id,
                "quarantine_reasons": "unresolved_parent_variants"}, {"_id": 0, "listing_id": 1})
            if known_child or known_parent:
                raw = {**raw, "_unresolved_parent": True}
        norm = _normalize_raw_product(raw, store["name"])
        offer_id = stable_id(store["id"], norm["listing_id"], norm["variant_id"])
        if offer_id in seen_offers:
            continue
        seen_offers.add(offer_id)
        norm["offer_id"] = offer_id
        if not norm["comparable"]:
            await db.observation_quarantine.update_one(
                {"event_id": stable_id(offer_id, now.isoformat())},
                {"$setOnInsert": {**norm, "store_id": store["id"], "observed_at": now,
                                   "ingested_at": datetime.now(timezone.utc)}}, upsert=True)
            marker = {**norm, "store_id": store["id"], "store_name": store["name"],
                      "event_id": stable_id(offer_id, now.isoformat()), "crawled_at": now,
                      "qty_available": norm.get("qty"), "confidence_score": confidence,
                      "quarantined": True, "source_tier": tier}
            inserted = await db.product_snapshots.update_one({"event_id": marker["event_id"]}, {"$setOnInsert": marker}, upsert=True)
            from evidence_ledger import record
            persisted = marker if inserted.upserted_id else await db.product_snapshots.find_one({'event_id': marker['event_id']}, {'_id': 0})
            await record(db, persisted)
            continue
        product_url = _absolutize_url(norm.get("product_url"), store_domain)

        existing = await db.products.find_one({"offer_id": offer_id}, {"_id": 0})
        # iter36 — hybrid classifier input: product name + the store's own
        # category tag names (when the raw payload carries them).
        store_cats = extract_store_category_names(raw)
        if not existing:
            pid = str(uuid.uuid4())
            category = guess_category(norm["name_ar"])
            await db.products.insert_one({
                "id": pid, "sku": norm["sku"], "offer_id": offer_id,
                "store_id": store["id"], "listing_id": norm["listing_id"], "variant_id": norm["variant_id"],
                "metadata_source": "store_observation",
                # iter61 — _normalize_raw_product has extracted this since
                # iter35 (variant-aware, from skus[].barcode/gtin/mpn) and both
                # write sites dropped it. The matcher's Level-1 barcode step
                # therefore had NO competitor barcode to compare against and
                # could only fire when a store happened to type a bare EAN into
                # its SKU field. Persisting it is what makes Level 1 real.
                "barcode": norm.get("barcode") or "",
                "name_ar": norm["name_ar"], "name_en": norm["name_ar"],
                "brand": extract_brand(norm["name_ar"]),
                "category": category,
                # additive: parent category stays; None = confidently generic
                "subcategory": classify_food_subcategory_hybrid(category, norm["name_ar"], store_cats),
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
            # iter61 — backfill the barcode onto rows written before it was
            # persisted, so existing products gain it on the next crawl rather
            # than only newly-discovered ones. Never overwrites a value we
            # already hold.
            if norm.get("barcode") and not existing.get("barcode"):
                patch["barcode"] = norm["barcode"]
            if norm["img_url"] and not existing.get("image_url"):
                patch["image_url"] = norm["img_url"]
            if product_url and not existing.get("product_url"):
                patch["product_url"] = product_url
            if "subcategory" not in existing:
                # iter36 — one-shot enrichment of pre-existing products (the
                # startup backfill covers products no crawl revisits).
                patch["subcategory"] = classify_food_subcategory_hybrid(
                    existing.get("category"),
                    " ".join(str(x) for x in (existing.get("name_ar"), existing.get("name_en")) if x),
                    store_cats)
            if patch:
                await db.products.update_one({"id": pid}, {"$set": patch})

        disc_pct = round((1 - norm["price"] / norm["original_price"]) * 100) if norm["original_price"] > norm["price"] > 0 else 0
        snapshot = {
            "id": str(uuid.uuid4()),
            "product_id": pid,
            "store_id": store["id"],
            "store_name": store["name"],
            "sku": norm["sku"],
            **{k: norm.get(k) for k in ("offer_id", "listing_id", "variant_id", "attributes", "name_ar", "name_en", "brand", "brand_source", "currency", "price_basis", "price_kind", "price_decimal", "observation_version", "is_synthetic", "data_origin", "comparable", "sold_count_observed", "quantity_observed", "present_on_store")},
            "event_id": stable_id(offer_id, now.isoformat()),
            "observed_at": now, "ingested_at": datetime.now(timezone.utc),
            # iter61 — snapshots carry it too. db.products is ONE row per SKU
            # shared across every store (first writer wins), so the per-store
            # observation of a barcode is only recoverable from the snapshot.
            "barcode": norm.get("barcode") or "",
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
            # iter59 — Salla's cumulative badge counter, persisted so velocity
            # can be diffed between crawls. Was parsed and discarded before.
            "sold_count_cumulative": norm.get("sold_count_cumulative"),
            "sold_count_capped": norm.get("sold_count_capped", False),
            "product_url": product_url,
            # iter73v (Aug 8 2026) — variant arrays persisted so the matcher's
            # Level-1 barcode step + `_seller_snapshots` direct-key fallback
            # can join on ANY variant key. Always non-empty (contains the
            # primary sku/barcode) so downstream code that reads either
            # array does not need a None guard.
            "variant_skus": norm.get("variant_skus", [norm["sku"]]),
            "variant_barcodes": norm.get("variant_barcodes",
                                         [norm.get("barcode")] if norm.get("barcode") else []),
            "source_tier": tier,
            "confidence_score": confidence,
            "crawled_at": now,
        }
        result = await db.product_snapshots.update_one({"event_id": snapshot["event_id"]}, {"$setOnInsert": snapshot}, upsert=True)
        from evidence_ledger import record
        persisted = snapshot if result.upserted_id else await db.product_snapshots.find_one({'event_id': snapshot['event_id']}, {'_id': 0})
        await record(db, persisted)
        # Replay the persisted evidence, not a retry's potentially changed payload.
        # Daily ledger writes are idempotent; retry must repair a prior interrupted write.
        ledger_obs.append(ledger.crawl_observation({**persisted, "qty": persisted.get("qty_available")}))
        snap_count += 1

    # Snapshots remain durable if the ledger fails. Surface failure so the checkpoint
    # stays replayable rather than declaring incomplete work successful.
    await ledger.record_observations(
        db, store["id"], store["name"], ledger_obs, now,
        source_tier=tier, confidence=confidence)

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
        # iter75 — paced + backed-off + UA-rotated (see fetch_policy). Without
        # a residential proxy a single IP gets rate-limited fast; a bare
        # client.get() here is what turned Salla 429s into "tier failed".
        resp = await polite_get(http, ep["url"], params=ep.get("params"))
        if resp is None:
            attempt["status"] = 0
            attempt["error"] = "No response after retries"
            crawl_log["endpoints_tried"].append(attempt)
            return [], None
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
        if isinstance(items, list) and len(items) >= 1:
            ep["_initial_body"] = body
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
    from catalog_pagination import paginate
    return await paginate(http, ep, initial_items, polite_get)


async def _retired_paginate_endpoint(http, ep, initial_items):
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
                r = await polite_get(http, fetch_url)
                if r is None or r.status_code != 200:
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
                r = await polite_get(http, ep["url"], params=params)
                if r is None or r.status_code != 200:
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
    creds = await resolve_proxy_for(store, crawl_log, "1")
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
        crawl_log.update(winning_endpoint.get("_pagination") or {})
        # Retain collected pages before any slow optional barcode enrichment.
        for offset in range(0, len(all_raw), 50):
            await db.crawl_checkpoints.update_one({"_id": f"{crawl_log['id']}:{offset}"}, {"$setOnInsert": {"store_id": store["id"], "observed_at": now, "rows": all_raw[offset:offset+50], "pagination": winning_endpoint.get("_pagination")}}, upsert=True)
        # iter73w — soft-block guard. If this crawl produced far fewer products
        # than the store's recent baseline (typical Salla HTTP 200 + data:[]
        # false success under Cloudflare/WAF rate-limits), refuse to persist:
        # the previous snapshot cohort is preserved untouched. The supplement
        # is also skipped since there are effectively no items to enrich.
        soft_blocked, sb_reason = await _detect_soft_block(db, store, len(all_raw), crawl_log)
        if soft_blocked:
            _apply_soft_block(crawl_log, len(all_raw), winning_endpoint["tag"], sb_reason)
        else:
            crawl_log["tier_used"] = 1
            crawl_log["http_status"] = 200
            crawl_log["endpoint_used"] = winning_endpoint["tag"]
            crawl_log["products_found"] = len(all_raw)
            await db.stores.update_one({"id": store["id"]}, {"$set": {"working_endpoint": winning_endpoint["tag"]}})
            from crawl_persistence import persist
            new_count, snap_count = await persist(db, store, all_raw, now, crawl_log)
            crawl_log["products_new"] = new_count
            crawl_log["products_updated"] = len(all_raw) - new_count
            crawl_log["snapshots_created"] = snap_count
    else:
        last_attempt = crawl_log["endpoints_tried"][-1] if crawl_log["endpoints_tried"] else {}
        crawl_log["http_status"] = last_attempt.get("status", 0)
        crawl_log["error"] = f"Tier 1 exhausted — all {len(endpoints)} endpoints failed. Escalating to Tier 2. Last: {last_attempt.get('error', 'unknown')}"
        crawl_log["endpoint_used"] = "none — tier 2 stub"
        # iter64 — every Salla crawl log carries a supplement entry, failures too
        await _maybe_salla_detail_supplement(db, store, all_raw, crawl_log)

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
            creds = await resolve_proxy_for(store, crawl_log, "2")
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
        # iter73w — soft-block guard applies at every tier; Salla soft-blocks
        # can appear as truncated XHR payloads too.
        soft_blocked, sb_reason = await _detect_soft_block(db, store, len(captured_products), crawl_log)
        if soft_blocked:
            _apply_soft_block(crawl_log, len(captured_products), winning_pattern or "xhr", sb_reason)
        else:
            crawl_log["tier_used"] = 2
            crawl_log["http_status"] = 200
            crawl_log["products_found"] = len(captured_products)
            # iter64 — supplement before persistence (mutates the raw items). This
            # is the tier that succeeded on Zarafa 2026-07-31 19:09 with 3000
            # products while the supplement's only host path (Tier 2.5) sat blocked.
            from crawl_persistence import persist
            new_c, snap_c = await persist(db, store, captured_products, now, crawl_log, tier=2, confidence=88)
            crawl_log["products_new"] = new_c
            crawl_log["products_updated"] = len(captured_products) - new_c
            crawl_log["snapshots_created"] = snap_c
            if winning_pattern:
                await db.stores.update_one({"id": store["id"]}, {"$set": {"working_xhr_pattern": winning_pattern}})
    else:
        count = len(captured_products) if captured_products else 0
        if not crawl_log["error"]:
            crawl_log["error"] = f"Tier 2 insufficient — captured {count} products (need 5+). Escalating to Tier 3"
        await _maybe_salla_detail_supplement(db, store, captured_products, crawl_log)

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
            creds = await resolve_proxy_for(store, crawl_log, "3")
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
        # iter73w — soft-block guard applies at every tier.
        soft_blocked, sb_reason = await _detect_soft_block(db, store, len(products_extracted), crawl_log)
        if soft_blocked:
            _apply_soft_block(crawl_log, len(products_extracted), "html", sb_reason)
        else:
            crawl_log["tier_used"] = 3
            crawl_log["http_status"] = 200
            crawl_log["products_found"] = len(products_extracted)
            # iter64 — supplement before persistence. HTML-extracted items usually
            # carry no Salla numeric id, in which case the wrapper's missing filter
            # finds nothing fetchable and writes a "skipped" entry instead.
            from crawl_persistence import persist
            new_c, snap_c = await persist(db, store, products_extracted, now, crawl_log, tier=3, confidence=75)
            crawl_log["products_new"] = new_c
            crawl_log["products_updated"] = len(products_extracted) - new_c
            crawl_log["snapshots_created"] = snap_c
    else:
        if not crawl_log["error"]:
            crawl_log["error"] = f"Tier 3 extracted {len(products_extracted)} products — all tiers exhausted"
        await _maybe_salla_detail_supplement(db, store, products_extracted, crawl_log)

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
        # iter73 (Feb 2026) — Zarafa (and other newer Salla themes) link
        # categories as `/{locale}/{slug-or-dash}/c{id}` (e.g. `/ar/-/c622249111`)
        # instead of the legacy `/categories/{id}` shape. The old query missed
        # every category on Zarafa's homepage (0 discovered → 0 products
        # captured → whole store went dark), which is why SKU 5060122491365
        # (Applaws Chicken 400 g) and the rest of Zarafa's catalog were absent
        # from Price Intel. Match BOTH shapes so any theme works.
        ids = await page.evaluate("""
            () => {
              const out = new Set();
              document.querySelectorAll('a[href]').forEach(a => {
                const h = a.href || a.getAttribute('href') || '';
                let m = h.match(/categories\\/(\\d+)/);
                if (m) out.add(m[1]);
                m = h.match(/\\/c(\\d{6,})(?:$|[\\/?#])/);
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


# ── iter63: Salla detail supplement — recover barcodes the LISTING omits ─────
# Live evidence (Zarafa, Hills GI Biome p1694697895): the Tier 2.5 listing
# payload (api.salla.dev/store/v1/products?source=categories) carries NO
# per-variant skus[] barcodes — the static page's JSON-LD "sku" is a different
# number entirely, and the real barcode (052742059518) only arrives client-side
# from the product-DETAIL XHR. So for these stores iter61's barcode persistence
# has nothing to persist, and the matcher's Level 1 stays blind.
#
# The supplement re-fetches ONLY products whose listing yielded no barcode,
# using the SAME captured store-identifier header and the same httpx client
# the category walk just used.
#
# iter73v (Aug 8 2026) — client mandate: "high-catalog stores like Zarafa
# must be crawled completely, including all products and all variants".
# The 300-product per-crawl cap that used to trickle-fill coverage over
# ~14 crawls has been REMOVED. Every remaining product now gets a detail
# supplement pass in the same crawl. Rate-limit backoff and existing
# retry logic keep the outbound traffic Cloudflare-friendly. Set to a
# very large sentinel rather than None so `min(cap, missing_total)` still
# works and diagnostics remain readable.
SALLA_DETAIL_SUPPLEMENT_CAP = 100000


def _salla_raw_barcode(raw):
    """The barcode the normalizer would extract from this raw payload, or "".

    Mirrors _normalize_raw_product's candidate scan exactly (variants first,
    iter35 key order, then root) so "missing" here means "iter61 will persist
    nothing for this product".

    iter73u (Aug 8 2026) — extended to also scan `sku` in both scopes,
    matching the normalizer's new fallback so the supplement's skip logic
    doesn't re-fetch products we already have a barcode for.
    """
    variants = raw.get("skus")
    if isinstance(variants, list):
        for v in variants:
            if not isinstance(v, dict):
                continue
            for key in ("barcode", "gtin", "mpn", "sku"):
                cand = str(v.get(key) or "").strip()
                if _NUMERIC_BARCODE_RE.match(cand):
                    return cand
    for key in ("gtin", "mpn", "barcode", "ean", "upc", "sku"):
        cand = str(raw.get(key) or "").strip()
        if _NUMERIC_BARCODE_RE.match(cand):
            return cand
    return ""


def _select_salla_variant_barcode(detail, listed_price=0.0):
    """Barcode of the variant that matches the LISTED product, or "".

    Selection order (the listing's price is what Daleel displays, so the
    barcode must describe that same item — attaching another variant's GTIN to
    this price is exactly the pack-size collision iter51-53 guard against):
      1. the variant whose price equals the listed price
      2. else the first in-stock variant
      3. else the first variant
    Only the CHOSEN variant's identifiers are read; if it carries none, fall
    back to the detail payload's root fields, else give up ("").

    A candidate counts only if canonical_barcode() accepts it. Returned as the
    raw digits when the whole string is already an EAN, else as the canonical
    GTIN-14 form (a suffixed variant value like "9003579308936carton" persists
    as its digits-only canonical form, since the normalizer's root scan
    requires a full-digit match).
    """
    def _usable(cand):
        cand = str(cand or "").strip()
        if not cand:
            return ""
        canon = canonical_barcode(cand)
        if not canon:
            return ""
        return cand if _NUMERIC_BARCODE_RE.match(cand) else canon

    variants = [v for v in (detail.get("skus") or []) if isinstance(v, dict)] \
        if isinstance(detail, dict) else []
    chosen = None
    if variants:
        if listed_price and listed_price > 0:
            chosen = next((v for v in variants
                           if abs(_price_amount(v.get("price")) - listed_price) < 0.01), None)
        if chosen is None:
            chosen = next((v for v in variants
                           if (v.get("stock_quantity") or 0) > 0), None)
        if chosen is None:
            chosen = variants[0]
        for key in ("barcode", "gtin", "mpn"):
            got = _usable(chosen.get(key))
            if got:
                return got
    if isinstance(detail, dict):
        for key in ("gtin", "mpn", "barcode", "ean", "upc"):
            got = _usable(detail.get(key))
            if got:
                return got
    return ""


def _salla_missing_barcode_items(items):
    """The items the supplement would fetch — one definition, used by both the
    skip decision and the fetch loop so the two can never disagree."""
    return [it for it in items
            if isinstance(it, dict) and it.get("id") is not None
            and not _salla_raw_barcode(it)]


# ── iter65: strict GTIN validation for weak-signal sources ───────────────────
# Production 31 Jul: the details route's root `sku` is often a merchant-internal
# numeric code ("5274204208") that HAPPENS to pass the 8-14 digit gate — and by
# luck can even pass the mod-10 check digit. What it cannot fake is GTIN
# LENGTH: real trade-item numbers are GTIN-8/12/13/14 exactly. Sources that are
# not barcode fields by declaration (root sku, DOM text) must pass BOTH tests;
# declared barcode/gtin fields keep the shipped canonical-only gate.
_GTIN_LENGTHS = {8, 12, 13, 14}


def _is_strict_gtin(val):
    """Digits only, a real GTIN length, and a valid mod-10 check digit."""
    s = str(val or "").strip()
    if not s.isdigit() or len(s) not in _GTIN_LENGTHS:
        return False
    total = sum(int(c) * (3 if i % 2 == 0 else 1)
                for i, c in enumerate(reversed(s[:-1])))
    return (10 - total % 10) % 10 == int(s[-1])


def _stage1_extract_barcode(detail, listed_price=0.0):
    """Barcode from a /details response, or "".

    Order: the iter63 variant/root scan first (skus[] when present, then the
    declared root gtin/mpn/barcode/ean/upc fields, canonical-gated) — then, new
    in iter65, the root `sku` under STRICT GTIN validation only. The details
    route's root sku is usually an internal code ("5274204208", length 10) and
    must never be promoted to a barcode on the digit-run gate alone.
    """
    got = _select_salla_variant_barcode(detail, listed_price=listed_price)
    if got:
        return got
    if isinstance(detail, dict):
        sku = str(detail.get("sku") or "").strip()
        if _is_strict_gtin(sku):
            return sku
    return ""


async def _salla_detail_barcode_supplement(client, captured, store_domain=None,
                                           store_identifier=None,
                                           cap=SALLA_DETAIL_SUPPLEMENT_CAP):
    """Stage 1 — cheap HTTP fill from the product-DETAILS route.

    iter65 — the iter63/64 route GET api.salla.dev/store/v1/products/{id} is
    RETIRED: production 31 Jul returned 410 for all 299 attempts
    (failed_410=299). The working route, found by direct testing, is

        GET https://{store_domain}/en/api/v1/products/{id}/details      (no
            store-identifier needed)

    with GET https://api.salla.dev/store/v1/products/{id}/details (identifier
    required) as the fallback when the store domain answers 4xx/5xx.

    Mutates the raw listing items in place: a recovered barcode is injected as
    the item's root `gtin`, which _normalize_raw_product's root scan picks up —
    persistence flows through the exact iter61 path and the listing's price
    fields stay untouched. Fail-soft per product, sequential on the same
    client. The combined ran/skipped observability entry is written by
    _maybe_salla_detail_supplement, which also runs stage 2 on what this stage
    could not fill.

    Returns (filled, missing_total, failed, bytes_consumed, failed_by_status);
    failures are bucketed by the LAST status observed for the product.
    """
    missing = _salla_missing_barcode_items(captured)
    todo = missing[:cap]
    filled = failed = 0
    bytes_consumed = 0
    failed_by_status = {}
    # iter75 — circuit breaker. Some stores answer 404 for EVERY product on this
    # route (Caty) and others 429 the whole pass (CutePets: 277 throttles in one
    # crawl). Firing one request per product regardless burned 20+ minutes and
    # recovered nothing, so a run of consecutive failures now stops the stage
    # and records why instead of grinding to the end of the catalogue.
    consecutive_failures = 0
    for it in todo:
        pid = it.get("id")
        urls = []
        if store_domain:
            urls.append(f"https://{store_domain}/en/api/v1/products/{pid}/details")
        if store_identifier or not store_domain:
            urls.append(f"https://api.salla.dev/store/v1/products/{pid}/details")
        last_status = None
        detail = None
        saturated_host = None
        for url in urls:
            try:
                # attempts=2: a per-product 429 means the whole route is
                # throttled, not that this product needs another go.
                r = await polite_get(client, url, attempts=2)
                if r is None:
                    last_status = "exception"
                    continue
                bytes_consumed += len(r.content or b"")
                last_status = r.status_code
                if r.status_code == 200:
                    body = r.json()
                    detail = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else body
                    break
                if host_saturated(url):
                    saturated_host = url
                logger.info(f"[DetailSupplement] product={pid} http_status={r.status_code} url={url}")
            except Exception as e:
                last_status = "exception"
                logger.info(f"[DetailSupplement] product={pid} failed: {str(e)[:80]}")
        if detail is None:
            failed += 1
            key = last_status if last_status is not None else "exception"
            failed_by_status[key] = failed_by_status.get(key, 0) + 1
            consecutive_failures += 1
            if saturated_host:
                failed_by_status["aborted_host_saturated"] = consecutive_failures
                logger.warning(
                    "[DetailSupplement] %s: aborting stage 1 — host is rate-limiting "
                    "us to the maximum backoff (%s). Kept the barcodes we already "
                    "have instead of burning the crawl window.",
                    store_domain, saturated_host)
                break
            if consecutive_failures >= SUPPLEMENT_ABORT_AFTER:
                failed_by_status["aborted_after_consecutive"] = consecutive_failures
                logger.warning(
                    "[DetailSupplement] %s: aborting stage 1 after %d consecutive "
                    "failures (last status %s) — this route is not serving this store",
                    store_domain, consecutive_failures, key)
                break
            continue
        consecutive_failures = 0
        barcode = _stage1_extract_barcode(detail, listed_price=_price_amount(it.get("price")))
        if barcode:
            it["gtin"] = barcode
            filled += 1
    return filled, len(missing), failed, bytes_consumed, failed_by_status


# ── iter65 stage 2: the barcode that exists ONLY in the rendered DOM ─────────
# Zarafa 31 Jul, confirmed in-browser: the real variant barcode (052742059518)
# is displayed as text under the variant picker next to a barcode icon — an
# in-page find locates it, while a DevTools network search across ALL variant
# XHRs finds nothing, and plain curl of the HTML lacks it (JS-rendered). For
# these products no API response carries the value; reading the rendered page
# is the only remaining source.
SALLA_DOM_BARCODE_CAP = 100000       # iter73v — cap removed; DOM pass now covers every product still missing after the API-detail stage. Playwright throughput self-limits via existing per-page timeouts.

# digit runs with hard boundaries — "12345678901" inside a longer number is not
# a candidate
_DOM_DIGIT_RUN_RE = re.compile(r"(?<!\d)(\d{8,14})(?!\d)")

# JS evaluated in the product page: texts of elements that look barcode-related
# (class/id mentioning barcode, or the visible words), texts of the
# variant/options component, and the full visible body text as last resort.
_DOM_BARCODE_JS = """
() => {
  const texts = (sel) => Array.from(document.querySelectorAll(sel))
      .map(el => el.innerText || el.textContent || "").filter(Boolean);
  const labelled = texts('[class*="barcode" i], [id*="barcode" i]');
  for (const el of document.querySelectorAll('span, div, p, li, small, bdi')) {
    const t = (el.innerText || "");
    if (t.length < 120 && (/barcode/i.test(t) || t.includes("\u0628\u0627\u0631\u0643\u0648\u062f"))) {
      labelled.push(t);
      if (el.parentElement) labelled.push(el.parentElement.innerText || "");
    }
  }
  const options = texts('[class*="option" i], [class*="variant" i], salla-product-options');
  return { preferred: labelled.concat(options).slice(0, 60),
           body: (document.body ? document.body.innerText : "").slice(0, 20000) };
}
"""


def _pick_dom_barcode(preferred_texts, body_text):
    """Choose one barcode from rendered-page text, or "".

    Preference order:
      1. a strict GTIN inside a barcode-labelled / variant-picker element —
         first hit wins (that is the value the merchant is displaying AS the
         barcode of the selected variant);
      2. else the body-wide digit runs, but only when EXACTLY ONE distinct
         strict GTIN appears — a page with several candidates and no label to
         disambiguate is skipped rather than guessed at. Page text is full of
         8-14 digit runs that are not barcodes (a 12-digit Saudi phone number
         passes the length gate), which is why every DOM candidate must pass
         _is_strict_gtin, not just the canonical gate.
    """
    for t in preferred_texts or []:
        for run in _DOM_DIGIT_RUN_RE.findall(str(t)):
            if _is_strict_gtin(run):
                return run
    body_hits = {run for run in _DOM_DIGIT_RUN_RE.findall(str(body_text or ""))
                 if _is_strict_gtin(run)}
    if len(body_hits) == 1:
        return next(iter(body_hits))
    return ""


def _salla_item_page_url(it, store_domain):
    """The customer-facing product page URL for a raw listing item, or ""."""
    url = ""
    urls = it.get("urls")
    if isinstance(urls, dict):
        url = str(urls.get("customer") or "").strip()
    if not url:
        url = str(it.get("url") or "").strip()
    return _absolutize_url(url, store_domain) if url else ""


async def _salla_dom_barcode_supplement(store, items, cap=SALLA_DOM_BARCODE_CAP,
                                        dom_reader=None):
    """Stage 2 — read the barcode out of the rendered product page.

    `items` are the products still missing after stage 1. One browser context,
    sequential navigation, the same render wait the category-discovery pass
    uses. Fail-soft per product; a page that yields no unambiguous strict GTIN
    counts as failed, never guessed.

    dom_reader: injectable async (page, url) -> (preferred_texts, body_text).
    Tests supply one and no browser is launched; production leaves it None.

    Returns (filled, attempted, failed).
    """
    todo = items[:cap]
    if not todo:
        return 0, 0, 0
    filled = failed = 0
    dom_consecutive_failures = [0]      # list so the inner closure can mutate it

    async def _fill(read, page):
        nonlocal filled, failed
        for it in todo:
            url = _salla_item_page_url(it, store.get("domain"))
            if not url:
                failed += 1
                dom_consecutive_failures[0] += 1
                if dom_consecutive_failures[0] >= SUPPLEMENT_ABORT_AFTER:
                    logger.warning(
                        "[DomBarcode] %s: aborting DOM pass — %d consecutive "
                        "items carry no product URL",
                        store.get("domain"), dom_consecutive_failures[0])
                    return
                continue
            try:
                preferred, body = await read(page, url)
                barcode = _pick_dom_barcode(preferred, body)
                if barcode:
                    it["gtin"] = barcode
                    filled += 1
                    dom_consecutive_failures[0] = 0
                else:
                    failed += 1
                    dom_consecutive_failures[0] += 1
            except Exception as e:
                failed += 1
                dom_consecutive_failures[0] += 1
                logger.info(f"[DomBarcode] product={it.get('id')} failed: {str(e)[:80]}")
            # iter75 — same circuit breaker as stage 1: a long run of misses
            # means the page shape changed or the store is refusing us, and
            # every extra Playwright navigation costs ~3s for nothing.
            if dom_consecutive_failures[0] >= SUPPLEMENT_ABORT_AFTER:
                logger.warning(
                    "[DomBarcode] %s: aborting DOM pass after %d consecutive misses",
                    store.get("domain"), dom_consecutive_failures[0])
                return

    if dom_reader is not None:
        await _fill(dom_reader, None)
        return filled, len(todo), failed

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            creds = await resolve_proxy_for(store, None, "dom_barcode")
            if creds:
                user, pwd, host, port = creds
                launch_kwargs["proxy"] = playwright_proxy_config(user, pwd, host, port)
            browser = await pw.chromium.launch(**launch_kwargs)
            try:
                ctx = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="ar-SA",
                )
                page = await ctx.new_page()

                async def _read(pg, url):
                    await page.goto(url, wait_until="domcontentloaded", timeout=18000)
                    await page.wait_for_timeout(1500)   # same render wait as category discovery
                    got = await page.evaluate(_DOM_BARCODE_JS)
                    return (got or {}).get("preferred") or [], (got or {}).get("body") or ""

                await _fill(_read, page)
            finally:
                await browser.close()
    except Exception as e:
        # browser-level failure: everything unprocessed is failed, never fatal
        logger.info(f"[DomBarcode] browser unavailable for {store.get('domain')}: {str(e)[:80]}")
        failed = len(todo) - filled
    return filled, len(todo), failed


# iter64 — a crawl that produced fewer products than this is degraded/blocked
# (Zarafa production 2026-07-31: Tier 2.5 captured 0 after Salla started
# defending). Piling detail requests onto a store that is already pushing back
# is how a soft block becomes a hard one, so the supplement stands down.
SALLA_DETAIL_MIN_PRODUCTS = 50


async def _maybe_salla_detail_supplement(db, store, raw_items, crawl_log,
                                         store_identifier=None, client=None):
    """iter64/65 — run the barcode supplement after ANY Salla crawl, any tier.

    Two stages (iter65): a cheap HTTP pass against the working /details route,
    then a bounded Playwright DOM read for the products whose barcode exists
    only in the rendered page (Zarafa evidence 31 Jul: no API response carries
    it). The iter64 framework is unchanged — any-tier wiring, caps, politeness
    guard, and EXACTLY ONE `detail_barcode_supplement` entry per Salla crawl:

        status "ran"      counts: missing/attempted/filled with the split
                          filled_details/filled_dom, failed(+failed_<status>
                          buckets for stage 1), dom_attempted, dom_failed
        status "skipped"  reason: no_products | degraded_crawl |
                          no_missing_barcodes | exception:<msg>

    Must be called BEFORE process_crawled_products — both stages mutate the raw
    items, so they have to run before persistence.

    store-identifier is now OPTIONAL (iter65): the primary /details route runs
    against the store domain with no identifier, so nothing is skipped for the
    lack of one. The identifier (caller's captured value, else the one cached
    on the store doc) only unlocks the api.salla.dev fallback host.
    """
    if (store.get("platform") or "").lower() != "salla":
        return

    def _skip(reason):
        crawl_log["endpoints_tried"].append({
            "endpoint": "detail_barcode_supplement", "status": "skipped",
            "products": 0, "error": reason,
        })
        logger.info(f"[DetailSupplement] {store.get('name')}: skipped ({reason})")

    try:
        items = [it for it in (raw_items or []) if isinstance(it, dict)]
        if not items:
            return _skip("no_products")
        if len(items) < SALLA_DETAIL_MIN_PRODUCTS:
            return _skip("degraded_crawl")
        missing_total = len(_salla_missing_barcode_items(items))
        if not missing_total:
            return _skip("no_missing_barcodes")

        sid = store_identifier or store.get("salla_store_identifier")
        if not sid:
            doc = await db.stores.find_one(
                {"id": store.get("id")}, {"_id": 0, "salla_store_identifier": 1})
            sid = (doc or {}).get("salla_store_identifier")

        owns_client = client is None
        if owns_client:
            base = f"https://{store['domain']}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ar",
                "x-requested-with": "XMLHttpRequest",
                "Referer": f"{base}/",
                "Origin": base,
            }
            if sid:
                headers["store-identifier"] = sid
            httpx_kwargs = {"timeout": 20.0, "headers": headers}
            creds = await resolve_proxy_for(store, crawl_log, "detail_supplement")
            if creds:
                u, p, h, port = creds
                httpx_kwargs["proxy"] = f"http://{u}:{p}@{h}:{port}"
            client = httpx.AsyncClient(**httpx_kwargs)
        try:
            filled_details, _m, s1_failed, nbytes, by_status = \
                await _salla_detail_barcode_supplement(
                    client, items, store_domain=store.get("domain"),
                    store_identifier=sid)
        finally:
            if owns_client:
                await client.aclose()
        if store.get("use_proxy") and nbytes > 0:
            await record_proxy_usage(db, store, nbytes)

        # Stage 2 — only what stage 1 could not fill, under its own smaller cap
        still_missing = _salla_missing_barcode_items(items)
        filled_dom = dom_attempted = dom_failed = 0
        if still_missing:
            filled_dom, dom_attempted, dom_failed = \
                await _salla_dom_barcode_supplement(store, still_missing)

        attempted = min(missing_total, SALLA_DETAIL_SUPPLEMENT_CAP)
        filled = filled_details + filled_dom
        summary = (f"missing={missing_total} attempted={attempted} filled={filled}"
                   f" filled_details={filled_details} filled_dom={filled_dom}"
                   f" failed={s1_failed}")
        summary += "".join(f" failed_{k}={v}" for k, v in sorted(by_status.items(), key=str))
        summary += f" dom_attempted={dom_attempted} dom_failed={dom_failed}"
        crawl_log["endpoints_tried"].append({
            "endpoint": "detail_barcode_supplement", "status": "ran",
            "products": filled, "error": summary,
        })
        logger.info(f"[DetailSupplement] {store.get('name')}: {summary}")
    except Exception as e:
        _skip(f"exception:{str(e)[:80]}")


class _CheapPathIsEnough(Exception):
    """Control-flow marker: HTML + categories API already gave us everything."""


_SALLA_STORE_ID_PATTERNS = (
    r'"store"\s*:\s*\{\s*"id"\s*:\s*(\d{5,})',
    r'"store_id"\s*:\s*"?(\d{5,})',
    r'store-identifier["\'\s:=]+(\d{5,})',
    r'storeId["\'\s:=]+(\d{5,})',
)


async def _salla_store_identifier_from_html(domain):
    """Read the Salla store id straight out of the storefront HTML.

    iter75 — Hamtaro exposes `"store":{"id":1278867981,...}`, a shape none of the
    Playwright DOM patterns matched, so identifier capture returned None and the
    crawl fell back to Tier 2 and harvested **10 products out of ~2500**. One
    regex over the HTML fixes that and is ~60s cheaper than a browser launch.
    """
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
            resp = await polite_get(client, f"https://{domain}/")
        if resp is None or resp.status_code != 200:
            return None
        html = resp.text or ""
    except Exception as exc:
        logger.info("[StorefrontCategories] %s: HTML store-id probe failed: %s",
                    domain, str(exc)[:90])
        return None
    for pat in _SALLA_STORE_ID_PATTERNS:
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return None


def _flatten_salla_categories(nodes, out=None, depth=0):
    """Every numeric category id in a Salla category tree, parents included."""
    out = out if out is not None else []
    if depth > 6 or not isinstance(nodes, list):
        return out
    for node in nodes:
        if not isinstance(node, dict):
            continue
        cid = node.get("id_") or node.get("id")
        if isinstance(cid, int) or (isinstance(cid, str) and str(cid).isdigit()):
            out.append(str(cid))
        _flatten_salla_categories(
            node.get("sub_categories") or node.get("children") or [], out, depth + 1)
    return out


async def _salla_categories_from_api(store_identifier, domain=None):
    """The store's FULL category tree from the storefront API.

    iter75 — scraping the rendered menu only sees what the theme draws (Hamtaro:
    2 categories, and a 60-page hover walk to find more). This one request
    returns every nested node (Hamtaro: 99), and category coverage is what
    decides how much of a catalogue a crawl can even reach.
    """
    headers = {"Accept": "application/json",
               "store-identifier": str(store_identifier)}
    if domain:
        headers["Referer"] = f"https://{domain}/"
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=headers) as client:
            resp = await polite_get(client, "https://api.salla.dev/store/v1/categories",
                                    params={"limit": 100})
        if resp is None or resp.status_code != 200:
            return []
        body = resp.json()
    except Exception as exc:
        logger.info("[StorefrontCategories] categories API failed: %s", str(exc)[:90])
        return []
    data = body.get("data") if isinstance(body, dict) else body
    return list(dict.fromkeys(
        _flatten_salla_categories(data if isinstance(data, list) else [])))


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

    # Phase 0 — iter75 cheap path: store id from the storefront HTML plus the
    # FULL category tree from the storefront API. No browser needed, and far
    # more complete than scraping a rendered menu.
    store_identifier = await _salla_store_identifier_from_html(store["domain"])
    if store_identifier:
        cat_ids = await _salla_categories_from_api(store_identifier, store["domain"])
        logger.info("[StorefrontCategories] %s: HTML+API → store_identifier=%s categories=%d",
                    store["name"], store_identifier, len(cat_ids))
        crawl_log["endpoints_tried"].append({
            "endpoint": "categories_api", "status": 200, "products": 0,
            "error": f"store-id={store_identifier} categories={len(cat_ids)}"})

    # Phase 1 — Playwright: capture store-identifier + discover all categories (incl. nested)
    try:
        if store_identifier and len(cat_ids) >= 3:
            raise _CheapPathIsEnough
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            creds = await resolve_proxy_for(store, crawl_log, "storefront_categories")
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
            store_identifier = await _capture_salla_store_identifier(page, base) or store_identifier
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
                          document.querySelectorAll('a[href]').forEach(a => {
                            const h = a.href || a.getAttribute('href') || '';
                            let m = h.match(/categories\\/(\\d+)/);
                            if (m) out.add(m[1]);
                            m = h.match(/\\/c(\\d{6,})(?:$|[\\/?#])/);
                            if (m) out.add(m[1]);
                          });
                          return Array.from(out);
                        }
                    """)
                    sub_ids.update(new_sub)
                except Exception:
                    pass
            # iter75 — merge, never replace: the categories API tree (phase 0)
            # and the rendered-menu walk see different slices of a store.
            cat_ids = list(dict.fromkeys(list(cat_ids) + list(sub_ids)))[:max_categories]
            crawl_log["endpoints_tried"].append({"endpoint": "subcategory_discovery", "status": 200, "products": 0, "error": f"total_categories_discovered={len(cat_ids)}"})
            await browser.close()
    except _CheapPathIsEnough:
        logger.info("[StorefrontCategories] %s: browser skipped — HTML+API already "
                    "resolved store_identifier and %d categories",
                    store["name"], len(cat_ids))
    except ImportError:
        crawl_log["error"] = "Playwright not installed"
    except Exception as e:
        crawl_log["error"] = f"Storefront crawler discovery error: {str(e)[:200]}"

    if not store_identifier:
        crawl_log["error"] = (crawl_log.get("error") or "") + " | Failed to capture store-identifier"
        crawl_log["duration_secs"] = round(time.time() - start_time, 1)
        # iter64 — the observability entry exists even on the dead path that hid
        # the Zarafa 2026-07-31 outage (16:58 capture failure -> 19:05 zero
        # products, and no supplement line anywhere to say so).
        await _maybe_salla_detail_supplement(db, store, [], crawl_log)
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
                    r = await polite_get(client, url)
                    if r is None:
                        crawl_log["endpoints_tried"].append({"endpoint": f"cat={cid} p={page_num+1}", "status": 0, "products": 0, "error": "No response after retries"})
                        break
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

        # iter63/64 — bounded barcode supplement from the product-detail
        # endpoint, reusing this walk's client / headers / pacing and the
        # already-captured store-identifier. The wrapper writes the "ran" or
        # "skipped" observability entry and never raises. Proxy bytes for the
        # borrowed client are settled inside the wrapper via record_proxy_usage.
        # Enrichment follows durable capture and the soft-block check below.

    now = datetime.now(timezone.utc)
    crawl_log["duration_secs"] = round(time.time() - start_time, 1)

    if captured:
        # iter73w — soft-block guard: same policy as every other tier.
        soft_blocked, sb_reason = await _detect_soft_block(db, store, len(captured), crawl_log)
        if soft_blocked:
            _apply_soft_block(crawl_log, len(captured), "salla_storefront_categories_direct", sb_reason)
        else:
            crawl_log["tier_used"] = 2
            crawl_log["http_status"] = 200
            crawl_log["products_found"] = len(captured)
            from crawl_persistence import persist
            new_c, snap_c = await persist(db, store, captured, now, crawl_log, tier=2, confidence=88,
                                         store_identifier=store_identifier)
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
    from observation_contract import gtin
    return gtin(val) is not None


# Zid's Merchant API has exposed the cumulative sold counter under different
# names across API versions/plans; probe them in priority order. Capturing this
# is what powers the "My Revenue / Units Sold" KPIs via the estimator's
# sold_count_diff method — before Feb 2026 own-store snapshots hardcoded
# sold_count=0, which made own-store sales estimation structurally impossible.
ZID_SOLD_FIELD_CANDIDATES = ("sold_quantity", "sold_count", "sales_count", "total_sold", "sold")


def _extract_zid_sold_count(product: dict) -> int:
    from observation_contract import observed_int
    return next((observed_int(product[k]) for k in ZID_SOLD_FIELD_CANDIDATES if product.get(k) is not None), None)


def _retired_extract_zid_sold_count(product):
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


# iter46 — KSA standard VAT rate. Used ONLY to gross up Merchant-API prices for
# products the storefront does not list; storefront prices are already inclusive.
KSA_VAT_RATE = 0.15


def _zid_is_taxable(p):
    """Tristate tax flag from a Zid Merchant API product: True / False / None.

    None means 'the API did not tell us' — the caller must NOT assume taxable,
    because guessing wrong inflates a real price by 15%.
    """
    for key in ("is_taxable", "taxable"):
        v = p.get(key)
        if isinstance(v, bool):
            return v
    return None


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
                from observation_contract import expand_variants, money, observed_int
                for p in [v for item in items for v in expand_variants(item)]:
                    name_obj = p.get("name") or {}
                    if isinstance(name_obj, str):
                        name_obj = {"ar": name_obj, "en": name_obj}
                    # iter73d — preserve the LIST price separately so
                    # `resolve_own_price` can gross both list AND sale to the
                    # same VAT basis. Before, `raw.price` collapsed to
                    # `sale_price OR list`, dropping the list on on-sale
                    # products — which erased the strikethrough / discount %
                    # everywhere the Discounts / detail panels expect it.
                    _list = money(p.get("price")) or 0
                    _sale = money(p.get("sale_price")) or 0
                    _eff = _sale if _sale and _sale > 0 else _list
                    out.append({
                        "sku": str(p.get("sku") or "").strip(),
                        "barcode": str(p.get("barcode") or "").strip(),
                        "name_ar": name_obj.get("ar") or "",
                        "name_en": name_obj.get("en") or "",
                        "price": _eff,
                        "sale_price": _sale if _sale and _sale > 0 else None,
                        "list_price": _list,       # NEW — always the regular price
                        "qty_available": None if p.get("is_infinite") else observed_int(p.get("quantity")),
                        "in_stock": True if p.get("is_infinite") else (observed_int(p.get("quantity")) > 0 if observed_int(p.get("quantity")) is not None else None),
                        "listing_id": p.get("_listing_id"), "variant_id": p.get("_variant_id"),
                        "_unresolved_parent": p.get("_unresolved_parent"), "has_options": p.get("has_options"),
                        "_resolved_child": p.get("_resolved_child"), "_parent_sku": p.get("_parent_sku"),
                        "attributes": p.get("attributes"), "currency": p.get("currency"),
                        # Cumulative units-sold counter — feeds the estimator's
                        # sold_count_diff method (works even for is_infinite
                        # products whose qty can never show depletion).
                        "sold_count": _extract_zid_sold_count(p),
                        # iter46 — needed to decide whether a non-storefront
                        # product may be grossed up by VAT. Preserved as a
                        # TRISTATE: True / False / None(unknown) — never
                        # coerced, so "unknown" can be tagged instead of
                        # silently inflating a price.
                        "is_taxable": _zid_is_taxable(p),
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
                    return out, "partial"
    except httpx.HTTPError as e:
        logger.error(f"[OwnSync][Zid API] network error after {len(out)} products: {e}")
        return out, "partial" if out else "network_failed"
    logger.info(f"[OwnSync][Zid API] fetched {len(out)} products in {page} page(s)")
    return out, "ok"


def storefront_shelf_price(raw):
    """iter44 Step 2 — (shelf, list) price from a RAW storefront row.

    `effective_price` is the price actually on the shelf (it reflects any live
    discount); `price` is the list price and the fallback when effective_price
    is absent/zero. Both are VAT-INCLUSIVE — this is what a shopper pays and
    what every competitor row already holds.
    """
    list_price = _price_amount(raw.get("price"))
    effective = _price_amount(raw.get("effective_price"))
    shelf = effective if effective > 0 else list_price
    return shelf, list_price


# iter45 — the own catalogue carries barcode variants like
# "9003579308936carton" (a case/carton pack sharing the unit EAN). Match on the
# leading 8-14 digit run as well as the literal value, in BOTH directions, so a
# suffix on either side still matches.
# iter47 — plus the canonical GTIN-14 form, so UPC-A-with-leading-zero and
# EAN-without bridge.
#
# iter61 — `_BARCODE_LEAD_RE` and `barcode_keys` now live in core.utils and are
# imported at the top of this module. They used to be DEFINED here, which meant
# the MATCHER could not reach them: it intersected raw strings and so failed on
# exactly the pair iter47 was written to fix. `crawlers.barcode_keys` is still a
# valid import.


# Zid storefront product links look like /products/15 (Salla: /p15) — the
# trailing id is the storefront row id, which the index already carries.
_PRODUCT_URL_ID_RE = re.compile(r"/(?:products?/|p)(\d+)")


def product_url_id(url):
    """Storefront row id embedded in a product URL, or None."""
    m = _PRODUCT_URL_ID_RE.search(str(url or ""))
    return m.group(1) if m else None


def build_key_index(rows, payload_fn):
    """Index catalogue rows three ways — by SKU, by barcode (literal AND
    suffix-stripped), and by row id — mapping each key to payload_fn(row).

    iter45/46 — my_products keys are heterogeneous (merchant SKUs, Zid internal
    ids like "Z.123456", barcodes with variant suffixes), so the SAME rules are
    used for the storefront and the Merchant catalogues.
    """
    idx = {"by_sku": {}, "by_barcode": {}, "by_id": {}, "sku_barcodes": {}}
    def put(bucket, key, value):
        idx[bucket][key] = None if key in idx[bucket] else value
    for r in rows:
        payload = payload_fn(r)
        if payload is None:
            continue
        sku = str(r.get("sku") or "").strip().lower()
        if sku:
            put("by_sku", sku, payload)
            idx["sku_barcodes"][sku] = canonical_barcode(r.get("barcode"))
        for k in barcode_keys(r.get("barcode")):
            put("by_barcode", k, payload)
        rid = str(r.get("id") or r.get("_zid_id") or "").strip().lower()
        if rid:
            put("by_id", rid, payload)
    return idx


def _storefront_price_index(rows):
    """Storefront rows → (shelf_price, list_price) per key. Unpriced rows drop."""
    def _payload(r):
        from observation_contract import unresolved_identity
        if unresolved_identity(r):
            return None
        shelf, list_price = storefront_shelf_price(r)
        return (shelf, list_price) if shelf > 0 else None
    from observation_contract import expand_variants
    return build_key_index([v for raw in rows for v in expand_variants(raw)], _payload)


def merchant_index(rows):
    """iter46 — Merchant-API rows → the raw row per key, so the fallback can
    read both the ex-VAT price and the is_taxable tristate."""
    return build_key_index(rows, lambda r: r)


def storefront_price_lookup(idx, sku=None, barcode=None, product_url=None, canonical=True):
    """Resolve a my_products row against a catalogue index.

    Returns ((shelf, list), method) or (None, None). Order, strongest first:
    exact SKU, barcode (literal -> suffix-stripped -> GTIN-14 canonical), the
    storefront id embedded in the product URL, the SKU treated as a barcode,
    and finally a Zid internal id ("Z.123456").

    canonical=False disables the iter47 keys (GTIN-14 + product URL) so the
    caller can measure what the previous key set would have matched.
    """
    s = str(sku or "").strip().lower()
    bc = canonical_barcode(barcode)
    for key in barcode_keys(barcode) if bc else []:
        if idx["by_barcode"].get(key) is not None:
            return idx["by_barcode"][key], "barcode"
    observed_bc = idx.get("sku_barcodes", {}).get(s)
    if bc and observed_bc and bc != observed_bc:
        return None, "contradictory_barcode"
    if s and s in idx["by_sku"]:
        return idx["by_sku"][s], "sku"

    bc_raw = str(barcode or "").strip().lower()
    bc_lead = None
    m = _BARCODE_LEAD_RE.match(bc_raw) if bc_raw else None
    if m:
        bc_lead = m.group(1)
    for k in barcode_keys(barcode, canonical=canonical):
        if k in idx["by_barcode"]:
            if k == bc_raw:
                method = "barcode"
            elif k == bc_lead:
                method = "barcode_normalized"
            else:
                method = "barcode_gtin14"
            return idx["by_barcode"][k], method

    # B (reverse direction) — our barcode may be their SKU. The forward
    # direction (our SKU is their barcode) is handled below.
    if canonical:
        for k in barcode_keys(barcode, canonical=False):
            if k in idx["by_sku"]:
                return idx["by_sku"][k], "barcode_as_sku"

    # C — the product URL carries the storefront row id verbatim
    if canonical:
        pid = product_url_id(product_url)
        if pid and pid in idx["by_id"]:
            return idx["by_id"][pid], "product_url_id"

    # a numeric-looking SKU may itself be a barcode (B — now GTIN-aware via A)
    if s:
        for k in barcode_keys(s, canonical=canonical):
            if k in idx["by_barcode"]:
                return idx["by_barcode"][k], ("sku_as_barcode" if k == s else "sku_as_barcode_gtin14")
        if s.startswith("z."):
            zid = s[2:]
            if zid in idx["by_id"]:
                return idx["by_id"][zid], "zid_internal_id"
            if zid in idx["by_sku"]:
                return idx["by_sku"][zid], "zid_internal_id"
    return None, None


# methods that only exist because of the iter47 keys — used for before/after
ITER47_METHODS = {"barcode_gtin14", "barcode_as_sku", "product_url_id",
                  "sku_as_barcode_gtin14"}


# iter45 — own-store storefront pagination. The SHARED _paginate_endpoint stops
# on `len(page) < 20`, a "short page means last page" heuristic that truncated
# our own catalogue at 1,184 of 2,590 products. That helper is also used by the
# COMPETITOR crawl, so it is left untouched; the own-store fetch gets this
# dedicated paginator driven by the response's explicit pagination metadata.
OWN_SF_MAX_PAGES = 200
OWN_SF_PAGE_TIMEOUT = 20.0
_OWN_SF_PAGE_DELAY = 0.08


def _sf_items(body):
    """Extract the product list from any storefront envelope shape."""
    if not isinstance(body, dict):
        return []
    items = body.get("data", body.get("products", body.get("results", [])))
    if isinstance(items, dict):                      # legacy nested envelope
        inner = items.get("products")
        if isinstance(inner, dict) and isinstance(inner.get("data"), list):
            return inner["data"]
        if isinstance(items.get("data"), list):
            return items["data"]
        return []
    return items if isinstance(items, list) else []


def _sf_page_meta(body):
    """(total_pages, total_results, has_next) from whichever metadata the
    storefront exposes — pages_count / last_page / results / next."""
    if not isinstance(body, dict):
        return None, None, None
    pg = body.get("pagination") if isinstance(body.get("pagination"), dict) else {}

    def _int(*vals):
        for v in vals:
            if isinstance(v, bool):
                continue
            try:
                if v is not None:
                    return int(v)
            except (TypeError, ValueError):
                continue
        return None

    total_pages = _int(body.get("pages_count"), pg.get("pages_count"),
                       body.get("last_page"), pg.get("last_page"),
                       body.get("total_pages"), pg.get("total_pages"))
    total_results = _int(body.get("total"), pg.get("total"),
                         body.get("results"), pg.get("results"),
                         body.get("count") if not isinstance(body.get("data"), list) else None)
    nxt = pg.get("next", body.get("next"))
    has_next = None if nxt is None and "next" not in pg and "next" not in body else bool(nxt)
    return total_pages, total_results, has_next


async def _paginate_own_storefront(http, ep, initial_items, max_pages=OWN_SF_MAX_PAGES):
    from catalog_pagination import paginate
    rows = await paginate(http, ep, initial_items, polite_get, max_pages=max_pages)
    meta = ep["_pagination"]
    return rows, meta["pages_fetched"], meta["stop_reason"]


async def _retired_paginate_own_storefront(http, ep, initial_items, max_pages=OWN_SF_MAX_PAGES):
    """Walk the FULL own-store catalogue. Never stops on a short page — only on
    explicit end-of-pagination, an empty page, a page cap, or an error.
    Returns (rows, pages_fetched, stop_reason)."""
    rows = list(initial_items)
    seen = set()

    def _key(r):
        return (str(r.get("id") or "").strip()
                or str(r.get("sku") or "").strip()
                or str(r.get("barcode") or "").strip())

    for r in rows:
        seen.add(_key(r))

    page, stop_reason = 1, "exhausted"
    total_pages = total_results = None
    while page < max_pages:
        page += 1
        params = dict(ep.get("params", {}))
        params["page"] = page
        try:
            resp = await http.get(ep["url"], params=params, timeout=OWN_SF_PAGE_TIMEOUT)
            if resp.status_code != 200:
                stop_reason = f"http_{resp.status_code}"
                break
            body = resp.json()
        except Exception as exc:
            logger.warning(f"[OwnSF] page {page} failed: {exc}")
            stop_reason = "page_error"
            break
        more = _sf_items(body)
        if not more:
            stop_reason = "empty_page"
            break
        fresh = [r for r in more if _key(r) not in seen]
        for r in fresh:
            seen.add(_key(r))
        rows.extend(fresh)
        if not fresh:                     # same page echoed back — pagination is looping
            stop_reason = "duplicate_page"
            break
        tp, tr, has_next = _sf_page_meta(body)
        total_pages = tp if tp is not None else total_pages
        total_results = tr if tr is not None else total_results
        if has_next is False:
            stop_reason = "no_next"
            break
        if total_pages is not None and page >= total_pages:
            stop_reason = "pages_count_reached"
            break
        if total_results is not None and len(rows) >= total_results:
            stop_reason = "results_total_reached"
            break
        await asyncio.sleep(_OWN_SF_PAGE_DELAY)
    else:
        stop_reason = "max_pages"
    logger.info(f"[OwnSF] {len(rows)} products across {page} page(s) — stop={stop_reason}")
    return rows, page, stop_reason


# iter46 — the single place the own-store price basis is decided. Sync and
# backfill both call this, so the two can never drift apart.
#
#   on the storefront            -> its inc-VAT shelf price   storefront_inc_vat
#   not on it, is_taxable True   -> merchant price x (1+VAT)  merchant_computed_inc_vat
#   not on it, is_taxable False  -> merchant price unchanged  merchant_non_taxable
#   not on it, is_taxable None   -> merchant price x (1+VAT)  merchant_assumed_inc_vat
#                                                             (iter73d — Saudi
#                                                             default: retail
#                                                             goods are taxable)
#
# iter73d — the previous "unknown → keep ex-VAT" rule was correct in principle
# ("inflating a real price by 15% is a bug") but wrong in Saudi practice: 99%
# of retail goods ARE taxable, Zid's Merchant API doesn't always populate
# is_taxable, and the resulting mixed-basis rows were the cause of the "my
# prices show without VAT on some tabs" client report. The `merchant_assumed_
# inc_vat` tag keeps the auto-grossed rows countable, so operators can spot-
# check them; a genuinely non-taxable product must set is_taxable=False in
# Zid so the resolver keeps its ex-VAT basis.
#
# iter73i — new signal `storefront_authoritative` (Aug 3 2026). When the
# storefront overlay ran and produced a NON-EMPTY index, it is the source of
# truth for what a shopper actually pays. A SKU that is IN the merchant
# catalogue but MISSING from the storefront index means the shopper never
# sees the merchant's `sale_price` — that price is a phantom (scheduled
# promo, archived draft, unpublished variant). Trusting it produced the
# client-reported bug on SKU 8595602540877: website 237.02 SAR
# (= list × 1.15), Daleel 180.17 SAR (= phantom sale × 1.15).
# When authoritative + no sf_hit, drop the merchant sale_price entirely and
# gross up the LIST price only — matching what the shopper actually pays.
def resolve_own_price(sf_hit, merchant_price=None, merchant_sale_price=None,
                      merchant_list_price=None, is_taxable=None,
                      storefront_authoritative=False):
    """Return (price, sale_price, original_price, price_basis). All outputs 2dp.

    `original_price` is the pre-sale LIST/regular price grossed to the SAME
    basis as `price` — never dropped for on-sale items. Downstream writers
    can now emit `original_price > price` faithfully and Discounts / strike-
    through displays no longer need to reconstruct it after the fact.

    When `storefront_authoritative=True` and `sf_hit=None`, this row exists
    in the merchant catalogue but not on the public storefront. The shopper
    cannot see any merchant-side sale, so we drop `merchant_sale_price` and
    treat `merchant_list_price` (fall-back: `merchant_price`) as the sole
    effective price. Basis tags this branch so operators can audit the drift.
    """
    if sf_hit:
        shelf, list_price = sf_hit
        on_sale = list_price > 0 and shelf < list_price - 0.009
        _orig = round(list_price, 2) if list_price > 0 else round(shelf, 2)
        return (round(shelf, 2),
                (round(shelf, 2) if on_sale else None),
                _orig,
                "storefront_inc_vat")

    if is_taxable is None:
        # Missing tax evidence is not permission to add 15%.
        value = _price_amount(merchant_price)
        original = _price_amount(merchant_list_price) or value
        return value, None, original, "merchant_unknown_tax"

    price = _price_amount(merchant_price)
    sale = _price_amount(merchant_sale_price)
    # The list-price argument is optional so pre-iter73d callers still work;
    # when absent, the effective merchant_price is the best list-price proxy
    # we have (equal to the sale on on-sale items — the same info we had
    # before the argument existed, no regression).
    list_p = _price_amount(merchant_list_price) if merchant_list_price is not None else price

    # iter73i — storefront ran, this SKU isn't on it: the merchant sale is
    # invisible to the shopper. Anchor on the LIST price only.
    if False:  # Absence from a listing never proves that a merchant sale is hidden.
        # Effective price = list_price (fall back to merchant_price when the
        # merchant didn't distinguish list vs sale).
        eff = list_p if list_p > 0 else price
        if is_taxable is False:
            return (round(eff, 2),
                    None,
                    round(eff, 2),
                    "merchant_hidden_non_taxable")
        mult = 1 + KSA_VAT_RATE
        return (round(eff * mult, 2),
                None,
                round(eff * mult, 2),
                "merchant_hidden_from_storefront_inc_vat")

    if is_taxable is False:
        return (round(price, 2),
                (round(sale, 2) if sale > 0 else None),
                round(list_p, 2),
                "merchant_non_taxable")

    # is_taxable True OR None (Saudi default): gross up. Tag records which
    # path so a taxability regression is countable in the vat-audit surface.
    mult = 1 + KSA_VAT_RATE
    basis = "merchant_computed_inc_vat" if is_taxable is True else "merchant_assumed_inc_vat"
    return (round(price * mult, 2),
            round(sale * mult, 2) if sale > 0 else None,
            round(list_p * mult, 2),
            basis)


async def fetch_own_storefront_catalog_raw(store, max_pages=OWN_SF_MAX_PAGES):
    """iter44 (Step-1 validation) — fetch the own store's PUBLIC storefront
    catalogue and return the RAW rows, unnormalised.

    _normalize_raw_product() drops `effective_price` and `is_taxable`, which are
    exactly the fields the VAT-basis audit needs, so this returns the untouched
    JSON. Read-only: performs no DB writes and does not mutate the store doc
    (unlike the sync path, which caches working_endpoint).

    Returns (rows, meta) where meta records the endpoint used and whether the
    fetch looked complete.
    """
    base = f"https://{store['domain']}"
    platform = (store.get("platform") or "zid").lower()
    endpoints = _build_salla_endpoints(base, store.get("working_endpoint"), platform=platform)
    crawl_log = _make_crawl_log(store, tier_attempted=1)
    rows, matched, pages, stop_reason = [], None, 0, None
    try:
        async with httpx.AsyncClient(timeout=OWN_SF_PAGE_TIMEOUT, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html, */*",
        }) as http:
            for ep in endpoints:
                items, matched_ep = await _try_single_endpoint(http, ep, crawl_log)
                if matched_ep:
                    matched = matched_ep
                    rows, pages, stop_reason = await _paginate_own_storefront(
                        http, matched_ep, items, max_pages=max_pages)
                    break
    except Exception as e:
        return rows, {"ok": False, "error": str(e)[:300], "endpoint": (matched or {}).get("tag"),
                      "rows": len(rows), "pages": pages, "stop_reason": "exception",
                      "attempts": crawl_log.get("attempts")}
    return rows, {"ok": bool(matched), "complete": bool((matched or {}).get("_pagination", {}).get("complete")), "endpoint": (matched or {}).get("tag"),
                  "rows": len(rows), "pages": pages, "stop_reason": stop_reason,
                  "truncated": stop_reason == "max_pages",
                  "attempts": crawl_log.get("attempts")}


async def sync_own_store_prices(db, store=None, *, targeted_rows=None, observed_at=None):
    import job_control
    store = store or await db.stores.find_one({"is_own_store": True}, {"_id": 0})
    if not store:
        return {"status": "error", "error": "no_own_store_flagged"}
    owner = str(uuid.uuid4())
    if not await job_control.acquire(db, f"store:{store['id']}", owner):
        return {"status": "deferred", "error": "store_job_already_running"}
    try:
        task = _sync_own_store_prices_locked(db, store) if targeted_rows is None else _sync_own_store_prices_locked(db, store, targeted_rows=targeted_rows, observed_at=observed_at)
        return await asyncio.wait_for(task, timeout=2.5*3600)
    finally:
        await job_control.release(db, f"store:{store['id']}", owner)


async def _sync_own_store_prices_locked(db, store=None, *, targeted_rows=None, observed_at=None):
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

    started_at = observed_at or datetime.now(timezone.utc)
    logger.info(f"[OwnSync] Starting price sync for {store['name']} ({store.get('domain')})")

    # ── Try Zid Merchant API first; fall back to public crawl on miss ──
    sync_source_label = None
    all_raw, zid_status = (targeted_rows, "targeted_public") if targeted_rows is not None else await _fetch_zid_api_catalog(db, store)
    winning_endpoint = None
    crawl_log = _make_crawl_log(store, tier_attempted=1)

    if targeted_rows is not None:
        sync_source_label = "public_crawl"
        winning_endpoint = {"tag": "targeted_product_pages", "_pagination": {"complete": False}}
        crawl_log.update(tier_used=1, endpoint_used="targeted_product_pages", scope="targeted_listings")
    elif zid_status == "ok" and all_raw:
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

    # ── iter44 Step 2: inc-VAT price overlay ────────────────────────────────
    # The Zid MERCHANT API returns the ex-VAT base price, while the public
    # storefront returns the VAT-inclusive shelf price — the same basis as every
    # competitor row and as our own orders ledger. Storing the merchant price
    # made our store look ~15% cheaper than it is on every taxable product.
    # So when the merchant path wins we still take sold_count / quantity /
    # stock from it (the storefront does not expose those reliably) but overlay
    # the PRICE from the storefront, matched by SKU then barcode. A SKU the
    # storefront doesn't carry keeps the merchant price and is tagged
    # price_basis="merchant_ex_vat" so the fallback rate stays visible.
    sf_index = {"by_sku": {}, "by_barcode": {}, "by_id": {}}
    storefront_overlay_meta = None
    if sync_source_label == "zid_api":
        try:
            sf_rows, storefront_overlay_meta = await fetch_own_storefront_catalog_raw(store)
            sf_index = _storefront_price_index(sf_rows)
            logger.info(f"[OwnSync] storefront overlay: {len(sf_index['by_sku'])} SKUs / "
                        f"{len(sf_index['by_barcode'])} barcode keys priced inc-VAT "
                        f"({(storefront_overlay_meta or {}).get('pages')} pages)")
        except Exception as e:
            # Never fail the sync on the overlay — fall back to merchant prices,
            # tagged, so the basis is auditable rather than silently wrong.
            storefront_overlay_meta = {"ok": False, "error": str(e)[:200]}
            logger.error(f"[OwnSync] storefront overlay failed ({e}) — merchant prices retained")
    # iter54 — resolved own price per RAW sku, shared with the snapshot writer
    own_resolved_price = {}
    basis_counts = {"storefront_inc_vat": 0, "merchant_computed_inc_vat": 0,
                    "merchant_non_taxable": 0, "merchant_assumed_inc_vat": 0,
                    "merchant_hidden_from_storefront_inc_vat": 0,
                    "merchant_hidden_non_taxable": 0}
    # iter73i — the storefront index is AUTHORITATIVE when it fetched
    # successfully and produced any keyed entry. A SKU missing from an
    # authoritative index means the shopper never sees any merchant-side
    # sale on that product (see resolve_own_price for the rationale).
    storefront_authoritative = bool((storefront_overlay_meta or {}).get("complete"))
    catalog_complete = zid_status == "ok" if sync_source_label == "zid_api" else bool((winning_endpoint or {}).get("_pagination", {}).get("complete"))
    crawl_log["complete"] = catalog_complete

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
    sync_ts = started_at.isoformat()
    UPDATE_FIELDS_NEVER_OVERWRITE = {  # noqa: F841 — documentation only
        "sku", "barcode", "name_ar", "name_en", "description_ar", "description_en",
        "categories_ar", "categories_en", "images", "product_page_url",
        "is_own_store", "store_id", "imported_at",
    }

    own_store_id = store.get("id")
    from observation_contract import expand_variants, stable_id
    if sync_source_label == "public_crawl":
        all_raw = [v for row in all_raw for v in expand_variants({**row, "_currency": "SAR", "_price_basis": "storefront_inc_vat"})]

    # Own catalog APIs still identify rows and invoice lines by SKU. Never
    # assign one sibling's price or orders to another when that key is ambiguous.
    # Preserve the raw offers for explicit reconciliation rather than guessing.
    from own_quarantine import filter_own_rows
    all_raw, quarantined_own = await filter_own_rows(db, store, all_raw, sync_source_label, started_at, _normalize_raw_product)
    if quarantined_own:
        catalog_complete = False
        crawl_log['complete'] = False
        crawl_log['quarantined_offers'] = quarantined_own

    for raw in all_raw:
        # Zid API rows arrive pre-normalised (see _fetch_zid_api_catalog); the
        # public-crawl path needs _normalize_raw_product to reshape Salla/Zid
        # storefront JSON. Distinguish by the synthetic `_zid_id` marker.
        if raw.get("_zid_id"):
            # Stock/sales fields ALWAYS come from the merchant API; only the
            # price is overlaid from the storefront (iter44 Step 2).
            sf_hit, _sf_method = storefront_price_lookup(
                sf_index, sku=raw.get("sku"), barcode=raw.get("barcode"),
                product_url=raw.get("product_url"))
            # iter46 — two-tier basis: storefront shelf price when the product
            # is listed, else the Merchant price grossed up ONLY when Zid says
            # the product is taxable.
            # iter73i — plumb storefront_authoritative so hidden-SKU rows
            # anchor on the LIST price only (the phantom-sale fix).
            price_v, sale_v, orig_v, price_basis = resolve_own_price(
                sf_hit,
                merchant_price=raw.get("price"),
                merchant_sale_price=raw.get("sale_price"),
                merchant_list_price=raw.get("list_price"),
                is_taxable=raw.get("is_taxable"),
                storefront_authoritative=storefront_authoritative,
            )
            norm = {
                "sku": raw.get("sku") or "",
                "barcode": raw.get("barcode") or "",
                "name_ar": raw.get("name_ar") or "",
                "name_en": raw.get("name_en") or "",
                "price": price_v,
                "sale_price": sale_v,
                "original_price": orig_v,   # iter73d — surfaced through the norm
                "qty": raw.get("qty_available"),
                "in_stock": raw.get("in_stock"),
                "img_url": raw.get("img_url", ""),
                "product_url": raw.get("product_url", ""),
            }
        else:
            # Public-crawl fallback: `all_raw` IS the storefront payload, so it
            # is already inc-VAT. _normalize_raw_product is shared with the
            # COMPETITOR crawl and must not change, so apply the same
            # effective_price-first shelf rule here on the raw row.
            norm = _normalize_raw_product(raw, store["name"])
            price_basis = "storefront_inc_vat"
            shelf, list_price = storefront_shelf_price(raw)
            if shelf > 0:
                norm["price"] = shelf
                norm["sale_price"] = shelf if (list_price > 0 and shelf < list_price - 0.009) else None
                # iter73d — record the LIST price so the my_products /
                # snapshot writers pick it up as `original_price`. Fall back
                # to shelf when the storefront didn't carry a distinct list.
                norm["original_price"] = list_price if list_price > 0 else shelf
            else:
                norm["original_price"] = norm.get("price")
        if norm.get("price") is None:
            continue
        basis_counts[price_basis] = basis_counts.get(price_basis, 0) + 1
        # iter54 — hand the RESOLVED price to the snapshot writer below.
        # That writer re-read `raw["price"]` from scratch, i.e. the Zid Merchant
        # API's EX-VAT base, so my_products was corrected to the inc-VAT shelf
        # price while product_snapshots kept the ex-VAT one (Hills 052742059518:
        # my_products 170.00, snapshot 147.83). Every surface that reads
        # snapshots — the detail panel, price history, market position, the
        # rollups behind Insights — therefore showed our store 15% cheap.
        # Keyed by the RAW sku: the matching below may retarget to a different
        # my_products sku, but the snapshot is written under the raw one.
        _resolved_sku = str(norm.get("sku") or "").strip()
        if _resolved_sku:
            own_resolved_price[_resolved_sku] = (
                norm.get("price"), norm.get("sale_price"),
                norm.get("original_price"), price_basis)
        crawled_sku = str(norm["sku"]).strip()
        crawled_barcode = str(norm.get("barcode") or "").strip()
        own_offer_id = stable_id(own_store_id, raw.get("listing_id") or raw.get("_listing_id") or raw.get("_zid_id") or raw.get("id"), raw.get("variant_id") or raw.get("_variant_id") or "root")

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
                "offer_id": own_offer_id,
                "listing_id": raw.get("listing_id") or raw.get("_listing_id") or raw.get("_zid_id"),
                "variant_id": raw.get("variant_id") or raw.get("_variant_id") or "root",
                "quantity_observed_at": sync_ts, "quarantine_active": False,
                "barcode": crawled_barcode or "",
                "name_ar": norm.get("name_ar", ""),
                "name_en": norm.get("name_en") or norm.get("name_ar", ""),
                "image_url": norm.get("img_url", ""),
                "product_url": norm.get("product_url", ""),
                "price": round(norm["price"], 2),
                "sale_price": round(norm["sale_price"], 2) if norm.get("sale_price") else None,
                # iter73d — persist the LIST price alongside the effective /
                # sale so downstream readers (Discounts strikethrough,
                # detail-panel history) never need to reconstruct it.
                "original_price": round(norm["original_price"], 2) if norm.get("original_price") else round(norm["price"], 2),
                "quantity": norm["qty"],
                "in_stock": norm["in_stock"],
                "is_own_store": True,
                "store_id": own_store_id,
                "imported_at": sync_ts,
                "first_seen_on_store": sync_ts,
                "last_seen_on_store": sync_ts,
                "present_on_store": True,
                "last_synced_at": sync_ts,
                "sync_source": f"{sync_source_label}_auto_discovery",
                "price_basis": price_basis,
                "currency": "SAR",
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
            "offer_id": own_offer_id,
            "listing_id": raw.get("listing_id") or raw.get("_listing_id") or raw.get("_zid_id"),
            "variant_id": raw.get("variant_id") or raw.get("_variant_id") or "root",
            "quantity_observed_at": sync_ts, "quarantine_active": False,
            "price": round(norm["price"], 2),
            "sale_price": round(norm["sale_price"], 2) if norm.get("sale_price") else None,
            # iter73d — see setOnInsert comment above; must land on updates too.
            "original_price": round(norm["original_price"], 2) if norm.get("original_price") else round(norm["price"], 2),
            "quantity": norm["qty"],
            "in_stock": norm["in_stock"],
            "last_synced_at": sync_ts,
            "sync_source": sync_source_label,
            "price_basis": price_basis,
            "currency": "SAR",
            "present_on_store": True,
            "last_seen_on_store": sync_ts,
        }
        await db.my_products.update_one({"sku": target_sku}, {"$set": update_doc, "$unset": {"price_unavailable_reason": ""}})
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
        from observation_contract import stable_id, TRUSTED_PRICE_BASES
        from evidence_ledger import record
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
        _ledger_obs = []       # iter67 — ledger sees every product, dedup or not
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
            # iter54 — the SAME inc-VAT basis my_products got, not the raw
            # ex-VAT merchant price. Falls back to the raw value only for rows
            # loop 1 never resolved (it cannot happen for zid_api rows, but the
            # snapshot must still be written rather than dropped).
            _res = own_resolved_price.get(sku)
            price = (_res[0] if _res and _res[0] is not None else (raw.get("price") or 0))
            sale_price_v = _res[1] if _res else None
            list_price_v = _res[2] if _res else None
            price_basis_v = _res[3] if _res else "merchant_assumed_inc_vat"
            if price_basis_v not in TRUSTED_PRICE_BASES:
                continue
            offer_id = stable_id(own_store_id, raw.get("listing_id") or raw.get("_zid_id"), raw.get("variant_id") or "root")
            qty = raw.get("qty_available")
            in_stock = raw.get("in_stock") if not raw.get("_zid_is_infinite") else True
            barcode = raw.get("barcode") or ""
            _prev = _todays_latest.get(sku)
            # iter73 — the Zid own-store sync used to always write
            # `original_price = price, discount_pct = 0` even when the row
            # DID have a sale_price. That's the write-time origin of every
            # empty Discounts panel: the row's OWN arithmetic proved a
            # discount, but the fields it carried disagreed. The correct
            # semantics match the ingest-path / snapshot-writer contract:
            #   • price          = effective price the shopper pays
            #   • original_price = pre-sale reference; equals `price` when
            #                      no genuine sale (sale_price is None or
            #                      the sale isn't actually cheaper)
            #   • discount_pct   = round((1 - price/original) * 100) when
            #                      original > price > 0, else 0
            # The ledger observation right below now reads the SAME derived
            # values, so ledger + snapshot cannot disagree.
            _price_v = float(price)
            _sale_v = float(sale_price_v) if sale_price_v else 0.0
            _list_v = float(list_price_v) if list_price_v else _price_v
            # iter73d — the LIST price now flows through end-to-end. When the
            # product is on sale (`sale_v > 0` AND `list_v > sale_v`) we
            # record original_price = list_v (the pre-sale reference the
            # storefront strikethrough would show). If the list is silently
            # equal to the sale, the sale isn't a real discount — treat as
            # no-sale. This gives the Discounts tab a truthful original_price
            # WITH VAT for every genuinely discounted own-store product.
            if _sale_v > 0 and _list_v > _sale_v + 0.009:
                _snap_price = round(_sale_v, 2)
                _snap_original = round(_list_v, 2)
                _snap_disc_pct = round((1 - _snap_price / _snap_original) * 100)
            else:
                _snap_price = round(_price_v, 2)
                _snap_original = round(max(_list_v, _price_v), 2)
                _snap_disc_pct = 0
            # iter67 — the ledger records EVERY observed product, including the
            # ones the change-only snapshot dedup below skips: "unchanged" is
            # still an observation of that KSA day, and skipping it would make
            # a quiet day look like an uncrawled one.
            _ledger_obs.append({
                "sku": sku,
                "close_price": _snap_price,
                "close_sale_price": _snap_price if _snap_disc_pct > 0 else None,
                "close_original_price": _snap_original,
                "discount_pct": _snap_disc_pct,
                "on_sale": _snap_disc_pct > 0,
                "in_stock": in_stock,
                "qty_available": qty,
                "sold_count_cumulative": raw.get("sold_count"),
            })
            _snapshot_unchanged_today = _prev is not None and (
                round(float(_prev.get("price") or 0), 2) == _snap_price
                and _prev.get("qty_available") == qty
                and int(_prev.get("sold_count") or 0) == int(raw.get("sold_count") or 0)
                and bool(_prev.get("in_stock")) == in_stock
            )
            # Upsert catalog row (idempotent — only sets if new, preserves history)
            prod_upserts.append({
                "sku": sku,
                "set_on_insert": {
                    "id": str(uuid.uuid4()),
                    "sku": sku,
                    "store_id": own_store_id, "offer_id": offer_id,
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
                "offer_id": offer_id, "event_id": stable_id(offer_id, sync_ts),
                "listing_id": raw.get("listing_id"), "variant_id": raw.get("variant_id"),
                "observation_version": 2, "comparable": True, "currency": "SAR", "is_synthetic": False,
                "name_ar": raw.get("name_ar"), "name_en": raw.get("name_en"), "barcode": barcode,
                "sold_count_observed": raw.get("sold_count") is not None,
                "data_origin": "zid_merchant_observation",
                # iter73 — derived above, coherent with the ledger obs.
                # A row on sale now truthfully carries the sale price under
                # `price`, the regular reference under `original_price`, and
                # a non-zero `discount_pct` so Discounts / Insights read it
                # without a read-time repair pass.
                "price": _snap_price,
                "original_price": _snap_original,
                # iter54 — the basis this price was resolved on, so a future
                # capture regression is visible in our own data rather than
                # only in my_products.
                "price_basis": price_basis_v,
                "sale_price": _snap_price if _snap_disc_pct > 0 else None,
                "discount_pct": _snap_disc_pct,
                "in_stock": in_stock,
                "qty_available": qty,
                # Real cumulative sold counter from the Zid Merchant API (was
                # hardcoded 0 until Feb 2026, which zeroed all own-sales KPIs).
                "sold_count": raw.get("sold_count"),
                "product_url": raw.get("product_url") or "",
                "source_tier": 0,  # 0 = authenticated API (best signal we have)
                "confidence_score": 99,
                "crawled_at": started_at,
            })
        # Bulk upsert catalog rows (only sets on insert; never overwrites)
        for up in prod_upserts:
            await db.products.update_one({"offer_id": up["set_on_insert"]["offer_id"]}, {"$setOnInsert": up["set_on_insert"]}, upsert=True)
        # Bulk insert snapshots
        if snap_docs:
            await db.product_snapshots.insert_many(snap_docs)
            for snap in snap_docs:
                await record(db, snap)
            snapshots_created = len(snap_docs)
        # iter67 — own-store ledger write (source_tier 0 = authenticated API,
        # confidence 99: the same labels the synthetic snapshots carry).
        try:
            await ledger.record_observations(
                db, own_store_id, store["name"], _ledger_obs, started_at,
                source_tier=0, confidence=99)
        except Exception:
            logger.exception("[Ledger] own-sync write failed — sync unaffected")

    if sync_source_label == "public_crawl" and all_raw:
        before = await db.product_snapshots.count_documents({"store_id": own_store_id, "crawled_at": started_at})
        await process_crawled_products(db, store, all_raw, started_at, tier=1, confidence=95)
        snapshots_created = await db.product_snapshots.count_documents({"store_id": own_store_id, "crawled_at": started_at}) - before

    # ── Mark every my_products row NOT seen in this crawl as archived ──
    # Soft-archive only: row + history are preserved, but `present_on_store=False`
    # lets the UI badge them as "Removed from store" without filtering them out.
    archived = 0
    if all_raw and catalog_complete and len(seen_skus) == len({str(r.get("sku") or "") for r in all_raw}):
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
    if targeted_rows is not None:
        crawl_log.update(completed_at=datetime.now(timezone.utc).isoformat(), status="targeted_completed", complete=False)
        await db.crawl_logs.insert_one(dict(crawl_log))
        await db.stores.update_one({"id": store["id"]}, {"$set": {"last_targeted_sync": sync_ts}})
        return {"status": "targeted_completed", "scope": "targeted_listings", "updated": updated,
                "discovered": discovered, "archived": 0, "quarantined": quarantined_own,
                "snapshots_created": snapshots_created, "observed_at": sync_ts, "skus": sorted(seen_skus)}
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
            # iter44 — how many rows landed on each VAT basis this run
            "own_store_price_basis": basis_counts,
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
        "warning": sync_warning or (f'{quarantined_own} own offers quarantined for identity or money evidence' if quarantined_own else None),
        "quarantined": quarantined_own,
        "catalog_complete": catalog_complete,
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
        # iter44 Step 2 — VAT-basis visibility
        "price_basis_counts": basis_counts,
        "storefront_overlay": storefront_overlay_meta,
    }


# ── Waterfall Orchestrator ───────────────────────────────────
async def crawl_store_waterfall(db, store):
    if store.get("is_own_store"):
        return await sync_own_store_prices(db, store)
    import job_control
    owner = str(uuid.uuid4())
    if not await job_control.acquire(db, f"store:{store['id']}", owner):
        return {"status": "deferred", "error": "store_job_already_running"}
    try:
        return await asyncio.wait_for(_crawl_store_waterfall_locked(db, store), timeout=2.5*3600)
    finally:
        await job_control.release(db, f"store:{store['id']}", owner)


async def _crawl_store_waterfall_locked(db, store):
    """Run the multi-tier waterfall crawler for a store, with optional Tier 4 supplement.

    Special-case: own store (is_own_store=True) is sync'd into my_products via
    sync_own_store_prices() instead of going through the competitor snapshot pipeline.
    """
    if store.get("is_own_store"):
        return await sync_own_store_prices(db, store=store)

    from crawl_persistence import recover
    await recover(db, store)
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
