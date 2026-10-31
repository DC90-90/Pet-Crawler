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
    from observation_contract import gtin, sku_gtin
    for v in (row.get("barcode"), row.get("sku")):
        g = gtin(v) or sku_gtin(v)
        if g:
            return "gtin:" + g
    return "offer:" + str(row.get("offer_id"))


async def _own_matches(db, own_price_fn, own_id):
    """{competitor offer_id: own sku} from the comparison cohorts My Products
    and Pricing use; empty (barcode joins only) if they cannot be built."""
    if not own_id or own_price_fn is None:
        return {}
    import logging
    try:
        from comparison_views import context
        _, _, cohorts = await context(db, own_price_fn)
    except Exception:  # noqa: BLE001 — the page still shows, joined by barcode
        logging.getLogger(__name__).exception("[KeyBrands] own matches unavailable")
        return {}
    out = {}
    for sku, c in cohorts.items():
        for r in (c.get("sellers") or []) + (c.get("excluded") or []):
            if r.get("offer_id") and r.get("store_id") != own_id:
                out.setdefault(r["offer_id"], sku)
    return out


async def catalogue(db, own_price_fn=None, days=WINDOW_DAYS):
    from snapshot_reads import complete_latest, latest_pipeline
    from observation_contract import gtin
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stores = {s["id"]: s for s in await db.stores.find(
        {"is_active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1, "is_own_store": 1, "domain": 1}).to_list(200)}
    own_id = next((sid for sid, s in stores.items() if s.get("is_own_store")), None)
    proj = {k: 1 for k in ("sku", "barcode", "store_id", "store_name", "offer_id", "name_ar", "name_en", "brand", "price",
                           "original_price", "in_stock", "qty_available", "product_url", "image_url", "crawled_at")}
    name_rx = {"$regex": MONGO_RX, "$options": "i"}
    latest = {}
    # One store and one day at a time: each read stays inside the 10 s
    # operation limit. A whole week of one store's snapshots passed it once
    # the key-brand sweep grew the stores' listings, and the page kept
    # serving its 29 Oct copy (31 Oct 2026).
    for sid in stores:
        if sid == own_id:
            continue
        end = datetime.now(timezone.utc)
        while end > since:
            start = max(since, end - timedelta(days=1))
            for r in await complete_latest(db, latest_pipeline(
                    {"observation_version": 2, "is_synthetic": False, "store_id": sid,
                     "crawled_at": {"$gte": start, "$lt": end},
                     "$or": [{"name_ar": name_rx}, {"name_en": name_rx}, {"brand": name_rx}]}, proj)):
                prev = latest.get((sid, r.get("offer_id")))
                if prev is None or str(prev.get("crawled_at")) < str(r.get("crawled_at")):
                    latest[(sid, r.get("offer_id"))] = r
            end = start
    rows = list(latest.values())
    # The own catalogue (the My Products records), read first: its products
    # are the rows competitors' offers join.
    own_products, own_key = [], {}
    if own_id:
        async for p in db.my_products.find({}, {"_id": 0}):
            if p.get("superseded_parent") or not p.get("sku"):
                continue
            code = next((c for c in (gtin(p.get("barcode")), gtin(p.get("sku"))) if c), None)
            own_products.append((p, code))
            own_key[p["sku"]] = "gtin:" + code if code else "own:" + str(p["sku"])
    # Which own product each competitor offer is: the same matching My
    # Products uses (barcode, then name, size and pack). Zarafa and others
    # often publish no barcode, so a barcode-only join showed products the
    # client sells as "not sold by me" (27 Oct 2026).
    matched = await _own_matches(db, own_price_fn, own_id)
    groups = {}
    for r in rows:
        sid = r["store_id"]
        if sid == own_id:
            continue                      # the own offer comes from the own catalogue below
        # The name first; else the brand the store files it under.
        brand = brand_in_name(r.get("name_en"), r.get("name_ar")) or brand_in_name(r.get("brand"))
        if not brand:
            continue
        own_sku = matched.get(r.get("offer_id"))
        key = own_key.get(own_sku) or _group_key(r)
        g = groups.setdefault(key, {"key": key, "brand": brand, "barcode": key[5:] if key.startswith("gtin:") else None,
                                    "name_ar": None, "name_en": None, "image_url": None, "offers": {}})
        g["name_ar"] = g["name_ar"] or r.get("name_ar")
        g["name_en"] = g["name_en"] or r.get("name_en")
        g["image_url"] = g["image_url"] or r.get("image_url")
        prev = g["offers"].get(sid)
        if prev and str(prev["seen_at"]) >= str(r.get("crawled_at")):
            continue
        g["offers"][sid] = {"store_id": sid, "store_name": stores.get(sid, {}).get("name") or r.get("store_name"),
                            "own": False, "price": r.get("price"), "original_price": r.get("original_price"),
                            "in_stock": r.get("in_stock"), "qty": r.get("qty_available"),
                            "url": r.get("product_url"), "name": r.get("name_ar") or r.get("name_en"),
                            "seen_at": r.get("crawled_at")}
    # Own offers: the same shelf price and stock as every other page. An own
    # key-brand product nobody else sells is listed too.
    if own_id:
        from stock_evidence import own_stock
        for p, code in own_products:
            key = own_key[p["sku"]]
            brand = brand_in_name(p.get("name_en"), p.get("name_ar"))
            if key not in groups:
                if not brand:
                    continue
                groups[key] = {"key": key, "brand": brand, "barcode": code, "name_ar": p.get("name_ar"),
                               "name_en": p.get("name_en"), "image_url": p.get("image_url"), "offers": {}}
            g = groups[key]
            g["name_ar"] = p.get("name_ar") or g["name_ar"]          # my own name leads the row
            g["name_en"] = p.get("name_en") or g["name_en"]
            g["image_url"] = p.get("image_url") or g["image_url"]
            g["barcode"] = g["barcode"] or code
            g["offers"][own_id] = {"store_id": own_id, "store_name": stores[own_id]["name"], "own": True,
                                   "price": (own_price_fn(p) or None) if own_price_fn else p.get("price"),
                                   "in_stock": own_stock(p)["in_stock"], "qty": own_stock(p)["quantity"],
                                   "url": p.get("product_url"), "name": p.get("name_ar") or p.get("name_en"),
                                   "sku": p.get("sku"), "seen_at": p.get("last_synced_at")}
    items = []
    for g in groups.values():
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


# ── Coverage check (21 Oct 2026) ──────────────────────────────────────────
# Asks every store itself which key-brand items it lists, then checks each
# one is in Daleel with a reading from the last WINDOW_DAYS days. Salla: the
# store's own brand pages plus its search (names checked). Zid: the store's
# full public product list, kept when the name or the store's brand tag
# names a key brand. Runs on the server, one request at a time.
AUDIT_PAUSE = (1.0, 2.0)


def _raw_name(raw):
    n = raw.get("name") or raw.get("title") or ""
    return " ".join(str(v) for v in n.values()) if isinstance(n, dict) else str(n)


def _raw_brand(raw):
    b = raw.get("brand")
    if isinstance(b, dict):
        b = b.get("name")
        if isinstance(b, dict):
            b = " ".join(str(v) for v in b.values())
    return str(b or "")


def _raw_url(raw):
    u = raw.get("url") or raw.get("html_url") or raw.get("product_url")
    if isinstance(raw.get("urls"), dict):
        u = raw["urls"].get("customer") or u
    return u if isinstance(u, str) else None


def _raw_price(raw):
    p = raw.get("price")
    return p.get("amount") if isinstance(p, dict) else p


async def _store_listing_salla(client, store):
    import asyncio
    import random
    from fetch_policy import polite_get
    sid = store.get("salla_store_identifier")
    if not sid:
        return None, "no store identifier yet"
    base = f"https://{store['domain']}"
    headers = {"Accept": "application/json, text/plain, */*", "Accept-Language": "ar", "x-requested-with": "XMLHttpRequest",
               "Referer": base + "/", "Origin": base, "store-identifier": str(sid)}
    api = "https://api.salla.dev/store/v1"
    found, note = {}, []
    brands, page = [], 1
    while page <= 20:
        r = await polite_get(client, f"{api}/brands", params={"page": page}, headers=headers)
        if r is None or r.status_code != 200:
            break
        body = r.json()
        rows = [b for b in (body.get("data") or []) if isinstance(b, dict)]
        brands += rows
        if not rows or not (body.get("cursor") or {}).get("next"):
            break
        page += 1
        await asyncio.sleep(random.uniform(*AUDIT_PAUSE))
    jobs = [(brand_in_name(b.get("name"), b.get("label")), {"source": "brands", "source_value[]": b["id"], "limit": 50}, False)
            for b in brands if b.get("id") is not None and brand_in_name(b.get("name"), b.get("label"))]
    note.append(f"{len(jobs)} brand pages")
    jobs += [(brand, {"source": "search", "source_value": t, "limit": 50}, True)
             for brand, terms in SEARCH_TERMS.items() for t in terms]
    for brand, params, check_name in jobs:
        url, pages = f"{api}/products", 0
        while url and pages < (6 if check_name else 40):
            r = await polite_get(client, url, params=params, headers=headers)
            if r is None or r.status_code != 200:
                note.append(f"{brand}: http {getattr(r, 'status_code', 'none')}")
                break
            body = r.json()
            pages += 1
            for it in body.get("data") or []:
                if not isinstance(it, dict) or it.get("id") is None:
                    continue
                if check_name and brand_in_name(_raw_name(it)) != brand:
                    continue
                found.setdefault(str(it["id"]), {"brand": brand, "name": _raw_name(it), "url": _raw_url(it),
                                                 "price": _raw_price(it)})
            url, params = (body.get("cursor") or {}).get("next"), None
            await asyncio.sleep(random.uniform(*AUDIT_PAUSE))
    return found, "; ".join(note)


async def _store_listing_zid(client, store):
    import asyncio
    import random
    from fetch_policy import polite_get
    base = f"https://{store['domain']}/api/v1/products"
    found, page, total = {}, 1, 0
    while page <= 400:
        r = await polite_get(client, base, params={"page": page}, headers={"Accept": "application/json"})
        if r is None or r.status_code != 200:
            return found, f"stopped at page {page}: http {getattr(r, 'status_code', 'none')} after {total} listings"
        body = r.json()
        rows = (body.get("results") or body.get("data") or body.get("products") or []) if isinstance(body, dict) else []
        if not rows:
            break
        total += len(rows)
        for it in rows:
            if not isinstance(it, dict) or it.get("id") is None:
                continue
            brand = brand_in_name(_raw_name(it)) or brand_in_name(_raw_brand(it))
            if brand:
                found[str(it["id"])] = {"brand": brand, "name": _raw_name(it), "url": _raw_url(it),
                                        "price": _raw_price(it)}
        if "next" in body and not body.get("next"):
            break
        page += 1
        await asyncio.sleep(random.uniform(*AUDIT_PAUSE))
    return found, f"{total} listings read"


async def _in_daleel(db, store_id, ids, since):
    """The store's listing ids Daleel read this week, and those it ever held."""
    seen, known = set(), set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        seen |= {str(x) for x in await db.product_snapshots.distinct(
            "listing_id", {"store_id": store_id, "crawled_at": {"$gte": since}, "listing_id": {"$in": chunk}})}
        known |= {str(x) for x in await db.products.distinct(
            "listing_id", {"store_id": store_id, "listing_id": {"$in": chunk}})}
    return seen, known


def coverage_row(listed, seen, known):
    per = {}
    for lid, it in listed.items():
        b = per.setdefault(it["brand"], {"store_lists": 0, "in_daleel": 0, "missing": []})
        b["store_lists"] += 1
        if lid in seen:
            b["in_daleel"] += 1
        else:
            b["missing"].append({**it, "listing_id": lid,
                                 "why": "seen before, not this week" if lid in known else "never collected"})
    return {"store_lists": len(listed), "in_daleel": sum(b["in_daleel"] for b in per.values()),
            "brands": dict(sorted(per.items()))}


async def audit(db, days=WINDOW_DAYS):
    """Per store and brand: what the store lists, what Daleel holds this week,
    and every missing item by name and link. Stored in key_brand_audits."""
    import httpx
    started = datetime.now(timezone.utc)
    since = started - timedelta(days=days)
    stores = await db.stores.find({"is_active": {"$ne": False}, "is_own_store": {"$ne": True}}, {"_id": 0}).to_list(100)
    report = {"started_at": started, "status": "running", "stores": []}
    run_id = (await db.key_brand_audits.insert_one(dict(report))).inserted_id
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for store in sorted(stores, key=lambda s: s.get("name") or ""):
            row = {"store_id": store["id"], "store": store.get("name"), "platform": store.get("platform")}
            try:
                if store.get("platform") == "salla":
                    listed, note = await _store_listing_salla(client, store)
                elif store.get("platform") == "zid":
                    listed, note = await _store_listing_zid(client, store)
                else:
                    listed, note = None, "platform not checked"
                if listed is not None:
                    seen, known = await _in_daleel(db, store["id"], list(listed), since)
                    row.update(checked=True, **coverage_row(listed, seen, known))
                else:
                    row["checked"] = False
            except Exception as exc:  # noqa: BLE001 — one store's failure is reported, not fatal
                note, row["checked"] = f"error: {type(exc).__name__}: {str(exc)[:120]}", False
            row["note"] = note
            report["stores"].append(row)
            await db.key_brand_audits.update_one({"_id": run_id}, {"$set": {"stores": report["stores"]}})
    checked = [s for s in report["stores"] if s.get("checked")]
    report.update(status="done", finished_at=datetime.now(timezone.utc),
                  store_lists=sum(s["store_lists"] for s in checked), in_daleel=sum(s["in_daleel"] for s in checked))
    await db.key_brand_audits.update_one({"_id": run_id}, {"$set": report})
    return report


async def latest_audit(db):
    doc = await db.key_brand_audits.find_one({}, {"_id": 0}, sort=[("started_at", -1)])
    return doc or {"status": "never_run"}
