"""Durable raw capture before optional enrichment; idempotent recovery after interruption."""
from copy import deepcopy
from datetime import datetime, timezone

class RecoveryIncomplete(RuntimeError):
    def __init__(self, recovered, unresolved):
        self.result = {"recovered": recovered, "unresolved": unresolved, "status": "recovery_required"}
        super().__init__(f"{len(unresolved)} captured batches require recovery/reconciliation")


def captured_at(capture):
    return datetime.fromisoformat(capture["observed_at_iso"]) if capture.get("observed_at_iso") else capture["observed_at"].replace(tzinfo=timezone.utc)


async def mark_unresolved(db, key, exc):
    issue = {"type": type(exc).__name__, "detail": getattr(exc, "result", None)}
    await db.crawl_checkpoints.update_one({"_id": key}, {"$set": {
        "state": "recovery_required", "recovery_error": issue, "last_recovery_attempt": datetime.now(timezone.utc)}})
    return {"checkpoint": key, **issue}

async def checkpoint(db, store, rows, observed_at, run_id, tier, confidence):
    keys = []
    for offset in range(0, len(rows), 50):
        key = f"capture:{run_id}:{offset}"
        await db.crawl_checkpoints.update_one({"_id": key}, {"$setOnInsert": {
            "store_id": store["id"], "run_id": run_id, "observed_at": observed_at, "observed_at_iso": observed_at.isoformat(),
            "raw_rows": deepcopy(rows[offset:offset+50]), "tier": tier, "confidence": confidence,
            "state": "captured", "created_at": datetime.now(timezone.utc)}}, upsert=True)
        keys.append(key)
    return keys


async def recover(db, store):
    from crawlers import process_crawled_products
    count = 0
    unresolved = []
    async for capture in db.crawl_checkpoints.find({"store_id": store["id"], "state": {"$in": ["captured", "enriched", "recovery_required"]}}).sort("observed_at", 1):
        # The original timestamp and immutable payload survive; no re-dating or fake full-crawl success.
        try:
            _, snaps = await process_crawled_products(db, store, capture.get("enriched_rows", capture["raw_rows"]), captured_at(capture),
                                                    tier=capture["tier"], confidence=capture["confidence"])
            await db.crawl_checkpoints.update_one({"_id": capture["_id"]}, {"$set": {
                "state": "persisted" if snaps else "quarantined", "recovered": bool(snaps)}, "$unset": {"recovery_error": ""}})
            count += bool(snaps)
        except Exception as exc:
            unresolved.append(await mark_unresolved(db, capture["_id"], exc))
    if unresolved:
        raise RecoveryIncomplete(count, unresolved)
    return count


async def persist(db, store, rows, observed_at, log, tier=1, confidence=95, **enrichment_options):
    from crawlers import _maybe_salla_detail_supplement, process_crawled_products
    keys = await checkpoint(db, store, rows, observed_at, log["id"], tier, confidence)
    enriched = deepcopy(rows)
    try:
        await _maybe_salla_detail_supplement(db, store, enriched, log, **enrichment_options)
    except Exception as exc:
        log.update(complete=False, enrichment_error=type(exc).__name__)
        enriched = deepcopy(rows)
    new, snaps = 0, 0
    try:
        for offset, key in zip(range(0, len(enriched), 50), keys):
            chunk = enriched[offset:offset+50]
            # A separate field preserves the source capture rather than overwriting evidence.
            await db.crawl_checkpoints.update_one({"_id": key, "state": "captured"},
                {"$set": {"enriched_rows": chunk, "state": "enriched"}})
            saved = await db.crawl_checkpoints.find_one({"_id": key}, {"_id": 0})
            if saved["state"] == "persisted":
                snaps += saved.get("snapshot_count", 0)
                continue
            n, s = await process_crawled_products(db, store, saved.get("enriched_rows", saved["raw_rows"]), captured_at(saved), tier=tier, confidence=confidence)
            new += n; snaps += s
            await db.crawl_checkpoints.update_one({"_id": key}, {"$set": {"state": "persisted" if s else "quarantined", "snapshot_count": s}, "$unset": {"recovery_error": ""}})
    except Exception as exc:
        issue = await mark_unresolved(db, key, exc)
        log.update(error=f"Observation persistence failed: {type(exc).__name__}", complete=False, recovery_required=issue)
    if rows and not snaps and not log.get("error"):
        log.update(complete=False, error="No comparable observations persisted; captures retained for quarantine/recovery")
    return new, snaps