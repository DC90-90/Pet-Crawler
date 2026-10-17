"""Email delivery for the daily brief and weekly report (17 Oct 2026).

Sends through Resend (https://resend.com) when the server has RESEND_API_KEY
and REPORT_FROM_EMAIL (a sender on a domain verified in Resend), else reports
"not_configured" and the reports stay readable in Daleel. Recipients and
on/off switches live in app_settings "notifications", set on the Reports page.
"""
import logging
import os

import httpx

logger = logging.getLogger("notify")
RESEND_URL = "https://api.resend.com/emails"
DEFAULTS = {"daily_enabled": False, "weekly_enabled": False, "daily_recipients": [], "weekly_recipients": []}


def configured():
    return bool((os.environ.get("RESEND_API_KEY") or "").strip() and (os.environ.get("REPORT_FROM_EMAIL") or "").strip())


async def settings(db):
    doc = await db.app_settings.find_one({"_id": "notifications"}, {"_id": 0}) or {}
    return {**DEFAULTS, **{k: v for k, v in doc.items() if k in DEFAULTS}, "email_configured": configured(),
            "sender": (os.environ.get("REPORT_FROM_EMAIL") or "").strip() or None}


async def send_email(to, subject, html, http=None):
    to = [t.strip() for t in to if t and "@" in t]
    if not to:
        return {"status": "no_recipients"}
    if not configured():
        return {"status": "not_configured"}
    own = http is None
    http = http or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await http.post(RESEND_URL, json={"from": os.environ["REPORT_FROM_EMAIL"].strip(), "to": to,
                                                 "subject": subject, "html": html},
                               headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY'].strip()}"})
        if resp.status_code >= 300:
            logger.warning("[Notify] Resend refused: %s %s", resp.status_code, resp.text[:200])
            return {"status": "refused", "http_status": resp.status_code, "detail": resp.text[:300]}
        return {"status": "sent", "recipients": len(to)}
    except httpx.HTTPError as exc:
        return {"status": "error", "detail": f"{type(exc).__name__}"}
    finally:
        if own:
            await http.aclose()
