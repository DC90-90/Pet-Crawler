"""Media provider abstraction + LocalProvider + image variant generation."""
from __future__ import annotations

import io
import os
import re
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.core.config import settings
from app.models.common import new_id, now_utc
from app.repositories.collections import media_repo

VARIANT_SIZES = {"thumb": 200, "card": 600, "hero": 1600}


def sanitize_filename(filename: str) -> str:
    filename = os.path.basename(filename or "file")
    filename = filename.replace("\x00", "")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    name = name.strip("._") or "file"
    return name[:120]


class MediaProvider(ABC):
    @abstractmethod
    def save_bytes(self, key: str, data: bytes) -> str:
        """Persist raw bytes; return the public URL."""

    @abstractmethod
    def url_for(self, key: str) -> str: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class LocalProvider(MediaProvider):
    def __init__(self, base_dir: str, public_base: str):
        self.base_dir = os.path.abspath(base_dir)
        self.public_base = public_base.rstrip("/")
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        safe = key.lstrip("/")
        full = os.path.abspath(os.path.join(self.base_dir, safe))
        if not full.startswith(self.base_dir):
            raise ValueError("Invalid storage key")
        return full

    def save_bytes(self, key: str, data: bytes) -> str:
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return self.url_for(key)

    def url_for(self, key: str) -> str:
        return f"{self.public_base}/{key.lstrip('/')}"

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass


class CloudinaryProvider(MediaProvider):
    """Stub — configure CLOUDINARY_* and implement upload in production."""

    def save_bytes(self, key: str, data: bytes) -> str:  # pragma: no cover - stub
        raise NotImplementedError("Cloudinary provider not implemented; set MEDIA_PROVIDER=local")

    def url_for(self, key: str) -> str:  # pragma: no cover - stub
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover - stub
        raise NotImplementedError


class S3Provider(MediaProvider):
    """Stub — configure S3_* and implement upload in production."""

    def save_bytes(self, key: str, data: bytes) -> str:  # pragma: no cover - stub
        raise NotImplementedError("S3 provider not implemented; set MEDIA_PROVIDER=local")

    def url_for(self, key: str) -> str:  # pragma: no cover - stub
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover - stub
        raise NotImplementedError


def get_provider() -> MediaProvider:
    provider = settings.media_provider.lower()
    if provider == "cloudinary":
        return CloudinaryProvider()
    if provider == "s3":
        return S3Provider()
    return LocalProvider(settings.media_local_dir, settings.media_public_base)


class MediaValidationError(Exception):
    pass


def validate_upload(mime: str, size_bytes: int) -> str:
    """Return 'image' or 'video' kind, or raise MediaValidationError."""
    max_bytes = settings.media_max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise MediaValidationError(f"File exceeds {settings.media_max_mb} MB limit")
    if mime in settings.allowed_image_mimes:
        return "image"
    if mime in settings.allowed_video_mimes:
        return "video"
    raise MediaValidationError(f"Unsupported media type: {mime}")


def _generate_image_variants(
    data: bytes, base_key: str, provider: MediaProvider, mime: str
) -> tuple[dict[str, Any], Optional[int], Optional[int]]:
    from PIL import Image

    variants: dict[str, Any] = {}
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return variants, None, None
    orig_w, orig_h = img.size
    fmt = "PNG" if mime == "image/png" else "JPEG"
    ext = "png" if fmt == "PNG" else "jpg"

    # store original
    original_url = provider.save_bytes(base_key, data)
    variants["original"] = {"url": original_url, "w": orig_w, "h": orig_h}

    rgb = img.convert("RGB") if fmt == "JPEG" else img
    for name, target_w in VARIANT_SIZES.items():
        if orig_w <= target_w and name != "thumb":
            variants[name] = {"url": original_url, "w": orig_w, "h": orig_h}
            continue
        ratio = target_w / float(orig_w)
        new_w = min(target_w, orig_w)
        new_h = max(1, int(orig_h * min(ratio, 1.0)))
        resized = rgb.resize((new_w, new_h))
        buf = io.BytesIO()
        resized.save(buf, format=fmt, quality=85)
        vkey = f"{base_key.rsplit('.', 1)[0]}_{name}.{ext}"
        vurl = provider.save_bytes(vkey, buf.getvalue())
        variants[name] = {"url": vurl, "w": new_w, "h": new_h}
    return variants, orig_w, orig_h


async def store_upload(
    *, filename: str, mime: str, data: bytes, created_by: str | None
) -> dict:
    kind = validate_upload(mime, len(data))
    provider = get_provider()
    safe = sanitize_filename(filename)
    unique = uuid.uuid4().hex[:12]
    base_key = f"{unique}_{safe}"

    width = height = None
    variants: dict[str, Any] = {}
    storage_key = base_key
    if kind == "image":
        variants, width, height = _generate_image_variants(data, base_key, provider, mime)
    else:
        url = provider.save_bytes(base_key, data)
        variants = {"original": {"url": url, "w": None, "h": None}}

    doc = {
        "id": new_id(),
        "kind": kind,
        "provider": settings.media_provider.lower(),
        "storageKey": storage_key,
        "originalFilename": safe,
        "mimeType": mime,
        "sizeBytes": len(data),
        "width": width,
        "height": height,
        "altText": {"en": ""},
        "caption": {"en": ""},
        "tags": [],
        "variants": variants,
        "usageRefs": [],
        "archived": False,
        "createdAt": now_utc(),
        "createdBy": created_by,
    }
    return await media_repo.create(doc)


def detect_external_kind(url: str) -> tuple[str, str]:
    """Return (kind, provider) for a YouTube/Vimeo URL."""
    low = url.lower()
    if "youtube.com" in low or "youtu.be" in low:
        return "external_video", "youtube"
    if "vimeo.com" in low:
        return "external_video", "vimeo"
    return "external_video", "youtube"


async def register_external(*, url: str, created_by: str | None) -> dict:
    kind, prov = detect_external_kind(url)
    doc = {
        "id": new_id(),
        "kind": kind,
        "provider": prov,
        "externalUrl": url,
        "mimeType": "",
        "altText": {"en": ""},
        "caption": {"en": ""},
        "tags": [],
        "variants": {},
        "usageRefs": [],
        "archived": False,
        "createdAt": now_utc(),
        "createdBy": created_by,
    }
    return await media_repo.create(doc)
