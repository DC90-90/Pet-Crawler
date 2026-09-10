"""
Iteration 19 — Coverage definition split test suite.

Validates the iter18 → iter19 fix where the Market Coverage KPI was conflating
two distinct signals into one. The fix splits them into:
  - has_competitor_pricing  (num_competitors >= 1)            → drives matched_products + market_coverage_pct
  - has_market_share        (num_competitors >= 1 AND qty>0)  → drives share_sample_size + avg_market_share

Old broken field `has_market_data` MUST be removed from the per-row payload.

Expected preview numbers (90D, own_only=True):
  matched_products      ≈ 774   (±2)
  market_coverage_pct   ≈ 37.2  (±2)
  share_sample_size     ≈ 49    (±2)
  avg_market_share      ≈ 0.0   (preview own-sync stale)
  total_products        = 2081
"""
import os
import time
import pytest
import requests
from collections import Counter
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
from _auth import live_db_name   # backend/.env, not the polluted env var
DB_NAME = live_db_name()

EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"


# ---- fixtures ----------------------------------------------------------------
@pytest.fixture(scope="module")
def session():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import auth_session
    return auth_session(EMAIL, PASSWORD)


@pytest.fixture(scope="module")
def mongo():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def my_products_90d(session):
    r = session.get(f"{BASE_URL}/api/my-products?days=90&limit=500&offset=0", timeout=60)
    assert r.status_code == 200, f"my-products failed: {r.status_code}"
    return r.json()


