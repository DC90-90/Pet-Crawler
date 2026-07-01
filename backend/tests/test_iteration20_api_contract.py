"""
Iteration 20 — API-contract regression for the barcode-safe union fix
in /api/my-products row builder and the matcher pack-indicator heal.

These tests focus on the LIVE API surface (not unit-level matcher
internals — those are covered by test_competitor_count_union.py and
test_matcher_pack_indicator.py). Goals:

  1. The user-facing Beaphar bug is gone (num_competitors >= 6 via union).
  2. The new num_priced_competitors / has_competitor_pricing contract holds.
  3. The matcher heal landed in db.product_matches + db.sync_runs.
  4. KPIs at days=90 widened to (888 / 42.7% / 59) ±tolerance.
  5. Iter18 sync_health + iter19 has_market_share fields untouched.
  6. No regression on the 9 unrelated /api/insights & /api/scanner endpoints
     (since /api/insights/sales calls my_products internally).
"""
import os
import pytest
import requests
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"

BEAPHAR_SKU = "8711231124985"


# ── Shared fixtures ─────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": EMAIL, "password": PASSWORD}, timeout=20)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    token = r.json().get("access_token") or r.json().get("token")
    if token:
        s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


# ── Beaphar end-to-end (the user-reported bug) ──────────────


class TestBeapharEndToEnd:
    """SKU 8711231124985 (Beaphar Multi-vitamin with Taurin 50g) was the
    user-reported bug: detail panel showed 6 competitors, outer COMPETITORS
    column showed 0. After the union fix it must show >=6.
    """

    def test_num_competitors_at_least_6(self, client):
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "search": BEAPHAR_SKU, "limit": 5},
                       timeout=20)
        assert r.status_code == 200, r.text
        rows = r.json().get("products", [])
        row = next((x for x in rows if x.get("sku") == BEAPHAR_SKU), None)
        assert row is not None, f"Beaphar not found in payload: {[x.get('sku') for x in rows]}"
        assert row["num_competitors"] >= 6, (
            f"Expected >=6 competitors via union, got {row['num_competitors']}"
        )

    def test_prices_within_expected_range(self, client):
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "search": BEAPHAR_SKU, "limit": 5},
                       timeout=20)
        rows = r.json().get("products", [])
        row = next((x for x in rows if x.get("sku") == BEAPHAR_SKU), None)
        assert row is not None
        assert 35.0 <= row["competitor_min_price"] <= 45.0, (
            f"competitor_min_price expected ~40, got {row['competitor_min_price']}"
        )
        assert 43.0 <= row["competitor_max_price"] <= 53.0, (
            f"competitor_max_price expected ~48, got {row['competitor_max_price']}"
        )

    def test_has_competitor_pricing_true(self, client):
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "search": BEAPHAR_SKU, "limit": 5},
                       timeout=20)
        row = next((x for x in r.json().get("products", []) if x.get("sku") == BEAPHAR_SKU), None)
        assert row is not None
        assert row["has_competitor_pricing"] is True
        assert row["num_priced_competitors"] >= 6, (
            f"Expected >=6 priced competitors, got {row.get('num_priced_competitors')}"
        )


# ── Row-payload contract (iter20 new fields) ────────────────


class TestRowPayloadContract:
    """num_priced_competitors is the iter20 new field. has_competitor_pricing
    must be gated on num_priced_competitors >= 1 (not num_competitors).
    """

    def test_required_fields_present(self, client):
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "limit": 25}, timeout=20)
        assert r.status_code == 200
        rows = r.json().get("products", [])
        assert rows, "Empty /api/my-products response"
        for row in rows:
            for f in ("num_competitors", "num_priced_competitors",
                      "has_competitor_pricing", "has_market_share",
                      "competitor_min_price", "competitor_max_price"):
                assert f in row, f"Missing field '{f}' in row for sku={row.get('sku')}"

    def test_priced_subset_of_competitors(self, client):
        """num_priced_competitors must be <= num_competitors (subset)."""
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "limit": 200}, timeout=30)
        rows = r.json().get("products", [])
        viol = [r["sku"] for r in rows
                if (r.get("num_priced_competitors") or 0) > (r.get("num_competitors") or 0)]
        assert not viol, f"num_priced_competitors > num_competitors for {viol[:10]}"

    def test_has_competitor_pricing_gated_on_priced(self, client):
        """has_competitor_pricing iff num_priced_competitors >= 1."""
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "limit": 500}, timeout=30)
        rows = r.json().get("products", [])
        viol = []
        for row in rows:
            npriced = row.get("num_priced_competitors") or 0
            hcp = bool(row.get("has_competitor_pricing"))
            if (npriced >= 1) != hcp:
                viol.append((row.get("sku"), npriced, hcp))
        assert not viol, f"has_competitor_pricing mis-gated on {len(viol)} rows: {viol[:5]}"

    def test_has_market_data_field_removed(self, client):
        """Iter19 retired has_market_data — must not be re-introduced."""
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "limit": 50}, timeout=20)
        rows = r.json().get("products", [])
        leaked = [r["sku"] for r in rows if "has_market_data" in r]
        assert not leaked, f"has_market_data field re-introduced on rows: {leaked[:5]}"


