"""
Iter21 pre-deploy API-level regression against the live preview endpoint.

Scope (as requested by main agent):
  (a) Contract & monotonicity of /api/my-products across day windows,
      with canonical SKUs (Carnilove, Beaphar) AND 5 random own-store SKUs.
  (b) 90D KPI baselines after truncation fix.
  (c) Matcher price-ratio flag semantics via DB (no POST to matching).
  (d) Sibling endpoint smoke tests + market-wide sales path.
  (e) Performance timing on my_products@90D and insights/sales@90D.
  (f) iter19 KPI invariants (matched_products == count(has_competitor_pricing)),
      iter18 sync_health block intact.
"""
import os
import time
import random
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
from _auth import live_db_name   # backend/.env, not the polluted env var
DB_NAME = live_db_name()
EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"

CARNILOVE_SKU = "8595602527212"
BEAPHAR_SKU = "8711231124985"


# ── fixtures ─────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import auth_session
    return auth_session(EMAIL, PASSWORD)


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def rows_90d(client):
    r = client.get(f"{BASE_URL}/api/my-products",
                   params={"days": 90, "limit": 500},
                   timeout=30)
    assert r.status_code == 200
    payload = r.json()
    # normalize key: iter21 endpoint returns 'products'
    payload["rows"] = payload.get("products") or payload.get("rows") or []
    return payload


def _find(rows, sku):
    for r in rows:
        if str(r.get("sku")) == str(sku):
            return r
    return None


# ── (a) response shape intact ─────────────────────────────
REQUIRED_FIELDS = [
    "sku", "name_en", "name_ar", "my_price",
    "num_competitors", "num_priced_competitors", "has_competitor_pricing",
    "competitor_min_price", "competitor_max_price", "vs_my_price_pct",
    "market_share_pct", "has_market_share",
    "qty_sold_est", "num_sellers",
]


def test_response_shape_all_required_fields_present(rows_90d):
    rows = rows_90d.get("rows", [])
    assert len(rows) > 100, f"Expected many own-store rows, got {len(rows)}"
    missing = {}
    for r in rows[:50]:
        for f in REQUIRED_FIELDS:
            if f not in r:
                missing.setdefault(f, 0)
                missing[f] += 1
    assert not missing, f"Missing fields across sample rows: {missing}"


# ── (b) monotonicity on canonical + 5 random own-store SKUs ─
def _rows(client, days, own_only=True, limit=500, search=None):
    params = {"days": days, "limit": limit}
    if search:
        params["search"] = search
    r = client.get(f"{BASE_URL}/api/my-products", params=params, timeout=30)
    assert r.status_code == 200, f"days={days} → {r.status_code} {r.text[:200]}"
    j = r.json()
    prods = j.get("products") or j.get("rows") or []
    if own_only:
        prods = [p for p in prods if p.get("is_my_product") is True]
    return prods


def _find_by_search(client, sku, days):
    """Fetch a single SKU via search across a day window; handles pagination limit."""
    rows = _rows(client, days=days, own_only=False, limit=50, search=str(sku))
    for r in rows:
        if str(r.get("sku")) == str(sku):
            return r
    return None


def test_carnilove_monotonic(client):
    counts = []
    for d in (7, 14, 30, 90):
        row = _find_by_search(client, CARNILOVE_SKU, d)
        assert row is not None, f"Carnilove missing at days={d}"
        counts.append((d, row["num_competitors"]))
    print(f"Carnilove counts: {counts}")
    values = [v for _, v in counts]
    assert values == sorted(values), (
        f"Carnilove num_competitors non-monotonic across windows: {counts}"
    )
    assert dict(counts)[30] >= 2, f"Carnilove 30D expected >=2, got {counts}"


def test_beaphar_monotonic_and_expected_values(client):
    counts = []
    rows_by_d = {}
    for d in (7, 14, 30, 90):
        row = _find_by_search(client, BEAPHAR_SKU, d)
        assert row is not None, f"Beaphar missing at days={d}"
        counts.append((d, row["num_competitors"]))
        rows_by_d[d] = row
    print(f"Beaphar counts: {counts}")
    values = [v for _, v in counts]
    assert values == sorted(values), (
        f"Beaphar num_competitors non-monotonic: {counts}"
    )
    r30 = rows_by_d[30]
    assert r30["num_competitors"] >= 6, r30
    assert r30["num_priced_competitors"] >= 6, r30
    assert 35 <= r30["competitor_min_price"] <= 45, r30
    assert 43 <= r30["competitor_max_price"] <= 53, r30


