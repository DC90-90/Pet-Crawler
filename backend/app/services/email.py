"""Email service. No-op unless EMAIL_ENABLED (SMTP send left as integration point)."""
from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger("app.email")


async def _send(to: str, subject: str, body: str) -> bool:
    if not settings.email_enabled:
        logger.info("Email disabled; skipping send to %s (%s)", to, subject)
        return False
    # Integration point: wire real SMTP here. Kept as a safe no-op by default.
    logger.info("Would send email to %s: %s", to, subject)
    return True


async def send_password_reset(to: str, token: str) -> bool:
    link = f"{settings.public_site_url}/reset?token={token}"
    return await _send(to, "Password reset", f"Reset your password: {link}")


async def notify_new_inquiry(inquiry: dict) -> bool:
    if not settings.inquiry_notify_to:
        return False
    return await _send(
        settings.inquiry_notify_to,
        "New inquiry received",
        f"New inquiry from {inquiry.get('fullName')} <{inquiry.get('email')}>",
    )
