"""Shared model building blocks: LocalizedText, publishing envelope, SeoBlock."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class LocalizedText(BaseModel):
    model_config = ConfigDict(extra="ignore")
    en: str = ""
    ka: Optional[str] = None
    ar: Optional[str] = None

    def resolve(self, lang: str = "en") -> str:
        return getattr(self, lang, None) or self.en


class Status(str, Enum):
    draft = "draft"
    scheduled = "scheduled"
    published = "published"
    archived = "archived"


class VerificationStatus(str, Enum):
    verified = "verified"
    needs_verification = "needs_verification"


class SeoBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: Optional[LocalizedText] = None
    description: Optional[LocalizedText] = None
    ogImageMediaId: Optional[str] = None
    noindex: bool = False
    canonicalPath: Optional[str] = None


class PublishingEnvelope(BaseModel):
    """Fields shared by all publishable documents."""

    status: Status = Status.draft
    publishAt: Optional[datetime] = None
    unpublishAt: Optional[datetime] = None
    publishedAt: Optional[datetime] = None
    createdAt: datetime = Field(default_factory=now_utc)
    updatedAt: datetime = Field(default_factory=now_utc)
    createdBy: Optional[str] = None
    lastEditedBy: Optional[str] = None
    verificationStatus: VerificationStatus = VerificationStatus.needs_verification
    isVerified: bool = False


def is_effectively_published(doc: dict, now: datetime | None = None) -> bool:
    """Server-side effective visibility computation."""
    now = now or now_utc()
    if doc.get("status") != "published":
        return False
    publish_at = doc.get("publishAt")
    if publish_at is not None and _aware(publish_at) > now:
        return False
    unpublish_at = doc.get("unpublishAt")
    if unpublish_at is not None and _aware(unpublish_at) <= now:
        return False
    return True


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
