"""The client's key brands (21 Oct 2026): every item of these brands, in every
tracked store, recognised from the product name.

Most of these items carried no brand tag or a wrong one (Kit Cat 766 with no
brand, 53 tagged "Almo"; Farmina split into "N&D", "فارمينا" and "Farmina"),
and six of the brands were missing from the brand list, so brand views showed
a fraction of them. The name decides: a key brand written in the name wins
over any store-supplied tag.

brand_in_name(): the key brand a product name names, or None.
catalogue(): per brand, every item across stores, grouped by barcode, with
each store's latest price and stock and whether the own store sells it.
"""
import re
from datetime import datetime, timedelta, timezone

# Canonical name → patterns over Latin and Arabic spellings seen on the stores.
KEY_BRANDS = {
    "Carnilove": [r"carni\s*love", r"كارني\s*لوف", r"كارنيلوف"],
    "Life Cat": [r"life\s*cat", r"لايف\s*كات"],
    "Taste of the Wild": [r"taste\s*of\s*the\s*wild", r"تيست\s*[اأ]وف", r"طيست\s*[اأ]وف"],
    "Applaws": [r"applaws", r"[اأ]بلاوز", r"[اأ]بلوز"],
    "Schesir": [r"schesir", r"شيزير", r"شزير", r"شيزر", r"شيسير"],
    "GimCat": [r"gim\s*cat", r"gimborn", r"جيم\s*كات", r"جيمكات"],
    "Beso": [r"\bbeso\b", r"بيسو"],
    "Canvit": [r"canvit", r"كانفيت"],
    "Farmina": [r"farmina", r"\bn\s*&\s*d\b", r"فارمينا", r"[اإ]ن\s*[اآ]ند\s*دي"],
    "Intersand": [r"intersand", r"[اإ]نترساند"],
    "Kit Cat": [r"kit\s*cat\b", r"kitcat", r"كيت\s*كات"],
}
_RX = {b: re.compile("|".join(p), re.I) for b, p in KEY_BRANDS.items()}
# What the crawl types into a store's own search, per brand (crawlers.py
# brand sweep); results are kept only when the name names the brand.
SEARCH_TERMS = {
    "Carnilove": ["carnilove", "كارني لوف"], "Life Cat": ["life cat", "لايف كات"],
    "Taste of the Wild": ["taste of the wild", "تيست اوف ذا وايلد"], "Applaws": ["applaws", "ابلاوز"],
    "Schesir": ["schesir", "شيزير", "شيزر"], "GimCat": ["gimcat", "جيم كات"], "Beso": ["beso", "بيسو"],
    "Canvit": ["canvit", "كانفيت"], "Farmina": ["farmina", "فارمينا", "N&D"],
    "Intersand": ["intersand", "انترساند"], "Kit Cat": ["kit cat", "كيت كات"],
}
# A Mongo pre-filter: any key-brand spelling in either name.
MONGO_RX = "|".join(p for pats in KEY_BRANDS.values() for p in pats)
WINDOW_DAYS = 7


def brand_in_name(*names):
    text = " ".join(str(n or "") for n in names)
    if not text.strip():
        return None
    hits = [(m.start(), b) for b, rx in _RX.items() for m in [rx.search(text)] if m]
    # "Kit Cat" can sit inside another brand's name; the earliest mention is
    # the maker (brands lead the name on these stores).
    return min(hits)[1] if hits else None


def _group_key(row):
    from observation_contract import gtin
    for v in (row.get("barcode"), row.get("sku")):
        g = gtin(v)
        if g:
            return "gtin:" + g
    return "offer:" + str(row.get("offer_id"))


