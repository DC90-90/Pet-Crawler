"""iter38 — live Market Strength store ranking (fixed 30d window).

Score = 100·(0.25·breadth + 0.35·price + 0.25·stock + 0.15·freshness) — the
client-approved weights. Integration seeds a small multi-store market on real
Mongo (coverage + matches + stores + my_products + sales rollups) and checks
every component, the rank order, the own-store row, revenue statuses
(measurable vs "not measurable" vs accumulating), the stale badge, and the
neutral-price rule for stores with no shared skus. The compute is find/$sum
based, so it runs end-to-end on the FerretDB shim.
"""
import asyncio
import math
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# iter75 — HARD override, not setdefault: when this module runs in the same
# pytest session as any module that imports `server` (which calls
# load_dotenv and sets DB_NAME), setdefault silently no-ops and the
# delete_many({}) resets below wipe the REAL working database.
os.environ["DB_NAME"] = "test_store_ranking"
import server  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
NOW = datetime.now(timezone.utc)
FRESH = NOW - timedelta(hours=2)          # inside the 48h freshness floor
OLDISH = NOW - timedelta(days=10)         # in 30d window, outside 48h
W = server._RANKING_WEIGHTS


def _cov(store, sku, price, in_stock=True, seen=FRESH, sold_sig=False, qty_sig=True):
    d = {"_id": f"{sku}|{store}", "sku": sku, "store_id": store,
         "last_priced_at": seen, "last_priced_price": float(price),
         "last_priced_store_name": store,
         "last_seen_at": seen, "last_price": float(price), "last_confidence": 99,
         "last_in_stock": in_stock, "last_qty": 5, "last_store_name": store,
         "last_seen_any_at": seen}
    if sold_sig:
        d["last_sold_pos_at"] = seen
    if qty_sig:
        d["last_usable_qty_at"] = seen
    return d


async def _seed(db):
    for c in ("sku_store_coverage", "stores", "my_products", "product_matches",
              "sku_sales_daily", "own_store_orders", "dashboard_cache"):
        await db[c].delete_many({})
    await db.stores.insert_many([
        {"id": "own", "name": "Pets Houses", "platform": "zid", "is_own_store": True},
        {"id": "zbig", "name": "BigZid", "platform": "zid"},
        {"id": "salla1", "name": "SallaOne", "platform": "salla"},
        {"id": "dead", "name": "DeadStore", "platform": "zid"},
        {"id": "lonely", "name": "LonelyStore", "platform": "salla"},
    ])
    # market: skus A,B shared by zbig + salla1 (+ own via matches)
    await db.sku_store_coverage.insert_many([
        # zbig: 3 products, always the cheaper co-seller, 1 OOS, all fresh, sold signal
        _cov("zbig", "A", 10, sold_sig=True),
        _cov("zbig", "B", 20, in_stock=False, sold_sig=True),
        _cov("zbig", "C", 30, sold_sig=True),
        # salla1: 2 products, always the dearer co-seller, in stock, fresh, NO signals
        _cov("salla1", "A", 14, qty_sig=False),
        _cov("salla1", "B", 26, qty_sig=False),
        # dead: 1 product, no shared skus, stale (seen 10 days ago)
        _cov("dead", "D", 50, seen=OLDISH),
        # lonely: 1 product, no shared skus, fresh, HAS a qty signal but no
        # detected sales yet → revenue status "accumulating"
        _cov("lonely", "E", 40),
    ])
    # own store: 2 priced products, 1 in stock, both synced recently
    await db.my_products.insert_many([
        {"sku": "MA", "price": 12.0, "sale_price": None, "in_stock": True,
         "quantity": 3, "last_synced_at": FRESH.isoformat()},
        {"sku": "MB", "price": 22.0, "sale_price": None, "in_stock": False,
         "quantity": 0, "last_synced_at": FRESH.isoformat()},
    ])
    # matches: own MA ↔ zbig A (10) + salla1 A (14); own is 12 → middle (P50)
    await db.product_matches.insert_many([
        {"my_sku": "MA", "competitor_sku": "A", "competitor_store_id": "zbig", "confidence": 100},
        {"my_sku": "MA", "competitor_sku": "A", "competitor_store_id": "salla1", "confidence": 100},
    ])
    # revenue: zbig sells (rollup); own has a real order
    await db.sku_sales_daily.insert_one(
        {"_id": "zbig|A|d", "store_id": "zbig", "sku": "A",
         "date": (NOW - timedelta(days=2)).strftime("%Y-%m-%d"),
         "units_sold": 3, "rev_sold": 30.0, "units_qty": 0, "rev_qty": 0.0, "qty_drop": 3})
    await db.own_store_orders.insert_one(
        {"order_id": "o1", "created_at": NOW - timedelta(days=1), "excluded": False,
         "total": 99.5, "units": 2, "items": []})


