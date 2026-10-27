"""The brand of every product (27 Oct 2026 — the client: "display the brand
name for each item").

Most stores give no brand in their product data (Zid stores leave it empty),
but Salla stores file every product under a brand page, which the crawl now
reads, and Panda and the key-brand rules give more. This directory turns that
evidence into a brand for any product:

  1. a key brand named in the name (key_brands.py) — the client's 11 brands;
  2. the brand stores give for the same barcode (same product, any store:
     a Zid store's item takes the brand Zarafa files it under);
  3. a known brand name written in the product name (names collected from
     every store's brands, longest first);
  4. the product's own tag.

refresh() rebuilds it from db.products; brand_for() is a pure lookup.
"""
import re
import time
from collections import Counter, defaultdict

TRUSTED = {"reviewed": 10, "key_brand_name": 3, "store_supplied": 1}
MAX_AGE_SECS = 3600
# Words that are product words, not brands, even when a store files them as one.
_NOT_BRANDS = {"cat", "cats", "dog", "dogs", "pet", "pets", "food", "dry food", "wet food", "litter", "toys", "toy",
               "accessories", "other", "others", "general", "no brand", "none", "n/a", "na", "قطط", "كلاب", "اخرى",
               "أخرى", "عام", "بدون", "اكسسوارات", "ألعاب", "العاب", "رمل", "طعام", "اكل"}

_state = {"at": 0.0, "by_code": {}, "names": [], "pattern": None, "canon": {}}


def _norm(name):
    return re.sub(r"\s+", " ", str(name or "")).strip()


def _code(p):
    from observation_contract import gtin, sku_gtin
    return gtin(p.get("barcode")) or gtin(p.get("sku")) or sku_gtin(p.get("sku"))


def _canonical(name):
    try:
        from crawlers import canonical_brand
        return canonical_brand(name) or _norm(name)
    except Exception:  # noqa: BLE001
        return _norm(name)


def _usable(name):
    n = _norm(name)
    return len(n) >= 3 and n.casefold() not in _NOT_BRANDS and not n.isdigit()


async def refresh(db):
    """Rebuild from every product whose brand a store, a reviewer or the key
    brand rules gave."""
    votes, counts = defaultdict(Counter), Counter()
    async for p in db.products.find({"brand_source": {"$in": list(TRUSTED)}, "brand": {"$nin": [None, ""]}},
                                    {"_id": 0, "brand": 1, "brand_source": 1, "barcode": 1, "sku": 1}):
        if not _usable(p["brand"]):
            continue
        brand = _canonical(p["brand"])
        counts[brand] += 1
        code = _code(p)
        if code:
            votes[code][brand] += TRUSTED[p["brand_source"]]
    by_code = {code: c.most_common(1)[0][0] for code, c in votes.items()}
    install(by_code, [b for b, n in counts.items() if n >= 2])
    return {"barcodes": len(by_code), "names": len(_state["names"])}


def install(by_code, names):
    from key_brands import KEY_BRANDS
    try:
        from crawlers import CANONICAL_BRAND_MAP
        known = set(CANONICAL_BRAND_MAP.values())
    except Exception:  # noqa: BLE001
        known = set()
    pool = {_norm(n) for n in list(names) + list(known) + list(KEY_BRANDS) if _usable(n)}
    ordered = sorted(pool, key=len, reverse=True)       # "Royal Canin" before "Royal"
    parts = [r"(?<![\w؀-ۿ])" + re.escape(n).replace(r"\ ", r"\s*") + r"(?![\w؀-ۿ])" for n in ordered]
    _state.update(at=time.time(), by_code=dict(by_code), names=ordered,
                  canon={n.casefold().replace(" ", ""): n for n in ordered},
                  pattern=re.compile("|".join(parts), re.I) if parts else None)


async def ensure(db):
    if time.time() - _state["at"] > MAX_AGE_SECS:
        try:
            await refresh(db)
        except Exception:  # noqa: BLE001 — a lookup without the directory still answers
            import logging
            logging.getLogger(__name__).exception("[Brands] directory refresh failed")
            _state["at"] = time.time()


def brand_for(name_ar=None, name_en=None, codes=(), existing=None):
    from key_brands import brand_in_name
    key = brand_in_name(name_en, name_ar)
    if key:
        return key, "key_brand_name"
    from observation_contract import gtin, sku_gtin
    for c in codes or ():
        g = gtin(c) or sku_gtin(c)
        if g and g in _state["by_code"]:
            return _state["by_code"][g], "same_barcode"
    text = " ".join(str(x or "") for x in (name_en, name_ar))
    if _state["pattern"] is not None and text.strip():
        m = _state["pattern"].search(text)
        if m:
            found = m.group(0)
            return _state["canon"].get(found.casefold().replace(" ", ""), _norm(found)), "name"
    if existing and _usable(existing):
        return _canonical(existing), "store_tag"
    return None, None