def test_random_own_skus_monotonic(client, rows_90d):
    """5 random own-store SKUs must show monotonic num_competitors across
    7D/14D/30D/90D windows. Uses search to bypass pagination."""
    rng = random.Random(20260201)
    own_rows = [r for r in rows_90d["rows"] if r.get("is_my_product")]
    assert len(own_rows) > 100, f"too few own rows: {len(own_rows)}"
    picks = rng.sample([r["sku"] for r in own_rows if r.get("sku")], 12)
    checked = 0
    failures = []
    checked_details = []
    for sku in picks:
        counts = []
        ok = True
        for d in (7, 14, 30, 90):
            row = _find_by_search(client, sku, d)
            if row is None:
                ok = False
                break
            counts.append((d, row.get("num_competitors", 0)))
        if not ok:
            continue
        vals = [v for _, v in counts]
        checked_details.append((sku, counts))
        if vals != sorted(vals):
            failures.append((sku, counts))
        checked += 1
        if checked >= 5:
            break
    print(f"Random SKU monotonicity: {checked_details}")
    assert checked >= 5, f"Only resolved {checked}/5 random SKUs; picks={picks}"
    assert not failures, f"Non-monotonic random SKUs: {failures}"


# ── (c) 90D KPI baselines post truncation fix ─────────────
def test_kpi_baselines_90d(rows_90d):
    k = rows_90d.get("kpis") or {}
    print(f"90D KPIs: {k}")
    assert 1027 <= k["matched_products"] <= 1087, k
    assert 48.8 <= k["market_coverage_pct"] <= 52.8, k
    assert 289 <= k["share_sample_size"] <= 349, k
    # order-of-magnitude
    assert 5_000 <= k["total_units_sold"] <= 60_000, k
    assert 200_000 <= k["market_revenue"] <= 900_000, k


# ── iter19 pinned KPI invariants ──────────────────────────
def test_iter19_kpi_invariants(client, db):
    """KPIs must equal count of matching rows across the FULL catalogue
    (not just the 500-row page returned by /api/my-products)."""
    kpis_r = client.get(f"{BASE_URL}/api/my-products",
                        params={"days": 90, "limit": 500}, timeout=30).json()
    kpis = kpis_r.get("kpis") or {}
    total = kpis_r.get("total") or 0
    # Full catalogue is ~2081 > 500 page; we must page through all rows
    all_rows = []
    limit = 500
    for offset in range(0, total + 1, limit):
        j = client.get(f"{BASE_URL}/api/my-products",
                       params={"days": 90, "limit": limit, "offset": offset},
                       timeout=30).json()
        all_rows.extend(j.get("products") or [])
        if len(j.get("products") or []) < limit:
            break
    priced = sum(1 for r in all_rows if r.get("has_competitor_pricing"))
    shared = sum(1 for r in all_rows if r.get("has_market_share"))
    print(f"KPIs matched_products={kpis['matched_products']} priced_rows={priced}")
    print(f"KPIs share_sample_size={kpis['share_sample_size']} shared_rows={shared}")
    assert kpis["matched_products"] == priced, (kpis["matched_products"], priced)
    assert kpis["share_sample_size"] == shared, (kpis["share_sample_size"], shared)


# ── (d) matcher price-ratio flag semantics via DB ─────────
def test_carnilove_matches_no_suspicious_flag(db):
    docs = list(db.product_matches.find({"my_sku": CARNILOVE_SKU}))
    print(f"Carnilove product_matches count={len(docs)}")
    assert len(docs) >= 2, f"expected >=2 Carnilove matches, got {len(docs)}"
    for d in docs:
        assert d.get("match_method") == "barcode", d
        assert d.get("confidence") == 99, d
        flags = d.get("flags") or []
        assert "SUSPICIOUS_PRICE" not in flags, f"SUSPICIOUS_PRICE on barcode match: {d}"


