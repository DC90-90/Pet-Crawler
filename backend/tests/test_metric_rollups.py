"""iter30/iter31 — write-time metric rollups.

iter30 moved price_drops / product_gaps / median_spread off the read path;
iter31 moved avg_confidence, the freshness breakdown and the market-position 7d
snapshot fetch too. After iter31, _insights_summary_compute must not touch
product_snapshots AT ALL — asserted below by tokenizing its source.

The write-time rebuild (find + Python + insert) runs natively on the FerretDB
sandbox shim, so the integration test exercises the REAL machinery against real
Mongo: seed controlled snapshots → run the real rebuild → validate the built
collections and (where the shim supports the operators) the real read helpers.

Plus pure-Python cross-checks that the coverage-derived product_gaps and
median_spread are byte-identical to the OLD snapshot-scan definitions.
"""
import asyncio
import io
import inspect
import os
import random
import statistics
import sys
import tokenize
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_metric_rollups"
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
FLOOR = server.MIN_AGGREGATION_CONFIDENCE


def _snap(store, sku, days_ago, price, conf=99, in_stock=True, qty=5, sold=0):
    # distinct crawled_at per (store,sku,day); spread within the day is irrelevant
    # because the rollup keeps the LATEST price of each day.
    base = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {"id": f"{store}-{sku}-{days_ago}", "store_id": store, "sku": sku,
            "store_name": f"{store}-name", "in_stock": in_stock, "qty_available": qty,
            "sold_count": sold, "price": float(price), "confidence_score": conf,
            "crawled_at": base.replace(microsecond=days_ago * 1000)}


# Controlled dataset with hand-computed expectations (all within the last 3 days).
SNAPS = [
    # S1 / sku A: 20 -> 10 (drop) -> 15 (rise)   => 1 drop event; in stock
    _snap("S1", "A", 3, 20), _snap("S1", "A", 2, 10), _snap("S1", "A", 1, 15),
    # S1 / sku B: 50 -> 40 (drop); qty 10 -> 6    => 1 drop + 4 units qty-depletion
    _snap("S1", "B", 3, 50, qty=10), _snap("S1", "B", 2, 40, qty=6),
    # S2 / sku A: 30 -> 25 (drop); LATEST is OOS  => restock candidate; qty 5->0 = 5 units
    _snap("S2", "A", 3, 30), _snap("S2", "A", 2, 25, in_stock=False, qty=0),
    # S1 / sku F: sold_count 10 -> 14 (+4) with qty 50 -> 48 (-2). The counter
    # method must WIN per pair (units 4, not 2), matching the estimator's
    # Method-1 preference; the raw qty_drop (2) still feeds trending.
    _snap("S1", "F", 3, 30, qty=50, sold=10), _snap("S1", "F", 2, 30, qty=48, sold=14),
    _snap("S1", "F", 1, 30, qty=48, sold=14),
    # S2 / sku C: single day, floor confidence    => 0 drops, pulls avg down
    _snap("S2", "C", 2, 5, conf=FLOOR),
    # S3 / sku A: single day                      => 0
    _snap("S3", "A", 1, 22),
    # iter33 — sku E: accepted but price 0 (crawler tiers CAN write price-0):
    # counts for summary-gaps/freshness/restock (no price filter) but must be
    # EXCLUDED from endpoint-gaps and price-wars (price>0 filter).
    _snap("S1", "E", 2, 0),
    # low-confidence noise: would be a drop but must be EXCLUDED from accepted
    # metrics (drops/gaps/spread/conf) — yet still counted by FRESHNESS, which
    # never had a confidence filter.
    _snap("S1", "D", 3, 100, conf=max(0, FLOOR - 1)),
    _snap("S1", "D", 2, 50, conf=max(0, FLOOR - 1)),
]
# Expected (window covering all days):
#   drops = 3  (S1/A, S1/B, S2/A; E flat, F flat price, D low-conf)
#   summary gaps (no price filter) = 4: B(1 store), C(1), E(1), F(1); A in 3 no
#   endpoint gaps (price>0, total_stores=3) = B, C, F (E has no priced crawl)
#   latest accepted price per (sku,store): A:{S1:15,S2:25,S3:22}=>spread 10;
#     B/C/E/F single store => 0 → median over >0 spreads = 10.0
#   avg_confidence = snapshot-weighted mean over the 13 ACCEPTED snaps
#   freshness: 8 pairs total (incl. low-conf D + price-0 E) → this_week=8
#   restock: sku A only (S2 OOS, S1+S3 in stock)
#   sales (iter34, all deltas land on day-2): S1/B qty-method 4u @40=160;
#     S2/A qty-method 5u @25=125; S1/F counter-method 4u @30=120 (qty drop 2
#     recorded for trending but counter wins the pair)
EXPECT_DROPS, EXPECT_GAPS, EXPECT_SPREAD = 3, 4, 10.0
_ACCEPTED_CONFS = [s["confidence_score"] for s in SNAPS if s["confidence_score"] >= FLOOR]
EXPECT_CONF_AVG = sum(_ACCEPTED_CONFS) / len(_ACCEPTED_CONFS)
EXPECT_PAIRS = 8          # 7 accepted pairs + S1/D (low-conf only)
EXPECT_FRESH = {"total": 8, "today": 0, "this_week": 8, "this_month": 0, "stale": 0}
EXPECT_SALES = {  # (store, sku) -> (units, revenue, qty_drop)
    ("S1", "B"): (4, 160.0, 4),
    ("S2", "A"): (5, 125.0, 5),
    ("S1", "F"): (4, 120.0, 2),
}


