"""Versioned, shared current-price cohort. Historical rows are labelled, never actionable."""
from datetime import datetime, timezone, timedelta
from observation_contract import gtin, money, stable_id, TRUSTED_PRICE_BASES
from pack_guard import slug_descriptor, stated_weight_grams, slug_pack_reject, cluster_outliers, discount_escapes
from price_read_limits import query_max_ms, bounded_read
from cohort_reads import read_cohort_snapshots

POLICY_VERSION = "offers-v3-parent-aware-current-7d"
FIELDS = {k: 1 for k in ("sku", "barcode", "store_id", "store_name", "offer_id", "listing_id", "variant_id", "name_ar", "name_en", "price", "currency", "price_basis", "in_stock", "qty_available", "product_url", "crawled_at", "observation_version", "confidence_score", "comparable", "is_synthetic", "present_on_store", "variant_skus", "variant_barcodes")}
FIELDS["_id"] = 0
FIELDS["brand"] = 1
FIELDS["brand_source"] = 1
FIELDS["data_origin"] = 1


def max_offer_age_days():
    import os
    try:
        return max(1, int(os.environ.get("MAX_OFFER_AGE_DAYS", "14")))
    except ValueError:
        return 14


def aware(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value if isinstance(value, datetime) else None


def identity_keys(row):
    # An explicit GTIN is stronger evidence than a merchant's numeric local SKU.
    code = gtin(row.get('barcode')) or gtin(row.get('sku'))
    return {code} if code else set()


async def reviewed_brand_map(db):
    return {(p.get('store_id'), p['offer_id']): p.get('brand') async for p in db.products.find(
        {'brand_source': 'reviewed', 'offer_id': {'$type': 'string'}},
        {'_id': 0, 'store_id': 1, 'offer_id': 1, 'brand': 1})}


def apply_brand_review(offer, reviews):
    key = (offer.get('store_id'), offer.get('offer_id'))
    return {**offer, 'brand': reviews[key], 'brand_source': 'reviewed'} if key in reviews else offer


def identity_agrees(own, offer, manual=False):
    ours, theirs = identity_keys(own), identity_keys(offer)
    # Contradictory observed identifiers cannot be overruled by local SKU equality.
    if ours and theirs and not ours.intersection(theirs):
        return False
    # A human confirmation outranks the name/brand heuristics below; only a
    # contradictory observed GTIN (above) can still refuse it.
    if manual:
        return True
    if own.get("brand") and offer.get("brand") and own.get("brand_source") in ("store_supplied", "reviewed") and offer.get("brand_source") in ("store_supplied", "reviewed"):
        from crawlers import canonical_brand
        if canonical_brand(own["brand"]) != canonical_brand(offer["brand"]):
            return False
    name = f"{own.get('name_ar') or ''} {own.get('name_en') or ''}"
    observed_name = " ".join(str(offer.get(k) or "") for k in ("name_ar", "name_en"))
    # A reused EAN is not proof that a named carton is the same as a single.
    # Use source names here (not lossy URL slugs); unresolved packs stay out.
    # Kept on _pack_compatible deliberately: an explicit-both-sides-only rule
    # lets "24 Pieces*400g" match a silent "400g" (test_pack_count_guard Beso
    # fixtures); slug_pack_reject below already applies the explicit-both-sides
    # rule on the slug axis.
    from matcher import _pack_compatible
    if name.strip() and observed_name.strip() and not _pack_compatible(name, observed_name):
        return False
    descriptor = " ".join(str(offer.get(k) or "") for k in ("name_ar", "name_en")) + " " + slug_descriptor(offer.get("product_url"))
    reject, _ = slug_pack_reject(name, stated_weight_grams(name), descriptor)
    return not reject and (bool(ours & theirs) or manual)


def exclusion(row, now=None):
    now = now or datetime.now(timezone.utc)
    if row.get("superseded_parent"):
        return "parent_listing_not_an_offer"
    if row.get("is_synthetic") or row.get("data_origin") == "demo_seed":
        return "synthetic_observation"
    if row.get("observation_version") != 2 or row.get("comparable") is not True:
        return "legacy_or_unverified_offer"
    if row.get("currency") != "SAR" or row.get("price_basis") not in TRUSTED_PRICE_BASES:
        return "currency_or_tax_unverified"
    if not (money(row.get("price")) or 0) > 0:
        return "price_unavailable"
    ts = aware(row.get("crawled_at") or row.get("last_crawl_at"))
    if ts is None or ts > now + timedelta(minutes=5) or now - ts >= timedelta(days=max_offer_age_days()):
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
                cutoff=(now-timedelta(days=max_offer_age_days())).isoformat(), currency="SAR", stock_policy="in_stock_only")


