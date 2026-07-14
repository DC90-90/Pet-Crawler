"""Audit log service."""
from __future__ import annotations

from typing import Optional

from app.models.common import new_id, now_utc
from app.repositories.collections import audit_logs_repo

VALID_ACTIONS = {
    "login", "login_failed", "create", "edit", "publish", "unpublish",
    "archive", "delete", "media_replace", "user_change", "settings_change",
}


async def record(
    action: str,
    entity: str,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    entity_id: Optional[str] = None,
    summary: str = "",
    ip: Optional[str] = None,
) -> None:
    await audit_logs_repo.create(
        {
            "id": new_id(),
            "at": now_utc(),
            "userId": user_id,
            "userEmail": user_email,
            "action": action,
            "entity": entity,
            "entityId": entity_id,
            "summary": summary,
            "ip": ip,
        }
    )