async def _fresh_db(name):
    db = AsyncIOMotorClient(MONGO)[name]
    for c in ("product_snapshots", "metric_daily_rollups", "sku_store_coverage",
              "sku_sales_daily", "metric_rollup_meta"):
        await db[c].delete_many({})
    return db


async def _try_helper(coro):
    """Run a real read helper; return its value, or None if the FerretDB shim
    lacks an operator the helper uses ($min/$max/$cond/$sum). On Atlas these all
    exist, so None only ever happens in the sandbox."""
    try:
        return await coro
    except Exception as e:
        if "not implemented" in str(e).lower():
            return None
        raise


def _naive(dt):
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def _run_integration():
    db = await _fresh_db("test_metric_rollups")
    await db.product_snapshots.insert_many([dict(s) for s in SNAPS])
    # The novel/risky part — the write-time rebuild (find + Python + insert) — runs
    # natively on FerretDB, so this exercises the REAL machinery on real Mongo.
    stats = await server.recompute_all_store_metrics(db)
    assert stats["stores"] == 3, stats
    assert stats["pairs"] == EXPECT_PAIRS, stats

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=30)
    since_str = server._metric_day_str(since)
    since_naive = since.replace(tzinfo=None)

    # ── Validate the built collections directly (backend-independent) ──
    rollups = await db.metric_daily_rollups.find({}, {"_id": 0}).to_list(length=None)
    in_window = [r for r in rollups if r["date"] >= since_str]
    drops = sum(r["drops"] for r in in_window)
    assert drops == EXPECT_DROPS, f"rollup drops {drops} != {EXPECT_DROPS}"
    # iter31: per-day confidence sums — windowed snapshot-weighted mean
    conf_sum = sum(r["conf_sum"] for r in in_window)
    conf_count = sum(r["conf_count"] for r in in_window)
    assert conf_count == len(_ACCEPTED_CONFS), conf_count
    assert abs(conf_sum / conf_count - EXPECT_CONF_AVG) < 1e-9

    coverage = await db.sku_store_coverage.find({}, {"_id": 0}).to_list(length=None)
    assert len(coverage) == EXPECT_PAIRS
    # iter31: low-conf sku D HAS a coverage doc (freshness counts it) but carries
    # NO accepted fields (gaps/spread/market-position exclude it).
    d_docs = [c for c in coverage if c["sku"] == "D"]
    assert len(d_docs) == 1
    assert "last_seen_any_at" in d_docs[0]
    assert "last_seen_at" not in d_docs[0] and "last_price" not in d_docs[0]
    # accepted pairs: last_price = latest accepted price; last_confidence present
    lp = {(c["sku"], c["store_id"]): c.get("last_price") for c in coverage}
    assert lp[("A", "S1")] == 15 and lp[("A", "S2")] == 25 and lp[("A", "S3")] == 22
    assert lp[("B", "S1")] == 40 and lp[("C", "S2")] == 5
    lc = {(c["sku"], c["store_id"]): c.get("last_confidence") for c in coverage}
    assert lc[("C", "S2")] == FLOOR and lc[("A", "S1")] == 99

    # ── iter33: stock + priced fields ──
    cov_by_key = {(c["sku"], c["store_id"]): c for c in coverage}
    a_s2 = cov_by_key[("A", "S2")]
    assert a_s2["last_in_stock"] is False and a_s2["last_qty"] == 0
    assert a_s2["last_store_name"] == "S2-name"
    assert a_s2["last_priced_price"] == 25          # latest price>0 crawl
    e_s1 = cov_by_key[("E", "S1")]
    assert e_s1.get("last_price") == 0 and "last_seen_at" in e_s1
    assert "last_priced_at" not in e_s1             # price-0 only → never priced
    assert e_s1["last_in_stock"] is True

    # endpoint-gaps (price>0, total_stores=3): B and C only — E excluded
    ep_gaps = {}
    for c in coverage:
        lpa = c.get("last_priced_at")
        if lpa is not None and _naive(lpa) >= since_naive:
            ep_gaps[c["sku"]] = ep_gaps.get(c["sku"], 0) + 1
    assert {k: v for k, v in ep_gaps.items() if v < 3} == {"B": 1, "C": 1, "F": 1}
    # price-wars (>=3 priced stores): only A — min 15 / max 25 / spread 10
    assert ep_gaps.get("A") == 3
    # restock: only A has mixed stock state (S2 OOS; S1+S3 in stock)
    mixed = {}
    for c in coverage:
        ls = c.get("last_seen_at")
        if ls is not None and _naive(ls) >= since_naive:
            m = mixed.setdefault(c["sku"], {"oos": [], "ins": []})
            (m["ins"] if c["last_in_stock"] else m["oos"]).append(c["last_store_name"])
    restock_skus = {k for k, m in mixed.items() if m["oos"] and m["ins"]}
    assert restock_skus == {"A"}, restock_skus
    assert mixed["A"]["oos"] == ["S2-name"] and sorted(mixed["A"]["ins"]) == ["S1-name", "S3-name"]

    # ── iter34: daily sales facts ──
    sales = await db.sku_sales_daily.find({}, {"_id": 0}).to_list(length=None)
    # per-pair method selection mirror of _sales_pairs_from_rollups
    per_pair = {}
    for r in sales:
        key = (r["store_id"], r["sku"])
        acc = per_pair.setdefault(key, [0, 0.0, 0, 0.0, 0])
        acc[0] += r["units_sold"]; acc[1] += r["rev_sold"]
        acc[2] += r["units_qty"]; acc[3] += r["rev_qty"]; acc[4] += r["qty_drop"]
    resolved = {k: ((a[0], a[1], a[4]) if a[0] > 0 else (a[2], a[3], a[4]))
                for k, a in per_pair.items()}
    assert resolved == EXPECT_SALES, resolved
    # F's doc must carry BOTH variants (counter 4 units / qty 2 units)
    f_doc = next(r for r in sales if r["sku"] == "F")
    assert f_doc["units_sold"] == 4 and f_doc["units_qty"] == 2 and f_doc["qty_drop"] == 2
    # price-0 sku E and low-conf D must have no sales docs
    assert not any(r["sku"] in ("D", "E") for r in sales)

    # real iter34 read helper (where the shim supports the operators)
    h_sp = await _try_helper(server._sales_pairs_from_rollups(db, since))
    if h_sp is not None:
        got = {(p["store_id"], p["sku"]): (p["units"], round(p["revenue"], 2), p["qty_drop"]) for p in h_sp}
        assert got == EXPECT_SALES, got

    # real iter33 read helpers (where the shim supports the operators)
    h_gr = await _try_helper(server._gaps_rows_from_coverage(db, since, 3))
    if h_gr is not None:
        assert {g["_id"]: g["num_stores"] for g in h_gr} == {"B": 1, "C": 1, "F": 1}
    h_pw = await _try_helper(server._price_wars_rows_from_coverage(db, since))
    if h_pw is not None:
        assert len(h_pw) == 1 and h_pw[0]["sku"] == "A" and h_pw[0]["spread"] == 10
    h_rs = await _try_helper(server._restock_rows_from_coverage(db, since))
    if h_rs is not None:
        rs = {r["_id"]: r["stores"] for r in h_rs}
        assert "A" in rs and len(rs["A"]) == 3

    # gaps + spread from coverage (Python mirror of the read helpers)
    per_sku_stores, per_sku_prices = {}, {}
    for c in coverage:
        ls = c.get("last_seen_at")
        if ls is not None and _naive(ls) >= since_naive:
            per_sku_stores[c["sku"]] = per_sku_stores.get(c["sku"], 0) + 1
            per_sku_prices.setdefault(c["sku"], []).append(c["last_price"])
    gaps = sum(1 for n in per_sku_stores.values() if n < 3)
    assert gaps == EXPECT_GAPS, f"coverage gaps {gaps} != {EXPECT_GAPS}"
    spreads = [max(v) - min(v) for v in per_sku_prices.values() if max(v) - min(v) > 0]
    assert round(statistics.median(spreads), 2) == EXPECT_SPREAD

    # freshness from coverage (Python mirror of _freshness_from_coverage)
    day_24h = _naive(now - timedelta(hours=24))
    day_7d = _naive(now - timedelta(days=7))
    day_30d = _naive(now - timedelta(days=30))
    fr = {"total": 0, "today": 0, "this_week": 0, "this_month": 0, "stale": 0}
    for c in coverage:
        la = _naive(c["last_seen_any_at"])
        fr["total"] += 1
        if la >= day_24h:
            fr["today"] += 1
        elif la >= day_7d:
            fr["this_week"] += 1
        elif la >= day_30d:
            fr["this_month"] += 1
        else:
            fr["stale"] += 1
    assert fr == EXPECT_FRESH, fr

    # ── Also run the REAL read helpers where the shim supports the operators ──
    h_drops = await _try_helper(server._drops_from_rollups(db, since))
    if h_drops is not None:
        assert h_drops == EXPECT_DROPS, f"_drops_from_rollups {h_drops}"
    h_gaps = await _try_helper(server._gaps_from_coverage(db, since))
    if h_gaps is not None:
        assert h_gaps == EXPECT_GAPS, f"_gaps_from_coverage {h_gaps}"
    h_spread = await _try_helper(server._spread_docs_from_coverage(db, since))
    if h_spread is not None:
        hv = [d["max_p"] - d["min_p"] for d in h_spread if d["max_p"] > d["min_p"]]
        assert round(statistics.median(hv), 2) == EXPECT_SPREAD
    h_conf = await _try_helper(server._conf_avg_from_rollups(db, since))
    if h_conf is not None:
        assert abs(h_conf - EXPECT_CONF_AVG) < 1e-9, h_conf
    h_fresh = await _try_helper(server._freshness_from_coverage(db, now))
    if h_fresh is not None:
        assert {k: h_fresh.get(k, 0) for k in EXPECT_FRESH} == EXPECT_FRESH

    # ── Idempotency: rebuild again → identical reads and no dup docs ──
    n_cov = await db.sku_store_coverage.count_documents({})
    n_roll = await db.metric_daily_rollups.count_documents({})
    await server.recompute_all_store_metrics(db)
    assert await db.sku_store_coverage.count_documents({}) == n_cov
    assert await db.metric_daily_rollups.count_documents({}) == n_roll
    rollups2 = await db.metric_daily_rollups.find({}, {"_id": 0}).to_list(length=None)
    assert sum(r["drops"] for r in rollups2 if r["date"] >= since_str) == EXPECT_DROPS

    # ── iter34 schema-version guard: a stale (or missing) version marker forces
    # a full rebuild at startup — this is how iter31/iter33/iter34 field
    # additions reach an already-deployed database. Simulate a pre-upgrade DB:
    # strip newer fields, wipe the sales collection, downgrade the marker.
    await db.sku_store_coverage.update_many(
        {}, {"$unset": {"last_seen_any_at": "", "last_in_stock": "", "last_priced_at": ""}})
    await db.sku_sales_daily.delete_many({})
    await db.metric_rollup_meta.delete_many({})   # pre-marker deploys have no doc
    await server._maybe_backfill_store_metrics(db)
    assert await db.sku_store_coverage.count_documents({"last_seen_any_at": {"$exists": True}}) == EXPECT_PAIRS
    assert await db.sku_store_coverage.count_documents({"last_in_stock": {"$exists": True}}) == EXPECT_PAIRS - 1  # all but low-conf D
    assert await db.sku_sales_daily.count_documents({}) == len(EXPECT_SALES)
    marker = await db.metric_rollup_meta.find_one({"_id": "schema"})
    assert marker and marker["version"] == server._METRIC_SCHEMA_VERSION
    # …and a CURRENT marker must NOT retrigger a rebuild (delete sales docs as a
    # tracer: if backfill ran again they would reappear).
    await db.sku_sales_daily.delete_many({})
    await server._maybe_backfill_store_metrics(db)
    assert await db.sku_sales_daily.count_documents({}) == 0
    # restore consistent state for anything running after
    await server.recompute_all_store_metrics(db)


