"""Sales evidence from the sealed daily ledger (14 Oct 2026).

`sales_facts_v2` starts on 12 Oct 2026, so a "30-day" revenue was built from
one or two days: Pets Houses showed 5,457 SAR for a period in which the owner
sold over 50,000 SAR. The sealed `daily_ledger` holds one closing row per
store, SKU and KSA day since 1 Aug 2026. Day-over-day changes in that ledger
give the same proxy as the interval facts (same caps as `sales_evidence`), for
the whole window:

* a public sold counter that rises (Salla) -> units = counter delta;
* otherwise a stock level that falls (Zid exact inventory) -> units = drop;
* consecutive ledger days at most MAX_GAP_DAYS apart; a single SKU-day above
  the caps is a stock adjustment, not a sale, and is left out.

Shared stock: some storefronts draw on one inventory (Mowkly, Panda Store and
aleef move by the same quantities on the same days). Their depletion is one
set of sales, so a drop that a group member already reported is not counted
again for another member. Groups are detected from the data, not configured.

`rebuild` materializes `ledger_sales_daily` (one row per store, offer, day) and
`ledger_sales_meta`; `sales_map` reads it in the shape of
`evidence_ledger.sales_map`, so every revenue view uses the same numbers.
"""
import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from observation_contract import stable_id
from sales_evidence import PLACEHOLDERS

logger = logging.getLogger(__name__)

VERSION = 3                   # 2: measured zeros; 3: ledger holes completed from snapshots
HOLE_FRACTION = 0.9           # a store-day below 90% of the store's median ledger rows is a hole
HOLE_MIN_ROWS = 50
MAX_GAP_DAYS = 2              # same 48 h limit as interval facts
STOCK_CAP_PER_DAY = 30        # same cap as sales_evidence (30 units / 24 h)
COUNTER_CAP_PER_DAY = 50      # same cap as sales_evidence for sold counters
SHARED_KEY_MIN_QTY = 20       # a drop from >= 20 units identifies a stock movement
SHARED_KEY_MIN_UNITS = 3
SHARED_MIN_KEYS = 30          # pairs sharing this many movements share stock...
SHARED_MIN_FRACTION = 0.15    # ...when that is this share of the smaller store's movements
DEDUPE_MIN_QTY = 10           # small drops (2 -> 1) coincide by chance; never deduped
BUILD_DAYS = 70
LEASE_KEY = "ledger-sales-rebuild"
_ROW_FIELDS = {"_id": 0, "store_id": 1, "sku": 1, "ksa_date": 1, "qty_available": 1,
               "sold_count_cumulative": 1, "close_price": 1, "in_stock": 1}


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _days_between(a, b):
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days


def _intervals(by_date, exact_stock):
    """Yield (date, units, revenue, source, key) for one store-SKU series.

    Zid storefronts expose exact inventory, so their sales are stock drops only:
    the Zid "sold" figure that appeared on 11 Oct 2026 is a lifetime total that
    goes down as well as up (25 -> 19), and its first appearance (0 -> 25) is
    not a sale. Elsewhere a sold counter present on both days takes precedence."""
    dates = sorted(by_date)
    counter_series = not exact_stock and any((_num(by_date[d].get("sold_count_cumulative")) or 0) > 0 for d in dates)
    for a, b in zip(dates, dates[1:]):
        gap = _days_between(a, b)
        if gap < 1 or gap > MAX_GAP_DAYS:
            continue
        ra, rb = by_date[a], by_date[b]
        price = _num(rb.get("close_price")) or _num(ra.get("close_price"))
        if counter_series:
            sa, sb = _num(ra.get("sold_count_cumulative")), _num(rb.get("sold_count_cumulative"))
            if not sa or not sb:          # absent or not yet reported: no interval
                continue
            units = sb - sa
            if units == 0:
                yield b, 0, 0.0, "sold_counter_diff", None     # measured: sold nothing
                continue
            if units < 0 or units > COUNTER_CAP_PER_DAY * gap:
                continue
            yield b, units, units * price if price else 0.0, "sold_counter_diff", None
        else:
            qa, qb = _num(ra.get("qty_available")), _num(rb.get("qty_available"))
            if qa is None or qb is None:
                continue
            if not exact_stock and (qa in PLACEHOLDERS or qa > 200 or qb in PLACEHOLDERS):
                continue
            if qb >= qa:
                # Exact stock read on both days with no drop is a measured zero
                # (a restock hides sales, so only an unchanged level counts).
                if exact_stock and qb == qa and qa > 0:
                    yield b, 0, 0.0, "stock_depletion", None
                continue
            units = qa - qb
            if units > STOCK_CAP_PER_DAY * gap:
                continue
            yield b, units, units * price if price else 0.0, "stock_depletion", (b, qa, qb)


