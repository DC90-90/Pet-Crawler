"""
iter73f test: Revenue consistency between store profile, insights leaderboard,
and market strength ranking; plus regression checks for discount endpoints.
"""
import os
import requests
import pytest

def _load_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip()
                        break
        except Exception:
            pass
    assert v, "REACT_APP_BACKEND_URL not set"
    return v.rstrip("/")

BASE_URL = _load_backend_url()
EMAIL = "a.disi@taqueen.sa"
PASSWORD = "Ahmaddc90@"


@pytest.fixture(scope="module")
def token():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import login_token
    tok = login_token(EMAIL, PASSWORD)
    assert isinstance(tok, str) and len(tok) > 10
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


# --- Auth login sanity ---
def test_login_returns_jwt(token):
    assert token


# --- Leaderboard shape ---
def test_insights_leaderboard_shape(headers):
    r = requests.get(f"{BASE_URL}/api/insights/leaderboard?days=30",
                     headers=headers, timeout=60)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    # accept either list or dict wrapper
    rows = body if isinstance(body, list) else (
        body.get("stores") or body.get("leaderboard") or body.get("items") or body.get("data") or []
    )
    assert isinstance(rows, list)
    print(f"leaderboard rows: {len(rows)}")
    for row in rows:
        assert "revenue_est" in row, f"missing revenue_est in {list(row.keys())}"
        assert "revenue_status" in row, f"missing revenue_status in {list(row.keys())}"
        assert "units_sold" in row, f"missing units_sold in {list(row.keys())}"
        rev = row["revenue_est"] or 0
        status = row["revenue_status"]
        assert status in ("computed", "sales_data_unavailable", "insufficient_history"), status
        if rev and rev > 0:
            assert status == "computed", f"positive revenue={rev} but status={status}"
        else:
            assert status in ("sales_data_unavailable", "insufficient_history"), status


# --- Store ranking sort order ---
def test_store_ranking_sorted_by_revenue(headers):
    r = requests.get(f"{BASE_URL}/api/price-intel/store-ranking",
                     headers=headers, timeout=60)
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    rows = body.get("stores") if isinstance(body, dict) else body
    assert isinstance(rows, list)
    print(f"ranking rows: {len(rows)}")

    # collect revenue_rank_value list; nulls must all be at end
    vals = [row.get("revenue_rank_value") for row in rows]
    seen_null = False
    for v in vals:
        if v is None:
            seen_null = True
        else:
            assert not seen_null, "non-null revenue_rank_value appears after a null"

    # descending among non-nulls
    non_null = [v for v in vals if v is not None]
    for i in range(len(non_null) - 1):
        assert non_null[i] >= non_null[i + 1], (
            f"not descending at {i}: {non_null[i]} < {non_null[i+1]}"
        )


# --- Profile revenue_status + consistency with leaderboard ---
def test_store_profile_revenue_status_and_consistency(headers):
    # Get stores
    r_stores = requests.get(f"{BASE_URL}/api/stores", headers=headers, timeout=60)
    assert r_stores.status_code == 200, r_stores.text[:300]
    stores_body = r_stores.json()
    stores = stores_body if isinstance(stores_body, list) else (
        stores_body.get("stores") or stores_body.get("items") or []
    )
    assert len(stores) > 0, "no stores available"

    # Grab leaderboard for consistency map
    lb = requests.get(f"{BASE_URL}/api/insights/leaderboard?days=30",
                      headers=headers, timeout=60).json()
    lb_rows = lb if isinstance(lb, list) else (
        lb.get("stores") or lb.get("leaderboard") or lb.get("items") or lb.get("data") or []
    )
    lb_map = {}
    for row in lb_rows:
        sid = row.get("store_id") or row.get("id") or row.get("_id")
        if sid:
            lb_map[str(sid)] = row

    tested = 0
    checked_positive = 0
    # Test up to first 5 stores
    for s in stores[:5]:
        sid = s.get("id") or s.get("_id") or s.get("store_id")
        if not sid:
            continue
        sid = str(sid)
        r = requests.get(f"{BASE_URL}/api/stores/{sid}/profile",
                         headers=headers, timeout=60)
        assert r.status_code == 200, f"profile {sid}: {r.status_code} {r.text[:200]}"
        prof = r.json()
        kpis = prof.get("kpis") or {}
        assert "revenue_status" in kpis, f"revenue_status missing in kpis for {sid}: keys={list(kpis.keys())}"
        rs = kpis["revenue_status"]
        assert rs in ("computed", "sales_data_unavailable", "insufficient_history"), rs
        assert "est_monthly_revenue" in kpis, "est_monthly_revenue missing"
        prof_rev = kpis["est_monthly_revenue"] or 0
        tested += 1

        lb_row = lb_map.get(sid)
        if lb_row:
            lb_rev = lb_row.get("revenue_est") or 0
            if lb_rev > 0:
                assert prof_rev > 0, (
                    f"store {sid}: leaderboard revenue={lb_rev} but profile revenue={prof_rev}"
                )
                assert rs == "computed", f"store {sid}: lb rev>0 but profile status={rs}"
                checked_positive += 1

    assert tested >= 1, "no store profiles tested"
    print(f"profiles tested: {tested}; positive-revenue consistency checks: {checked_positive}")


# --- Discount endpoints must not 500 ---
@pytest.mark.parametrize("path", [
    "/api/discounts/top-pct?days=90",
    "/api/discounts/top-amount?days=90",
    "/api/discounts/timeline",
    "/api/discounts/aggression",
])
def test_discount_endpoints_no_500(headers, path):
    r = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=60)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:300]}"