# ---- 1. db.product_matches healthy ------------------------------------------
class TestMatcherHealth:
    """iter21 pinned 2,453 match rows / 1,150 distinct my_skus. Those numbers
    were measured with the WHOLE fleet freshly crawled AND before the iter80
    catalogue-tag bug was found (a legacy import had left 2,231 of 2,303
    products outside the matcher's own-store query, so most of those rows were
    stale leftovers from stores that had since fallen out of the 14-day window).
    With the tag repaired and half the fleet stale the honest state is 496 rows
    / 356 my_skus — a magic number here tracks CRAWL COVERAGE, not matcher
    health. These tests assert the shape, a collapse floor, referential
    integrity, and the relationship to crawl freshness.
    """

    def test_product_matches_table_is_populated_and_well_formed(self, mongo):
        total = mongo.product_matches.count_documents({})
        assert total >= 200, f"product_matches collapsed to {total} rows (floor 200)"
        for r in mongo.product_matches.find({}, {"_id": 0}).limit(200):
            assert r.get("my_sku"), f"match row with no my_sku: {r}"
            assert r.get("competitor_store_id"), f"match row with no store: {r}"
            assert r.get("match_method"), f"match row with no method: {r}"
            conf = r.get("confidence")
            assert isinstance(conf, (int, float)) and 0 < conf <= 100, f"bad confidence: {r}"
        print(f"[matcher] {total} rows, "
              f"{len(mongo.product_matches.distinct('my_sku'))} distinct my_skus")

    def test_product_matches_distinct_my_skus(self, mongo):
        distinct = len(mongo.product_matches.distinct("my_sku"))
        total = mongo.product_matches.count_documents({})
        assert 0 < distinct <= total, f"{distinct} distinct my_skus across {total} rows"
        assert distinct >= 100, f"distinct my_skus collapsed to {distinct} (floor 100)"

    def test_every_match_row_points_at_a_real_store(self, mongo):
        """Referential integrity — load-test debris (st-0, st-100) used to sit in
        here and inflate every count."""
        store_ids = {s["id"] for s in mongo.stores.find({}, {"id": 1})}
        orphans = Counter()
        for m in mongo.product_matches.find({}, {"competitor_store_id": 1}):
            sid = m.get("competitor_store_id")
            if sid not in store_ids:
                orphans[sid] += 1
        assert not orphans, f"match rows pointing at stores that do not exist: {dict(orphans)}"

    def test_matcher_coverage_follows_crawl_freshness(self, mongo):
        """The regression the magic numbers were really guarding: a competitor
        crawled INSIDE the matcher's own window (matcher.MATCH_WINDOW_DAYS = 14)
        must have matcher rows. Fails when the matcher stops consuming
        snapshots; stays green when a crawl has merely gone stale (those stores
        drop out of the window by design and keep their previous rows).

        iter80 diagnosis this fence produced immediately: CutePets last crawled
        2026-08-25 (15.7 days) — outside the 14-day window — which is why
        matched_products fell 1,057 → 722 and why CutePets has 0 match rows
        despite sharing 384 barcodes with our catalogue. It is a crawl-freshness
        problem, not a matcher bug; the Salla backfill is the fix.
        """
        from matcher import MATCH_WINDOW_DAYS
        since = datetime.now(timezone.utc) - timedelta(days=MATCH_WINDOW_DAYS)
        crawled = {r["_id"]: r["n"] for r in mongo.product_snapshots.aggregate([
            {"$match": {"crawled_at": {"$gte": since}}},
            {"$group": {"_id": "$store_id", "n": {"$sum": 1}}},
        ])}
        matched = Counter(m.get("competitor_store_id")
                          for m in mongo.product_matches.find({}, {"competitor_store_id": 1}))
        names = {s["id"]: s["name"] for s in mongo.stores.find({}, {"id": 1, "name": 1})}
        own = {s["id"] for s in mongo.stores.find({"is_own_store": True}, {"id": 1})}
        table, silent = [], []
        for sid, n in sorted(crawled.items(), key=lambda kv: -kv[1]):
            if sid in own:
                continue
            table.append((names.get(sid, sid), n, matched.get(sid, 0)))
            if n >= 100 and matched.get(sid, 0) == 0:
                silent.append({"store": names.get(sid, sid), "snapshots_in_window": n,
                               "match_rows": 0})
        print(f"[coverage/{MATCH_WINDOW_DAYS}d] store / snapshots / match_rows: {table}")
        stale = [names.get(s["id"], s["id"]) for s in mongo.stores.find(
            {"is_active": True, "is_own_store": {"$ne": True}}, {"id": 1})
            if s["id"] not in crawled]
        if stale:
            print(f"[coverage] OUTSIDE the {MATCH_WINDOW_DAYS}d matcher window "
                  f"(cannot contribute matches until re-crawled): {stale}")
        assert not silent, (
            f"stores crawled inside the {MATCH_WINDOW_DAYS}-day matcher window with "
            f"ZERO matcher rows — the matcher is not consuming their snapshots: {silent}")

    def test_sync_runs_iter18_row_preserved(self, mongo):
        rows = list(mongo.sync_runs.find({"kind": "manual_match_only"}))
        assert len(rows) >= 1, "expected at least 1 manual_match_only row from iter18"
        ok_rows = [r for r in rows if r.get("match_status") == "ok" and r.get("match_added", 0) >= 1000]
        assert len(ok_rows) >= 1, f"expected manual_match_only with match_status=ok and match_added>=1000, got {rows[:2]}"