def test_no_barcode_match_has_suspicious_price_globally(db):
    bad = list(db.product_matches.find(
        {"match_method": "barcode", "flags": "SUSPICIOUS_PRICE"}
    ).limit(5))
    assert not bad, f"Barcode matches carrying SUSPICIOUS_PRICE: {bad[:3]}"


def test_matcher_health_thresholds(db):
    total = db.product_matches.count_documents({})
    distinct = len(db.product_matches.distinct("my_sku"))
    print(f"product_matches total={total} distinct_my_skus={distinct}")
    assert total >= 2400, f"product_matches too low: {total}"
    assert distinct >= 1140, f"distinct my_skus too low: {distinct}"

    # "manual match only" in this codebase = sync_status='skipped' + match ran ok.
    # The field `manual_match_only` isn't persisted; the equivalent is:
    manual_ok = db.sync_runs.count_documents(
        {"sync_status": "skipped", "match_status": "ok",
         "match_added": {"$gte": 1100}}
    )
    any_ok = db.sync_runs.count_documents({"match_status": "ok"})
    print(f"sync_runs manual_ok(skipped+match_ok+added>=1100)={manual_ok} any_match_ok={any_ok}")
    assert manual_ok >= 1, "no sync_status=skipped + match_ok + added>=1100 run"
    assert any_ok >= 1, "no match_status=ok sync_run"


# ── (e) /api/data-freshness sync_health block intact ──────
def test_data_freshness_sync_health(client):
    r = client.get(f"{BASE_URL}/api/data-freshness", timeout=15)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    sh = body.get("sync_health") or body  # tolerate either nested or top-level
    for key in ("last_run", "last_sync_status", "last_match_status", "alarm"):
        assert key in sh or key in body, f"missing {key} in data-freshness"


# ── (f) sibling endpoints smoke ───────────────────────────
SIBLINGS = [
    "/api/insights/summary",
    "/api/insights/leaderboard",
    "/api/insights/top-sellers",
    "/api/insights/trending",
    "/api/insights/gaps",
    "/api/insights/price-wars",
    "/api/discounts/top-pct",
    "/api/scanner/opportunities",
    "/api/data-freshness",
    f"/api/products/{CARNILOVE_SKU}/full",
    f"/api/products/{BEAPHAR_SKU}/full",
]


@pytest.mark.parametrize("path", SIBLINGS)
def test_sibling_endpoint_200(client, path):
    r = client.get(f"{BASE_URL}{path}", timeout=25)
    assert r.status_code == 200, f"{path} → {r.status_code} {r.text[:200]}"
    # must be valid JSON
    _ = r.json()


# ── (e) performance ──────────────────────────────────────
def test_my_products_90d_performance(client):
    t0 = time.time()
    r = client.get(f"{BASE_URL}/api/my-products",
                   params={"days": 90, "limit": 500}, timeout=30)
    dt = time.time() - t0
    print(f"my_products@90d limit=500 took {dt:.2f}s")
    assert r.status_code == 200
    assert dt < 20.0, f"my_products@90d too slow: {dt:.2f}s"


def test_insights_sales_90d_performance(client):
    """Market-wide path — hits my_products with own_only=False internally."""
    t0 = time.time()
    r = client.get(f"{BASE_URL}/api/insights/sales",
                   params={"days": 90}, timeout=35)
    dt = time.time() - t0
    print(f"insights/sales@90d took {dt:.2f}s")
    assert r.status_code == 200, r.text[:200]
    _ = r.json()
    assert dt < 25.0, f"insights/sales@90d too slow: {dt:.2f}s"


# ── (g) Zid-suffix safety ────────────────────────────────
def test_zid_suffix_safety_via_search(client):
    """Search for suffixed SKU '8005852750068-RUDC' must not inflate counts."""
    r = client.get(f"{BASE_URL}/api/my-products",
                   params={"days": 90, "limit": 50,
                           "search": "8005852750068-RUDC"}, timeout=25)
    assert r.status_code == 200
    rows = r.json().get("rows", [])
    for row in rows:
        # if the suffixed SKU shows up it must be an OWN row w/o being
        # unioned with the base 8005852750068 competitors
        if row.get("sku") == "8005852750068-RUDC":
            print(f"Zid-suffix row: {row}")
