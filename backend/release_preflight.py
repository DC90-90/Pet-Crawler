"""Read-only schema prerequisites. No automatic index repair."""


async def writer_schema(db):
    missing = []
    for collection, field in (("products", "offer_id"), ("product_snapshots", "event_id")):
        indexes = await db[collection].index_information()
        if not any(v.get("unique") is True and v.get("key") == [(field, 1)] and
                   v.get("partialFilterExpression") == {field: {"$type": "string"}} for v in indexes.values()):
            missing.append(f"{collection}.{field}:unique-string-index")
    return {"ready": not missing, "missing": missing}