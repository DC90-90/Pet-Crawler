"""iter40 preview-only API verification for scope-dependent comparisons (read-only)."""

import pytest
import requests

from _auth import auth_headers, base_url


BASE = base_url().rstrip("/")
SKU = "8699245859829"


# modules/features: live preview scope resolution and endpoint consistency
@pytest.fixture(scope="module")
def headers():
    return auth_headers()


@pytest.fixture(scope="module")
def competitor_ids(headers):
    r = requests.get(f"{BASE}/api/stores", headers=headers, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    stores = body.get("stores") if isinstance(body, dict) else body
    stores = stores or []
    petsy = next((s for s in stores if "petsy" in (s.get("name") or "").lower()), None)
    zarafa = next((s for s in stores if "zarafa" in (s.get("name") or "").lower()), None)
    own = next((s for s in stores if s.get("is_own_store")), None)
    assert petsy and zarafa and own, f"missing expected stores: {[s.get('name') for s in stores]}"
    return {"petsy": petsy["id"], "zarafa": zarafa["id"], "own": own["id"]}


def _dashboard_row(headers, mode, ids):
    params = {"comparison_mode": mode, "competitor_ids": ids}
    r = requests.get(f"{BASE}/api/price-intel/dashboard", headers=headers, params=params, timeout=90)
    assert r.status_code == 200, r.text
    rows = r.json().get("full_table") or []
    return next((x for x in rows if x.get("my_sku") == SKU), None)


def test_price_intel_scope_switches_lowest_competitor(headers, competitor_ids):
    all_row = _dashboard_row(headers, "all", None)
    p_row = _dashboard_row(headers, "selected", competitor_ids["petsy"])
    z_row = _dashboard_row(headers, "selected", competitor_ids["zarafa"])
    none_row = _dashboard_row(headers, "selected", "")

    assert all_row and p_row and z_row and none_row
    assert all_row.get("cheapest_price") == 83.95
    assert p_row.get("cheapest_price") == 87.0
    assert z_row.get("cheapest_price") == 83.95
    assert none_row.get("cheapest_price") is None


def test_price_intel_detail_scope_switches_min_price(headers, competitor_ids):
    def detail(ids):
        r = requests.get(
            f"{BASE}/api/price-intel/product/{SKU}",
            headers=headers,
            params={"comparison_mode": "selected", "competitor_ids": ids},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        return r.json()["market_summary"]["lowest_price"]

    assert detail(competitor_ids["petsy"]) == 87.0
    assert detail(competitor_ids["zarafa"]) == 83.95
    assert detail("") is None


def test_scanner_scope_switches_market_lowest(headers, competitor_ids):
    def low(ids):
        r = requests.get(
            f"{BASE}/api/scanner/opportunities",
            headers=headers,
            params={"days": 14, "comparison_mode": "selected", "competitor_ids": ids},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        rows = (r.json().get("well_positioned") or []) + (r.json().get("opportunities") or [])
        row = next((x for x in rows if x.get("sku") == SKU), None)
        return row.get("market_lowest") if row else None

    assert low(competitor_ids["petsy"]) == 87.0
    assert low(competitor_ids["zarafa"]) == 83.95


def test_market_share_scope_consistent_on_my_products_and_detail(headers, competitor_ids):
    p = requests.get(
        f"{BASE}/api/market-share/my-products",
        headers=headers,
        params={"days": 30, "search": SKU, "comparison_mode": "selected", "competitor_ids": competitor_ids["petsy"]},
        timeout=90,
    )
    z = requests.get(
        f"{BASE}/api/market-share/my-products",
        headers=headers,
        params={"days": 30, "search": SKU, "comparison_mode": "selected", "competitor_ids": competitor_ids["zarafa"]},
        timeout=90,
    )
    assert p.status_code == 200 and z.status_code == 200
    p_row = next((x for x in p.json().get("rows", []) if x.get("sku") == SKU), None)
    z_row = next((x for x in z.json().get("rows", []) if x.get("sku") == SKU), None)
    assert p_row and z_row
    assert p_row.get("competitor_price_min") == 87.0
    assert z_row.get("competitor_price_min") == 83.95

    pd = requests.get(
        f"{BASE}/api/market-share/product/{SKU}",
        headers=headers,
        params={"days": 30, "comparison_mode": "selected", "competitor_ids": competitor_ids["petsy"]},
        timeout=90,
    )
    assert pd.status_code == 200
    assert pd.json()["product"]["competitor_price_min"] == 87.0
    sellers = [s for s in pd.json()["product"]["sellers"] if not s.get("is_own")]
    assert sellers and all("petsy" in (s.get("store_name") or "").lower() for s in sellers)


def test_market_share_export_includes_scope_fields(headers, competitor_ids):
    r = requests.get(
        f"{BASE}/api/market-share/export",
        headers=headers,
        params={"days": 30, "section": "my_products", "comparison_mode": "selected", "competitor_ids": competitor_ids["petsy"]},
        timeout=90,
    )
    assert r.status_code == 200
    txt = r.text
    assert "selected" in txt and competitor_ids["petsy"] in txt
    assert "proxy" in txt.lower() or "inventory" in txt.lower()


def test_unknown_or_own_store_ids_rejected_422(headers, competitor_ids):
    bad = requests.get(
        f"{BASE}/api/price-intel/dashboard",
        headers=headers,
        params={"comparison_mode": "selected", "competitor_ids": "unknown-store-id"},
        timeout=60,
    )
    own = requests.get(
        f"{BASE}/api/price-intel/dashboard",
        headers=headers,
        params={"comparison_mode": "selected", "competitor_ids": competitor_ids["own"]},
        timeout=60,
    )
    assert bad.status_code == 422
    assert own.status_code == 422


def test_my_products_search_contains_refreshed_hair_skin(headers):
    r = requests.get(
        f"{BASE}/api/my-products",
        headers=headers,
        params={"search": "Hair & Skin", "limit": 200, "offset": 0},
        timeout=90,
    )
    assert r.status_code == 200, r.text
    rows = r.json().get("products") or []
    assert {"5065023629268", "5065023629848", "Hair & Skin"} <= {x.get("sku") for x in rows}
