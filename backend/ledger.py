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
from ledger_receipts import write_batch, require_complete, day_lock

logger = logging.getLogger(__name__)

LEDGER_WRITER_VERSION = 2

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
        "event_id": norm.get("event_id"),
        "close_price": round(price, 2) if isinstance(price, (int, float)) else None,
        "close_sale_price": round(norm["sale_price"], 2) if norm.get("sale_price") else None,
        "close_original_price": round(original, 2) if isinstance(original, (int, float)) else None,
        "discount_pct": max(0, disc),
        "on_sale": bool(norm.get("sale_price")) or disc > 0,
        "in_stock": norm.get("in_stock"),
        "qty_available": norm.get("qty"),
        # the LEVEL of the cumulative counter — never a delta (Ahmad ruling 2)
        "sold_count_cumulative": norm.get("sold_count_cumulative"),
        "sold_count_observed": norm.get("sold_count_observed"),
        "sold_count_capped": norm.get("sold_count_capped"),
        "offer_id": norm.get("offer_id"),
    }


async def ensure_ledger_indexes(db):
    await db.daily_ledger.create_index([("store_id", 1), ("ksa_date", 1)])
    await db.daily_ledger.create_index([("store_id", 1), ("sku", 1)])
    await db.daily_ledger.create_index([("ksa_date", 1), ("sealed_at", 1)])
    await db.daily_ledger_store.create_index([("ksa_date", 1)])


async def record_observations(db, store_id, store_name, observations, observed_at,
                              source_tier=None, confidence=None, crawl_run_id=None):
    """Apply immutable observation receipts. Callers must propagate incomplete outcomes."""
    return await write_batch(db, store_id, store_name, observations, observed_at,
                             source_tier, confidence, crawl_run_id)


def sealed_ksa_window(days, now=None):
    """iter73 — Ledger Phase 2 read helper.

    Return `(start_utc, end_utc)` covering the `days` most-recent FULLY-SEALED
    KSA calendar days. The `end` is KSA-midnight of TODAY (so today's still-
    accumulating hours are excluded); the `start` is KSA-midnight of the day
    that closed `days` days before that.

    This is the stability primitive for revenue / units KPIs: within one KSA
    calendar day every call to `sealed_ksa_window(N)` returns the SAME UTC
    boundaries, so a "past N days" reader that respects them cannot shift its
    answer between page visits. The window only advances at KSA midnight, when
    a new day seals.

    Anything that happened today is NOT in the returned window — it belongs to
    a separate "today so far" surface that clients may show alongside, never
    mixed in, because it is by definition provisional.
    """
    now = now or datetime.now(timezone.utc)
    now_ksa = now.astimezone(KSA_TZ)
    end_ksa = now_ksa.replace(hour=0, minute=0, second=0, microsecond=0)
    start_ksa = end_ksa - timedelta(days=int(days))
    return start_ksa.astimezone(timezone.utc), end_ksa.astimezone(timezone.utc)


async def sealed_days_in_window(db, days, now=None):
    """Count how many of the `days` calendar days in the sealed window ACTUALLY
    have their `daily_ledger_store.sealed_at` set — the honest health signal
    for callers that need to know whether the window is fully covered by the
    ledger or is falling back to live rollups for holes.

    Returns {"expected": days, "sealed_days": int, "unsealed_days": int,
             "start_ksa_date": "YYYY-MM-DD", "end_ksa_date": "YYYY-MM-DD"}.
    Never raises — a broken ledger must not brick the KPI it accompanies.
    """
    now = now or datetime.now(timezone.utc)
    start_utc, end_utc = sealed_ksa_window(days, now)
    start_day = ksa_day_str(start_utc)
    # end_utc is EXCLUSIVE — the last covered KSA day is end_utc - 1s
    end_day = ksa_day_str(end_utc - timedelta(seconds=1))
    try:
        # DISTINCT sealed days across ALL stores — one sealed store means the
        # day is sealed (silence for a store is a `no_data` sealed row, still
        # sealed). We report the SET size, not the row count.
        sealed = set()
        cur = db.daily_ledger_store.find(
            {"ksa_date": {"$gte": start_day, "$lte": end_day},
             "sealed_at": {"$ne": None}},
            {"_id": 0, "ksa_date": 1}).batch_size(2000)
        async for r in cur:
            sealed.add(r["ksa_date"])
        n = int(days)
        return {"expected": n, "sealed_days": len(sealed),
                "unsealed_days": max(0, n - len(sealed)),
                "start_ksa_date": start_day, "end_ksa_date": end_day}
    except Exception as e:
        logger.warning("[Ledger] sealed_days_in_window failed: %s", str(e)[:120])
        return {"expected": int(days), "sealed_days": 0,
                "unsealed_days": int(days),
                "start_ksa_date": start_day, "end_ksa_date": end_day}


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
    if day >= ksa_day_str(now):
        raise ValueError("Only completed KSA days may be sealed")
    summary = {"day": day, "stores_sealed": 0, "no_data_stores": 0, "rows_sealed": 0}

    stores = [s async for s in db.stores.find(
        {"is_active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1})]
    for s in stores:
        async with day_lock(db, s["id"], day):
            await _seal_store_day(db, s, day, now, summary)
    logger.info("[Ledger] sealed %s: %s", day, summary)
    return summary


async def _seal_store_day(db, store, day, sealed_at, summary):
    sid, sd_id = store["id"], _store_day_id(store["id"], day)
    sd = await db.daily_ledger_store.find_one({"_id": sd_id}, {"_id": 0})
    if sd and sd.get("sealed_at") is not None:
        # Finish only row seals interrupted by a prior seal; never alter values/counters.
        res = await db.daily_ledger.update_many({"store_id": sid, "ksa_date": day, "sealed_at": None},
                                               {"$set": {"sealed_at": sd["sealed_at"]}})
        summary["rows_sealed"] += res.modified_count
        return
    rows = await db.daily_ledger.find({"store_id": sid, "ksa_date": day}, {"_id": 0, "sku": 1, "is_first_day_for_store": 1}).to_list(None)
    known = set(await db.sku_store_coverage.distinct("sku", {"store_id": sid}))
    today = {r["sku"] for r in rows}
    # Missing store-day metadata with durable rows means interrupted work, NOT no_data.
    unresolved = (sd or {}).get("unresolved_observation_ids", [])
    status = "partial" if unresolved or (known and len(today) < PARTIAL_BELOW*len(known)) or (rows and sd is None) else "ok"
    if not rows and not sd:
        status = "no_data"
    await db.daily_ledger_store.update_one({"_id": sd_id, "sealed_at": None}, {
        "$set": {"status": status, "skus_observed": len(rows), "first_seen_count": len({r["sku"] for r in rows if r.get("is_first_day_for_store")}),
                 "absent_count": len(known-today) if status != "no_data" else None, "sealed_at": sealed_at},
        "$setOnInsert": {"store_id": sid, "ksa_date": day, "store_name": store.get("name"), "crawl_run_id": None,
                         "writer_version": LEDGER_WRITER_VERSION}}, upsert=True)
    summary["no_data_stores" if status == "no_data" else "stores_sealed"] += 1
    res = await db.daily_ledger.update_many({"store_id": sid, "ksa_date": day, "sealed_at": None}, {"$set": {"sealed_at": sealed_at}})
    summary["rows_sealed"] += res.modified_count