def compute(rows, sealed, start_date, end_date, stores, offer_index):
    """Pure computation. rows: ledger rows; sealed: {(store_id, date)}; stores:
    {id: {"name", "platform"}}; offer_index: {(store_id, sku): offer_id}.
    Returns (facts, groups) where facts are per (store, offer, date)."""
    series = defaultdict(dict)
    for r in rows:
        if (r["store_id"], r["ksa_date"]) in sealed:
            series[(r["store_id"], r["sku"])][r["ksa_date"]] = r
    events = defaultdict(list)          # store_id -> [(date, sku, units, revenue, source, key)]
    for (sid, sku), by_date in series.items():
        exact = (stores.get(sid) or {}).get("platform") == "zid"
        for date, units, revenue, source, key in _intervals(by_date, exact):
            if start_date <= date <= end_date:
                events[sid].append((date, sku, units, revenue, source, key))

    # Shared-stock groups: stores whose stock moves by the same amounts on the same days.
    movement = {sid: {e[5] for e in evs if e[5] and e[5][1] >= SHARED_KEY_MIN_QTY and e[2] >= SHARED_KEY_MIN_UNITS}
                for sid, evs in events.items()}
    parent = {sid: sid for sid in events}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    ids = sorted(movement)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = len(movement[a] & movement[b])
            smaller = min(len(movement[a]), len(movement[b])) or 1
            if shared >= SHARED_MIN_KEYS and shared / smaller >= SHARED_MIN_FRACTION:
                parent[find(a)] = find(b)
    members = defaultdict(list)
    for sid in ids:
        members[find(sid)].append(sid)
    groups = []
    for group in members.values():
        if len(group) < 2:
            continue
        # The member with the most movements reports a shared drop; the others
        # report only drops no earlier member reported.
        order = sorted(group, key=lambda s: (-len(movement[s]), (stores.get(s) or {}).get("name", s)))
        groups.append({"lead": order[0], "members": order,
                       "names": [(stores.get(s) or {}).get("name", s) for s in order]})

    facts, deduped = {}, defaultdict(lambda: {"units": 0, "revenue": 0.0})
    observed = {}                       # (store, offer or sku) -> dates read on both days, no sale
    group_of = {sid: g for g in groups for sid in g["members"]}
    seen_by_group = defaultdict(set)
    store_order = sorted(events, key=lambda s: group_of[s]["members"].index(s) if s in group_of else 0)
    for sid in store_order:
        g = group_of.get(sid)
        for date, sku, units, revenue, source, key in events[sid]:
            oid = offer_index.get((sid, sku))
            if g and key and key[1] >= DEDUPE_MIN_QTY:
                bucket = seen_by_group[g["lead"]]
                if key in bucket:
                    deduped[sid]["units"] += units
                    deduped[sid]["revenue"] += revenue
                    units = 0               # counted under the lead; measured here as zero
                else:
                    bucket.add(key)
            if not units:
                o = observed.setdefault((sid, oid or sku), {"store_id": sid, "sku": sku, "offer_id": oid,
                                                             "source": source, "dates": set()})
                o["dates"].add(date)
                continue
            fid = (sid, oid or sku, date)
            f = facts.setdefault(fid, {"store_id": sid, "sku": sku, "offer_id": oid, "date": date,
                                       "units": 0.0, "revenue": 0.0, "source": source})
            f["units"] += units
            f["revenue"] += revenue
    for g in groups:
        g["deduped"] = {(stores.get(s) or {}).get("name", s): {"units": round(deduped[s]["units"]), "revenue": round(deduped[s]["revenue"], 2)}
                        for s in g["members"] if s in deduped}
    # A store whose readings never move in the window is not a live signal
    # (Hobba: static stock numbers), so its unchanged readings are not zeros.
    moving = {sid for sid, evs in events.items() if any(e[2] > 0 for e in evs)}
    obs = [{**o, "dates": sorted(o["dates"])} for o in observed.values() if o["store_id"] in moving]
    return list(facts.values()), groups, obs