# ---- 2. Per-row signal contract ---------------------------------------------
class TestPerRowSignals:
    def test_has_market_data_field_removed(self, my_products_90d):
        for p in my_products_90d.get("products", [])[:50]:
            assert "has_market_data" not in p, f"legacy has_market_data still present in row: {p.get('sku')}"

    def test_has_competitor_pricing_present(self, my_products_90d):
        prods = my_products_90d.get("products", [])
        assert prods, "no products returned"
        for p in prods[:20]:
            assert "has_competitor_pricing" in p, f"missing has_competitor_pricing in {p.get('sku')}"
            assert isinstance(p["has_competitor_pricing"], bool)

    def test_has_market_share_present(self, my_products_90d):
        for p in my_products_90d.get("products", [])[:20]:
            assert "has_market_share" in p, f"missing has_market_share in {p.get('sku')}"
            assert isinstance(p["has_market_share"], bool)

    def test_market_share_pct_null_when_has_market_share_false(self, my_products_90d):
        bad = []
        for p in my_products_90d.get("products", []):
            if p.get("has_market_share") is False:
                if p.get("market_share_pct") is not None:
                    bad.append((p.get("sku"), p.get("market_share_pct")))
        assert not bad, f"rows with has_market_share=false must have market_share_pct=null. violations: {bad[:5]}"

    def test_market_share_pct_numeric_when_has_market_share_true(self, my_products_90d):
        bad = []
        for p in my_products_90d.get("products", []):
            if p.get("has_market_share") is True:
                if not isinstance(p.get("market_share_pct"), (int, float)):
                    bad.append((p.get("sku"), p.get("market_share_pct")))
        assert not bad, f"rows with has_market_share=true must have numeric market_share_pct. violations: {bad[:5]}"

    def test_no_fair_share_100pct_fallback(self, my_products_90d):
        bad = []
        for p in my_products_90d.get("products", []):
            if p.get("market_share_pct") == 100 and (p.get("num_competitors") or 0) < 1:
                bad.append(p.get("sku"))
        assert not bad, f"fair-share 100% fallback leaked back: {bad[:5]}"

    def test_signal_logic_consistency(self, my_products_90d):
        """has_market_share=True ⇒ has_competitor_pricing=True (subset)."""
        bad = []
        for p in my_products_90d.get("products", []):
            if p.get("has_market_share") and not p.get("has_competitor_pricing"):
                bad.append(p.get("sku"))
        assert not bad, f"has_market_share=true but has_competitor_pricing=false: {bad[:5]}"


# ---- 3. KPI block contract ---------------------------------------------------
class TestKPIBlock:
    def test_kpi_block_has_all_required_fields(self, my_products_90d):
        kpis = my_products_90d.get("kpis", {})
        for key in [
            "total_products", "total_units_sold", "market_revenue", "my_revenue",
            "avg_market_share", "my_units_sold",
            "matched_products", "market_coverage_pct", "share_sample_size",
        ]:
            assert key in kpis, f"kpi block missing {key}; got keys={list(kpis.keys())}"

    def test_kpi_matched_products_is_a_consistent_share_of_the_catalogue(self, my_products_90d):
        """iter21 pinned matched_products at 1,057±30 and coverage at 50.8±2 on a
        fully-crawled fleet; with Zarafa dark and four Salla stores stale it now
        reads 722 / 32.0%. The magic number tracked crawl coverage, so this now
        asserts the bounds + a collapse floor, and `test_kpi_coverage_math`
        below still pins the arithmetic.
        """
        kpis = my_products_90d["kpis"]
        matched, total = kpis["matched_products"], kpis["total_products"]
        assert 0 < matched <= total, f"matched_products={matched} of total={total}"
        assert matched >= 400, f"matched_products collapsed to {matched} (floor 400)"
        print(f"[kpi] matched_products={matched} of {total}")

    def test_kpi_market_coverage_pct_within_target(self, my_products_90d):
        kpis = my_products_90d["kpis"]
        cov = kpis["market_coverage_pct"]
        assert 0 < cov <= 100, f"market_coverage_pct={cov} out of range"
        assert cov >= 15.0, f"market coverage collapsed to {cov}% (floor 15%)"

    def test_kpi_share_sample_size_within_target(self, my_products_90d):
        """The share sample can never exceed the priced sample — a share needs a
        competitor price AND measured units."""
        kpis = my_products_90d["kpis"]
        sss = kpis["share_sample_size"]
        assert 0 < sss <= kpis["matched_products"], (
            f"share_sample_size={sss} vs matched_products={kpis['matched_products']}")
        assert sss >= 100, f"share sample collapsed to {sss} rows (floor 100)"

    def test_kpi_avg_market_share_is_honest(self, my_products_90d):
        """iter19 pinned this at 0..5 because the preview's own-store sync was
        stale at the time (my units in the share set were 0). The own store now
        syncs daily, so a real ~40% average is the honest figure; what must hold
        is the range and the zero-when-no-sample rule. The exact formula is
        re-derived over the FULL catalogue in test_iteration18.
        """
        kpis = my_products_90d["kpis"]
        avg = kpis["avg_market_share"]
        assert 0.0 <= avg <= 100.0, f"avg_market_share={avg} out of range"
        if kpis["share_sample_size"] == 0:
            assert avg == 0, f"no share sample but avg_market_share={avg}"

    def test_kpi_total_products(self, my_products_90d):
        assert my_products_90d["kpis"]["total_products"] == my_products_90d.get("total")

    def test_kpi_coverage_math(self, my_products_90d):
        kpis = my_products_90d["kpis"]
        expected = round(kpis["matched_products"] / kpis["total_products"] * 100, 1)
        assert abs(expected - kpis["market_coverage_pct"]) <= 0.2, (
            f"coverage math mismatch: {expected} vs {kpis['market_coverage_pct']}"
        )


