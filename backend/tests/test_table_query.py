"""Per-column filters and sorting for the Market tables (27 Oct 2026)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import table_query as tq  # noqa: E402

ROWS = [
    {"name": "Felyn Go Litter Box", "brand": "Felyn Go", "market_units": 62, "competitors": ["Lana Pets", "Mowkly"],
     "top_competitor": {"store_name": "Lana Pets"}, "trend": {"revenue_pct": 12.5}, "confidence": "low"},
    {"name": "Meow tuna 30 cans", "brand": "Meow", "market_units": 259, "competitors": ["Panda Store"],
     "top_competitor": None, "trend": {"revenue_pct": -3}, "confidence": "medium"},
    {"name": "Pramy wet 70g", "brand": None, "market_units": None, "competitors": ["CutePets", "Hamtaro"],
     "top_competitor": {"store_name": "CutePets"}, "trend": {}, "confidence": "unavailable"},
]


def names(rows):
    return [r["name"].split()[0] for r in rows]


def test_text_number_and_list_filters_combine():
    assert names(tq.apply(ROWS, json.dumps({"name": {"q": "TUNA"}}))) == ["Meow"]
    assert names(tq.apply(ROWS, json.dumps({"market_units": {"min": 100}}))) == ["Meow"]
    assert names(tq.apply(ROWS, json.dumps({"market_units": {"min": "", "max": 100}}))) == ["Felyn"]
    assert names(tq.apply(ROWS, json.dumps({"competitors": {"q": "panda"}}))) == ["Meow"]
    assert names(tq.apply(ROWS, json.dumps({"top_competitor.store_name": {"q": "cute"}}))) == ["Pramy"]
    assert names(tq.apply(ROWS, json.dumps({"confidence": {"in": ["Low", "medium"]}}))) == ["Felyn", "Meow"]
    assert names(tq.apply(ROWS, json.dumps({"brand": {"q": "o"}, "market_units": {"min": 50}}))) == ["Felyn", "Meow"]


def test_a_missing_value_never_passes_a_filter_on_it():
    assert names(tq.apply(ROWS, json.dumps({"brand": {"q": ""}}))) == ["Felyn", "Meow", "Pramy"]   # empty = no filter
    assert "Pramy" not in names(tq.apply(ROWS, json.dumps({"market_units": {"max": 1000}})))


def test_sort_by_any_column_blanks_last():
    assert names(tq.apply(ROWS, None, "market_units", "desc")) == ["Meow", "Felyn", "Pramy"]
    assert names(tq.apply(ROWS, None, "market_units", "asc")) == ["Felyn", "Meow", "Pramy"]
    assert names(tq.apply(ROWS, None, "trend.revenue_pct", "asc")) == ["Meow", "Felyn", "Pramy"]
    assert names(tq.apply(ROWS, None, "brand", "asc")) == ["Felyn", "Meow", "Pramy"]


def test_bad_input_changes_nothing():
    assert tq.apply(ROWS, "not json") == ROWS
    assert tq.apply(ROWS, json.dumps(["a"])) == ROWS
    assert tq.apply(ROWS, json.dumps({"name": "x"})) == ROWS
