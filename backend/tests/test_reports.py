"""Daily brief / weekly report rendering and email delivery (17 Oct 2026)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import notify  # noqa: E402
import reports  # noqa: E402

DAILY = {"kind": "daily", "day": "2026-10-16", "counts": {"price_cuts": 1},
         "price_cuts": [{"name_ar": "رمل <قطط>", "store_name": "Hamtaro", "old_price": 80, "new_price": 70, "change_pct": -12.5, "my_price": 75}],
         "price_rises": [], "went_out": [], "came_back": [], "new_products": {"aleef": 3},
         "raise_now": [{"name_ar": "بريت", "price": 69, "recommended_price": 83.15, "profit_change_30d": 147.65}]}


def test_daily_email_is_rtl_escaped_and_has_its_sections():
    html = reports.render_html(DAILY)
    assert 'dir="rtl"' in html and "الموجز اليومي" in html
    assert "رمل &lt;قطط&gt;" in html and "<قطط>" not in html          # product names are escaped
    assert "خفّض منافسون أسعارهم (1)" in html and "فرص رفع السعر" in html and "aleef: 3" in html
    assert "رفع منافسون أسعارهم" not in html                           # empty sections are left out


def test_weekly_email_states_revenue_change_and_rank():
    html = reports.render_html({"kind": "weekly", "from": "2026-10-08", "to": "2026-10-14", "my_revenue": 19271.77,
                                "my_change_pct": -22.6, "my_rank": 5, "stores_ranked": 7, "ranking": [], "campaigns": []})
    assert "19,272 ريال" in html and "-22.6%" in html and "الترتيب 5 من 7" in html


class _Resp:
    def __init__(self, code):
        self.status_code, self.text = code, ""


class _Http:
    def __init__(self, code=200):
        self.code, self.sent = code, []

    async def post(self, url, json=None, headers=None):
        self.sent.append(json)
        return _Resp(self.code)


def test_email_needs_configuration_and_valid_recipients(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert asyncio.run(notify.send_email(["a@b.co"], "s", "<p>x</p>"))["status"] == "not_configured"
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setenv("REPORT_FROM_EMAIL", "Daleel <reports@example.com>")
    assert asyncio.run(notify.send_email(["not-an-email"], "s", "x"))["status"] == "no_recipients"
    http = _Http()
    assert asyncio.run(notify.send_email(["a@b.co"], "s", "<p>x</p>", http=http))["status"] == "sent"
    assert http.sent[0]["to"] == ["a@b.co"] and http.sent[0]["from"] == "Daleel <reports@example.com>"
    assert asyncio.run(notify.send_email(["a@b.co"], "s", "x", http=_Http(422)))["status"] == "refused"