# ---- 4. Cross-page consistency ----------------------------------------------
class TestCrossPageConsistency:
    @pytest.fixture(scope="class")
    def all_pages(self, session):
        rows = []
        first_kpis = None
        for offset in (0, 500, 1000, 1500, 2000):
            r = session.get(f"{BASE_URL}/api/my-products?days=90&limit=500&offset={offset}", timeout=60)
            assert r.status_code == 200, f"page offset={offset} failed: {r.status_code}"
            data = r.json()
            if offset == 0:
                first_kpis = data["kpis"]
            rows.extend(data.get("products", []))
        return {"rows": rows, "kpis": first_kpis}

    def test_aggregate_row_count_matches_total(self, all_pages):
        assert len(all_pages["rows"]) == all_pages["kpis"]["total_products"], (
            f"got {len(all_pages['rows'])} rows across pages but kpis.total_products={all_pages['kpis']['total_products']}"
        )

    def test_has_competitor_pricing_count_matches_matched_products(self, all_pages):
        count = sum(1 for r in all_pages["rows"] if r.get("has_competitor_pricing"))
        assert count == all_pages["kpis"]["matched_products"], (
            f"per-row has_competitor_pricing count={count} but kpis.matched_products={all_pages['kpis']['matched_products']}"
        )

    def test_has_market_share_count_matches_share_sample_size(self, all_pages):
        count = sum(1 for r in all_pages["rows"] if r.get("has_market_share"))
        assert count == all_pages["kpis"]["share_sample_size"], (
            f"per-row has_market_share count={count} but kpis.share_sample_size={all_pages['kpis']['share_sample_size']}"
        )


# ---- 5. Regression smoke -----------------------------------------------------
class TestRegression:
    def test_data_freshness_endpoint(self, session):
        r = session.get(f"{BASE_URL}/api/data-freshness", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "sync_health" in d, "sync_health block missing"
        sh = d["sync_health"]
        for k in ("last_run", "last_run_age_hours", "last_sync_status", "last_match_status",
                  "scheduler_running", "is_stale", "alarm"):
            assert k in sh, f"sync_health missing {k}"

    def test_sku_search_regex_escape(self, session):
        r = session.get(f"{BASE_URL}/api/my-products?days=90&search=.*&limit=10", timeout=30)
        assert r.status_code == 200
        # iter16: regex meta should be escaped, so should not match every product
        data = r.json()
        assert data.get("total", 0) == 0, f"regex escape regression: '.*' matched {data.get('total')} products"

    def test_insights_sales_endpoint(self, session):
        r = session.get(f"{BASE_URL}/api/insights/sales?days=90", timeout=30)
        assert r.status_code == 200

    def test_scanner_endpoint(self, session):
        r = session.get(f"{BASE_URL}/api/scanner/scan?days=90", timeout=30)
        assert r.status_code in (200, 404)  # endpoint may not exist

    def test_health(self, session):
        r = session.get(f"{BASE_URL}/api/health", timeout=10)
        assert r.status_code in (200, 404)