async def catalogue(db, own_price_fn=None, days=WINDOW_DAYS):
    from snapshot_reads import complete_latest, latest_pipeline
    from observation_contract import gtin
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stores = {s["id"]: s for s in await db.stores.find(
        {"is_active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1, "is_own_store": 1, "domain": 1}).to_list(200)}
    own_id = next((sid for sid, s in stores.items() if s.get("is_own_store")), None)
    proj = {k: 1 for k in ("sku", "barcode", "store_id", "store_name", "offer_id", "name_ar", "name_en", "price",
                           "original_price", "in_stock", "qty_available", "product_url", "image_url", "crawled_at")}
    name_rx = {"$regex": MONGO_RX, "$options": "i"}
    rows = []
    # One store at a time: each read stays inside the 10 s operation limit.
    for sid in stores:
        rows += await complete_latest(db, latest_pipeline(
            {"observation_version": 2, "is_synthetic": False, "store_id": sid, "crawled_at": {"$gte": since},
             "$or": [{"name_ar": name_rx}, {"name_en": name_rx}]}, proj))
    # The own catalogue: its live price and barcodes, so an item is marked
    # "you sell it" even when its own listing names the brand differently.
    own_codes = {}
    if own_id:
        # Whole records: the shelf-price rule reads sync time, basis and identity.
        async for p in db.products.find({"store_id": own_id}, {"_id": 0}):
            for v in (p.get("sku"), p.get("barcode")):
                g = gtin(v)
                if g:
                    own_codes[g] = p
    groups = {}
    for r in rows:
        brand = brand_in_name(r.get("name_en"), r.get("name_ar"))
        if not brand:
            continue
        key = _group_key(r)
        g = groups.setdefault(key, {"key": key, "brand": brand, "barcode": key[5:] if key.startswith("gtin:") else None,
                                    "name_ar": None, "name_en": None, "image_url": None, "offers": {}})
        g["name_ar"] = g["name_ar"] or r.get("name_ar")
        g["name_en"] = g["name_en"] or r.get("name_en")
        g["image_url"] = g["image_url"] or r.get("image_url")
        sid = r["store_id"]
        price = r.get("price")
        if sid == own_id and own_price_fn and g["barcode"] in own_codes:
            price = own_price_fn(own_codes[g["barcode"]]) or None   # the shelf price, VAT included
        prev = g["offers"].get(sid)
        if prev and str(prev["seen_at"]) >= str(r.get("crawled_at")):
            continue
        g["offers"][sid] = {"store_id": sid, "store_name": stores.get(sid, {}).get("name") or r.get("store_name"),
                            "own": sid == own_id, "price": price, "original_price": r.get("original_price"),
                            "in_stock": r.get("in_stock"), "qty": r.get("qty_available"),
                            "url": r.get("product_url"), "name": r.get("name_ar") or r.get("name_en"),
                            "seen_at": r.get("crawled_at")}
    items = []
    for g in groups.values():
        own_p = own_codes.get(g["barcode"]) if g["barcode"] else None
        if own_p and own_id not in g["offers"]:
            price = (own_price_fn(own_p) or None) if own_price_fn else own_p.get("price")
            g["offers"][own_id] = {"store_id": own_id, "store_name": stores[own_id]["name"], "own": True, "price": price,
                                   "in_stock": own_p.get("in_stock"), "url": own_p.get("product_url"),
                                   "name": own_p.get("name_ar") or own_p.get("name_en"), "seen_at": None}
        offers = sorted(g.pop("offers").values(), key=lambda o: (o["price"] is None, o["price"] or 0))
        comp = [o for o in offers if not o["own"]]
        live = [o for o in comp if o["in_stock"] and o["price"]]
        mine = next((o for o in offers if o["own"]), None)
        cheapest = min(live, key=lambda o: o["price"]) if live else None
        items.append({**g, "offers": offers, "stores": len(offers), "competitors": len(comp),
                      "competitors_in_stock": len(live), "own_sells": bool(mine), "own_price": mine and mine["price"],
                      "own_in_stock": mine and mine["in_stock"],
                      "cheapest_price": cheapest and cheapest["price"], "cheapest_store": cheapest and cheapest["store_name"],
                      "own_vs_cheapest_pct": round((mine["price"] - cheapest["price"]) / cheapest["price"] * 100, 1)
                      if mine and mine["price"] and cheapest else None})
    items.sort(key=lambda i: (i["brand"], -i["stores"], i["name_ar"] or i["name_en"] or ""))
    brands = []
    for b in KEY_BRANDS:
        its = [i for i in items if i["brand"] == b]
        per_store = {}
        for i in its:
            for o in i["offers"]:
                per_store[o["store_name"]] = per_store.get(o["store_name"], 0) + 1
        brands.append({"brand": b, "items": len(its), "own_sells": sum(i["own_sells"] for i in its),
                       "not_sold_by_me": sum(not i["own_sells"] for i in its),
                       "me_cheapest": sum(1 for i in its if i["own_vs_cheapest_pct"] is not None and i["own_vs_cheapest_pct"] <= 0),
                       "me_dearer": sum(1 for i in its if (i["own_vs_cheapest_pct"] or 0) > 0),
                       "per_store": dict(sorted(per_store.items(), key=lambda kv: -kv[1]))})
    return {"brands": brands, "items": items, "window_days": days, "stores": len(stores),
            "computed_at": datetime.now(timezone.utc).isoformat()}


async def tag_products(db, delay_secs=0):
    """Backfill: label every stored product whose name names a key brand with
    that brand (never over a reviewed label). Per store and brand, so each
    write stays inside the operation limit; safe to run again."""
    import asyncio
    import logging
    log = logging.getLogger(__name__)
    await asyncio.sleep(delay_secs)
    changed = 0
    try:
        for sid in await db.stores.distinct("id"):
            for brand, pats in KEY_BRANDS.items():
                rx = {"$regex": "|".join(pats), "$options": "i"}
                res = await db.products.update_many(
                    {"store_id": sid, "brand_source": {"$ne": "reviewed"}, "brand": {"$ne": brand},
                     "$or": [{"name_ar": rx}, {"name_en": rx}]},
                    {"$set": {"brand": brand, "brand_source": "key_brand_name"}})
                changed += res.modified_count
    except Exception:
        log.exception("[KeyBrands] tagging stopped after %d products", changed)
    log.info("[KeyBrands] tagged %d products with their key brand", changed)
    return changed
