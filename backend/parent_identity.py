"""Monotonic listing identity, independent of catalogue materialization.

Current-view annotations never edit historical offers or observation timestamps.
"""
from observation_contract import stable_id, unresolved_identity


def listing_id(row):
    return str(row.get("_listing_id") or row.get("listing_id") or row.get("_zid_id") or row.get("zid_id") or row.get("id") or row.get("sku") or "")


def is_child(row):
    return str(row.get("_variant_id") or row.get("variant_id") or "root") != "root"


async def remember(db, store_id, row, observed_at, reason):
    listing = listing_id(row)
    if not listing:
        return
    parent_sku = row.get("_parent_sku") if is_child(row) else row.get("sku")
    update = {"$setOnInsert": {"store_id": store_id, "listing_id": listing, "known_variant_parent": True},
              "$min": {"first_observed_at": observed_at}, "$max": {"last_observed_at": observed_at},
              "$addToSet": {"reasons": reason}}
    if parent_sku:
        update["$addToSet"]["parent_skus"] = str(parent_sku)
    await db.listing_identities.update_one({"_id": stable_id(store_id, listing)}, update, upsert=True)


async def register_rows(db, store_id, rows, observed_at):
    # First pass: even a root preceding its children in one batch is unavailable.
    for row in rows:
        if is_child(row) or unresolved_identity(row):
            await remember(db, store_id, row, observed_at,
                           "resolved_children" if is_child(row) else "unresolved_parent_variants")


async def index(db):
    listings, skus = set(), set()
    async for r in db.listing_identities.find({}, {"_id": 0}):
        listings.add((r["store_id"], r["listing_id"]))
        skus.update((r["store_id"], s) for s in r.get("parent_skus", []))
    # Read-through protection for pre-registry evidence; no migration/backfill.
    async for r in db.products.find({"variant_id": {"$exists": True, "$nin": [None, "root", ""]}},
                                   {"_id": 0, "store_id": 1, "listing_id": 1}):
        if r.get("listing_id"):
            listings.add((r.get("store_id"), str(r["listing_id"])))
    async for r in db.observation_quarantine.find({"quarantine_reasons": {"$in": ["unresolved_parent_variants", "parent_listing_has_child_offers"]}},
                                                {"_id": 0, "store_id": 1, "listing_id": 1, "sku": 1}):
        if r.get("listing_id"):
            listings.add((r.get("store_id"), str(r["listing_id"])))
        if r.get("sku"):
            skus.add((r.get("store_id"), r["sku"]))
    return listings, skus


def is_parent(row, parents, store_id=None):
    if is_child(row):
        return False
    sid = row.get("store_id") or store_id
    return unresolved_identity(row) or (sid, listing_id(row)) in parents[0] or (sid, row.get("sku")) in parents[1]


def annotate(row, parents, store_id=None):
    if not is_parent(row, parents, store_id):
        return row
    return {**row, "superseded_parent": True, "known_variant_parent": True,
            "quarantine_active": True, "price_unavailable_reason": "parent_listing_not_an_offer"}