def test_integration_rollups_ferretdb():
    # asyncio.run (not get_event_loop) — robust to earlier tests closing the loop;
    # the Motor client is created inside the coroutine so it binds to this loop.
    asyncio.run(_run_integration())


def test_summary_compute_never_touches_product_snapshots():
    """iter31 contract: _insights_summary_compute and every read helper it uses
    must not reference product_snapshots in CODE (comments don't count)."""
    def code_of(fn):
        src = inspect.getsource(fn)
        toks = tokenize.generate_tokens(io.StringIO(src).readline)
        return " ".join(t.string for t in toks if t.type != tokenize.COMMENT)

    assert "product_snapshots" not in code_of(server._insights_summary_compute)
    for h in (server._drops_from_rollups, server._gaps_from_coverage,
              server._spread_docs_from_coverage, server._conf_avg_from_rollups,
              server._freshness_from_coverage,
              # iter33 — gaps / price-wars / restock endpoints + their helpers
              server._insights_gaps_compute, server._insights_price_wars_compute,
              server._insights_restock_compute, server._gaps_rows_from_coverage,
              server._price_wars_rows_from_coverage, server._restock_rows_from_coverage,
              # iter34 — leaderboard / top-sellers / trending + sales helper
              server._insights_leaderboard_compute, server._insights_top_sellers_compute,
              server._insights_trending_compute, server._sales_pairs_from_rollups):
        assert "product_snapshots" not in code_of(h), h.__name__


