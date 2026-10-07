"""One interval estimator for all proxy analytics. Not a sales or revenue claim."""
from datetime import datetime, timezone
from observation_contract import decimal_number

VERSION = 2
PLACEHOLDERS = {99, 100, 999, 1000, 9999, 10000, 99999, 100000}


def number(v):
    value = decimal_number(v)
    return float(value) if value is not None else None


def interval(previous, current):
    """Returns (units, shelf-value proxy, method); None means no valid interval."""
    if any(s.get("is_synthetic") or s.get("quarantined") for s in (previous, current)):
        return None, None, "unavailable"
    if any(s.get("confidence_score") is not None and s["confidence_score"] < 85 for s in (previous, current)):
        return None, None, "low_source_confidence"
    times = [s.get("crawled_at") or s.get("observed_at") for s in (previous, current)]
    if all(isinstance(t, datetime) for t in times):
        seconds = (times[1].replace(tzinfo=timezone.utc) - times[0].replace(tzinfo=timezone.utc)).total_seconds()
        if seconds <= 0 or seconds > 48 * 3600:
            return None, None, "observation_gap"
    sold = [number(s.get("sold_count")) for s in (previous, current)]
    counter_present = any(v is not None and v > 0 for v in sold) or all(s.get("sold_count_observed") is True for s in (previous, current))
    if counter_present:
        if None in sold or any(s.get("sold_count_capped") for s in (previous, current)):
            return None, None, "counter_gap"
        delta = sold[1] - sold[0]
        if delta < 0 or delta > 50:
            return None, None, "counter_anomaly"
        method = "sold_count_diff"
    else:
        qty = [number(s.get("qty_available")) for s in (previous, current)]
        if any(v is None or v in PLACEHOLDERS or v > 200 for v in qty):
            return None, None, "stock_gap"
        delta = max(0, qty[0] - qty[1])
        if delta > 10:
            return None, None, "stock_anomaly"
        method = "qty_positive_delta_sum"
    price = number(current.get("price"))
    return delta, round(delta * price, 2) if price is not None and price > 0 else None, method


def estimate(snaps, days):
    if len(snaps or []) < 2:
        return 0, 0.0, "insufficient_data"
    results = [interval(a, b) for a, b in zip(snaps, snaps[1:])]
    valid = [r for r in results if r[0] is not None]
    if not valid:
        return 0, 0.0, "insufficient_signal"
    # A counter takes precedence for the whole series; no switching to stock at a missing counter.
    counter_series = any(number(s.get("sold_count")) not in (None, 0) or s.get("sold_count_observed") for s in snaps)
    if counter_series:
        valid = [r for r in valid if r[2] == "sold_count_diff"]
    if not valid:
        return 0, 0.0, "insufficient_signal"
    units = sum(r[0] for r in valid)
    if units > 30 * max(1, days):
        return 0, 0.0, "anomalous_signal"
    return units, round(sum(r[1] or 0 for r in valid), 2), valid[0][2]