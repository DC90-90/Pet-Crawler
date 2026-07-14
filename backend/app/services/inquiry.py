"""Inquiry service: create, update (status/notes/timeline), CSV export."""
from __future__ import annotations

import csv
import io
from typing import Optional

from app.core.security import hash_ip
from app.models.common import new_id, now_utc
from app.repositories.collections import inquiries_repo
from app.services import audit
from app.services.email import notify_new_inquiry

VALID_STATUSES = {
    "new", "reviewing", "contacted", "quoted", "confirmed", "completed", "closed", "spam",
}


async def create_inquiry(payload: dict, ip: Optional[str]) -> dict:
    doc = dict(payload)
    doc["id"] = new_id()
    doc["status"] = "new"
    doc["notes"] = []
    doc["timeline"] = [{"type": "created", "at": now_utc(), "by": None, "summary": "Inquiry received"}]
    doc["ipHash"] = hash_ip(ip)
    doc["createdAt"] = now_utc()
    doc["updatedAt"] = now_utc()
    created = await inquiries_repo.create(doc)
    await audit.record("create", "inquiry", entity_id=created["id"], summary="New inquiry")
    await notify_new_inquiry(created)
    return created


async def update_inquiry(
    inquiry_id: str, *, status: Optional[str], note_text: Optional[str],
    timeline_summary: Optional[str], actor: dict,
) -> Optional[dict]:
    doc = await inquiries_repo.get(inquiry_id)
    if not doc:
        return None
    patch: dict = {}
    if status:
        if status not in VALID_STATUSES:
            raise ValueError("Invalid status")
        patch["status"] = status
    notes = list(doc.get("notes", []))
    timeline = list(doc.get("timeline", []))
    if note_text:
        notes.append({"authorId": actor.get("id"), "text": note_text, "at": now_utc()})
        patch["notes"] = notes
    if status or timeline_summary:
        timeline.append(
            {
                "type": "status_change" if status else "note",
                "at": now_utc(),
                "by": actor.get("id"),
                "summary": timeline_summary or (f"Status → {status}" if status else ""),
            }
        )
        patch["timeline"] = timeline
    updated = await inquiries_repo.update(inquiry_id, patch)
    await audit.record(
        "edit", "inquiry", user_id=actor.get("id"), user_email=actor.get("email"),
        entity_id=inquiry_id, summary="Updated inquiry",
    )
    return updated


def to_csv(inquiries: list[dict]) -> str:
    buf = io.StringIO()
    fields = [
        "id", "fullName", "email", "phone", "country", "status", "groupSize",
        "children", "selectedTourId", "arrivalDate", "departureDate", "message",
        "consent", "marketingOptIn", "createdAt",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for inq in inquiries:
        writer.writerow({k: inq.get(k, "") for k in fields})
    return buf.getvalue()