def cohort_history_days():
    """How far back the cohort read looks for discount corroboration and the
    historical maximum price. 180 days scanned ~1M production snapshots per
    request; 90 keeps a full quarter of history at half the cost."""
    import os
    try:
        return max(max_offer_age_days() + 1, int(os.environ.get("COHORT_HISTORY_DAYS", "90")))
    except ValueError:
        return 90


def snapshot_pipeline(active, now):
    # Keep the discount corroboration/excluded-seller history window.
    # Project BEFORE $$ROOT grouping so unused crawl payloads cannot fill it.
    # Latest selection still precedes all identity/stock/eligibility filtering.
    return [
        {"$match": {"store_id": {"$in": active}, "crawled_at": {"$gte": now-timedelta(days=cohort_history_days())}}},
        {"$sort": {"crawled_at": -1}},
        {"$project": FIELDS},
        {"$group": {"_id": {"$ifNull": ["$offer_id", {"store": "$store_id", "sku": "$sku"}]},
                    "latest": {"$first": "$$ROOT"}, "history_oldest_at": {"$min": "$crawled_at"},
                    "historical_max": {"$max": {"$cond": [{"$and": [
                        {"$eq": ["$observation_version", 2]}, {"$eq": ["$comparable", True]},
                        {"$not": [{"$ifNull": ["$is_synthetic", False]}]},
                        {"$ne": [{"$ifNull": ["$data_origin", ""]}, "demo_seed"]}
                    ]}, "$price", None]}}}},
        {"$replaceRoot": {"newRoot": {"$mergeObjects": ["$latest", {"historical_max_price": "$historical_max", "history_oldest_at": "$history_oldest_at"}]}}},
        {"$project": {**FIELDS, "historical_max_price": 1, "history_oldest_at": 1}},
    ]


def freshness_transition(value, now):
    ts = aware(value)
    if ts is not None:
        if ts > now+timedelta(minutes=5):
            return ts-timedelta(minutes=5)
        if ts+timedelta(days=max_offer_age_days()) > now:
            return ts+timedelta(days=max_offer_age_days())
    return now+timedelta(days=max_offer_age_days())  # Already-stale/missing dates do not become fresh.


import copy as _copy
import hashlib as _hashlib
import time as _time

# One cohort build per data revision. A cache rebuild used to run the same
# 90-day snapshot scan once per time window and again for every cached page
# (10+ full passes over 8.45M production snapshots); the cohort depends only
# on the observations, the own catalogue and the competitor scope, so it is
# computed once and reused while the revision is unchanged.
COHORT_MEMO_TTL_SECONDS = 900
_cohort_memo = {}
_cohort_inflight = {}


def _own_signature(own_rows, own_price_fn):
    h = _hashlib.sha256()
    for r in sorted(own_rows, key=lambda r: str(r.get("sku") or "")):
        h.update(f"{r.get('sku')}|{r.get('barcode')}|{own_price_fn(r) if own_price_fn else ''}|{r.get('present_on_store')}|{r.get('quantity_observed_at') or r.get('last_synced_at')}".encode("utf-8", "replace"))
    return h.hexdigest()


async def _data_revision(db):
    doc = await db.data_versions.find_one({"_id": "observations"}, {"_id": 0, "revision": 1})
    return (doc or {}).get("revision", 0)


def reset_cohort_memo():
    _cohort_memo.clear()
    _cohort_inflight.clear()


