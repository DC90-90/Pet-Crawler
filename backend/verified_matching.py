"""Only observed offer identities can enter product_matches v2."""
from price_cohort import identity_agrees


async def match(db, own, snapshots=None, own_store_id=None):
    if snapshots is None:
        from matcher import _build_competitor_lookups
        if own_store_id is None:
            store = await db.stores.find_one({"is_own_store": True}, {"_id": 0, "id": 1}) or {}
            own_store_id = store.get("id")
        snapshots, _ = await _build_competitor_lookups(db, own_store_id)
    blocked = [r async for r in db.match_blacklist.find({"my_sku": own.get("sku")}, {"_id": 0})]
    confirmed = [r async for r in db.product_matches.find({"my_sku": own.get("sku"), "manually_confirmed": True, "identity_version": 2}, {"_id": 0})]
    out = []
    from matcher import _build_match
    for offer in snapshots:
        if offer.get("store_id") == own_store_id or offer.get("observation_version") != 2 or not offer.get("offer_id") or offer.get("is_synthetic"):
            continue
        if any(b.get("competitor_store_id") == offer["store_id"] and
               (b.get("competitor_offer_id") == offer["offer_id"] or b.get("competitor_sku") == offer.get("sku")) for b in blocked):
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