"""Admin inquiries management + CSV export."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.helpers import pagination
from app.core.deps import csrf_protect, get_current_user
from app.repositories.collections import inquiries_repo
from app.schemas.dto import InquiryUpdateRequest
from app.services import inquiry as inquiry_service

router = APIRouter(prefix="/api/admin/inquiries", tags=["admin"])


@router.get("")
async def list_inquiries(request: Request, user: dict = Depends(get_current_user)):
    page, size = pagination(request)
    query: dict = {}
    if request.query_params.get("status"):
        query["status"] = request.query_params["status"]
    q = request.query_params.get("q")
    if q:
        query["$or"] = [
            {"fullName": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
        ]
    items = await inquiries_repo.list(query, sort=[("createdAt", -1)], page=page, page_size=size)
    total = await inquiries_repo.count(query)
    return {"items": items, "total": total, "page": page, "pageSize": size}


@router.get("/export.csv")
async def export_csv(request: Request, user: dict = Depends(get_current_user)):
    query: dict = {}
    if request.query_params.get("status"):
        query["status"] = request.query_params["status"]
    items = await inquiries_repo.list(query, sort=[("createdAt", -1)], page_size=10000)
    csv_data = inquiry_service.to_csv(items)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inquiries.csv"},
    )


@router.get("/{inquiry_id}")
async def get_inquiry(inquiry_id: str, user: dict = Depends(get_current_user)):
    doc = await inquiries_repo.get(inquiry_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return doc


@router.put("/{inquiry_id}")
async def update_inquiry(
    inquiry_id: str, body: InquiryUpdateRequest, user: dict = Depends(csrf_protect)
):
    try:
        updated = await inquiry_service.update_inquiry(
            inquiry_id, status=body.status, note_text=body.noteText,
            timeline_summary=body.timelineSummary, actor=user,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return updated
