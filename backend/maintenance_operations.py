"""Named, previewable operations. Never invoked by application startup."""
import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from release_control import state, writer, ReleaseBlocked
from release_identity import identity

OPERATIONS = {
    "integrity-indexes": "May drop legacy unique SKU indexes and create offer/event uniqueness indexes.",
    "ledger-indexes": "Create the reviewed ledger and coverage indexes; no history backfill.",
    "query-indexes": "Create the application's query indexes.",
    "store-registry": "Apply registry additions/retags/deletions; review the affected store list first.",
    "legacy-match-cleanup": "Remove unconfirmed legacy name/low-confidence matches, then record the migration.",
    "food-categories": "Classify existing product food subcategories.",
    "metric-rollups": "Rebuild classifier/metric rollups if stored versions require it.",
}


async def plan(db, operation):
    if operation not in OPERATIONS:
        raise HTTPException(422, "Unknown controlled operation")
    s = await state(db)
    stores = await db.stores.find({}, {"_id": 0, "id": 1, "domain": 1, "name": 1, "is_active": 1, "is_own_store": 1}).sort("id", 1).to_list(None)
    indexes = {}
    for collection in ("products", "product_snapshots", "daily_ledger"):
        indexes[collection] = await db[collection].index_information()
    result = {"operation": operation, "description": OPERATIONS[operation], "release_id": identity()["release_id"],
              "control_revision": s["revision"], "mode": s["mode"], "stores": stores, "indexes": indexes,
              "counts": {c: await db[c].count_documents({}) for c in ("my_products", "products", "product_snapshots", "product_matches", "daily_ledger")}}
    result["plan_hash"] = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
    return result


async def apply(db, operation, expected_hash, approval, actor):
    proposed = await plan(db, operation)
    if not approval or len(approval.strip()) < 8 or proposed["plan_hash"] != expected_hash:
        raise ReleaseBlocked("approval_or_plan_changed", 409)
    s = await state(db)
    if s["mode"] != "frozen" or s["active_writers"]:
        raise ReleaseBlocked("frozen_and_drained_required", 409)
    import server
    import integrity_indexes
    import ledger
    from store_registry import ensure_stores as registry_ensure
    async def cleanup():
        result = await db.product_matches.delete_many({"manually_confirmed": {"$ne": True}, "$or": [{"match_method": {"$regex": "^name_"}}, {"confidence": {"$lt": 95}}]})
        await db.migrations.update_one({"_id": "legacy_name_matches_purged_v4"}, {"$set": {"applied_at": datetime.now(timezone.utc).isoformat(), "deleted": result.deleted_count}}, upsert=True)
        return {"deleted": result.deleted_count}
    actions = {"integrity-indexes": lambda: integrity_indexes.ensure(db), "ledger-indexes": lambda: ledger.ensure_ledger_indexes(db),
               "query-indexes": lambda: server.ensure_all_indexes(db), "store-registry": lambda: registry_ensure(db),
               "legacy-match-cleanup": cleanup, "food-categories": lambda: server.backfill_food_subcategories(db),
               "metric-rollups": lambda: server._maybe_backfill_store_metrics(db)}
    async with writer(db, "maintenance:"+operation, actor=actor):
        await db.maintenance_runs.insert_one({"operation": operation, "plan_hash": expected_hash, "approval": approval,
                                             "actor": actor, "release_id": identity()["release_id"], "status": "running"})
        try:
            result = await actions[operation]()
            if isinstance(result, dict) and any(isinstance(v, dict) and v.get("ok") is False for v in result.values()):
                raise RuntimeError("One or more controlled index operations failed")
            await db.maintenance_runs.update_one({"plan_hash": expected_hash, "status": "running"}, {"$set": {"status": "completed"}})
            return {"status": "completed", "operation": operation, "result": result}
        except Exception as exc:
            await db.maintenance_runs.update_one({"plan_hash": expected_hash, "status": "running"}, {"$set": {"status": "failed", "error": type(exc).__name__}})
            raise