# ── pure-Python cross-checks: coverage semantics == OLD snapshot definitions ──
def _old_gaps(snaps, since):
    # OLD pipeline_gaps: group by sku, $addToSet store, count skus with <3 stores
    per_sku = {}
    for s in snaps:
        if s["confidence_score"] >= FLOOR and s["crawled_at"] >= since:
            per_sku.setdefault(s["sku"], set()).add(s["store_id"])
    return sum(1 for stores in per_sku.values() if len(stores) < 3)


def _cov_gaps(snaps, since):
    # coverage: last_seen (accepted) per (sku,store); count stores with last_seen>=since
    last_seen = {}
    for s in snaps:
        if s["confidence_score"] >= FLOOR:
            k = (s["sku"], s["store_id"])
            if k not in last_seen or s["crawled_at"] > last_seen[k]:
                last_seen[k] = s["crawled_at"]
    per_sku = {}
    for (sku, store), ts in last_seen.items():
        if ts >= since:
            per_sku[sku] = per_sku.get(sku, 0) + 1
    return sum(1 for n in per_sku.values() if n < 3)


def _old_spread(snaps, since):
    # OLD pipeline_spread: latest price per (sku,store) in window, per-sku max-min
    latest = {}
    for s in snaps:
        if s["confidence_score"] >= FLOOR and s["crawled_at"] >= since:
            k = (s["sku"], s["store_id"])
            if k not in latest or s["crawled_at"] > latest[k][0]:
                latest[k] = (s["crawled_at"], s["price"])
    per_sku = {}
    for (sku, store), (_ts, price) in latest.items():
        per_sku.setdefault(sku, []).append(price)
    vals = [max(v) - min(v) for v in per_sku.values() if max(v) - min(v) > 0]
    return round(statistics.median(vals), 2) if vals else 0


