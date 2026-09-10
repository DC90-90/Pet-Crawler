"""
Iteration 16 — Tests for:
 (1) GET /api/data-freshness  — banner data endpoint
 (2) /api/my-products search fixes — SKU/barcode + regex meta-char safety
"""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://daleel-price-intel.preview.emergentagent.com").rstrip("/")
SUPER_ADMIN_EMAIL = "a.disi@taqueen.sa"
SUPER_ADMIN_PASSWORD = "Ahmaddc90@"
VALID_BUCKETS = {"today", "this_week", "this_month", "stale", "no_data"}


@pytest.fixture(scope="module")
def auth_token():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import login_token
    return login_token(SUPER_ADMIN_EMAIL, SUPER_ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


# -------------------- /api/data-freshness --------------------
class TestDataFreshness:
    def test_endpoint_returns_200(self, headers):
        r = requests.get(f"{BASE_URL}/api/data-freshness", headers=headers, timeout=20)
        assert r.status_code == 200, r.text

    def test_response_shape(self, headers):
        r = requests.get(f"{BASE_URL}/api/data-freshness", headers=headers, timeout=20)
        data = r.json()
        # top-level keys
        for k in ["overall", "stores", "next_run", "crawl_paused", "checked_at"]:
            assert k in data, f"missing key {k}; got keys={list(data.keys())}"

        overall = data["overall"]
        for k in [
            "bucket",
            "age_days",
            "latest_competitor_crawl",
            "oldest_competitor_crawl",
            "own_store_last_sync",
            "competitor_store_count",
        ]:
            assert k in overall, f"missing overall.{k}"
        assert overall["bucket"] in VALID_BUCKETS

        assert isinstance(data["stores"], list)
        assert len(data["stores"]) > 0, "Expected at least one store entry"
        for s in data["stores"]:
            for k in [
                "store_id",
                "store_name",
                "is_own_store",
                "last_crawled_at",
                "age_days",
                "bucket",
                "snapshot_count",
            ]:
                assert k in s, f"missing store.{k}; row={s}"
            assert s["bucket"] in VALID_BUCKETS

    def test_own_store_is_today(self, headers):
        r = requests.get(f"{BASE_URL}/api/data-freshness", headers=headers, timeout=20)
        data = r.json()
        own_stores = [s for s in data["stores"] if s.get("is_own_store")]
        assert len(own_stores) >= 1, "Expected at least one own_store entry (Pets houses)"
        own = own_stores[0]
        # own-store should be fresh (today) because Zid syncs every 6h
        assert own["bucket"] == "today", (
            f"Own store bucket expected 'today', got {own['bucket']} (age_days={own.get('age_days')})"
        )

    def test_competitors_stale(self, headers):
        r = requests.get(f"{BASE_URL}/api/data-freshness", headers=headers, timeout=20)
        data = r.json()
        competitors = [s for s in data["stores"] if not s.get("is_own_store")]
        assert len(competitors) > 0, "Expected competitor stores"
        # Per spec: competitor crawls last ran 36-70d ago => 'stale'
        stale_count = sum(1 for s in competitors if s["bucket"] == "stale")
        assert stale_count >= 1, (
            f"Expected >=1 stale competitor; got buckets={[s['bucket'] for s in competitors]}"
        )


# -------------------- /api/my-products search fix --------------------
class TestMyProductsSearch:
    def test_exact_sku_returns_single_product(self, headers):
        sku = "8595602569199"
        r = requests.get(
            f"{BASE_URL}/api/my-products",
            params={"search": sku, "days": 90, "limit": 5},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        products = data.get("products", data) if isinstance(data, dict) else data
        assert isinstance(products, list), f"Unexpected payload: {type(products)}"
        assert len(products) == 1, f"Expected exactly 1 product, got {len(products)}"
        p = products[0]
        # SKU OR barcode should equal the searched value
        assert (
            str(p.get("sku")) == sku or str(p.get("barcode")) == sku
        ), f"Got product with sku={p.get('sku')} barcode={p.get('barcode')}"

    def test_partial_prefix_matches_many(self, headers):
        prefix = "8005852"
        r = requests.get(
            f"{BASE_URL}/api/my-products",
            params={"search": prefix, "days": 90, "limit": 10},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        products = data.get("products", data) if isinstance(data, dict) else data
        assert isinstance(products, list)
        assert len(products) > 0, "Expected partial-prefix search to return >=1 product"
        for p in products:
            sku = str(p.get("sku") or "")
            barcode = str(p.get("barcode") or "")
            assert prefix in sku or prefix in barcode, (
                f"Product missing prefix '{prefix}' in sku/barcode: sku={sku} barcode={barcode} name={p.get('name')}"
            )

    def test_regex_metachar_escaped(self, headers):
        # ".*" must be literal — not a regex wildcard
        r = requests.get(
            f"{BASE_URL}/api/my-products",
            params={"search": ".*", "days": 90, "limit": 5},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        products = data.get("products", data) if isinstance(data, dict) else data
        assert isinstance(products, list)
        # Should be 0 (or only items literally containing '.*'); definitely not 5
        for p in products:
            blob = (
                f"{p.get('sku','')} {p.get('barcode','')} "
                f"{p.get('name','')} {p.get('name_en','')} {p.get('name_ar','')}"
            )
            assert ".*" in blob, (
                f"regex meta-char leaked: search='.*' returned non-matching product sku={p.get('sku')} name={p.get('name')}"
            )

    def test_name_search_regression(self, headers):
        r = requests.get(
            f"{BASE_URL}/api/my-products",
            params={"search": "Royal", "days": 90, "limit": 10},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        products = data.get("products", data) if isinstance(data, dict) else data
        assert isinstance(products, list)
        assert len(products) > 0, "Expected 'Royal' name search to return products"
        royal_hits = sum(
            1
            for p in products
            if "royal" in ((p.get("name") or p.get("name_en") or p.get("name_ar") or "").lower())
        )
        assert royal_hits >= 1, (
            f"Expected >=1 product with 'Royal' in name; "
            f"got names_en={[p.get('name_en') for p in products]}"
        )
