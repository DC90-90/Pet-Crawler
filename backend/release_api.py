"""Authorized control plane; data-plane writer gates cannot be overridden by role."""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
import re
import release_control as control
from release_runtime import public_status


class Transition(BaseModel):
    action: str
    expected_revision: int
    approval: str = Field(min_length=8, max_length=500)
    expected_release: str | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)


class MaintenanceApply(BaseModel):
    operation: str
    plan_hash: str
    approval: str = Field(min_length=8, max_length=500)


def install_release_routes(router, db_getter, require_admin, boot_getter):
    @router.get("/release")
    async def release_info():
        return await public_status(db_getter())

    @router.get("/ready")
    async def ready():
        db = db_getter()
        try:
            await db.command("ping")
            r = await public_status(db)
            from release_preflight import writer_schema
            schema = await writer_schema(db)
            boot = boot_getter()
            ok = boot.get("status") == "done" and not boot.get("errors") and r["manifest_verified"] and bool(re.fullmatch(r"[0-9a-f]{40}", r.get("git_commit") or ""))
            return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "release": r,
                                "writer_schema": schema,
                                "boot_status": boot.get("status"), "reason": None if ok else "boot_or_release_identity_unverified"})
        except Exception:
            return JSONResponse(status_code=503, content={"ready": False, "reason": "database_or_release_unavailable"})

    @router.get("/admin/release-control")
    async def release_control_state(user=Depends(require_admin)):
        return {"release": await public_status(db_getter()), "control": await control.state(db_getter())}

    @router.post("/admin/release-control")
    async def release_control_change(body: Transition, user=Depends(require_admin)):
        result = await control.transition(db_getter(), body.action, body.expected_revision, user["id"],
                                          body.approval, body.capabilities, body.expected_release)
        return {"control": result, "release": await public_status(db_getter())}

    @router.get("/admin/maintenance/plan/{operation}")
    async def maintenance_plan(operation: str, user=Depends(require_admin)):
        from maintenance_operations import plan
        return await plan(db_getter(), operation)

    @router.post("/admin/maintenance/apply")
    async def maintenance_apply(body: MaintenanceApply, user=Depends(require_admin)):
        from maintenance_operations import apply
        return await apply(db_getter(), body.operation, body.plan_hash, body.approval, user["id"])