def _cov_spread(snaps, since):
    last = {}
    for s in snaps:
        if s["confidence_score"] >= FLOOR:
            k = (s["sku"], s["store_id"])
            if k not in last or s["crawled_at"] > last[k][0]:
                last[k] = (s["crawled_at"], s["price"])
    per_sku = {}
    for (sku, store), (ts, price) in last.items():
        if ts >= since:                                  # last_seen>=since filter
            per_sku.setdefault(sku, []).append(price)
    vals = [max(v) - min(v) for v in per_sku.values() if max(v) - min(v) > 0]
    return round(statistics.median(vals), 2) if vals else 0


def _old_freshness(snaps, now):
    # OLD freshness_pipeline: per-(sku,store) $max crawled_at over ALL snapshots
    # (no confidence filter), bucketed today/week/month/stale.
    latest = {}
    for s in snaps:
        k = (s["sku"], s["store_id"])
        if k not in latest or s["crawled_at"] > latest[k]:
            latest[k] = s["crawled_at"]
    fr = {"total": 0, "today": 0, "this_week": 0, "this_month": 0, "stale": 0}
    d24, d7, d30 = now - timedelta(hours=24), now - timedelta(days=7), now - timedelta(days=30)
    for ts in latest.values():
        fr["total"] += 1
        if ts >= d24:
            fr["today"] += 1
        elif ts >= d7:
            fr["this_week"] += 1
        elif ts >= d30:
            fr["this_month"] += 1
        else:
            fr["stale"] += 1
    return fr