def test_store_ranking_end_to_end():
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        out = await server._store_ranking_compute(db)
        rows = {r["store_id"]: r for r in out["stores"]}
        assert out["total_stores"] == 5 and set(rows) == {"own", "zbig", "salla1", "dead", "lonely"}
        assert out["weights"] == {"breadth": 0.25, "price": 0.35, "stock": 0.25, "freshness": 0.15}

        # ── component math, hand-computed ──
        zb = rows["zbig"]
        assert zb["components"]["breadth"]["products"] == 3
        assert zb["components"]["breadth"]["score"] == round(math.log1p(3) / math.log1p(3), 4) == 1.0
        # zbig cheapest on both shared skus → percentile 0, price score 1.0
        assert zb["components"]["price"]["score"] == 1.0
        assert zb["components"]["price"]["cheapest_rate"] == 1.0
        assert zb["components"]["price"]["shared_products"] == 2
        assert zb["components"]["stock"]["score"] == round(2 / 3, 4)
        assert zb["components"]["freshness"]["score"] == 1.0
        exp_zb = round(100 * (W["breadth"] * 1.0 + W["price"] * 1.0
                              + W["stock"] * round(2 / 3, 4) + W["freshness"] * 1.0), 1)
        assert zb["score"] == exp_zb, (zb["score"], exp_zb)

        s1 = rows["salla1"]
        # always the dearer of 2 sellers → percentile 100, price score 0
        assert s1["components"]["price"]["score"] == 0.0
        assert s1["components"]["price"]["avg_percentile"] == 100.0
        assert s1["components"]["stock"]["score"] == 1.0

        # no shared skus → neutral 0.5 price, no percentile
        assert rows["lonely"]["components"]["price"]["score"] == 0.5
        assert rows["lonely"]["components"]["price"]["avg_percentile"] is None

        # ── own store row: real position, ledger revenue, Insights percentile ──
        own = rows["own"]
        assert own["is_own_store"] and out["own_rank"] == own["rank"]
        assert own["components"]["breadth"]["products"] == 2
        assert own["components"]["stock"]["score"] == 0.5          # 1 of 2 in stock
        assert own["components"]["freshness"]["score"] == 1.0
        # own price 12 among sellers (10, 12, 14) → middle → percentile 50 → 0.5
        assert own["components"]["price"]["avg_percentile"] == 50.0
        assert own["components"]["price"]["score"] == 0.5
        assert own["revenue_30d"] == 99.5 and own["revenue_status"] == "ledger"
        assert own["overlap"] is None

        # ── revenue statuses ──
        assert zb["revenue_30d"] == 30.0 and zb["revenue_status"] == "computed"
        assert s1["revenue_30d"] is None and s1["revenue_status"] == "not_measurable"
        assert rows["lonely"]["revenue_status"] == "accumulating"   # qty signal, no revenue yet

        # ── stale badge: dead store seen 10 days ago → freshness 0 → stale ──
        assert rows["dead"]["components"]["freshness"]["score"] == 0.0
        assert rows["dead"]["stale"] is True
        assert zb["stale"] is False

        # ── ordering: ranks are 1..N sorted by REVENUE desc (iter62) ──
        # This used to assert score-desc. The client requires a sales
        # leaderboard, so revenue is now the primary key and the score is the
        # tie-break; zbig is dominant on every score axis and still ranks below
        # `own` because `own` sold more.
        ordered = sorted(out["stores"], key=lambda r: r["rank"])
        assert [r["rank"] for r in ordered] == list(range(1, 6))
        vals = [r["revenue_rank_value"] for r in ordered]
        numeric = [v for v in vals if v is not None]
        assert numeric == sorted(numeric, reverse=True), vals
        # every None is at the END — no revenue figure sorts last, and is not
        # given a fabricated 0
        assert all(v is None for v in vals[len(numeric):]), vals
        assert ordered[0]["store_id"] == "own" and ordered[0]["revenue_rank_value"] == 99.5
        assert ordered[-1]["store_id"] == "dead"
        assert ordered[-1]["revenue_rank_value"] is None
        assert ordered[-1]["revenue_rank_basis"] == "none"
        # the score is still on every row, and still computed only from the
        # four components — revenue never feeds it
        for r in ordered:
            c = r["components"]
            assert r["score"] == round(100 * (W["breadth"] * c["breadth"]["score"]
                                              + W["price"] * c["price"]["score"]
                                              + W["stock"] * c["stock"]["score"]
                                              + W["freshness"] * c["freshness"]["score"]), 1)
        # zbig outscores own but is outsold by it — proof the score is not the key
        assert zb["score"] > rows["own"]["score"]
        assert zb["rank"] > rows["own"]["rank"]
        assert out["sorted_by"] == "revenue_desc"
        assert (out["ranked_on_measured"] + out["ranked_on_estimate"]
                + out["no_revenue_value"]) == out["total_stores"]

        # overlap column (distinct my_skus matched per store)
        assert zb["overlap"] == 1 and s1["overlap"] == 1

        # ── cache spec registered → recomputed by the standard hooks ──
        assert any(base == "price-intel/store-ranking" for base, _f in server._SINGLE_CACHE_SPECS)

        # ── endpoint serves through the page cache with headers ──
        from starlette.responses import Response
        r0 = Response()
        body = await server.price_intel_store_ranking(response=r0, user={"id": "t", "email": "t", "role": "super_admin"})
        assert body["own_rank"] == own["rank"]
        r1 = Response()
        await server.price_intel_store_ranking(response=r1, user={"id": "t", "email": "t", "role": "super_admin"})
        assert r1.headers["x-cache-source"] == "cache"

        # ── preview endpoint: super_admin only, bypasses cache ──
        prev = await server.store_ranking_preview(user={"id": "t", "email": "t", "role": "super_admin"})
        assert prev["total_stores"] == 5
        # iter40 diagnostics
        diag = prev["diagnostics"]
        assert diag["own_orders"]["docs_in_window"] == 1
        assert diag["own_orders"]["helper_result"] == {"revenue": 99.5, "orders": 1}
        audit_by_id = {a["store_id"]: a for a in diag["platform_audit"]}
        assert audit_by_id["salla1"]["platform_tag"] == "salla"
        assert audit_by_id["salla1"]["flag"] is None                 # no computed revenue → no flag
        hists = diag["percentile_histograms"]
        # zbig cheapest on both shared skus → both land in the 0–25% bucket
        assert hists["zbig"]["buckets_0_25_50_75"][0] == 2 and hists["zbig"]["shared"] == 2
        assert hists["salla1"]["buckets_0_25_50_75"][3] == 2         # always dearest
        assert hists["zbig"]["median_price_ratio_vs_market"] < 1 < hists["salla1"]["median_price_ratio_vs_market"]
        try:
            await server.store_ranking_preview(user={"id": "t", "email": "t", "role": "viewer"})
            raise AssertionError("viewer should be rejected")
        except Exception as e:
            assert getattr(e, "status_code", None) == 403
    asyncio.run(main())


def test_market_position_summary_extraction_unchanged():
    """The iter38 extraction of _compute_market_position_summary must feed the
    summary compute the exact same object (structure + values)."""
    async def main():
        db = AsyncIOMotorClient(MONGO)[os.environ["DB_NAME"]]
        await _seed(db)
        server.db = db
        mp = await server._compute_market_position_summary(db)
        assert mp is not None
        assert mp["total_my_products"] == 2
        assert mp["ranked_products"] == 1              # only MA has matched sellers
        assert mp["avg_percentile"] == 50.0            # 12 between 10 and 14
        assert mp["cheapest_count"] == 0 and mp["most_expensive_count"] == 0
    asyncio.run(main())


if __name__ == "__main__":
    test_store_ranking_end_to_end()
    test_market_position_summary_extraction_unchanged()
    print("PASS: iter38 store ranking")
