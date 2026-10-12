"""Durable raw capture before optional enrichment; idempotent recovery after interruption."""
import asyncio
import logging
from copy import deepcopy
from datetime import datetime, timezone

from pymongo.errors import AutoReconnect, ConnectionFailure, ExecutionTimeout, NetworkTimeout

logger = logging.getLogger(__name__)
# A busy database (cache rebuilds, index builds) made single writes exceed the
# socket timeout and the whole store's crawl was marked failed with nothing
# persisted (11 Oct 2026). Every write below is idempotent (event_id upserts,
# keyed checkpoints), so a transient failure is retried, never skipped.
TRANSIENT_ERRORS = (NetworkTimeout, AutoReconnect, ConnectionFailure, ExecutionTimeout)
RETRY_WAITS = (5, 20, 60)


async def retry_transient(operation, label):
    for attempt, wait in enumerate((*RETRY_WAITS, None)):
        try:
            return await operation()
        except TRANSIENT_ERRORS as exc:
            if wait is None:
                raise
            logger.warning("Transient database error during %s (%s); retry %d in %ss",
                           label, type(exc).__name__, attempt + 1, wait)
            await asyncio.sleep(wait)

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


SEALED_REASON = "sealed_history_requires_reconciliation"


def _sealed_only_result(type_name, result):
    if type_name != "LedgerIncomplete" or not isinstance(result, dict) or result.get("skipped"):
        return False
    errors = result.get("errors") or []
    return bool(errors or result.get("rejected_sealed")) and all(e.get("reason") == SEALED_REASON for e in errors)


def sealed_ledger_only(exc):
    """Only the daily ledger refused the replay because that KSA day is sealed;
    the capture's snapshots and observation events are stored."""
    return _sealed_only_result(type(exc).__name__, getattr(exc, "result", None))


def awaiting_reconciliation(capture):
    """A capture already replayed once whose only problem is a sealed ledger
    day. It stays `recovery_required` (sealed history changes only through an
    explicit reconciliation) but is not replayed again on every crawl: each
    replay rewrote nothing and cost minutes per store (12 Oct 2026)."""
    issue = capture.get("recovery_error") or {}
    return capture.get("state") == "recovery_required" and _sealed_only_result(issue.get("type"), issue.get("detail"))


async def recover(db, store):
    from crawlers import process_crawled_products
    count = 0
    unresolved = []
    async for capture in db.crawl_checkpoints.find({"store_id": store["id"], "state": {"$in": ["captured", "enriched", "recovery_required"]}}).sort("observed_at", 1):
        if awaiting_reconciliation(capture):
            continue
        # The original timestamp and immutable payload survive; no re-dating or fake full-crawl success.
        try:
            _, snaps = await retry_transient(
                lambda: process_crawled_products(db, store, capture.get("enriched_rows", capture["raw_rows"]), captured_at(capture),
                                                 tier=capture["tier"], confidence=capture["confidence"]),
                f"recover {store.get('name')} {capture['_id']}")
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
            n, s = await retry_transient(
                lambda: process_crawled_products(db, store, saved.get("enriched_rows", saved["raw_rows"]), captured_at(saved), tier=tier, confidence=confidence),
                f"persist {store.get('name')} chunk {offset}")
            new += n; snaps += s
            await retry_transient(lambda: db.crawl_checkpoints.update_one({"_id": key}, {"$set": {"state": "persisted" if s else "quarantined", "snapshot_count": s}, "$unset": {"recovery_error": ""}}),
                                  f"checkpoint {key}")
    except Exception as exc:
        issue = await mark_unresolved(db, key, exc)
        log.update(error=f"Observation persistence failed: {type(exc).__name__}", complete=False, recovery_required=issue)
    if rows and not snaps and not log.get("error"):
        log.update(complete=False, error="No comparable observations persisted; captures retained for quarantine/recovery")
    return new, snaps