async def fill_ledger_holes(db, rows, store_ids, read_from, end_date):
    """Closing rows for store-days the ledger missed, from the raw snapshots.

    The 9-11 Oct 2026 persistence failures left store-days whose snapshots were
    saved but whose ledger rows were not (Petsy, Hamtaro, CutePets on 11 Oct;
    Mowkly on 30 Sep; ...). A hole breaks the day-over-day chain, which
    understated competitor sales by 7-14% against a recount from the raw
    snapshots. A store-day with fewer than HOLE_FRACTION of the store's median
    ledger rows is completed from that day's last snapshot per SKU; SKUs the
    ledger already has for that day are left as they are."""
    from statistics import median
    from archive import ksa_day_bounds_utc
    count, have = defaultdict(int), defaultdict(set)
    for r in rows:
        count[(r["store_id"], r["ksa_date"])] += 1
        have[(r["store_id"], r["ksa_date"])].add(r["sku"])
    first = datetime.fromisoformat(read_from)
    days = [(first + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range((datetime.fromisoformat(end_date) - first).days + 1)]
    filled, pairs = [], []
    for sid in store_ids:
        seen = [count[(sid, d)] for d in days if count[(sid, d)]]
        if not seen or median(seen) < HOLE_MIN_ROWS:
            continue
        for day in days:
            if count[(sid, day)] >= HOLE_FRACTION * median(seen):
                continue
            start, end = ksa_day_bounds_utc(day)
            last = {}
            async for s in db.product_snapshots.find(
                    {"store_id": sid, "crawled_at": {"$gte": start, "$lt": end}, "is_synthetic": {"$ne": True}},
                    {"_id": 0, "sku": 1, "crawled_at": 1, "qty_available": 1, "sold_count": 1, "price": 1}):
                if s.get("sku") and s["sku"] not in have[(sid, day)]:
                    prev = last.get(s["sku"])
                    if prev is None or s["crawled_at"] > prev["crawled_at"]:
                        last[s["sku"]] = s
            for sku, s in last.items():
                filled.append({"store_id": sid, "sku": sku, "ksa_date": day, "qty_available": s.get("qty_available"),
                               "sold_count_cumulative": s.get("sold_count"), "close_price": s.get("price"),
                               "filled_from": "snapshots"})
            if last:
                pairs.append((sid, day))
    return filled, pairs


async def offer_index(db):
    """(store_id, sku) -> latest offer_id, from the immutable observation events."""
    out = {}
    pipeline = [{"$match": {"offer_id": {"$type": "string"}}}, {"$sort": {"observed_at": 1}},
                {"$group": {"_id": {"s": "$store_id", "k": "$sku"}, "o": {"$last": "$offer_id"}}}]
    async for r in db.observation_events.aggregate(pipeline, allowDiskUse=True):
        out[(r["_id"]["s"], r["_id"]["k"])] = r["o"]
    return out


async def rebuild(db, days=BUILD_DAYS, now=None):
    """Materialize the window ending with the last sealed KSA day."""
    import ledger
    now = now or datetime.now(timezone.utc)
    end_date = ledger.ksa_day_str(now - timedelta(days=1))
    start_date = ledger.ksa_day_str(now - timedelta(days=days))
    read_from = ledger.ksa_day_str(now - timedelta(days=days + MAX_GAP_DAYS))
    stores = {s["id"]: s async for s in db.stores.find({}, {"_id": 0, "id": 1, "name": 1, "platform": 1})}
    sealed = {(r["store_id"], r["ksa_date"]) async for r in db.daily_ledger_store.find(
        {"ksa_date": {"$gte": read_from, "$lte": end_date}, "sealed_at": {"$ne": None}},
        {"_id": 0, "store_id": 1, "ksa_date": 1})}
    rows = await db.daily_ledger.find({"ksa_date": {"$gte": read_from, "$lte": end_date}},
                                      _ROW_FIELDS).batch_size(5000).to_list(None)
    filled, filled_pairs = await fill_ledger_holes(db, rows, list(stores), read_from, end_date)
    rows += filled
    sealed |= set(filled_pairs)        # completed days only: end_date is yesterday
    index = await offer_index(db)
    facts, groups, observed = await asyncio.to_thread(compute, rows, sealed, start_date, end_date, stores, index)
    build = f"{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    docs = [{"_id": stable_id(VERSION, build, f["store_id"], f["offer_id"] or f["sku"], f["date"]), "build": build,
             **f, "units": round(f["units"], 2), "revenue": round(f["revenue"], 2)} for f in facts]
    obs_docs = [{"_id": stable_id(VERSION, build, o["store_id"], o["offer_id"] or o["sku"]), "build": build,
                 **o, "first": o["dates"][0], "last": o["dates"][-1]} for o in observed]
    try:
        await db.ledger_sales_daily.create_index([("build", 1), ("date", 1)])
        await db.ledger_sales_observed.create_index([("build", 1), ("last", 1)])
    except Exception:  # noqa: BLE001 — reads still work on a small collection
        logger.warning("[LedgerSales] index creation failed", exc_info=True)
    for coll, rows_out in ((db.ledger_sales_daily, docs), (db.ledger_sales_observed, obs_docs)):
        for i in range(0, len(rows_out), 5000):
            await coll.insert_many(rows_out[i:i + 5000], ordered=False)
    await db.ledger_sales_meta.update_one({"_id": "current"}, {"$set": {
        "build": build, "built_at": now, "start_date": start_date, "end_date": end_date,
        "facts": len(docs), "observed": len(obs_docs), "groups": groups, "version": VERSION,
        "filled_store_days": [{"store": (stores.get(s) or {}).get("name", s), "date": d} for s, d in sorted(filled_pairs)],
        "filled_rows": len(filled)}}, upsert=True)
    await db.ledger_sales_daily.delete_many({"build": {"$ne": build}})
    await db.ledger_sales_observed.delete_many({"build": {"$ne": build}})
    # Cached pages are keyed on the observation revision: new evidence, new pages.
    await db.data_versions.update_one({"_id": "observations"}, {"$inc": {"revision": 1}}, upsert=True)
    logger.info("[LedgerSales] build %s: %d facts %s..%s, shared groups %s", build, len(docs),
                start_date, end_date, [g["names"] for g in groups])
    return {"build": build, "facts": len(docs), "start_date": start_date, "end_date": end_date, "groups": groups}


