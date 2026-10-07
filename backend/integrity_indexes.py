"""Non-destructive identity migration; old rows remain inspectable but untrusted."""
async def ensure(db):
    indexes = await db.products.index_information()
    for name, index in indexes.items():
        if index.get("unique") and index.get("key") == [("sku", 1)]:
            await db.products.drop_index(name)
    await db.products.create_index("offer_id", unique=True, partialFilterExpression={"offer_id": {"$type": "string"}})
    await db.product_snapshots.create_index("event_id", unique=True, partialFilterExpression={"event_id": {"$type": "string"}})
    await db.product_snapshots.create_index([("store_id", 1), ("offer_id", 1), ("crawled_at", -1)])
    await db.observation_events.create_index([("offer_id", 1), ("observed_at", -1)])
    await db.sales_facts_v2.create_index([("date", 1), ("store_id", 1)])
    await db.revoked_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.job_runs.create_index([("status", 1), ("created_at", -1)])