def _cov_freshness(snaps, now):
    # coverage: last_seen_any_at per pair (all confidences), same bucketing
    last_any = {}
    for s in snaps:
        k = (s["sku"], s["store_id"])
        if k not in last_any or s["crawled_at"] > last_any[k]:
            last_any[k] = s["crawled_at"]
    fr = {"total": 0, "today": 0, "this_week": 0, "this_month": 0, "stale": 0}
    d24, d7, d30 = now - timedelta(hours=24), now - timedelta(days=7), now - timedelta(days=30)
    for ts in last_any.values():
        fr["total"] += 1
        if ts >= d24:
            fr["today"] += 1
        elif ts >= d7:
            fr["this_week"] += 1
        elif ts >= d30:
            fr["this_month"] += 1
        else:
            fr["stale"] += 1
    return fr


def _old_conf_avg(snaps, since):
    # OLD pipeline_conf: $avg confidence over accepted snapshots in the window
    vals = [s["confidence_score"] for s in snaps
            if s["confidence_score"] >= FLOOR and s["crawled_at"] >= since]
    return round(sum(vals) / len(vals), 1) if vals else 0


def _rollup_conf_avg(snaps, since_day):
    # rollup: per-day conf sums over accepted snapshots, windowed by calendar day
    day_conf = {}
    for s in snaps:
        if s["confidence_score"] >= FLOOR:
            day = s["crawled_at"].strftime("%Y-%m-%d")
            dc = day_conf.setdefault(day, [0.0, 0])
            dc[0] += s["confidence_score"]
            dc[1] += 1
    tot_s = sum(v[0] for d, v in day_conf.items() if d >= since_day)
    tot_n = sum(v[1] for d, v in day_conf.items() if d >= since_day)
    return round(tot_s / tot_n, 1) if tot_n else 0


def _rand_snaps(rng):
    snaps = []
    now = datetime.now(timezone.utc)
    for _ in range(rng.randint(5, 60)):
        store = f"S{rng.randint(0, 5)}"
        sku = f"K{rng.randint(0, 8)}"
        days_ago = rng.randint(0, 45)
        snaps.append({"store_id": store, "sku": sku, "store_name": f"{store}-name",
                      # ~1 in 8 snapshots price 0 — crawler tiers can write these,
                      # and the endpoint gaps/price-wars price>0 filter must hold
                      "price": 0.0 if rng.random() < 0.125 else float(rng.randint(5, 300)),
                      "in_stock": rng.random() < 0.7,
                      "qty_available": rng.randint(0, 50),
                      "confidence_score": rng.choice([FLOOR, 99, max(0, FLOOR - 5)]),
                      "crawled_at": now - timedelta(days=days_ago, seconds=rng.randint(0, 80000))})
    return snaps


# ── iter33 models: endpoint gaps / price-wars / restock, old vs coverage ──────
def _pair_latest(snaps, since, need_priced):
    """Latest in-window accepted snapshot per (sku,store); need_priced adds the
    endpoints' price>0 predicate. OLD semantics: filter first, then latest."""
    latest = {}
    for s in snaps:
        if s["confidence_score"] < FLOOR or s["crawled_at"] < since:
            continue
        if need_priced and not (s["price"] > 0):
            continue
        k = (s["sku"], s["store_id"])
        if k not in latest or s["crawled_at"] > latest[k]["crawled_at"]:
            latest[k] = s
    return latest


