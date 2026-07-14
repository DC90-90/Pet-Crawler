"""Request/response DTOs."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=200)


class ExternalMediaRequest(BaseModel):
    url: str = Field(min_length=5, max_length=1000)
    title: Optional[str] = None


class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = ""
    role: str = "editor"
    forcePasswordChange: bool = False


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: Optional[str] = None
    role: Optional[str] = None
    isActive: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=200)
    forcePasswordChange: Optional[bool] = None


class InquiryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    fullName: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=50)
    country: Optional[str] = None
    preferredLanguage: Optional[str] = None
    arrivalDate: Optional[str] = None
    departureDate: Optional[str] = None
    flexibleDates: bool = False
    groupSize: Optional[int] = Field(default=None, ge=0, le=1000)
    children: Optional[int] = Field(default=None, ge=0, le=1000)
    selectedTourId: Optional[str] = None
    interests: list[str] = Field(default_factory=list)
    activityLevel: Optional[str] = None
    needTransport: bool = False
    pickupLocation: Optional[str] = None
    accommodationStatus: Optional[str] = None
    message: str = Field(default="", max_length=5000)
    consent: bool = False
    marketingOptIn: bool = False


class InquiryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: Optional[str] = None
    noteText: Optional[str] = None
    timelineSummary: Optional[str] = None


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    difficulty: Optional[str] = None
    family: Optional[bool] = None
    lowWalking: Optional[bool] = None
    winter: Optional[bool] = None
    season: Optional[str] = None
    durationDays: Optional[float] = None
    interests: list[str] = Field(default_factory=list)
    limit: int = Field(default=5, ge=1, le=20)


class GenericDoc(BaseModel):
    """Accept arbitrary content payloads for generic CRUD."""

    model_config = ConfigDict(extra="allow")
