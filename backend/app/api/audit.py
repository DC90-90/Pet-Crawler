"""Admin audit-log trail (read-only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.helpers import pagination
from app.core.deps import get_current_user
from app.repositories.collections import audit_logs_repo

router = APIRouter(prefix="/api/admin/audit-logs", tags=["admin"])


@router.get("")
async def list_audit_logs(request: Request, user: dict = Depends(get_current_user)):
    page, size = pagination(request)
    query: dict = {}
    if request.query_params.get("action"):
        query["action"] = request.query_params["action"]
    if request.query_params.get("entity"):
        query["entity"] = request.query_params["entity"]
    items = await audit_logs_repo.list(query, sort=[("at", -1)], page=page, page_size=size)
    total = await audit_logs_repo.count(query)
    return {"items": items, "total": total, "page": page, "pageSize": size}
