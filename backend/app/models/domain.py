"""Domain models per collection (Pydantic v2). Permissive to allow editing."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import (
    LocalizedText,
    PublishingEnvelope,
    SeoBlock,
    new_id,
    now_utc,
)


class BaseDoc(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(default_factory=new_id)


class User(BaseDoc):
    email: str
    passwordHash: str
    role: str = "editor"  # owner | editor
    name: str = ""
    isActive: bool = True
    forcePasswordChange: bool = False
    failedLoginCount: int = 0
    lockedUntil: Optional[datetime] = None
    lastLoginAt: Optional[datetime] = None
    createdAt: datetime = Field(default_factory=now_utc)
    updatedAt: datetime = Field(default_factory=now_utc)


class Session(BaseDoc):
    userId: str
    refreshTokenHash: str
    userAgent: Optional[str] = None
    ip: Optional[str] = None
    expiresAt: datetime
    createdAt: datetime = Field(default_factory=now_utc)
    revokedAt: Optional[datetime] = None


class Tour(BaseDoc, PublishingEnvelope):
    slug: str
    name: LocalizedText = Field(default_factory=LocalizedText)
    shortDescription: LocalizedText = Field(default_factory=LocalizedText)
    fullDescription: LocalizedText = Field(default_factory=LocalizedText)
    coverMediaId: Optional[str] = None
    galleryMediaIds: list[str] = Field(default_factory=list)
    promoVideoId: Optional[str] = None
    destinationIds: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    durationHours: Optional[float] = None
    durationDays: Optional[float] = None
    startLocation: Optional[str] = None
    endLocation: Optional[str] = None
    suggestedStartTime: Optional[str] = None
    walkingDistanceKm: Optional[float] = None
    drivingDistanceKm: Optional[float] = None
    elevationGainM: Optional[float] = None
    maxAltitudeM: Optional[float] = None
    difficulty: str = "moderate"
    fitnessLevel: Optional[str] = None
    minAge: Optional[int] = None
    groupSizeMin: Optional[int] = None
    groupSizeMax: Optional[int] = None
    tourType: str = "private"
    seasons: list[str] = Field(default_factory=list)
    weatherDependency: Optional[str] = None
    accessibilityNotes: LocalizedText = Field(default_factory=LocalizedText)
    familyFriendly: bool = False
    lowWalking: bool = False
    winter: bool = False
    inclusions: list[LocalizedText] = Field(default_factory=list)
    exclusions: list[LocalizedText] = Field(default_factory=list)
    whatToBring: list[LocalizedText] = Field(default_factory=list)
    itinerary: list[dict[str, Any]] = Field(default_factory=list)
    safetyNotes: LocalizedText = Field(default_factory=LocalizedText)
    priceDisplay: str = "contact"
    priceAmount: Optional[float] = None
    currency: str = "GEL"
    offerId: Optional[str] = None
    featured: bool = False
    displayOrder: int = 0
    seo: SeoBlock = Field(default_factory=SeoBlock)


class Destination(BaseDoc, PublishingEnvelope):
    slug: str
    name: LocalizedText = Field(default_factory=LocalizedText)
    intro: LocalizedText = Field(default_factory=LocalizedText)
    description: LocalizedText = Field(default_factory=LocalizedText)
    coordinates: dict[str, float] = Field(default_factory=dict)
    altitudeM: Optional[float] = None
    bestSeasons: list[str] = Field(default_factory=list)
    galleryMediaIds: list[str] = Field(default_factory=list)
    videoIds: list[str] = Field(default_factory=list)
    relatedTourIds: list[str] = Field(default_factory=list)
    culturalNotes: LocalizedText = Field(default_factory=LocalizedText)
    practicalAdvice: LocalizedText = Field(default_factory=LocalizedText)
    accessibilityInfo: LocalizedText = Field(default_factory=LocalizedText)
    safetyNotice: LocalizedText = Field(default_factory=LocalizedText)
    relatedArticleIds: list[str] = Field(default_factory=list)
    displayOrder: int = 0
    seo: SeoBlock = Field(default_factory=SeoBlock)


class Article(BaseDoc, PublishingEnvelope):
    slug: str
    title: LocalizedText = Field(default_factory=LocalizedText)
    excerpt: LocalizedText = Field(default_factory=LocalizedText)
    body: LocalizedText = Field(default_factory=LocalizedText)
    coverMediaId: Optional[str] = None
    author: str = ""
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    relatedTourIds: list[str] = Field(default_factory=list)
    relatedDestinationIds: list[str] = Field(default_factory=list)
    readingMinutes: Optional[int] = None
    seo: SeoBlock = Field(default_factory=SeoBlock)


class Offer(BaseDoc, PublishingEnvelope):
    title: LocalizedText = Field(default_factory=LocalizedText)
    description: LocalizedText = Field(default_factory=LocalizedText)
    code: Optional[str] = None
    discountType: str = "display"
    discountValue: Optional[float] = None
    terms: LocalizedText = Field(default_factory=LocalizedText)
    relatedTourIds: list[str] = Field(default_factory=list)
    bannerId: Optional[str] = None
    cta: Optional[dict[str, Any]] = None
    featured: bool = False
    priority: int = 0
    languageTargets: list[str] = Field(default_factory=list)
    startAt: Optional[datetime] = None
    endAt: Optional[datetime] = None


class Banner(BaseDoc):
    name: str = ""
    placement: str = "announcement"
    title: LocalizedText = Field(default_factory=LocalizedText)
    subtitle: LocalizedText = Field(default_factory=LocalizedText)
    desktopMediaId: Optional[str] = None
    mobileMediaId: Optional[str] = None
    overlayIntensity: float = 0.4
    cta: Optional[dict[str, Any]] = None
    pageTargets: list[str] = Field(default_factory=lambda: ["*"])
    languageTargets: list[str] = Field(default_factory=list)
    priority: int = 0
    active: bool = True
    startAt: Optional[datetime] = None
    endAt: Optional[datetime] = None
    createdAt: datetime = Field(default_factory=now_utc)
    updatedAt: datetime = Field(default_factory=now_utc)
    createdBy: Optional[str] = None
    lastEditedBy: Optional[str] = None


class Popup(BaseDoc):
    title: LocalizedText = Field(default_factory=LocalizedText)
    body: LocalizedText = Field(default_factory=LocalizedText)
    mediaId: Optional[str] = None
    cta: Optional[dict[str, Any]] = None
    startAt: Optional[datetime] = None
    endAt: Optional[datetime] = None
    pageTargets: list[str] = Field(default_factory=lambda: ["*"])
    languageTargets: list[str] = Field(default_factory=list)
    deviceTargets: list[str] = Field(default_factory=lambda: ["desktop", "mobile"])
    delaySeconds: int = 0
    scrollDepthPercent: Optional[int] = None
    exitIntent: bool = False
    audience: str = "all"
    frequency: str = "once_session"
    frequencyDays: Optional[int] = None
    dismissible: bool = True
    priority: int = 0
    active: bool = True
    createdAt: datetime = Field(default_factory=now_utc)
    updatedAt: datetime = Field(default_factory=now_utc)


class Media(BaseDoc):
    kind: str = "image"
    provider: str = "local"
    storageKey: Optional[str] = None
    externalUrl: Optional[str] = None
    originalFilename: Optional[str] = None
    mimeType: str = ""
    sizeBytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    durationSeconds: Optional[float] = None
    altText: LocalizedText = Field(default_factory=LocalizedText)
    caption: LocalizedText = Field(default_factory=LocalizedText)
    credit: Optional[str] = None
    location: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    collection: Optional[str] = None
    posterMediaId: Optional[str] = None
    variants: dict[str, Any] = Field(default_factory=dict)
    usageRefs: list[dict[str, Any]] = Field(default_factory=list)
    archived: bool = False
    createdAt: datetime = Field(default_factory=now_utc)
    createdBy: Optional[str] = None


class GalleryAlbum(BaseDoc):
    title: LocalizedText = Field(default_factory=LocalizedText)
    slug: str
    category: Optional[str] = None
    coverMediaId: Optional[str] = None
    mediaIds: list[str] = Field(default_factory=list)
    displayOrder: int = 0
    published: bool = False
    createdAt: datetime = Field(default_factory=now_utc)
    updatedAt: datetime = Field(default_factory=now_utc)


class Video(BaseDoc):
    title: LocalizedText = Field(default_factory=LocalizedText)
    caption: LocalizedText = Field(default_factory=LocalizedText)
    kind: str = "youtube"
    mediaId: Optional[str] = None
    externalUrl: Optional[str] = None
    posterMediaId: Optional[str] = None
    featured: bool = False
    displayOrder: int = 0
    published: bool = False
    createdAt: datetime = Field(default_factory=now_utc)
    updatedAt: datetime = Field(default_factory=now_utc)


class Review(BaseDoc):
    reviewerName: str = ""
    country: Optional[str] = None
    rating: int = 5
    text: str = ""
    date: Optional[datetime] = None
    tourId: Optional[str] = None
    source: str = "manual"
    sourceUrl: Optional[str] = None
    permissionStatus: str = "unknown"
    featured: bool = False
    published: bool = False
    isSample: bool = False
    createdAt: datetime = Field(default_factory=now_utc)


class Faq(BaseDoc):
    question: LocalizedText = Field(default_factory=LocalizedText)
    answer: LocalizedText = Field(default_factory=LocalizedText)
    category: str = "general"
    displayOrder: int = 0
    published: bool = False


class Inquiry(BaseDoc):
    fullName: str
    email: str
    phone: Optional[str] = None
    country: Optional[str] = None
    preferredLanguage: Optional[str] = None
    arrivalDate: Optional[datetime] = None
    departureDate: Optional[datetime] = None
    flexibleDates: bool = False
    groupSize: Optional[int] = None
    children: Optional[int] = None
    selectedTourId: Optional[str] = None
    interests: list[str] = Field(default_factory=list)
    activityLevel: Optional[str] = None
    needTransport: bool = False
    pickupLocation: Optional[str] = None
    accommodationStatus: Optional[str] = None
    message: str = ""
    consent: bool = False
    marketingOptIn: bool = False
    status: str = "new"
    notes: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    ipHash: Optional[str] = None
    createdAt: datetime = Field(default_factory=now_utc)
    updatedAt: datetime = Field(default_factory=now_utc)


class Redirect(BaseDoc):
    fromPath: str
    toPath: str
    statusCode: int = 301
    createdAt: datetime = Field(default_factory=now_utc)
    createdBy: Optional[str] = None


class AuditLog(BaseDoc):
    at: datetime = Field(default_factory=now_utc)
    userId: Optional[str] = None
    userEmail: Optional[str] = None
    action: str = "edit"
    entity: str = ""
    entityId: Optional[str] = None
    summary: str = ""
    ip: Optional[str] = None
