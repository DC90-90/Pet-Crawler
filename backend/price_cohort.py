"""Versioned, shared current-price cohort. Historical rows are labelled, never actionable."""
from datetime import datetime, timezone, timedelta
from observation_contract import gtin, money, stable_id, TRUSTED_PRICE_BASES
from pack_guard import slug_descriptor, stated_weight_grams, slug_pack_reject, cluster_outliers, discount_escapes

POLICY_VERSION = "offers-v2-current-7d"
FIELDS = {k: 1 for k in ("sku", "barcode", "store_id", "store_name", "offer_id", "listing_id", "variant_id", "name_ar", "name_en", "price", "currency", "price_basis", "in_stock", "qty_available", "product_url", "crawled_at", "observation_version", "confidence_score", "comparable", "is_synthetic", "present_on_store", "variant_skus", "variant_barcodes")}
FIELDS["_id"] = 0
FIELDS["brand"] = 1
FIELDS["brand_source"] = 1


def aware(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value if isinstance(value, datetime) else None


def identity_keys(row):
    return {k for k in (gtin(row.get("barcode")), gtin(row.get("sku"))) if k}


def identity_agrees(own, offer, manual=False):
    ours, theirs = identity_keys(own), identity_keys(offer)
    # Contradictory observed identifiers cannot be overruled by local SKU equality.
    if ours and theirs and not ours.intersection(theirs):
        return False
    if own.get("brand") and offer.get("brand") and own.get("brand_source") in ("store_supplied", "reviewed") and offer.get("brand_source") in ("store_supplied", "reviewed"):
        from crawlers import canonical_brand
        if canonical_brand(own["brand"]) != canonical_brand(offer["brand"]):
            return False
    name = f"{own.get('name_ar') or ''} {own.get('name_en') or ''}"
    descriptor = " ".join(str(offer.get(k) or "") for k in ("name_ar", "name_en")) + " " + slug_descriptor(offer.get("product_url"))
    reject, _ = slug_pack_reject(name, stated_weight_grams(name), descriptor)
    return not reject and (bool(ours & theirs) or manual)


def exclusion(row, now=None):
    now = now or datetime.now(timezone.utc)
    if row.get("is_synthetic") or row.get("data_origin") == "demo_seed":
        return "synthetic_observation"
    if row.get("observation_version") != 2 or row.get("comparable") is not True:
        return "legacy_or_unverified_offer"
    if row.get("currency") != "SAR" or row.get("price_basis") not in TRUSTED_PRICE_BASES:
        return "currency_or_tax_unverified"
    if not (money(row.get("price")) or 0) > 0:
        return "price_unavailable"
    ts = aware(row.get("crawled_at") or row.get("last_crawl_at"))
    if ts is None or ts > now + timedelta(minutes=5) or now - ts >= timedelta(days=7):
        return "stale_or_unknown_observation"
    if (row.get("confidence_score") or 0) < 85:
        return "low_source_confidence"
    if row.get("present_on_store") is False:
        return "hidden_listing"
    if row.get("in_stock") is not True:
        return "out_of_stock" if row.get("in_stock") is False else "stock_unknown"
    return None


def select_cohort(own, rows, own_price, *, now=None, history=()):
    now = now or datetime.now(timezone.utc)
    kept, excluded = [], []
    for source in rows:
        row = dict(source)
        reason = exclusion(row, now)
        if reason:
            excluded.append({**row, "eligible": False, "excluded_reason": reason})
        else:
            kept.append(row)
    outliers = cluster_outliers([(r["store_id"], r["price"]) for r in kept], own_price=own_price)
    for sid in discount_escapes(outliers, [(r["store_id"], r.get("price")) for r in history]):
        outliers.pop(sid, None)
    best = {}
    for row in kept:
        sid = row["store_id"]
        if sid in outliers:
            excluded.append({**row, "eligible": False, "excluded_reason": "below_corroborated_cluster"})
        elif sid not in best or row["price"] < best[sid]["price"]:
            best[sid] = {**row, "eligible": True, "is_own": False}
    rows = sorted(best.values(), key=lambda r: (r["price"], r["store_id"]))
    prices = [r["price"] for r in rows]
    return dict(sellers=rows, excluded=excluded, min=min(prices) if prices else None,
                max=max(prices) if prices else None, avg=round(sum(prices)/len(prices), 2) if prices else None,
                cohort_id=stable_id(POLICY_VERSION, [(r.get("offer_id"), str(r.get("crawled_at")), r["price"]) for r in rows]),
                policy_version=POLICY_VERSION, observed_at=max([aware(r["crawled_at"]) for r in rows], default=None),
                cutoff=(now-timedelta(days=7)).isoformat(), currency="SAR", stock_policy="in_stock_only")


async def build_cohorts(db, own_rows, own_store_id, own_price_fn, now=None):
    now = now or datetime.now(timezone.utc)
    own_by_sku = {r["sku"]: r for r in own_rows if r.get("sku")}
    by_key = {}
    for sku, row in own_by_sku.items():
        for key in identity_keys(row):
            by_key.setdefault(key, set()).add(sku)
    manual, blocked = set(), set()
    async for m in db.product_matches.find({"manually_confirmed": True, "identity_version": 2}, {"_id": 0}):
        manual.add((m.get("my_sku"), m.get("competitor_store_id"), m.get("competitor_offer_id")))
    async for m in db.match_blacklist.find({}, {"_id": 0}):
        blocked.add((m.get("my_sku"), m.get("competitor_store_id"), m.get("competitor_offer_id")))
    grouped, history = {}, {}
    # Latest offer first, BEFORE eligibility: an OOS reading must not resurrect an older in-stock price.
    seen = set()
    active = await db.stores.distinct("id", {"is_active": {"$ne": False}, "id": {"$ne": own_store_id}})
    cursor = db.product_snapshots.aggregate([
        {"$match": {"store_id": {"$in": active}, "crawled_at": {"$gte": now-timedelta(days=180)}}},
        {"$sort": {"crawled_at": -1}},
        {"$group": {"_id": {"$ifNull": ["$offer_id", {"store": "$store_id", "sku": "$sku"}]},
                    "latest": {"$first": "$$ROOT"},
                    "historical_max": {"$max": {"$cond": [{"$and": [{"$eq": ["$observation_version", 2]}, {"$eq": ["$comparable", True]}]}, "$price", None]}}}},
        {"$replaceRoot": {"newRoot": {"$mergeObjects": ["$latest", {"historical_max_price": "$historical_max"}]}}},
        {"$project": {**FIELDS, "historical_max_price": 1}},
    ], allowDiskUse=True).batch_size(2000)
    manual_by_offer = {}
    for sku, sid, oid in manual:
        manual_by_offer.setdefault((sid, oid), set()).add(sku)
    async for row in cursor:
        candidates = set(manual_by_offer.get((row["store_id"], row.get("offer_id")), ()))
        for key in identity_keys(row):
            candidates.update(by_key.get(key, ()))
        offer_key = (row["store_id"], row.get("offer_id") or row.get("sku"))
        for sku in candidates:
            own = own_by_sku.get(sku)
            scoped = (sku, row["store_id"], row.get("offer_id"))
            if own and scoped not in blocked and identity_agrees(own, row, scoped in manual):
                if row.get("observation_version") == 2:
                    history.setdefault(sku, []).append({**row, "price": row.get("historical_max_price") or row.get("price")})
                if offer_key not in seen:
                    grouped.setdefault(sku, []).append(row)
        seen.add(offer_key)
    return {sku: select_cohort(own, grouped.get(sku, []), own_price_fn(own), now=now,
                               history=history.get(sku, [])) for sku, own in own_by_sku.items()}