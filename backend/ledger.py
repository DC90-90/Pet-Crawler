"""iter67 — Ledger Phase 1: the append-only daily ledger. WRITE-ONLY.

Daleel's audit (iter64 handoff) established that the existing "rollups" are a
cache, not a ledger: metric_daily_rollups / sku_store_coverage /
sku_sales_daily are wiped and rebuilt from product_snapshots on every crawl,
so every past day is a pure function of the current snapshot contents under
the current code. This module starts the approved history-first migration at
Phase 1: an append-only record written ALONGSIDE the rollups. Nothing reads
it yet; converting readers is Phase 4.

Ahmad's recorded rulings, all binding here:
  KSA days        every day boundary is Asia/Riyadh (UTC+3, no DST), matching
                  the own_store_orders bucketing — NOT the rollups' UTC days.
  levels          sold_count_cumulative stores the counter LEVEL, never a
                  delta. Differencing is a read-time concern; storing levels is
                  what makes rows independently addable and append-only.
  honest values   the ledger only ever contains OBSERVED values. No fallbacks,
                  no estimates, no placeholder anything. A field we did not
                  observe is absent/None, and a day with no crawl is a
                  `no_data` STORE-day row — never yesterday's values standing.
  marked backfill backfilled=False on everything this writer produces; the
                  Phase-3 backfill will write True and nothing may blur that.

Collections
-----------
daily_ledger        one row per (store_id, sku, KSA day),
                    _id "{store_id}|{sku}|{YYYY-MM-DD}". Intra-day, the latest
                    observation wins (a 14:00 ingest overwrites the 04:00
                    crawl); observations_that_day counts how many times the
                    pair was seen. Once sealed_at is set the row is immutable —
                    the writer's filter refuses it and the attempt is counted.
daily_ledger_store  one row per (store_id, KSA day): status ok|partial|no_data,
                    skus_observed, first_seen_count, absent_count,
                    crawl_run_id, sealed_at. This is what makes ABSENCE a
                    fact: a missing day reads as no_data, not as zero.

Sealing
-------
seal_ksa_day runs shortly after KSA midnight (scheduled from server startup)
and seals the day that just ended: sets sealed_at on every row, computes
absent_count / partial status for observed stores, and writes no_data rows for
active stores that produced nothing. Sealed rows are never modified again.
"""
import logging
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError, OperationFailure

logger = logging.getLogger(__name__)

LEDGER_WRITER_VERSION = 1

# Asia/Riyadh is UTC+3 with no DST — a fixed offset is exact, not approximate.
KSA_TZ = timezone(timedelta(hours=3))

# A store whose sealed day covered less than this share of its known catalogue
# is marked "partial" rather than "ok" — a thin day must not read as a full one.
PARTIAL_BELOW = 0.5


