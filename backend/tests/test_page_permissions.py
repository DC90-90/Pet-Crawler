"""One permission per menu page; retired keys keep their access (23 Oct 2026)."""
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from access_policy import PAGES, effective_pages, enforce  # noqa: E402


def allowed(pages, path, method="GET"):
    try:
        enforce({"role": "user", "allowed_pages": pages}, path, method)
        return True
    except HTTPException:
        return False


def test_retired_keys_become_the_menu_pages_they_merged_into():
    # The client's account (screenshot, 23 Oct 2026).
    old = ["my_products", "price_intel", "insights", "scanner", "discounts", "alerts"]
    assert effective_pages(old) == ["overview", "my_products", "pricing", "opportunities", "reports", "alerts"]
    assert effective_pages(["stores"]) == ["competitors", "data_quality"]
    assert effective_pages(["market_share"]) == ["market_share", "key_brands", "opportunities"]
    assert effective_pages(["pricing", "nonsense"]) == ["pricing"]
    assert effective_pages(None) == []


def test_every_menu_page_opens_the_calls_it_makes():
    calls = {
        "overview": ["/api/insights/summary", "/api/market-share/overview", "/api/price-intel/store-ranking"],
        "my_products": ["/api/my-products/", "/api/products/123", "/api/export/products"],
        "pricing": ["/api/pricing/recommendations", "/api/price-intel/dashboard", "/api/insights/price-wars",
                    "/api/discounts/top-pct", "/api/promotions/calendar", "/api/scanner/opportunities"],
        "market_share": ["/api/market-share/overview", "/api/market-share/brands"],
        "key_brands": ["/api/brands/key", "/api/brands/key/audit"],
        "opportunities": ["/api/insights/top-sellers", "/api/insights/restock-opportunities", "/api/stock/planner",
                          "/api/market-share/missing-products"],
        "competitors": ["/api/stores/", "/api/stores/abc"],
        "reports": ["/api/reports/latest", "/api/notifications/settings"],
        "data_quality": ["/api/data-quality/coverage", "/api/data-quality/matches"],
        "alerts": ["/api/alerts/", "/api/notifications/"],
        "import": ["/api/import/status"],
    }
    assert set(calls) | {"settings"} == set(PAGES)
    for page, paths in calls.items():
        for path in paths:
            assert allowed([page], path), (page, path)


def test_pages_stay_separate_and_unknown_calls_fail_closed():
    assert not allowed(["pricing"], "/api/brands/key")
    assert not allowed(["key_brands"], "/api/pricing/recommendations")
    assert not allowed(["alerts"], "/api/data-quality/coverage")
    assert not allowed(["pricing"], "/api/something-new")
    assert not allowed(["pricing"], "/api/admin/users")
    assert not allowed(["pricing"], "/api/pricing/apply", "POST")       # writes stay with the super admin


def test_shared_lookups_need_at_least_one_page():
    assert allowed(["key_brands"], "/api/stores/brands") and allowed(["alerts"], "/api/data-freshness/")
    assert not allowed([], "/api/stores/brands")


def test_an_account_with_retired_keys_reaches_the_new_pages():
    old = ["my_products", "price_intel", "insights", "scanner", "discounts", "alerts"]
    assert allowed(old, "/api/pricing/recommendations") and allowed(old, "/api/reports/latest")
    assert not allowed(old, "/api/brands/key")                    # never had Market Share


@pytest.mark.parametrize("page", PAGES)
def test_super_admin_opens_everything(page):
    enforce({"role": "super_admin", "allowed_pages": []}, "/api/brands/key", "GET")
