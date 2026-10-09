"""Persistent parent identity quarantine and explicit recovery for valid child offers."""
from observation_contract import stable_id, unresolved_identity
from stock_evidence import retained_history


async def quarantine(db, store, row, reason, observed_at):
    sku = str(row.get("sku") or "").strip()
    listing = str(row.get("listing_id") or row.get("_listing_id") or row.get("_zid_id") or row.get("id") or sku)
    parent = "parent" in reason
    if parent:
        from parent_identity import remember
        await remember(db, store["id"], {**row, "listing_id": listing}, observed_at, reason)
    await db.observation_quarantine.update_one({"event_id": stable_id(store["id"], observed_at.isoformat(), row, reason)},
        {"$setOnInsert": {"store_id": store["id"], "sku": sku, "listing_id": listing,
                         "observed_at": observed_at, "data_origin": "own_sync",
                         "quarantine_reasons": [reason], "raw_offer": row}}, upsert=True)
    previous = await db.my_products.find_one({"sku": sku}, {"_id": 0})
    if previous:
        fields = {**retained_history(previous), "price": None, "sale_price": None, "quantity": None,
                  "in_stock": None, "price_basis": "quarantined", "price_unavailable_reason": reason,
                  "quarantine_active": True, "quarantined_at": observed_at.isoformat(), "listing_id": listing}
        if parent:
            fields.update(known_variant_parent=True, variant_id="root")
        await db.my_products.update_one({"sku": sku}, {"$set": fields})


async def filter_own_rows(db, store, rows, source, observed_at, normalizer):
    from collections import Counter
    from parent_identity import register_rows, index, is_parent
    await register_rows(db, store["id"], rows, observed_at)
    parents = await index(db)
    counts = Counter(str(r.get("sku") or "").strip() for r in rows)
    accepted, quarantined, roots = [], 0, set()
    for row in rows:
        if row.get("_parent_sku") and row["_parent_sku"] != row.get("sku"):
            parent_key = (row["_parent_sku"], row.get("_listing_id") or row.get("listing_id"))
            if parent_key not in roots:
                roots.add(parent_key)
                await quarantine(db, store, {"sku": parent_key[0], "listing_id": parent_key[1]}, "parent_listing_has_child_offers", observed_at)
        sku = str(row.get("sku") or "").strip()
        previous = await db.my_products.find_one({"sku": sku}, {"_id": 0, "known_variant_parent": 1}) or {}
        reason = "unresolved_parent_variants" if is_parent(row, parents, store["id"]) or (previous.get("known_variant_parent") and not row.get("_resolved_child")) else "ambiguous_own_sku" if counts[sku] > 1 else None
        if source == "public_crawl" and not reason:
            contract = normalizer(row, store["name"])
            if not contract.get("comparable"):
                reason = ",".join(contract.get("quarantine_reasons") or ["invalid_own_offer"])
        if reason:
            quarantined += 1
            await quarantine(db, store, row, reason, observed_at)
        else:
            accepted.append(row)
    return accepted, quarantined