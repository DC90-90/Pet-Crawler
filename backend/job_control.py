"""Durable run records and cross-process leases. No in-process scheduler."""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from pymongo.errors import DuplicateKeyError


# A lease is held for LEASE_TTL and renewed every LEASE_RENEW_SECS by the
# process that holds it, up to the caller's maximum (`hours`). A holder that
# dies (every release restarts the backend) stops renewing, so its lease frees
# within LEASE_TTL instead of blocking cache rebuilds for an hour and store
# crawls for three (12 Oct 2026).
LEASE_TTL = timedelta(minutes=10)
LEASE_RENEW_SECS = 60
_renewals = {}   # (key, owner) -> asyncio.Task


async def acquire(db, key, owner, hours=3):
    now = datetime.now(timezone.utc)
    limit = now + timedelta(hours=hours)
    try:
        result = await db.job_leases.update_one(
            {"_id": key, "$or": [{"expires_at": {"$lte": now}}, {"owner": owner}]},
            {"$set": {"owner": owner, "expires_at": min(limit, now + LEASE_TTL), "max_until": limit,
                      "renewed_at": now}}, upsert=True)
        held = bool(result.upserted_id or result.modified_count)
    except DuplicateKeyError:
        return False
    if held:
        _start_renewal(db, key, owner, limit)
    return held


def _start_renewal(db, key, owner, limit):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    previous = _renewals.pop((key, owner), None)
    if previous is not None:
        previous.cancel()

    async def renew():
        while True:
            await asyncio.sleep(LEASE_RENEW_SECS)
            now = datetime.now(timezone.utc)
            if now >= limit:
                return
            try:
                result = await db.job_leases.update_one(
                    {"_id": key, "owner": owner},
                    {"$set": {"expires_at": min(limit, now + LEASE_TTL), "renewed_at": now}})
            except Exception:  # noqa: BLE001 — retry on the next tick
                continue
            if not result.matched_count:
                return   # released or taken over

    _renewals[(key, owner)] = loop.create_task(renew())


async def release(db, key, owner):
    task = _renewals.pop((key, owner), None)
    if task is not None:
        task.cancel()
    await db.job_leases.delete_one({"_id": key, "owner": owner})


async def queue(db, kind, key=None):
    run_id = key or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    from release_control import guarded, state
    from release_identity import identity
    fence = {}
    if guarded(db):
        control = await state(db)
        fence = {"release_id": identity()["release_id"], "writer_epoch": control["epoch"]}
    result = await db.job_runs.update_one({"_id": run_id}, {"$setOnInsert": {
        "id": run_id, "kind": kind, "status": "queued", "created_at": now, **fence,
    }}, upsert=True)
    return run_id, bool(result.upserted_id)


async def execute(db, run_id, kind, action):
    from release_control import guarded, state, permit, writer, ReleaseBlocked
    from release_identity import identity
    from release_runtime import JOB_CAPABILITIES
    if not guarded(db):
        return await _execute_claimed(db, run_id, kind, action)
    # Do not inherit a finished HTTP request's permit into a detached job.
    token = permit.set(None)
    try:
        control = await state(db)
        row = await db.job_runs.find_one({"_id": run_id}, {"_id": 0})
        if not row or row.get("release_id") != identity()["release_id"] or row.get("writer_epoch") != control["epoch"]:
            raise ReleaseBlocked("queued_job_release_fence_changed")
        async with writer(db, "job:"+kind, JOB_CAPABILITIES.get(kind, "manual_refresh")):
            return await _execute_claimed(db, run_id, kind, action)
    finally:
        permit.reset(token)


async def _execute_claimed(db, run_id, kind, action):
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
        await db.job_runs.update_one({"_id": run_id}, {"$set": {"status": "failed", "finished_at": datetime.now(timezone.utc), "error": type(exc).__name__, "recovery": getattr(exc, "result", None)}})
    finally:
        await release(db, f"job:{kind}", owner)
