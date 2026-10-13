"""Own price far from every competitor's is flagged for identity review;
merchant-hidden products are labelled hidden on the own store (13 Oct 2026)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from catalog_views import identity_check, hidden_on_storefront  # noqa: E402


def _cohort(*prices):
    return {"sellers": [{"price": p} for p in prices]}


def test_identity_check_flags_only_clear_outliers():
    assert identity_check(17.25, _cohort(33, 34.5, 34.51)) == "own_price_far_below_market"   # Persian barcode case
    assert identity_check(6.04, _cohort(11.96, 12.5)) == "own_price_far_below_market"        # piece vs pack
    assert identity_check(90, _cohort(93, 95, 96, 101.75)) is None                           # normal spread
    assert identity_check(300, _cohort(150, 160)) == "own_price_far_above_market"
    assert identity_check(6.04, _cohort(11.96)) is None        # one competitor is not enough evidence
    assert identity_check(None, _cohort(10, 11)) is None


def test_hidden_on_storefront_reads_the_sync_basis():
    assert hidden_on_storefront({"price_basis": "merchant_hidden_from_storefront_inc_vat"})
    assert hidden_on_storefront({"price_basis": "merchant_hidden_non_taxable"})
    assert not hidden_on_storefront({"price_basis": "storefront_inc_vat"})
    assert not hidden_on_storefront({})
