"""Price-position bands are exclusive and add up to the products compared: the
overlapping counts (cheapest is also below the median) summed to 1,648 of 951
products on the Overview (15 Oct 2026)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_bands_are_exclusive_and_sum_to_ranked():
    from comparison_views import _position_bands
    r = lambda c=False, e=False, b=False, a=False: {"is_cheapest": c, "is_most_expensive": e, "below_median": b, "above_median": a}  # noqa: E731
    ranked = [r(c=True, b=True), r(c=True, b=True), r(b=True), r(), r(a=True), r(e=True, a=True), r(c=True, e=True)]
    bands = _position_bands(ranked)
    assert bands == {"cheapest": 3, "below_median": 1, "at_median": 1, "above_median": 1, "most_expensive": 1}
    assert sum(bands.values()) == len(ranked)