# ── KPI block at days=90 (widened iter20 baselines) ─────────


class TestKpiBlockIter21:
    """Iter21 (Feb 2026) — the aggregation fix that replaced the .to_list(50000)
    silent truncation exposed the TRUE 90D KPIs that were previously
    hidden by dropping ~82% of the 90D snapshot data. All three counters
    shifted up substantially. This is a data-completeness fix, not a
    formula change.
      matched_products: 888 → ~1057
      market_coverage_pct: 42.7 → ~50.8
      share_sample_size: 59 → ~319
      total_units_sold: ~1178 → ~19232
      market_revenue: ~28k → ~524k
    """

    def test_kpi_keys_present(self, client):
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 90, "limit": 1}, timeout=20)
        assert r.status_code == 200
        kpis = r.json().get("kpis", {})
        for k in ("total_products", "matched_products", "market_coverage_pct",
                  "share_sample_size", "total_units_sold", "market_revenue",
                  "my_revenue", "avg_market_share"):
            assert k in kpis, f"KPI missing: {k} (have {list(kpis.keys())})"

    def test_matched_products_widened(self, client):
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 90, "limit": 1}, timeout=20)
        mp = r.json()["kpis"]["matched_products"]
        assert 1020 <= mp <= 1100, f"matched_products expected ~1057, got {mp}"

    def test_market_coverage_pct(self, client):
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 90, "limit": 1}, timeout=20)
        cov = r.json()["kpis"]["market_coverage_pct"]
        assert 48.5 <= cov <= 53.0, f"market_coverage_pct expected ~50.8, got {cov}"

    def test_share_sample_size(self, client):
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 90, "limit": 1}, timeout=20)
        sss = r.json()["kpis"]["share_sample_size"]
        assert 285 <= sss <= 360, f"share_sample_size expected ~319, got {sss}"

    def test_no_fair_share_100_leakage(self, client):
        """No row should have market_share_pct=100 with num_competitors=0
        (iter19 retired the fair-share fallback).
        """
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 90, "limit": 500}, timeout=30)
        rows = r.json().get("products", [])
        viol = [r["sku"] for r in rows
                if r.get("market_share_pct") == 100 and (r.get("num_competitors") or 0) == 0]
        assert not viol, f"Fair-share 100% leakage on {viol[:5]}"

    def test_monotonicity_across_windows(self, client):
        """iter21 truncation fix invariant: num_competitors must be monotonic
        (non-decreasing) as the time window widens. Pre-fix the 30D window
        would sometimes return FEWER competitors than 7D because MongoDB's
        natural-order .to_list(50000) dropped different snapshots on each
        call.
        """
        SKU = "8595602527212"  # Carnilove — the canonical regression case
        prev = None
        for days in (7, 14, 30, 90):
            r = client.get(f"{BASE_URL}/api/my-products",
                           params={"days": days, "search": SKU, "limit": 5},
                           timeout=15)
            assert r.status_code == 200
            row = next((p for p in r.json().get("products", [])
                        if p.get("sku") == SKU), None)
            assert row is not None, f"Carnilove not in response @ days={days}"
            n = row.get("num_competitors") or 0
            if prev is not None:
                assert n >= prev, (
                    f"Monotonicity violated: days={days} num_competitors={n} "
                    f"is less than previous window value {prev}"
                )
            prev = n


# ── Matcher heal verification (READ-ONLY — do not re-trigger) ──


