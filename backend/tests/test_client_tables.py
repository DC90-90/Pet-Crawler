"""The client's two plain tables: units per product and price per store
(2 Nov 2026)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import client_tables  # noqa: E402

STORES = [{"store_id": "own", "store_name": "Pets houses", "is_own": True},
          {"store_id": "a", "store_name": "Zarafa"},
          {"store_id": "b", "store_name": "Petsy"},
          {"store_id": "c", "store_name": "Lana Pets"}]


def _row(**kw):
    row = {"canonical_key": "0763163284440", "sku": "0763163284440", "barcode": "763163284440",
           "name_ar": "كت كات تونة وجمبري 400غ", "name_en": "KitCat Tuna & Prawn 400g",
           "brand": "Kit Cat", "category": "القطط", "my_price": 7.01,
           "my_units": 12, "market_units": 152, "sellers_with_sales": 6, "sellers_total": 10, "sellers": []}
    row.update(kw)
    return row


def test_a_row_carries_exactly_what_the_client_asked_for():
    out = client_tables.build({"stores": STORES, "my_products": [_row()], "window": {"days": 30}})
    assert out["own_store"] == {"store_id": "own", "store_name": "Pets houses"}
    assert [c["store_name"] for c in out["competitors"]] == ["Zarafa", "Petsy", "Lana Pets"]
    r = out["rows"][0]
    assert (r["name_ar"], r["brand"], r["category"]) == ("كت كات تونة وجمبري 400غ", "Kit Cat", "القطط")
    assert (r["my_units"], r["market_units"], r["my_price"]) == (12, 152, 7.01)


def test_unknown_units_stay_unknown_not_zero():
    r = client_tables.build({"stores": STORES, "my_products": [_row(my_units=None, market_units=None)]})["rows"][0]
    assert r["my_units"] is None and r["market_units"] is None


def test_one_price_per_store_in_its_own_column():
    sellers = [
        {"store_id": "own", "is_own": True, "price": 7.01},
        {"store_id": "a", "price": 8.0}, {"store_id": "a", "price": 7.5},             # two offers: the cheaper
        {"store_id": "b", "price": None, "price_excluded_reason": "out_of_stock", "historical_price": 6.5},
        {"store_id": "c", "price": None, "price_excluded_reason": "stale_price", "historical_price": 5.0},
        {"store_id": "gone", "price": 9.0},                                         # not a tracked store
    ]
    r = client_tables.build({"stores": STORES, "my_products": [_row(sellers=sellers)]})["rows"][0]
    # Columns follow `competitors`: 0 Zarafa, 1 Petsy, 2 Lana Pets.
    assert r["prices"] == {"0": [7.5, False], "1": [6.5, True]}


def test_an_in_stock_offer_beats_an_out_of_stock_one_at_the_same_store():
    sellers = [{"store_id": "a", "price": None, "price_excluded_reason": "out_of_stock", "historical_price": 5.0},
               {"store_id": "a", "price": 9.0}]
    r = client_tables.build({"stores": STORES, "my_products": [_row(sellers=sellers)]})["rows"][0]
    assert r["prices"] == {"0": [9.0, False]}
