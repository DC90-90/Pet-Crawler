"""Admin dashboard overview counters."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import get_current_user
from app.repositories.base import effective_published_query
from app.repositories.collections import (
    articles_repo,
    destinations_repo,
    inquiries_repo,
    media_repo,
    offers_repo,
    tours_repo,
)

router = APIRouter(prefix="/api/admin/overview", tags=["admin"])


@router.get("")
async def overview(user: dict = Depends(get_current_user)):
    pub = effective_published_query()
    return {
        "tours": {
            "total": await tours_repo.count(),
            "published": await tours_repo.count(pub),
            "draft": await tours_repo.count({"status": "draft"}),
        },
        "destinations": {
            "total": await destinations_repo.count(),
            "published": await destinations_repo.count(pub),
        },
        "articles": {
            "total": await articles_repo.count(),
            "published": await articles_repo.count(pub),
        },
        "offers": {"total": await offers_repo.count()},
        "media": {"total": await media_repo.count()},
        "inquiries": {
            "total": await inquiries_repo.count(),
            "new": await inquiries_repo.count({"status": "new"}),
        },
    }