async def rebuild_if_stale(db, now=None):
    """Run once per newly sealed KSA day (cheap no-op otherwise)."""
    import ledger
    import job_control
    now = now or datetime.now(timezone.utc)
    meta = await db.ledger_sales_meta.find_one({"_id": "current"}, {"_id": 0, "end_date": 1, "version": 1})
    if (meta and meta.get("version") == VERSION
            and meta.get("end_date") == ledger.ksa_day_str(now - timedelta(days=1))):
        return None
    owner = uuid.uuid4().hex
    if not await job_control.acquire(db, LEASE_KEY, owner, hours=1):
        return None
    try:
        return await rebuild(db, now=now)
    finally:
        await job_control.release(db, LEASE_KEY, owner)


async def meta(db):
    return await db.ledger_sales_meta.find_one({"_id": "current"}, {"_id": 0}) or {}


async def sales_map(db, start, end, sealed=True):
    """Same shape as evidence_ledger.sales_map, from the materialized ledger facts."""
    from ledger import ksa_day_str
    m = await meta(db)
    if not m:
        return {}
    q = {"build": m["build"], "date": {"$gte": ksa_day_str(start), "$lte": ksa_day_str(end - timedelta(seconds=1))}}
    out = {}
    async for r in db.ledger_sales_daily.find(q, {"_id": 0}):
        key = (r["store_id"], r.get("offer_id") or r["sku"])
        a = out.setdefault(key, {"sku": r["sku"], "offer_id": r.get("offer_id"), "units": 0, "revenue": 0.0,
                                 "source": r["source"], "intervals": 0, "value_basis": "shelf_price_proxy",
                                 "days": set(), "by_day": {}})
        a["units"] += r["units"]
        a["revenue"] += r["revenue"]
        a["intervals"] += 1
        a["days"].add(r["date"])
        a["by_day"][r["date"]] = a["by_day"].get(r["date"], 0) + r["revenue"]
    # Offers read on two consecutive days without a sale: a measured zero, so
    # market share can tell "sold nothing" from "cannot see this seller".
    lo, hi = q["date"]["$gte"], q["date"]["$lte"]
    async for r in db.ledger_sales_observed.find({"build": m["build"], "last": {"$gte": lo}, "first": {"$lte": hi}},
                                                  {"_id": 0}):
        dates = [d for d in r["dates"] if lo <= d <= hi]
        if not dates:
            continue
        key = (r["store_id"], r.get("offer_id") or r["sku"])
        a = out.setdefault(key, {"sku": r["sku"], "offer_id": r.get("offer_id"), "units": 0, "revenue": 0.0,
                                 "source": r["source"], "intervals": 0, "value_basis": "shelf_price_proxy",
                                 "days": set(), "by_day": {}})
        a["intervals"] += len(dates)
        a["days"].update(dates)
    for a in out.values():
        a["days"] = sorted(a["days"])
        a["revenue"] = round(a["revenue"], 2)
    return out


def shared_group_of(groups, store_id):
    return next((g for g in groups or () if store_id in g.get("members", ())), None)
