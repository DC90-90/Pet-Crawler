"""Durable run records and cross-process leases. No in-process scheduler."""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from pymongo.errors import DuplicateKeyError


async def acquire(db, key, owner, hours=3):
    now = datetime.now(timezone.utc)
    try:
        result = await db.job_leases.update_one(
            {"_id": key, "$or": [{"expires_at": {"$lte": now}}, {"owner": owner}]},
            {"$set": {"owner": owner, "expires_at": now+timedelta(hours=hours)}}, upsert=True)
        return bool(result.upserted_id or result.modified_count)
    except DuplicateKeyError:
        return False


async def release(db, key, owner):
    await db.job_leases.delete_one({"_id": key, "owner": owner})


async def queue(db, kind, key=None):
    run_id = key or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    result = await db.job_runs.update_one({"_id": run_id}, {"$setOnInsert": {
        "id": run_id, "kind": kind, "status": "queued", "created_at": now,
    }}, upsert=True)
    return run_id, bool(result.upserted_id)


async def execute(db, run_id, kind, action):
    owner = str(uuid.uuid4())
    if not await acquire(db, f"job:{kind}", owner):
        await db.job_runs.update_one({"_id": run_id, "status": "queued"}, {"$set": {"status": "deferred", "reason": "job_already_running"}})
        return
    try:
        now = datetime.now(timezone.utc)
        await db.job_runs.update_many({"kind": kind, "status": "running", "started_at": {"$lt": now-timedelta(hours=3)}}, {"$set": {"status": "interrupted", "finished_at": now}})
        claimed = await db.job_runs.update_one({"_id": run_id, "status": "queued"}, {"$set": {"status": "running", "started_at": now}})
        if not claimed.modified_count:
            return
        result = await asyncio.wait_for(action(), timeout=2.5*3600)
        status = "failed" if isinstance(result, dict) and (result.get("error") or result.get("status") in ("failed", "error", "auth_failed", "missing_token")) else "completed"
        if isinstance(result, dict):
            if result.get("sync_status") == "error" or result.get("match_status") == "error":
                status = "failed"
            elif status != "failed" and (result.get('status') in ('partial', 'degraded', 'deferred', 'paused') or result.get("sync_status") == "degraded" or result.get("orders_status") not in (None, "ok", "skipped")):
                status = "degraded"
        from fastapi.encoders import jsonable_encoder
        clean = {k: v for k, v in (result or {}).items() if k != "_id"} if isinstance(result, dict) else {}
        await db.job_runs.update_one({"_id": run_id}, {"$set": {"status": status, "finished_at": datetime.now(timezone.utc), "result": jsonable_encoder(clean)}})
    except Exception as exc:
        await db.job_runs.update_one({"_id": run_id}, {"$set": {"status": "failed", "finished_at": datetime.now(timezone.utc), "error": type(exc).__name__}})
    finally:
        await release(db, f"job:{kind}", owner)