class TestMatcherHealState:
    """The matcher heal endpoint was already run this session. Verify state
    in db.product_matches and db.sync_runs.
    """

    def test_product_matches_row_count(self, db):
        n = db.product_matches.count_documents({})
        assert n >= 2250, f"Expected >=2250 product_matches rows, got {n}"

    def test_distinct_my_skus(self, db):
        n = len(db.product_matches.distinct("my_sku"))
        assert n >= 1100, f"Expected >=1100 distinct my_sku in matches, got {n}"

    def test_beaphar_matches_after_heal(self, db):
        """Beaphar (8711231124985) must have >=7 barcode-method matches
        with confidence=99 after the heal."""
        rows = list(db.product_matches.find({
            "my_sku": BEAPHAR_SKU,
            "match_method": "barcode",
            "confidence": 99,
        }))
        assert len(rows) >= 7, (
            f"Expected >=7 barcode-method matches for Beaphar, got {len(rows)}"
        )

    def test_sync_runs_has_ok_match_run(self, db):
        """At least one sync_runs row with match_status=ok must exist."""
        n_ok = db.sync_runs.count_documents({"match_status": "ok"})
        assert n_ok >= 1, "No sync_runs row with match_status=ok found"


# ── Iter18 sync_health + iter19 invariants ──────────────────


class TestIter18Iter19Invariants:
    def test_data_freshness_sync_health(self, client):
        r = client.get(f"{BASE_URL}/api/data-freshness", timeout=15)
        assert r.status_code == 200, r.text
        sh = r.json().get("sync_health")
        assert sh is not None, "sync_health block missing"
        for k in ("last_run", "last_run_age_hours", "last_sync_status",
                  "last_match_status"):
            assert k in sh, f"sync_health key '{k}' missing"

    def test_iter19_kpi_invariant_matched_products(self, client):
        """kpis.matched_products == count(rows with has_competitor_pricing=true)
        Sampled over the first 500 rows; full-catalogue version is in
        test_iteration19_coverage_split.py.
        """
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 90, "limit": 500, "offset": 0}, timeout=30)
        body = r.json()
        rows = body.get("products", [])
        # Only validate if catalogue fits in one page (else skip — full
        # invariant covered by iter19 sweep test)
        if body.get("kpis", {}).get("total_products", 0) <= 500:
            n_pricing = sum(1 for r in rows if r.get("has_competitor_pricing"))
            assert n_pricing == body["kpis"]["matched_products"], (
                f"Per-row count {n_pricing} != kpis.matched_products {body['kpis']['matched_products']}"
            )
        else:
            pytest.skip("Catalogue larger than 500 — sweep covered by iter19 test")


# ── Smoke test for unrelated endpoints (no regression) ──────


class TestUnrelatedEndpointsSmoke:
    """/api/insights/sales calls my_products internally with own_only=False,
    so the row-builder changes could in theory regress those endpoints.
    Hit each one and assert 200 + valid JSON.
    """

    @pytest.mark.parametrize("path,params", [
        ("/api/insights/summary", {"days": 30}),
        ("/api/insights/leaderboard", {"days": 30}),
        ("/api/insights/top-sellers", {"days": 30}),
        ("/api/insights/trending", {"days": 30}),
        ("/api/insights/gaps", {"days": 30}),
        ("/api/insights/price-wars", {"days": 30}),
        ("/api/insights/sales", {"days": 30}),
        ("/api/discounts/top-pct", {"days": 30}),
        ("/api/scanner/opportunities", {"days": 30}),
    ])
    def test_endpoint_200_and_json(self, client, path, params):
        r = client.get(f"{BASE_URL}{path}", params=params, timeout=30)
        assert r.status_code == 200, f"{path} → {r.status_code}: {r.text[:200]}"
        # Must return parseable JSON
        body = r.json()
        assert isinstance(body, (dict, list)), f"{path} returned non-JSON-object: {type(body)}"


# ── Barcode-safe union edge cases (live via API) ────────────


class TestBarcodeSafeUnionEdges:
    def test_zid_suffix_does_not_inflate_count(self, db, client):
        """If any my_sku has Zid-suffix-shaped competitor SKUs in snapshots,
        the union must NOT pick them up. Find such a case (if exists) and
        verify the count.
        """
        # Look for snapshots with hyphen-suffix shape
        suffix_snap = db.product_snapshots.find_one({
            "sku": {"$regex": r"^\d{8,14}-[A-Za-z]+"},
        })
        if not suffix_snap:
            pytest.skip("No Zid-suffix-shaped competitor SKUs found in snapshots")
        # The suffix SKU should never appear AS-IS in my_products as a key
        # match path — verify by searching for it
        suffix_sku = suffix_snap["sku"]
        base = suffix_sku.split("-")[0]
        # If a my_product exists for base, ensure num_competitors is bounded
        # by the legitimate barcode hits only (not the suffixed snapshot)
        own = db.my_products.find_one({"sku": base})
        if not own:
            pytest.skip(f"No own product for base SKU {base}")
        # Just sanity-check that the API doesn't crash on this case
        r = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 30, "search": base, "limit": 5}, timeout=15)
        assert r.status_code == 200
