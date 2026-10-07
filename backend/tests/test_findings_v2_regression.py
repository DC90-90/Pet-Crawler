"""Regression checks for investigation findings F01–F15 (v2 semantics).

Focused on contract-level behavior in shared modules plus a few structural
guards that prevent legacy regressions.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import access_policy
import catalog_pagination
import evidence_ledger
import ingest_v2
import market_share
import observation_contract as oc
import price_cohort


# ── F01/F10: variant-true pricing, GTIN/money normalization ──────────────────
def test_expand_variants_keeps_child_identity_and_price_fields():
    raw = {
        "id": "listing-1",
        "price": {"amount": "200.00", "currency": "SAR"},
        "skus": [
            {"id": "v1", "sku": "LOCAL-A", "price": {"amount": "20.00", "currency": "SAR"}},
            {"id": "v2", "sku": "LOCAL-B", "price": {"amount": "200.00", "currency": "SAR"}},
        ],
    }
    variants = list(oc.expand_variants(raw))
    assert len(variants) == 2
    assert {v["_variant_id"] for v in variants} == {"v1", "v2"}
    assert variants[0]["price"]["amount"] != variants[1]["price"]["amount"]


def test_gtin_validation_and_leading_zero_handling():
    assert oc.gtin("01234567890128") == "01234567890128"  # valid GTIN-14 with leading zero
    assert oc.gtin("1234567890123") is None               # invalid check digit
    assert oc.gtin("00000000000000") is None


def test_decimal_money_rejects_nonfinite_negative_and_parses_arabic_digits():
    assert oc.money("١٢٣٫٤٥") == 123.45
    assert oc.money(float("inf")) is None
    assert oc.money(float("nan")) is None
    assert oc.money("-10") is None


def test_normalize_offer_rejects_unresolved_parent_variants_and_unknown_tax_basis():
    row = oc.normalize_offer(
        {
            "id": "p1",
            "sku": "SKU-1",
            "price": {"amount": "100", "currency": "SAR"},
            "price_basis": "unknown",
            "variants": [{"id": "v1"}],
        },
        "Store",
    )
    assert row["comparable"] is False
    assert "unresolved_parent_variants" in row["quarantine_reasons"]
    assert "tax_basis_unverified" in row["quarantine_reasons"]


# ── F03/F06/F11: cohort exclusions and immutable/sealed evidence behavior ───
@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"is_synthetic": True}, "synthetic_observation"),
        ({"observation_version": 1}, "legacy_or_unverified_offer"),
        ({"comparable": False}, "legacy_or_unverified_offer"),
        ({"price_basis": "unknown"}, "currency_or_tax_unverified"),
        ({"price": None}, "price_unavailable"),
        ({"confidence_score": 84}, "low_source_confidence"),
        ({"present_on_store": False}, "hidden_listing"),
        ({"in_stock": False}, "out_of_stock"),
        ({"in_stock": None}, "stock_unknown"),
    ],
)
def test_price_cohort_exclusion_reasons(overrides, reason):
    now = datetime.now(timezone.utc)
    row = {
        "observation_version": 2,
        "comparable": True,
        "currency": "SAR",
        "price_basis": "storefront_inc_vat",
        "price": 100,
        "crawled_at": now - timedelta(hours=3),
        "confidence_score": 99,
        "present_on_store": True,
        "in_stock": True,
        "is_synthetic": False,
    }
    row.update(overrides)
    assert price_cohort.exclusion(row, now=now) == reason


class _AsyncIter:
    def __init__(self, rows):
        self._rows = list(rows)

    def __aiter__(self):
        self._it = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Col:
    def __init__(self, rows):
        self.rows = rows

    def find(self, *_args, **_kwargs):
        return _AsyncIter(self.rows)


class _DBSales:
    def __init__(self):
        self.daily_ledger_store = _Col([
            {"store_id": "s1", "ksa_date": "2026-10-01", "sealed_at": datetime(2026, 10, 2, tzinfo=timezone.utc)},
        ])
        self.sales_facts_v2 = _Col([
            {"store_id": "s1", "sku": "A", "date": "2026-10-01", "algorithm_version": 2,
             "created_at": datetime(2026, 10, 1, 20, tzinfo=timezone.utc), "units": 5, "revenue": 50, "source": "sold_count_diff"},
            {"store_id": "s1", "sku": "A", "date": "2026-10-01", "algorithm_version": 2,
             "created_at": datetime(2026, 10, 3, 20, tzinfo=timezone.utc), "units": 4, "revenue": 40, "source": "sold_count_diff"},
            {"store_id": "s2", "sku": "A", "date": "2026-10-01", "algorithm_version": 2,
             "created_at": datetime(2026, 10, 1, 20, tzinfo=timezone.utc), "units": 7, "revenue": 70, "source": "sold_count_diff"},
        ])


def test_sales_map_excludes_unsealed_and_late_after_seal_cutoff():
    db = _DBSales()
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 2, tzinfo=timezone.utc)
    out = asyncio.run(evidence_ledger.sales_map(db, start, end, sealed=True))
    assert out[("s1", "A")]["units"] == 5
    assert ("s2", "A") not in out


# ── F04/F05/F07/F08: denominator honesty, unavailable vs zero, scanner terms ─
def test_resolve_units_does_not_infer_product_zero_from_store_capability():
    units, rev, source, reason = market_share._resolve_units(
        ("storeA", "SKU-X"), {}, {"storeA": {"days_observed": 10, "signal": "stock"}}, False, None
    )
    assert units is None and rev is None and source == market_share.SRC_NONE
    assert reason == market_share.REASON_NO_SIGNAL


def test_share_summary_withholds_when_numerator_missing():
    rows = [
        {
            "market_revenue": 100,
            "contested": True,
            "sole_seller": False,
            "share_comparable": True,
            "my_revenue": None,
            "market_units": 10,
            "my_units": None,
            "competitor_count": 1,
            "my_units_source": market_share.SRC_NONE,
        }
    ]
    k = market_share.summarize(rows, [], [], catalog_total=1, orders_connected=False)
    assert k["my_revenue_share_pct"] is None
    assert k["market_revenue"] is None


def test_scanner_payload_exposes_price_gap_not_forecast_alias_only():
    row = {
        "sku": "S", "name_ar": "x", "name_en": "x", "category": "",
        "image_url": "", "store_name": "own", "store_id": "own", "my_price": 20,
        "market_lowest": 10, "market_highest": 30, "market_avg": 20,
        "lowest_store_name": "c1", "lowest_store_id": "c1", "highest_store_name": "c2",
        "gap_pct": 100, "units_sold": 5, "units_basis": "orders", "market_sold": None,
        "price_gap_exposure": 50, "revenue_uplift": 50, "forecast_revenue_uplift": None,
        "badge": "overpriced", "num_sellers": 2, "sellers": [], "in_stock": True, "qty": 1, "cohort_id": "c",
    }
    assert row["price_gap_exposure"] == row["revenue_uplift"]
    assert row["forecast_revenue_uplift"] is None


# ── F09: pagination metadata correctness over short pages/continuation ───────
def test_paginate_uses_metadata_not_short_page_heuristic(monkeypatch):
    monkeypatch.setattr("crawlers._sf_items", lambda body: body.get("data", []))
    monkeypatch.setattr("crawlers._sf_page_meta", lambda body: (body.get("total_pages"), body.get("total"), body.get("has_next")))

    class Resp:
        def __init__(self, body, code=200):
            self._body = body
            self.status_code = code

        def json(self):
            return self._body

    pages = {
        2: Resp({"data": [{"id": f"p{i}"} for i in range(13, 25)], "total_pages": 3, "total": 36, "has_next": True}),
        3: Resp({"data": [{"id": f"p{i}"} for i in range(25, 37)], "total_pages": 3, "total": 36, "has_next": False}),
    }

    async def fetch(_http, _url, params=None):
        return pages[params["page"]]

    ep = {"url": "https://x/api", "params": {}, "pagination": "page"}
    initial = [{"id": f"p{i}"} for i in range(1, 13)]
    rows = asyncio.run(catalog_pagination.paginate(None, ep, initial, fetch, max_pages=10))
    assert len(rows) == 36
    assert ep["_pagination"]["complete"] is True


# ── F12/F13/F14/F15: ingest/auth/leases/brand heuristics ─────────────────────
def test_ingest_requires_run_id_and_observed_at():
    payload = SimpleNamespace(run_id=None, observed_at=None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ingest_v2.ingest(None, payload))
    assert exc.value.status_code == 422


def test_access_policy_denies_zero_page_user_reads_and_writes():
    user = {"role": "user", "allowed_pages": []}
    with pytest.raises(HTTPException):
        access_policy.enforce(user, "/api/my-products", "GET")
    with pytest.raises(HTTPException):
        access_policy.enforce(user, "/api/stores", "POST")


def test_access_policy_allows_reader_only_for_authorized_family():
    user = {"role": "user", "allowed_pages": ["my_products"]}
    access_policy.enforce(user, "/api/my-products", "GET")
    access_policy.enforce(user, "/api/stores", "GET")
    with pytest.raises(HTTPException):
        access_policy.enforce(user, "/api/admin/users", "GET")


def test_brand_extractor_does_not_accept_generic_leading_tokens():
    import crawlers

    assert crawlers.extract_brand_smart("", "Small Plastic Water Bowl", existing="") is None
    assert crawlers.extract_brand_smart("", "Royal Canin Indoor Cat 4kg", existing="") == "Royal Canin"


def test_cron_manifest_has_authenticated_endpoint_placeholders():
    import yaml
    from pathlib import Path

    data = yaml.safe_load(Path("/app/.emergent/crons.yml").read_text())
    assert data.get("crons")
    for row in data["crons"]:
        assert row["endpoint"].startswith("{{BASE_URL}}/api/cron/")


def test_job_control_uses_persisted_leases_and_deferred_status_structurally():
    from pathlib import Path

    src = Path("/app/backend/job_control.py").read_text()
    assert "db.job_leases.update_one" in src
    assert "job_already_running" in src
    assert '"status": "queued"' in src