def ksa_day_str(dt):
    """The KSA calendar day 'YYYY-MM-DD' of a datetime (naive treated as UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KSA_TZ).strftime("%Y-%m-%d")


def _store_day_id(store_id, day):
    return f"{store_id}|{day}"


def _row_id(store_id, sku, day):
    return f"{store_id}|{sku}|{day}"


def crawl_observation(norm):
    """Map a _normalize_raw_product dict to a ledger observation.

    Same discount arithmetic as the snapshot writer, so the ledger and the
    snapshot of the same observation can never disagree.
    """
    price = norm.get("price")
    original = norm.get("original_price")
    disc = 0
    if isinstance(original, (int, float)) and isinstance(price, (int, float)) \
            and original > price > 0:
        disc = round((1 - price / original) * 100)
    return {
        "sku": norm.get("sku"),
        "close_price": round(price, 2) if isinstance(price, (int, float)) else None,
        "close_sale_price": round(norm["sale_price"], 2) if norm.get("sale_price") else None,
        "close_original_price": round(original, 2) if isinstance(original, (int, float)) else None,
        "discount_pct": max(0, disc),
        "on_sale": bool(norm.get("sale_price")) or disc > 0,
        "in_stock": bool(norm.get("in_stock")),
        "qty_available": norm.get("qty"),
        # the LEVEL of the cumulative counter — never a delta (Ahmad ruling 2)
        "sold_count_cumulative": norm.get("sold_count_cumulative"),
    }


async def ensure_ledger_indexes(db):
    await db.daily_ledger.create_index([("store_id", 1), ("ksa_date", 1)])
    await db.daily_ledger.create_index([("store_id", 1), ("sku", 1)])
    await db.daily_ledger.create_index([("ksa_date", 1), ("sealed_at", 1)])
    await db.daily_ledger_store.create_index([("ksa_date", 1)])


async def record_observations(db, store_id, store_name, observations, observed_at,
                              source_tier=None, confidence=None, crawl_run_id=None):
    """Upsert one KSA day's ledger rows for a batch of observations.

    observations: iterable of crawl_observation() dicts. Latest wins intra-day.
    Writes to a sealed day are refused row-by-row and counted, never applied.

    Returns {"day", "written", "rejected_sealed", "first_seen", "skipped"}.
    Never raises on per-row trouble — the ledger must not cost a crawl — but a
    batch-level failure propagates to the caller's fail-soft wrapper so it is
    logged loudly rather than half-applied silently.
    """
    day = ksa_day_str(observed_at)
    out = {"day": day, "written": 0, "rejected_sealed": 0, "first_seen": 0, "skipped": 0}
    obs = [o for o in observations or [] if o.get("sku")]
    if not obs:
        return out

    # Day-level seal gate: one cheap read instead of N rejected upserts.
    sd_id = _store_day_id(store_id, day)
    sd = await db.daily_ledger_store.find_one({"_id": sd_id}, {"_id": 0, "sealed_at": 1})
    if sd and sd.get("sealed_at") is not None:
        out["rejected_sealed"] = len(obs)
        logger.warning("[Ledger] %s day %s is sealed — %d observations refused",
                       store_id, day, len(obs))
        return out

    # First-seen detection reads sku_store_coverage (read-only). At the moment
    # the crawl-path hook runs, coverage still reflects PRIOR crawls only —
    # _recompute_store_metrics rebuilds it after the crawl completes — so "not
    # in coverage" means "never seen by Daleel before", the honest new-arrival
    # signal. Bounded by catalogue size (one doc per pair), not by history.
    known_prior = set()
    async for c in db.sku_store_coverage.find(
            {"store_id": store_id}, {"_id": 0, "sku": 1}).batch_size(2000):
        known_prior.add(c["sku"])

    for o in obs:
        sku = str(o["sku"])
        rid = _row_id(store_id, sku, day)
        first = sku not in known_prior
        update = {
            "$set": {
                "close_price": o.get("close_price"),
                "close_sale_price": o.get("close_sale_price"),
                "close_original_price": o.get("close_original_price"),
                "discount_pct": o.get("discount_pct"),
                "on_sale": o.get("on_sale"),
                "in_stock": o.get("in_stock"),
                "qty_available": o.get("qty_available"),
                "sold_count_cumulative": o.get("sold_count_cumulative"),
                "confidence": confidence,
                "source_tier": source_tier,
                "last_observed_at": observed_at,
            },
            "$inc": {"observations_that_day": 1},
            "$setOnInsert": {
                "store_id": store_id, "sku": sku, "ksa_date": day,
                "is_first_day_for_store": first,
                "sealed_at": None,
                "writer_version": LEDGER_WRITER_VERSION,
                "backfilled": False,
            },
        }
        try:
            await db.daily_ledger.update_one(
                {"_id": rid, "sealed_at": None}, update, upsert=True)
            out["written"] += 1
            if first:
                out["first_seen"] += 1
                known_prior.add(sku)   # a second intra-batch sighting is not "first" again
        except DuplicateKeyError:
            out["rejected_sealed"] += 1      # row exists but is sealed — immutable
        except OperationFailure as e:
            if getattr(e, "code", None) == 11000:
                out["rejected_sealed"] += 1
            else:
                out["skipped"] += 1
                logger.warning("[Ledger] row %s failed: %s", rid, str(e)[:120])

    skus_observed = await db.daily_ledger.count_documents(
        {"store_id": store_id, "ksa_date": day})
    await db.daily_ledger_store.update_one(
        {"_id": sd_id, "sealed_at": None},
        {"$set": {
            "status": "ok",                 # finalised (ok|partial) at seal time
            "skus_observed": skus_observed,
            "store_name": store_name,
            "crawl_run_id": crawl_run_id,
            "last_observed_at": observed_at,
        },
         "$inc": {"first_seen_count": out["first_seen"]},
         "$setOnInsert": {
             "store_id": store_id, "ksa_date": day, "sealed_at": None,
             "absent_count": None,          # unknown until the day seals
             "writer_version": LEDGER_WRITER_VERSION,
         }},
        upsert=True)
    return out


async def seal_ksa_day(db, day=None, now=None):
    """Seal a finished KSA day. Idempotent; safe to re-run.

    Default day: yesterday in KSA — the job is scheduled shortly after KSA
    midnight, so 'yesterday' is the day that just closed.

    1. Every observed store-day gets absent_count (known pairs with no row
       today) and its final ok|partial status, then sealed_at.
    2. Every ACTIVE store with no store-day row gets a `no_data` row — absence
       recorded as a fact, not left as a hole that reads as zero.
    3. Every daily_ledger row of the day gets sealed_at. Sealed rows are never
       modified afterward; the writer's filter enforces it.
    """
    now = now or datetime.now(timezone.utc)
    if day is None:
        day = ksa_day_str(now - timedelta(days=1))
    sealed_at = now
    summary = {"day": day, "stores_sealed": 0, "no_data_stores": 0, "rows_sealed": 0}

    stores = [s async for s in db.stores.find(
        {"is_active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1})]
    for s in stores:
        sid = s["id"]
        sd_id = _store_day_id(sid, day)
        sd = await db.daily_ledger_store.find_one({"_id": sd_id})
        if sd is None:
            # silence is data: the store produced nothing this KSA day
            try:
                await db.daily_ledger_store.insert_one({
                    "_id": sd_id, "store_id": sid, "ksa_date": day,
                    "store_name": s.get("name"),
                    "status": "no_data", "skus_observed": 0,
                    "crawl_run_id": None, "first_seen_count": 0,
                    "absent_count": None,
                    "sealed_at": sealed_at,
                    "writer_version": LEDGER_WRITER_VERSION,
                })
                summary["no_data_stores"] += 1
            except (DuplicateKeyError, OperationFailure):
                pass                          # concurrent seal — already handled
            continue
        if sd.get("sealed_at") is not None:
            continue                          # idempotent re-run
        # absent = known catalogue pairs with no ledger row today. Both sets are
        # bounded by catalogue size. Coverage at seal time includes today's
        # crawl (rebuilt post-crawl), so absentees are genuine no-shows.
        known = set()
        async for c in db.sku_store_coverage.find(
                {"store_id": sid}, {"_id": 0, "sku": 1}).batch_size(2000):
            known.add(c["sku"])
        today = set()
        async for r in db.daily_ledger.find(
                {"store_id": sid, "ksa_date": day}, {"_id": 0, "sku": 1}).batch_size(2000):
            today.add(r["sku"])
        absent = len(known - today)
        observed = len(today)
        status = "ok"
        if known and observed < PARTIAL_BELOW * len(known):
            status = "partial"
        await db.daily_ledger_store.update_one(
            {"_id": sd_id, "sealed_at": None},
            {"$set": {"status": status, "skus_observed": observed,
                      "absent_count": absent, "sealed_at": sealed_at}})
        summary["stores_sealed"] += 1

    res = await db.daily_ledger.update_many(
        {"ksa_date": day, "sealed_at": None}, {"$set": {"sealed_at": sealed_at}})
    summary["rows_sealed"] = getattr(res, "modified_count", 0)
    logger.info("[Ledger] sealed %s: %s", day, summary)
    return summary