def _cov_pair_latest(snaps, since, need_priced):
    """COVERAGE semantics: latest [priced] accepted snapshot OVERALL per pair,
    then filter its timestamp into the window."""
    latest = {}
    for s in snaps:
        if s["confidence_score"] < FLOOR:
            continue
        if need_priced and not (s["price"] > 0):
            continue
        k = (s["sku"], s["store_id"])
        if k not in latest or s["crawled_at"] > latest[k]["crawled_at"]:
            latest[k] = s
    return {k: v for k, v in latest.items() if v["crawled_at"] >= since}


def _gaps_rows_model(latest, total_stores):
    per_sku = {}
    for (sku, _st) in latest:
        per_sku[sku] = per_sku.get(sku, 0) + 1
    return {sku: n for sku, n in per_sku.items() if n < total_stores}


def _wars_rows_model(latest):
    per_sku = {}
    for (sku, _st), s in latest.items():
        per_sku.setdefault(sku, []).append((s["store_name"], s["price"]))
    out = {}
    for sku, entries in per_sku.items():
        prices = [p for _n, p in entries]
        if len(entries) >= 3 and min(prices) > 0:
            out[sku] = (len(entries), min(prices), max(prices), tuple(sorted(entries)))
    return out


def _restock_rows_model(latest):
    per_sku = {}
    for (sku, _st), s in latest.items():
        m = per_sku.setdefault(sku, {"oos": [], "ins": []})
        (m["ins"] if s["in_stock"] else m["oos"]).append((s["store_name"], s["qty_available"]))
    return {sku: (tuple(sorted(m["oos"])), tuple(sorted(m["ins"])))
            for sku, m in per_sku.items() if m["oos"] and m["ins"]}


# ── iter34 models: daily-close sales rollup vs the live estimator ─────────────
def _daily_sales_model(snaps, since_day):
    """Python mirror of the iter34 rebuild + _sales_pairs_from_rollups read for
    ONE (sku, store): returns (units, revenue, qty_drop) over the window."""
    daymap = {}
    for s in snaps:
        if s["confidence_score"] < FLOOR:
            continue
        day = s["crawled_at"].strftime("%Y-%m-%d")
        cur = daymap.get(day)
        if cur is None or s["crawled_at"] > cur["crawled_at"]:
            daymap[day] = s
    prev_sold = prev_raw = None
    last_valid = None
    s_units = q_units = drop = 0
    s_rev = q_rev = 0.0
    for day in sorted(daymap):
        s = daymap[day]
        price = s["price"]
        if price is None or price <= 0:
            continue
        cur_sold = s.get("sold_count", 0) or 0
        cur_raw = s.get("qty_available", 0) or 0
        cur_valid = cur_raw if (cur_raw not in server.PLACEHOLDER_QTY_VALUES and cur_raw <= 200) else None
        us = uq = qd = 0
        if prev_sold is not None:
            d = cur_sold - prev_sold
            if d > 0:
                us = min(d, server.MAX_SOLD_COUNT_DELTA_PER_INTERVAL)
            rd = prev_raw - cur_raw
            if rd > 0:
                qd = rd
        if last_valid is not None and cur_valid is not None:
            vd = last_valid - cur_valid
            if vd > 0:
                uq = min(vd, server.MAX_DAILY_SALES_PER_SKU)
        if cur_valid is not None:
            last_valid = cur_valid
        prev_sold, prev_raw = cur_sold, cur_raw
        if day >= since_day:
            s_units += us
            s_rev += round(us * price, 4)
            q_units += uq
            q_rev += round(uq * price, 4)
            drop += qd
    if s_units > 0:
        return s_units, s_rev, drop
    return q_units, q_rev, drop