async def build_cohorts(db, own_rows, own_store_id, own_price_fn, now=None, competitor_store_ids=None, parents=None):
    import asyncio
    raw = getattr(db, "raw", db)
    revision = await _data_revision(db)
    key = (id(raw.client), raw.name, revision, own_store_id,
           tuple(sorted(competitor_store_ids)) if competitor_store_ids is not None else None,
           _own_signature(own_rows, own_price_fn))
    hit = _cohort_memo.get(key)
    if hit and hit[1] > _time.monotonic():
        return _copy.deepcopy(hit[0])
    if key in _cohort_inflight:
        result = await asyncio.shield(_cohort_inflight[key])
        return _copy.deepcopy(result)

    async def compute():
        result = await bounded_read(_build_cohorts(db, own_rows, own_store_id, own_price_fn, now,
                                                  competitor_store_ids, parents))
        if await _data_revision(db) == revision:
            if len(_cohort_memo) >= 8:
                _cohort_memo.pop(next(iter(_cohort_memo)))
            _cohort_memo[key] = (result, _time.monotonic() + COHORT_MEMO_TTL_SECONDS)
        return result

    task = asyncio.create_task(compute())
    _cohort_inflight[key] = task
    try:
        result = await asyncio.shield(task)
    finally:
        if _cohort_inflight.get(key) is task:
            _cohort_inflight.pop(key, None)
    return _copy.deepcopy(result)


async def _build_cohorts(db, own_rows, own_store_id, own_price_fn, now, competitor_store_ids, parents):
    now = now or datetime.now(timezone.utc)
    own_by_sku = {r["sku"]: r for r in own_rows if r.get("sku")}
    by_key = {}
    for sku, row in own_by_sku.items():
        for key in identity_keys(row):
            by_key.setdefault(key, set()).add(sku)
    manual, blocked = set(), set()
    async for m in db.product_matches.find({"manually_confirmed": True, "identity_version": 2}, {"_id": 0}):
        manual.add((m.get("my_sku"), m.get("competitor_store_id"), m.get("competitor_offer_id")))
    blocked_by_sku = set()
    async for m in db.match_blacklist.find({}, {"_id": 0}):
        if m.get("competitor_offer_id"):
            blocked.add((m.get("my_sku"), m.get("competitor_store_id"), m.get("competitor_offer_id")))
        else:
            # Rejections recorded before offer ids existed are keyed by the
            # competitor SKU; honour them the same way verified_matching does.
            blocked_by_sku.add((m.get("my_sku"), m.get("competitor_store_id"), m.get("competitor_sku")))
    grouped, history = {}, {}
    reviewed = await reviewed_brand_map(db)
    from parent_identity import index, annotate
    parents = parents if parents is not None else await index(db)
    # Latest offer first, BEFORE eligibility: an OOS reading must not resurrect an older in-stock price.
    seen = set()
    active = await db.stores.distinct("id", {"is_active": {"$ne": False}, "id": {"$ne": own_store_id}})
    if competitor_store_ids is not None:
        active = [sid for sid in active if sid in competitor_store_ids]
    rows = await read_cohort_snapshots(db, active, now, snapshot_pipeline,
                                      max_time_ms=query_max_ms())
    valid_until = min([freshness_transition(stamp, now) for r in own_rows
                       for stamp in (r.get("last_synced_at"), r.get("quantity_observed_at") or r.get("last_synced_at"))],
                      default=now+timedelta(days=max_offer_age_days()))
    manual_by_offer = {}
    for sku, sid, oid in manual:
        manual_by_offer.setdefault((sid, oid), set()).add(sku)
    for row in rows:
        oldest = aware(row.pop("history_oldest_at", None))
        valid_until = min(valid_until, freshness_transition(row.get("crawled_at"), now),
                          oldest+timedelta(days=cohort_history_days()) if oldest else valid_until)
        row = annotate(apply_brand_review(row, reviewed), parents)
        candidates = set(manual_by_offer.get((row["store_id"], row.get("offer_id")), ()))
        for key in identity_keys(row):
            candidates.update(by_key.get(key, ()))
        offer_key = (row["store_id"], row.get("offer_id") or row.get("sku"))
        for sku in candidates:
            own = own_by_sku.get(sku)
            scoped = (sku, row["store_id"], row.get("offer_id"))
            legacy_block = (sku, row["store_id"], row.get("sku")) in blocked_by_sku
            if own and scoped not in blocked and not legacy_block and identity_agrees(own, row, scoped in manual):
                if (row.get("observation_version") == 2 and not row.get("is_synthetic")
                        and row.get("data_origin") != "demo_seed"):
                    history.setdefault(sku, []).append({**row, "price": row.get("historical_max_price") or row.get("price")})
                if offer_key not in seen:
                    grouped.setdefault(sku, []).append(row)
        seen.add(offer_key)
    return {sku: {**select_cohort(own, grouped.get(sku, []), own_price_fn(own), now=now,
                               history=history.get(sku, [])), "valid_until": valid_until}
            for sku, own in own_by_sku.items()}
