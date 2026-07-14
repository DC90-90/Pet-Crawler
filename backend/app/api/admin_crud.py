"""Generic admin CRUD router covering all content resources."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from app.api.helpers import client_ip, pagination
from app.core.deps import csrf_protect, get_current_user
from app.core.security import sign_preview_token
from app.repositories.collections import (
    ENVELOPE_RESOURCES,
    RESOURCE_ENTITY,
    RESOURCE_REPOS,
)
from app.services import content as content_service
from app.services import publishing

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Resources handled by their own dedicated routers (not the generic factory)
_EXCLUDED = {"media"}


def _resolve(resource: str):
    if resource in _EXCLUDED or resource not in RESOURCE_REPOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown resource")
    return RESOURCE_REPOS[resource], RESOURCE_ENTITY[resource]


@router.get("/{resource}")
async def list_resource(resource: str, request: Request, user: dict = Depends(get_current_user)):
    repo, _ = _resolve(resource)
    page, size = pagination(request)
    query: dict = {}
    status_filter = request.query_params.get("status")
    if status_filter:
        query["status"] = status_filter
    q = request.query_params.get("q")
    if q:
        query["slug"] = {"$regex": q, "$options": "i"}
    items = await repo.list(query, sort=[("updatedAt", -1)], page=page, page_size=size)
    total = await repo.count(query)
    return {"items": items, "total": total, "page": page, "pageSize": size}


@router.post("/{resource}", status_code=status.HTTP_201_CREATED)
async def create_resource(
    resource: str, request: Request, payload: dict = Body(...),
    user: dict = Depends(csrf_protect),
):
    repo, entity = _resolve(resource)
    created = await content_service.create_doc(repo, entity, payload, user, client_ip(request))
    return created


@router.get("/{resource}/{doc_id}")
async def get_resource(resource: str, doc_id: str, user: dict = Depends(get_current_user)):
    repo, _ = _resolve(resource)
    doc = await repo.get(doc_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return doc


@router.put("/{resource}/{doc_id}")
async def update_resource(
    resource: str, doc_id: str, request: Request, payload: dict = Body(...),
    user: dict = Depends(csrf_protect),
):
    repo, entity = _resolve(resource)
    updated = await content_service.update_doc(repo, entity, doc_id, payload, user, client_ip(request))
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return updated


@router.delete("/{resource}/{doc_id}")
async def delete_resource(
    resource: str, doc_id: str, request: Request, user: dict = Depends(csrf_protect)
):
    repo, entity = _resolve(resource)
    ok = await content_service.delete_doc(repo, entity, doc_id, user, client_ip(request))
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return {"ok": True}


@router.post("/{resource}/{doc_id}/publish")
async def publish_resource(
    resource: str, doc_id: str, request: Request, user: dict = Depends(csrf_protect)
):
    if resource not in ENVELOPE_RESOURCES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Resource is not publishable")
    repo, entity = _resolve(resource)
    updated = await publishing.publish(repo, entity, doc_id, user, client_ip(request))
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return updated


@router.post("/{resource}/{doc_id}/unpublish")
async def unpublish_resource(
    resource: str, doc_id: str, request: Request, user: dict = Depends(csrf_protect)
):
    if resource not in ENVELOPE_RESOURCES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Resource is not publishable")
    repo, entity = _resolve(resource)
    updated = await publishing.unpublish(repo, entity, doc_id, user, client_ip(request))
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    return updated


@router.get("/{resource}/{doc_id}/preview-token")
async def preview_token(resource: str, doc_id: str, user: dict = Depends(get_current_user)):
    _resolve(resource)
    token = sign_preview_token(resource, doc_id)
    return {"token": token, "resource": resource, "id": doc_id}
