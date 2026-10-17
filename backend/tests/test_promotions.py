"""Promotions calendar campaign detection (17 Oct 2026)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import promotions  # noqa: E402


def _day(i, share, read=100, disc=20.0):
    return {"date": f"2026-09-{i:02d}", "read": read, "on_sale": int(share * read / 100), "share_pct": share, "avg_discount_pct": disc}


def test_campaign_is_a_run_clearly_above_the_stores_usual_level():
    days = [_day(i, 10.0) for i in range(1, 21)]
    days[9], days[10], days[12] = _day(10, 30.0, disc=35.0), _day(11, 28.0, disc=33.0), _day(13, 25.0)   # one-day gap merges
    days[5] = _day(6, 40.0, read=20)                       # partial crawl day: ignored
    campaigns, base = promotions.detect_campaigns(days)
    assert base == 10.0
    assert len(campaigns) == 1
    c = campaigns[0]
    assert (c["start"], c["end"], c["length_days"], c["peak_share_pct"]) == ("2026-09-10", "2026-09-13", 4, 30.0)


def test_permanent_discounter_has_no_campaigns_and_short_history_none():
    assert promotions.detect_campaigns([_day(i, 45.0) for i in range(1, 21)])[0] == []
    assert promotions.detect_campaigns([_day(i, 10.0) for i in range(1, 5)]) == ([], None)
