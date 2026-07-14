"""Media admin router: upload, external register, replace, list, delete."""
from __future__ import annotations

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from app.api.helpers import client_ip, pagination
from app.core.deps import csrf_protect, get_current_user, verify_csrf
from app.models.common import now_utc
from app.repositories.collections import media_repo
from app.schemas.dto import ExternalMediaRequest
from app.services import audit
from app.services import media as media_service

router = APIRouter(prefix="/api/admin/media", tags=["media"])


@router.get("")
async def list_media(request: Request, user: dict = Depends(get_current_user)):
    page, size = pagination(request)
    query: dict = {}
    kind = request.query_params.get("kind")
    if kind:
        query["kind"] = kind
    if request.query_params.get("archived") == "false":
        query["archived"] = False
    items = await media_repo.list(query, sort=[("createdAt", -1)], page=page, page_size=size)
    total = await media_repo.count(query)
    return {"items": items, "total": total, "page": page, "pageSize": size}


@router.get("/{media_id}")
async def get_media(media_id: str, user: dict = Depends(get_current_user)):
    doc = await media_repo.get(media_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return doc


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_media(
    request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)
):
    verify_csrf(request)
    data = await file.read()
    try:
        doc = await media_service.store_upload(
            filename=file.filename or "upload", mime=file.content_type or "",
            data=data, created_by=user["id"],
        )
    except media_service.MediaValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    await audit.record(
        "create", "media", user_id=user["id"], user_email=user["email"],
        entity_id=doc["id"], summary="Uploaded media", ip=client_ip(request),
    )
    return doc


@router.post("/external", status_code=status.HTTP_201_CREATED)
async def register_external(
    request: Request, body: ExternalMediaRequest, user: dict = Depends(csrf_protect)
):
    doc = await media_service.register_external(url=body.url, created_by=user["id"])
    if body.title:
        doc = await media_repo.update(doc["id"], {"caption": {"en": body.title}})
    await audit.record(
        "create", "media", user_id=user["id"], user_email=user["email"],
        entity_id=doc["id"], summary="Registered external video", ip=client_ip(request),
    )
    return doc


@router.put("/{media_id}")
async def update_media(
    media_id: str, request: Request, payload: dict = Body(...),
    user: dict = Depends(csrf_protect),
):
    doc = await media_repo.get(media_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    # Only metadata fields are editable
    allowed = {"altText", "caption", "credit", "location", "tags", "collection", "archived"}
    patch = {k: v for k, v in payload.items() if k in allowed}
    updated = await media_repo.update(media_id, patch)
    await audit.record(
        "edit", "media", user_id=user["id"], user_email=user["email"],
        entity_id=media_id, summary="Edited media metadata", ip=client_ip(request),
    )
    return updated


@router.post("/{media_id}/replace")
async def replace_media(
    media_id: str, request: Request, file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    verify_csrf(request)
    existing = await media_repo.get(media_id)
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    data = await file.read()
    try:
        new_doc = await media_service.store_upload(
            filename=file.filename or "upload", mime=file.content_type or "",
            data=data, created_by=user["id"],
        )
    except media_service.MediaValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    # keep refs + identity of the original doc, swap file/variant data
    patch = {
        "storageKey": new_doc["storageKey"],
        "mimeType": new_doc["mimeType"],
        "sizeBytes": new_doc["sizeBytes"],
        "width": new_doc.get("width"),
        "height": new_doc.get("height"),
        "variants": new_doc.get("variants", {}),
        "originalFilename": new_doc.get("originalFilename"),
        "updatedAt": now_utc(),
    }
    await media_repo.update(media_id, patch)
    await media_repo.delete(new_doc["id"])
    await audit.record(
        "media_replace", "media", user_id=user["id"], user_email=user["email"],
        entity_id=media_id, summary="Replaced media file (refs kept)", ip=client_ip(request),
    )
    return await media_repo.get(media_id)


@router.delete("/{media_id}")
async def delete_media(
    media_id: str, request: Request, user: dict = Depends(csrf_protect)
):
    doc = await media_repo.get(media_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    force = request.query_params.get("force") == "true"
    if doc.get("usageRefs") and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Media is in use; pass ?force=true to delete anyway.",
        )
    # remove underlying file for local provider
    if doc.get("provider") == "local" and doc.get("storageKey"):
        try:
            media_service.get_provider().delete(doc["storageKey"])
        except Exception:  # noqa: BLE001
            pass
    await media_repo.delete(media_id)
    await audit.record(
        "delete", "media", user_id=user["id"], user_email=user["email"],
        entity_id=media_id, summary="Deleted media", ip=client_ip(request),
    )
    return {"ok": True}
