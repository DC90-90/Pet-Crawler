"""A product without an observed interval at a store that does publish stock
is not reported as a store without any sales signal (12 Oct 2026)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import market_share as ms  # noqa: E402


def test_reason_distinguishes_store_capability_from_product_coverage():
    sales = {}
    stock_store = {"S": {"days_observed": 9, "signal": "stock"}}
    blind_store = {"S": {"days_observed": 9, "signal": "none"}}
    assert ms._resolve_units(("S", "o1"), sales, stock_store, False, None)[3] == ms.REASON_NO_INTERVAL
    assert ms._resolve_units(("S", "o1"), sales, blind_store, False, None)[3] == ms.REASON_NO_SIGNAL
    assert ms._resolve_units(("S", "o1"), sales, {"S": {"days_observed": 1, "signal": "stock"}}, False, None)[3] == ms.REASON_ONE_CRAWL
    assert ms._resolve_units(("S", "o1"), sales, {}, False, None)[3] == ms.REASON_NOT_CRAWLED
    sales = {("S", "o1"): {"units": 3, "revenue": 30.0, "source": "inventory_proxy"}}
    assert ms._resolve_units(("S", "o1"), sales, stock_store, False, None) == (3, 30.0, "inventory_proxy", None)


def test_frontend_has_a_label_for_every_reason():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "components", "marketShare", "SourceChip.jsx")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    for reason in (ms.REASON_NO_SIGNAL, ms.REASON_ONE_CRAWL, ms.REASON_NO_SELLER_DATA, ms.REASON_NOT_CRAWLED, ms.REASON_NO_INTERVAL):
        assert f"{reason}:" in src, reason
