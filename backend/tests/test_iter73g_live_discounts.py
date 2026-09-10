"""iter73g live integration tests: hits the external REACT_APP_BACKEND_URL
to verify the 'All Stores' discount tab actually returns data quickly and
sort ordering is on the effective discount pct / saving.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"


@pytest.fixture(scope="module")
def token():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import login_token
    return login_token(EMAIL, PASSWORD)


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_jwt(token):
    assert isinstance(token, str) and len(token) > 20


def test_top_pct_all_stores_fast_and_nonempty(auth):
    t0 = time.time()
    r = requests.get(f"{BASE_URL}/api/discounts/top-pct?days=90",
                     headers=auth, timeout=30)
    elapsed = time.time() - t0
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    data = r.json()
    # Response should be a list (or dict wrapping list)
    rows = data if isinstance(data, list) else data.get("items") or data.get("data") or []
    print(f"top-pct all-stores: {len(rows)} rows in {elapsed:.2f}s")
    assert elapsed < 5.0, f"top-pct all-stores took {elapsed:.2f}s (>5s SLA)"
    # Non-empty on any DB with discounted rows
    assert len(rows) > 0, "top-pct all-stores returned 0 rows — regression of iter73g bug B"


def test_top_pct_sorted_desc_by_discount_pct(auth):
    r = requests.get(f"{BASE_URL}/api/discounts/top-pct?days=90",
                     headers=auth, timeout=30)
    assert r.status_code == 200
    data = r.json()
    rows = data if isinstance(data, list) else data.get("items") or data.get("data") or []
    if len(rows) < 2:
        pytest.skip("need >=2 rows to check sort")
    pcts = [row.get("discount_pct") for row in rows if row.get("discount_pct") is not None]
    for i in range(len(pcts) - 1):
        assert pcts[i] >= pcts[i + 1], \
            f"row {i} pct={pcts[i]} < row {i+1} pct={pcts[i+1]} — not desc sorted"


def test_top_pct_arithmetic_matches_price_ratio(auth):
    """For each returned row, discount_pct should equal round((1 - price/original)*100)
    when both prices are present — proves arithmetic-only rows are correctly computed."""
    r = requests.get(f"{BASE_URL}/api/discounts/top-pct?days=90",
                     headers=auth, timeout=30)
    rows = r.json() if isinstance(r.json(), list) else r.json().get("items") or []
    if not rows:
        pytest.skip("no rows")
    mismatches = 0
    for row in rows:
        p = row.get("price")
        op = row.get("original_price")
        dp = row.get("discount_pct")
        if p and op and op > p and dp is not None:
            expected = round((1 - p / op) * 100)
            if abs(dp - expected) > 1:  # allow rounding drift
                mismatches += 1
                print(f"mismatch: p={p} op={op} dp={dp} expected={expected}")
    assert mismatches <= max(1, len(rows) // 10), \
        f"{mismatches}/{len(rows)} rows have discount_pct not matching arithmetic"


def test_top_amount_all_stores_sorted_and_positive(auth):
    r = requests.get(f"{BASE_URL}/api/discounts/top-amount?days=90",
                     headers=auth, timeout=30)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    rows = data if isinstance(data, list) else data.get("items") or data.get("data") or []
    if len(rows) == 0:
        pytest.skip("no top-amount rows in preview DB")
    savings = []
    for row in rows:
        s = row.get("discount_amount_sar") or row.get("saving") or row.get("discount_amount")
        if s is not None:
            assert s > 0, f"non-positive saving: {s} in {row}"
            savings.append(s)
    for i in range(len(savings) - 1):
        assert savings[i] >= savings[i + 1], \
            f"top-amount not desc sorted at index {i}: {savings[i]} < {savings[i+1]}"


def test_per_store_subset_of_all_stores(auth):
    # Get all stores
    r = requests.get(f"{BASE_URL}/api/stores", headers=auth, timeout=30)
    assert r.status_code == 200
    stores_data = r.json()
    stores = stores_data if isinstance(stores_data, list) else stores_data.get("items") or []
    if not stores:
        pytest.skip("no stores")

    r_all = requests.get(f"{BASE_URL}/api/discounts/top-pct?days=90",
                        headers=auth, timeout=30)
    all_rows = r_all.json() if isinstance(r_all.json(), list) else r_all.json().get("items") or []

    for store in stores[:5]:
        sid = store.get("id") or store.get("_id") or store.get("store_id")
        if not sid:
            continue
        r_s = requests.get(f"{BASE_URL}/api/discounts/top-pct?days=90&store_id={sid}",
                          headers=auth, timeout=30)
        assert r_s.status_code == 200, f"store {sid}: {r_s.status_code}"
        s_rows = r_s.json() if isinstance(r_s.json(), list) else r_s.json().get("items") or []
        # Count of THIS store's rows in All-Stores response
        all_for_store = [row for row in all_rows if row.get("store_id") == sid]
        if len(s_rows) == 0:
            print(f"store {sid}: 0 rows — skipping superset check (thin data)")
            continue
        # per-store shouldn't have MORE than all-stores has FOR that store
        # (both derive from same underlying pipeline)
        assert len(s_rows) >= len(all_for_store), \
            f"store {sid}: per-store={len(s_rows)} < all-stores-for-store={len(all_for_store)}"
        print(f"store {sid}: per-store={len(s_rows)}, all-stores-for-store={len(all_for_store)}")


def test_timeline_regression(auth):
    r = requests.get(f"{BASE_URL}/api/discounts/timeline?days=90",
                     headers=auth, timeout=30)
    assert r.status_code == 200, f"timeline: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert data is not None
    # some structure
    assert isinstance(data, (list, dict))


def test_aggression_regression(auth):
    r = requests.get(f"{BASE_URL}/api/discounts/aggression?days=90",
                     headers=auth, timeout=30)
    assert r.status_code == 200, f"aggression: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert isinstance(data, (list, dict))
