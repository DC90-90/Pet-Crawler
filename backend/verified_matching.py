"""Only observed offer identities can enter product_matches v2."""
from price_cohort import identity_agrees, reviewed_brand_map, apply_brand_review, exclusion
from datetime import datetime, timezone


async def prepare_candidates(db, snapshots, own_store_id=None):
    """One parent-aware eligibility policy for the batch guard and actual matching."""
    from parent_identity import index, annotate
    parents = await index(db)
    reviews = await reviewed_brand_map(db)
    now = datetime.now(timezone.utc)
    candidates = []
    for snapshot in snapshots:
        offer = annotate(apply_brand_review(snapshot, reviews), parents)
        if offer.get("store_id") != own_store_id and offer.get("offer_id") and exclusion(offer, now=now) is None:
            candidates.append(offer)
    return candidates


async def match(db, own, snapshots=None, own_store_id=None, *, candidates_prepared=False):
    if snapshots is None:
        from matcher import _build_competitor_lookups
        if own_store_id is None:
            store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1}) or {}
            own_store_id = store.get("id")
        snapshots, _ = await _build_competitor_lookups(db, own_store_id)
    blocked = [r async for r in db.match_blacklist.find({"my_sku": own.get("sku")}, {"_id": 0})]
    confirmed = [r async for r in db.product_matches.find({"my_sku": own.get("sku"), "manually_confirmed": True, "identity_version": 2}, {"_id": 0})]
    out = []
    if not candidates_prepared:
        snapshots = await prepare_candidates(db, snapshots, own_store_id)
    from matcher import _build_match
    for offer in snapshots:
        if any(b.get("competitor_store_id") == offer["store_id"] and
               (b.get("competitor_offer_id") == offer["offer_id"] if b.get("competitor_offer_id") else b.get("competitor_sku") == offer.get("sku")) for b in blocked):
            continue
        manual = any(c.get("competitor_store_id") == offer["store_id"] and c.get("competitor_offer_id") == offer["offer_id"] for c in confirmed)
        if not identity_agrees(own, offer, manual):
            continue
        row = _build_match(own, offer, offer, 100 if manual else 99, "manual" if manual else "barcode")
        row.update(competitor_offer_id=offer["offer_id"], competitor_listing_id=offer.get("listing_id"),
                   competitor_variant_id=offer.get("variant_id"), identity_version=2,
                   matched_barcode=offer.get("barcode"), manually_confirmed=manual,
                   match_evidence={"source": "specific_offer", "name": offer.get("name_ar"), "url": offer.get("product_url")})
        out.append(row)
    return out
