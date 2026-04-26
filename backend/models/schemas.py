"""Pydantic request/response schemas for Daleel API.

Extracted from server.py during the Feb 2026 refactor. Keeping all schemas in
one module avoids circular imports with the route handlers.
"""
from typing import Optional
from pydantic import BaseModel


class AuthIn(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class StoreIn(BaseModel):
    name: str
    domain: str
    platform: str
    base_url: Optional[str] = ""
    crawl_frequency_hrs: Optional[int] = 24


class StoreUpdate(BaseModel):
    name: Optional[str] = None
    platform: Optional[str] = None
    base_url: Optional[str] = None
    crawl_frequency_hrs: Optional[int] = None
    is_active: Optional[bool] = None


class AlertIn(BaseModel):
    product_sku: Optional[str] = None
    category: Optional[str] = None
    store_id: Optional[str] = None
    alert_type: str = "price_drop"
    threshold: Optional[float] = None
    channel: str = "in_app"


class SavedFilterIn(BaseModel):
    name: str
    filters: dict


class Tier4CredentialsIn(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    phone: Optional[str] = None


class OtpSubmitIn(BaseModel):
    store_id: str
    otp_code: str


class MatchActionIn(BaseModel):
    my_sku: str
    competitor_sku: str
    competitor_store_id: str


class IngestPayload(BaseModel):
    store_id: str
    store_name: str
    domain: str
    platform: str
    products: list
