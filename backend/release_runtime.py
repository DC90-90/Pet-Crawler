"""Request lifecycle permits and truthful public release/capability state."""
from contextlib import AsyncExitStack
from contextvars import ContextVar
from fastapi import HTTPException
from release_control import guarded, state, feature, require_feature, writer, request_path, ReleaseBlocked, UNAVAILABLE
from release_identity import identity

request_stack = ContextVar("release_request_stack", default=None)
JOB_CAPABILITIES = {"crawl": "automatic_refresh", "own-sync": "automatic_refresh", "seal": "ledger_sealing",
                    "archive": "archive", "digest": "digests", "manual-own-sync": "manual_refresh", "matching": "manual_refresh"}


class ReleaseRequestContext:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        async with AsyncExitStack() as stack:
            token = request_stack.set(stack)
            path_token = request_path.set(scope.get("path", ""))
            try:
                await self.app(scope, receive, send)
            finally:
                request_path.reset(path_token)
                request_stack.reset(token)


async def begin_request(db, purpose, capability=None, actor=None):
    if not guarded(db):
        return
    if capability:
        await require_feature(db, capability)
    stack = request_stack.get()
    if stack is None:
        raise ReleaseBlocked("request_lifecycle_missing")
    await stack.enter_async_context(writer(db, purpose, capability, actor))


async def authorize_request(db, request, actor):
    if not guarded(db):
        return
    path = request.url.path
    if path.startswith(("/api/admin/release", "/api/admin/maintenance")):
        return  # These handlers separately require the existing super-admin dependency.
    if path.startswith("/api/zid") and not await feature(db, "exact_orders"):
        raise ReleaseBlocked("exact_orders_disabled")
    if path.startswith(("/api/alerts", "/api/notifications", "/api/digest")):
        raise ReleaseBlocked("outbound_notifications_unavailable")
    if path == "/api/import/sync-orders" and not await feature(db, "exact_orders"):
        raise ReleaseBlocked("exact_orders_disabled")
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    if path.startswith("/api/auth/"):
        return
    # Existing data-changing admin endpoints cannot bypass explicit maintenance.
    if path.startswith("/api/admin/"):
        raise ReleaseBlocked("use_explicit_maintenance_plan_and_apply")
    refresh = any(word in path for word in ("crawl", "sync", "match", "import", "refresh", "backfill", "rebuild"))
    cap = "manual_refresh" if refresh else "manual_edits"
    await begin_request(db, "manual:"+path, cap, actor)


async def public_status(db):
    s, release = await state(db), identity()
    caps = {k: bool(k not in UNAVAILABLE and v and s["mode"] == "active" and s.get("owner_release") == release["release_id"])
            for k, v in s["capabilities"].items()}
    return {**release, "mode": s["mode"], "control_revision": s["revision"], "writer_epoch": s["epoch"],
            "scheduler_owner": s.get("owner_release"), "scheduler_authority": "platform-cron",
            "active_writer_count": len(s["active_writers"]), "drain_complete": s["mode"] == "frozen" and not s["active_writers"],
            "capabilities": caps, "price_comparison_only": not caps["exact_orders"],
            "price_semantics": "verified_observations_not_live", "maximum_offer_age_days": 7,
            "unsupported_email_delivery": True, "automatic_refresh_status": "enabled" if caps["automatic_refresh"] else "disabled"}