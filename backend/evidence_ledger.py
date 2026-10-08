"""Immutable offer events and idempotent, algorithm-versioned interval facts."""
from datetime import datetime, timezone, timedelta
from observation_contract import stable_id
from sales_evidence import interval, VERSION
from ledger import ksa_day_str


async def record(db, snapshot):
    event = {k: v for k, v in snapshot.items() if k != "_id"}
    event_id = event.get("event_id") or stable_id(event.get("offer_id"), str(event.get("crawled_at")))
    event.update(event_id=event_id, observed_at=event.get("crawled_at"), ingested_at=datetime.now(timezone.utc))
    prior = await db.observation_events.find_one(
        {"offer_id": event["offer_id"], "observed_at": {"$lt": event["observed_at"]}}, {"_id": 0}, sort=[("observed_at", -1)])
    inserted = await db.observation_events.update_one({"_id": event_id}, {"$setOnInsert": event}, upsert=True)
    if not inserted.upserted_id:
        event = await db.observation_events.find_one({'_id': event_id}, {'_id': 0})
    newer = await db.observation_events.find_one({"offer_id": event["offer_id"], "observed_at": {"$gt": event["observed_at"]}}, {"_id": 0, "event_id": 1})
    if newer:
        await db.late_observations.update_one({"_id": event_id}, {"$setOnInsert": {"event_id": event_id, "reason": "out_of_order_requires_explicit_rebuild"}}, upsert=True)
        return
    if not prior:
        if inserted.upserted_id:
            await db.data_versions.update_one({"_id": "observations"}, {"$inc": {"revision": 1}, "$max": {"observed_at": event["observed_at"]}}, upsert=True)
        return
    units, value, method = interval(prior, event)
    fact_id = stable_id(VERSION, prior["event_id"], event_id)
    fact = await db.sales_facts_v2.update_one({"_id": fact_id}, {"$setOnInsert": {
        "store_id": event["store_id"], "sku": event["sku"], "offer_id": event["offer_id"],
        "date": ksa_day_str(event["observed_at"]), "observed_at": event["observed_at"],
        "from_event_id": prior["event_id"], "to_event_id": event_id,
        "units": units, "revenue": value, "source": method, "algorithm_version": VERSION,
        "availability": "observed" if units is not None else "unavailable",
        "value_basis": "shelf_price_proxy", "created_at": datetime.now(timezone.utc),
    }}, upsert=True)
    if inserted.upserted_id or fact.upserted_id:
        await db.data_versions.update_one({'_id': 'observations'}, {'$inc': {'revision': 1}, '$max': {'observed_at': event['observed_at']}}, upsert=True)


async def sales_map(db, start, end, sealed=True):
    q = {"date": {"$gte": ksa_day_str(start), "$lte": ksa_day_str(end-timedelta(seconds=1))}, "algorithm_version": VERSION}
    out = {}
    sealed_days = {}
    if sealed:
        async for day in db.daily_ledger_store.find({"ksa_date": q["date"], "sealed_at": {"$ne": None}}, {"_id": 0, "store_id": 1, "ksa_date": 1, "sealed_at": 1}):
            sealed_days[(day["store_id"], day["ksa_date"])] = day["sealed_at"]
    async for r in db.sales_facts_v2.find(q, {"_id": 0}):
        if sealed and (r["store_id"], r["date"]) not in sealed_days:
            continue
        if sealed:
            cutoff = sealed_days[(r["store_id"], r["date"])].replace(tzinfo=timezone.utc)
            if r["created_at"].replace(tzinfo=timezone.utc) > cutoff:
                continue  # Late ingestion cannot rewrite a sealed answer.
        if r.get("units") is None:
            continue
        key = (r["store_id"], r.get("offer_id") or r["sku"])
        a = out.setdefault(key, {"sku": r["sku"], "offer_id": r.get("offer_id"), "units": 0, "revenue": 0.0, "source": "sold_counter_diff" if r["source"]=="sold_count_diff" else "stock_depletion", "intervals": 0, "value_basis": "shelf_price_proxy"})
        a["units"] += r["units"]
        a["revenue"] += r.get("revenue") or 0
        a["intervals"] += 1
    return out