def test_sales_rollup_matches_estimator_under_production_conditions():
    """Where the old and new definitions are meant to coincide — ≤1 snapshot per
    (pair, day) (production reality since the change-only-writes fix), all
    snapshots inside the window, constant price per pair, deltas under the caps,
    no placeholder quantities — the rollup totals must equal the REAL
    _estimate_sales_from_snapshots output exactly (units) / within accumulated
    rounding (revenue), and qty_drop must equal trending's raw positive-delta
    sum. Divergences outside these conditions are the documented iter34
    semantic changes."""
    rng = random.Random(20260803)
    now = datetime.now(timezone.utc)
    for _ in range(1500):
        days = rng.choice([7, 14, 30])
        since = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        since_day = since.strftime("%Y-%m-%d")
        n_days = rng.randint(2, min(days, 12))
        price = float(rng.randint(5, 300))
        use_counter = rng.random() < 0.4
        flat_counter = rng.random() < 0.2   # sold data present but never steps
        sold = rng.randint(0, 500)
        qty = rng.randint(20, 50)
        snaps = []
        day_offsets = sorted(rng.sample(range(days), n_days))
        for off in day_offsets:
            if use_counter and not flat_counter:
                sold += rng.randint(0, 8)
            if rng.random() < 0.15:
                qty = min(50, qty + rng.randint(6, 15))   # restock
            else:
                qty = max(0, qty - rng.randint(0, 6))     # depletion
            snaps.append({"store_id": "S", "sku": "K", "price": price,
                          "confidence_score": 99,
                          "sold_count": sold if use_counter else 0,
                          "qty_available": qty,
                          "crawled_at": since + timedelta(days=off, hours=12)})
        # OLD: real estimator over the window-filtered chronological list
        old_units, old_rev, _m = server._estimate_sales_from_snapshots(snaps, days)
        # OLD trending: raw positive deltas between consecutive snapshots
        old_drop = sum(max(0, snaps[i - 1]["qty_available"] - snaps[i]["qty_available"])
                       for i in range(1, len(snaps)))
        new_units, new_rev, new_drop = _daily_sales_model(snaps, since_day)
        assert new_units == old_units, (new_units, old_units)
        assert abs(new_rev - old_rev) < 0.02, (new_rev, old_rev)
        assert new_drop == old_drop, (new_drop, old_drop)


def test_endpoint_gaps_wars_restock_match_old_definitions():
    rng = random.Random(20260802)
    now = datetime.now(timezone.utc)
    for _ in range(3000):
        snaps = _rand_snaps(rng)
        since = now - timedelta(days=rng.choice([7, 14, 30, 90]))
        total_stores = rng.randint(0, 6)
        old_p = _pair_latest(snaps, since, need_priced=True)
        cov_p = _cov_pair_latest(snaps, since, need_priced=True)
        assert _gaps_rows_model(old_p, total_stores) == _gaps_rows_model(cov_p, total_stores)
        assert _wars_rows_model(old_p) == _wars_rows_model(cov_p)
        old_a = _pair_latest(snaps, since, need_priced=False)
        cov_a = _cov_pair_latest(snaps, since, need_priced=False)
        assert _restock_rows_model(old_a) == _restock_rows_model(cov_a)


def test_coverage_gaps_and_spread_match_old_definitions():
    rng = random.Random(20260730)
    now = datetime.now(timezone.utc)
    for _ in range(3000):
        snaps = _rand_snaps(rng)
        since = now - timedelta(days=rng.choice([7, 14, 30, 90]))
        assert _cov_gaps(snaps, since) == _old_gaps(snaps, since)
        assert _cov_spread(snaps, since) == _old_spread(snaps, since)


def test_coverage_freshness_identical_to_old_pipeline():
    rng = random.Random(20260731)
    now = datetime.now(timezone.utc)
    for _ in range(3000):
        snaps = _rand_snaps(rng)
        assert _cov_freshness(snaps, now) == _old_freshness(snaps, now)


def test_rollup_conf_avg_matches_old_within_day_granularity():
    """avg_confidence: the rollup mean equals the old windowed $avg whenever the
    window boundary falls on a day edge; with an intra-day boundary, only the
    boundary DAY's snapshots can differ (day-granular windowing, as with drops)."""
    rng = random.Random(20260801)
    now = datetime.now(timezone.utc)
    for _ in range(3000):
        snaps = _rand_snaps(rng)
        days = rng.choice([7, 14, 30, 90])
        since = now - timedelta(days=days)
        # exact-day boundary: truncate `since` to midnight → both windows contain
        # precisely the same snapshots → identical result
        since_mid = since.replace(hour=0, minute=0, second=0, microsecond=0)
        old = _old_conf_avg(snaps, since_mid)
        new = _rollup_conf_avg(snaps, since_mid.strftime("%Y-%m-%d"))
        assert old == new, (old, new)


if __name__ == "__main__":
    test_coverage_gaps_and_spread_match_old_definitions()
    test_coverage_freshness_identical_to_old_pipeline()
    test_rollup_conf_avg_matches_old_within_day_granularity()
    test_summary_compute_never_touches_product_snapshots()
    test_integration_rollups_ferretdb()
    print("PASS: iter31 rollups integration + freshness/conf equivalence + no-snapshot contract")
