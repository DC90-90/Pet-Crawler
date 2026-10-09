"""Explicit release ownership and drain-to-freeze protocol. No startup writes.

Active permits never expire automatically: a crashed writer prevents a false
claim of quiescence. Legacy/unfenced processes must be stopped by an operator.
"""
import uuid
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from fastapi import HTTPException
from pymongo import ReturnDocument
from release_identity import identity

KEY = "release-write-control-v1"
CAPABILITIES = {k: False for k in ("automatic_refresh", "manual_refresh", "manual_edits", "exact_orders",
                                  "proxy_crawling", "email", "digests", "archive", "ledger_sealing")}
UNAVAILABLE = {"email", "digests"}  # Not implemented delivery must never be toggled into a success claim.
permit = ContextVar("release_write_permit", default=None)
request_path = ContextVar("release_request_path", default="")


class ReleaseBlocked(HTTPException):
    def __init__(self, reason, status_code=423):
        super().__init__(status_code=status_code, detail={"code": "release_write_blocked", "reason": reason})


def guarded(db):
    return type(db).__name__ == "GuardedDatabase" and type(db).__module__ == "release_database"


def initial():
    return {"mode": "observer", "revision": 0, "epoch": 0, "owner_release": None,
            "capabilities": dict(CAPABILITIES), "active_writers": [], "policy_version": 1}


async def state(db):
    raw = db.raw if guarded(db) else db
    return await raw.release_control.find_one({"_id": KEY}, {"_id": 0}) or initial()


async def feature(db, name):
    if not guarded(db):
        return True  # Isolated legacy domain tests do not implement the runtime control plane.
    s = await state(db)
    return name not in UNAVAILABLE and s["mode"] == "active" and s.get("owner_release") == identity()["release_id"] and s["capabilities"].get(name, False)


async def require_feature(db, name):
    if not await feature(db, name):
        raise ReleaseBlocked(f"{name}_disabled")


async def require_permit(db):
    if guarded(db):
        p = permit.get()
        if not p or p["database"] != db.name or p["purpose"] == "security":
            raise ReleaseBlocked("explicit_writer_permit_required")
        await validate(db, p)


async def _ensure_control(raw):
    await raw.release_control.update_one({"_id": KEY}, {"$setOnInsert": initial()}, upsert=True)


@asynccontextmanager
async def writer(db, purpose, capability=None, actor=None):
    if not guarded(db):
        yield
        return
    parent = permit.get()
    if parent and parent["database"] == db.name:
        await validate(db, parent)
        yield
        return
    raw, release = db.raw, identity()["release_id"]
    if purpose != "security" and (not identity()["manifest_verified"] or not re.fullmatch(r"[0-9a-f]{40}", identity().get("git_commit") or "")):
        raise ReleaseBlocked("verified_committed_build_required")
    await _ensure_control(raw)
    token = uuid.uuid4().hex
    query = {"_id": KEY}
    if purpose == "security":
        query["mode"] = {"$in": ["observer", "active"]}
    elif purpose.startswith("maintenance:"):
        query.update(mode="frozen", active_writers={"$size": 0}, owner_release=release)
    else:
        query.update(mode="active", owner_release=release)
        if not capability:
            raise ReleaseBlocked("writer_capability_required")
        query[f"capabilities.{capability}"] = True
    entry = {"token": token, "release": release, "purpose": purpose, "actor": actor,
             "started_at": datetime.now(timezone.utc).isoformat()}
    row = await raw.release_control.find_one_and_update(query, {"$push": {"active_writers": entry}}, return_document=ReturnDocument.AFTER)
    if not row:
        raise ReleaseBlocked("frozen_disabled_or_wrong_release_owner")
    p = {**entry, "epoch": row["epoch"], "database": db.name}
    context_token = permit.set(p)
    try:
        yield
    finally:
        permit.reset(context_token)
        await raw.release_control.update_one({"_id": KEY}, {"$pull": {"active_writers": {"token": token}}})
        await raw.release_control.update_one({"_id": KEY, "mode": "freezing", "active_writers": {"$size": 0}},
                                            {"$set": {"mode": "frozen"}})


async def validate(db, p):
    s = await state(db)
    known = any(w["token"] == p["token"] for w in s["active_writers"])
    maintenance = p["purpose"].startswith("maintenance:")
    allowed_modes = {"frozen", "freezing"} if maintenance else {"observer", "active", "freezing"}
    if not known or s["epoch"] != p["epoch"] or s["mode"] not in allowed_modes:
        raise ReleaseBlocked("writer_fence_lost")
    if p["purpose"] != "security" and s.get("owner_release") != p["release"]:
        raise ReleaseBlocked("writer_release_superseded")


async def transition(db, action, revision, actor, approval, capabilities=None, expected_release=None):
    raw = db.raw
    if not approval or len(approval.strip()) < 8:
        raise ReleaseBlocked("explicit_approval_reference_required", 422)
    await _ensure_control(raw)
    s = await state(db)
    if s["revision"] != revision:
        raise ReleaseBlocked("control_revision_changed", 409)
    changes = {"last_approval": approval, "last_actor": actor, "changed_at": datetime.now(timezone.utc).isoformat()}
    query = {"_id": KEY, "revision": revision}
    if action == "freeze":
        changes["mode"] = "freezing"
    elif action in {"observer", "activate"}:
        if s["mode"] != "frozen" or s["active_writers"]:
            raise ReleaseBlocked("freeze_and_drain_required", 409)
        release = identity()
        if expected_release != release["release_id"]:
            raise ReleaseBlocked("release_identity_mismatch", 409)
        caps = dict(CAPABILITIES)
        if action == "activate":
            if not release["manifest_verified"] or not re.fullmatch(r"[0-9a-f]{40}", release.get("git_commit") or ""):
                raise ReleaseBlocked("verified_committed_build_required", 409)
            if set(capabilities or {}) - set(caps) or any((capabilities or {}).get(k) for k in UNAVAILABLE):
                raise ReleaseBlocked("unsupported_capability", 422)
            caps.update(capabilities or {})
            if any(caps.values()):
                from release_preflight import writer_schema
                schema = await writer_schema(db)
                if not schema["ready"]:
                    raise ReleaseBlocked("explicit_integrity_index_operation_required", 409)
        changes.update(mode="active" if action == "activate" else "observer", owner_release=release["release_id"],
                       epoch=s["epoch"]+1, capabilities=caps)
        query.update(mode="frozen", active_writers={"$size": 0})
    elif action == "claim-maintenance":
        if s["mode"] != "frozen" or s["active_writers"] or expected_release != identity()["release_id"]:
            raise ReleaseBlocked("frozen_matching_release_required", 409)
        query.update(mode="frozen", active_writers={"$size": 0})
        changes.update(owner_release=expected_release, epoch=s["epoch"]+1)
    else:
        raise ReleaseBlocked("unknown_transition", 422)
    result = await raw.release_control.update_one(query, {"$set": changes, "$inc": {"revision": 1},
                                                        "$push": {"audit": {"action": action, **changes}}})
    if not result.matched_count:
        raise ReleaseBlocked("control_revision_changed", 409)
    await raw.release_control.update_one({"_id": KEY, "mode": "freezing", "active_writers": {"$size": 0}}, {"$set": {"mode": "frozen"}})
    return await state(db)