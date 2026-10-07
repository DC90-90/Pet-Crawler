"""External workers use the same observed-offer writer as internal crawls."""
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from crawlers import process_crawled_products
from observation_contract import stable_id
import job_control


async def ingest(db, payload):
    domain = str(getattr(payload, "domain", "")).lower().rstrip(".")
    if domain == "example.com" or domain.endswith(".example.com"):
        raise HTTPException(400, "Reserved test domain cannot be ingested")
    if not payload.run_id or not payload.observed_at:
        raise HTTPException(422, "run_id and observed_at are required for replay-safe ingestion")
    try:
        at = datetime.fromisoformat(payload.observed_at.replace("Z", "+00:00"))
        if not at.tzinfo or at > datetime.now(timezone.utc)+timedelta(minutes=5):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "observed_at must be an ISO-8601 timestamp with timezone, not in the future")
    store = await db.stores.find_one({"id": payload.store_id, "domain": payload.domain, "is_active": True}, {"_id": 0})
    if not store:
        raise HTTPException(404, "Register and approve the store before ingesting observations")
    run_id = stable_id(store["id"], payload.run_id)
    payload_digest = stable_id(payload.observed_at, payload.products, payload.catalog_complete)
    async def completed_result():
        prior = await db.ingest_runs.find_one({"_id": run_id, "status": {"$in": ["complete", "partial"]}}, {"_id": 0})
        if not prior:
            return None
        if prior.get("payload_digest") not in (None, payload_digest):
            raise HTTPException(409, "run_id already belongs to a different payload")
        return {"status": "duplicate", "original_status": prior["status"], "quarantined": prior.get("quarantined", 0), "run_id": payload.run_id, "inserted": 0}
    prior = await completed_result()
    if prior:
        return prior
    import uuid
    lease_owner = str(uuid.uuid4())
    if not await job_control.acquire(db, f"store:{store['id']}", lease_owner):
        raise HTTPException(409, "Store observation writer already running")
    try:
        # Recheck under the lock: the first writer may finish between the first
        # idempotency lookup and this writer acquiring the released lease.
        prior = await completed_result()
        if prior:
            return prior
        rows = [{**r, "id": r.get("listing_id") or r.get("id") or r.get("sku"),
                 "name": r.get("name_ar") or r.get("name_en") or r.get("name"),
                 "_price_basis": r.get("price_basis"), "_currency": r.get("currency")} for r in payload.products if isinstance(r, dict)]
        before = await db.product_snapshots.count_documents({"store_id": store["id"], "crawled_at": at})
        await process_crawled_products(db, store, rows, at, tier=0, confidence=99)
        after = await db.product_snapshots.count_documents({"store_id": store["id"], "crawled_at": at})
        quarantined = await db.observation_quarantine.count_documents({"store_id": store["id"], "observed_at": at})
        result = {"status": "complete" if quarantined == 0 else "partial", "run_id": payload.run_id,
                  "inserted": after-before, "quarantined": quarantined, "observed_at": at,
                  "catalog_complete": payload.catalog_complete and quarantined == 0}
        await db.ingest_runs.update_one({"_id": run_id}, {"$set": {**result, "store_id": store["id"], "payload_digest": payload_digest}}, upsert=True)
        fields = {"last_crawl_attempt_at": datetime.now(timezone.utc).isoformat(), "last_crawl_status": result["status"]}
        if result["catalog_complete"]:
            fields.update(last_successful_crawl_at=at.isoformat(), last_crawled_at=at.isoformat())
        await db.stores.update_one({"id": store["id"]}, {"$set": fields})
        return result
    finally:
        await job_control.release(db, f"store:{store['id']}", lease_owner)