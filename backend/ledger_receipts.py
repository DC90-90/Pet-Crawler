"""Identity-idempotent daily materialization. No history rewrite or inferred backfill."""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pymongo.errors import OperationFailure, DuplicateKeyError
from observation_contract import stable_id
from price_cohort import aware
from job_control import acquire, release


class LedgerIncomplete(RuntimeError):
    def __init__(self, result):
        self.result = result
        super().__init__("Daily ledger incomplete: " + str(result.get("errors") or result.get("rejected_sealed")))


def require_complete(result):
    if result and (result.get("skipped") or result.get("rejected_sealed") or result.get("complete") is False):
        raise LedgerIncomplete(result)


@asynccontextmanager
async def day_lock(db, store_id, day):
    key, owner = f"ledger-day:{store_id}:{day}", uuid.uuid4().hex
    if not await acquire(db, key, owner, hours=1/12):
        raise LedgerIncomplete({"complete": False, "errors": [{"reason": "day_write_or_seal_in_progress"}]})
    try:
        yield key, owner
    finally:
        await release(db, key, owner)


def observation_id(store_id, row, stamp):
    return str(row.get("event_id") or stable_id(store_id, row.get("offer_id") or str(row["sku"]), stamp.isoformat(timespec="microseconds")))


async def write_batch(db, store_id, store_name, observations, observed_at, source_tier, confidence, crawl_run_id):
    from ledger import ksa_day_str, LEDGER_WRITER_VERSION
    stamp = aware(observed_at).astimezone(timezone.utc)
    day = ksa_day_str(stamp)
    obs = [o for o in observations or [] if o.get("sku")]
    out = dict(day=day, written=0, duplicate=0, rejected_sealed=0, first_seen=0, skipped=0, errors=[], complete=True)
    if not obs:
        return out
    async with day_lock(db, store_id, day) as (lock_key, owner):
        sd_id = f"{store_id}|{day}"
        sd = await db.daily_ledger_store.find_one({"_id": sd_id}, {"_id": 0})
        prior = set(await db.sku_store_coverage.distinct("sku", {"store_id": store_id}))
        prior.update(await db.daily_ledger.distinct("sku", {"store_id": store_id, "ksa_date": {"$lt": day}}))
        for o in obs:
            # Renew before each atomic row write. A lost lease aborts, never reports success.
            renewed = await db.job_leases.update_one({"_id": lock_key, "owner": owner, "expires_at": {"$gt": datetime.now(timezone.utc)}},
                                                     {"$set": {"expires_at": datetime.now(timezone.utc)+timedelta(minutes=5)}})
            if not renewed.matched_count:
                raise LedgerIncomplete({"complete": False, "errors": [{"reason": "day_lease_lost"}]})
            sku = str(o["sku"])
            rid = f"{store_id}|{o.get('offer_id') or sku}|{day}"
            oid = observation_id(store_id, o, stamp)
            existing = await db.daily_ledger.find_one({"_id": rid}, {"_id": 0})
            # A proven replay may acknowledge already committed sealed evidence, without any write.
            if existing and oid in existing.get("applied_observation_ids", []):
                out["duplicate"] += 1
                continue
            if (sd and sd.get("sealed_at") is not None) or (existing and existing.get("sealed_at") is not None):
                out["rejected_sealed"] += 1
                out["errors"].append({"event_id": oid, "reason": "sealed_history_requires_reconciliation"})
                continue
            # Old ledger versions have no receipts. Do not guess which old events contributed.
            legacy_cutoff = aware((existing or {}).get("legacy_identity_cutoff_at"))
            if existing and not existing.get("applied_observation_ids"):
                legacy_cutoff = aware(existing.get("last_observed_at"))
            # BSON dates truncate microseconds. A receipt-less observation within
            # the same stored millisecond is ambiguous, not provably newer.
            if legacy_cutoff and stamp.replace(microsecond=(stamp.microsecond // 1000)*1000) <= legacy_cutoff.replace(microsecond=(legacy_cutoff.microsecond // 1000)*1000):
                out["skipped"] += 1
                out["errors"].append({"event_id": oid, "reason": "legacy_observation_identity_unresolved"})
                continue
            latest = aware((existing or {}).get("last_observed_at_iso") or (existing or {}).get("last_observed_at"))
            closing = {} if latest and stamp < latest else {k: o.get(k) for k in (
                "close_price", "close_sale_price", "close_original_price", "discount_pct", "on_sale", "in_stock",
                "qty_available", "sold_count_cumulative", "sold_count_observed", "sold_count_capped", "offer_id")}
            if not latest or stamp >= latest:
                closing.update(confidence=confidence, source_tier=source_tier, last_observed_at=stamp,
                               last_observed_at_iso=stamp.isoformat(timespec="microseconds"))
            if legacy_cutoff:
                closing["legacy_identity_cutoff_at"] = legacy_cutoff
            first = sku not in prior
            update = {"$set": closing, "$inc": {"observations_that_day": 1}, "$addToSet": {"applied_observation_ids": oid},
                      "$setOnInsert": {"store_id": store_id, "sku": sku, "ksa_date": day, "is_first_day_for_store": first,
                                       "sealed_at": None, "writer_version": LEDGER_WRITER_VERSION, "backfilled": False}}
            try:
                result = await db.daily_ledger.update_one({"_id": rid, "sealed_at": None, "applied_observation_ids": {"$ne": oid}}, update, upsert=True)
                out["written"] += 1
                if result.upserted_id and first:
                    out["first_seen"] += 1
                    prior.add(sku)
            except (DuplicateKeyError, OperationFailure) as exc:
                out["skipped"] += 1
                out["errors"].append({"event_id": oid, "row_id": rid, "reason": "row_write_failed", "code": getattr(exc, "code", None)})
        out["complete"] = not (out["skipped"] or out["rejected_sealed"])
        if sd and sd.get("sealed_at") is not None:
            return out
        # Derived counters repair a crash between row and store-day writes. Never increment on replay.
        rows = await db.daily_ledger.find({"store_id": store_id, "ksa_date": day},
                    {"_id": 0, "sku": 1, "is_first_day_for_store": 1, "last_observed_at": 1}).to_list(None)
        first_skus = {r["sku"] for r in rows if r.get("is_first_day_for_store")}
        last = max([aware(r["last_observed_at"]) for r in rows if r.get("last_observed_at")], default=None)
        failed_ids = {e["event_id"] for e in out["errors"]}
        submitted_ids = {observation_id(store_id, o, stamp) for o in obs}
        unresolved = (set((sd or {}).get("unresolved_observation_ids", [])) - submitted_ids) | failed_ids
        await db.daily_ledger_store.update_one({"_id": sd_id, "sealed_at": None}, {
            "$set": {"status": "partial" if unresolved else "ok", "skus_observed": len(rows), "first_seen_count": len(first_skus),
                     "store_name": store_name, "crawl_run_id": crawl_run_id, "last_observed_at": last,
                     "unresolved_observation_ids": sorted(unresolved)},
            "$setOnInsert": {"store_id": store_id, "ksa_date": day, "sealed_at": None, "absent_count": None,
                             "writer_version": LEDGER_WRITER_VERSION}}, upsert=True)
    return out