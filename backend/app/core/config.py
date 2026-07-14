"""Application configuration via pydantic-settings (reads environment)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_JWT_DEFAULT = "change-me-in-production-please-use-a-long-random-value"
INSECURE_CSRF_DEFAULT = "change-me-csrf-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",), env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # Application
    app_env: str = "development"
    log_level: str = "info"

    # URLs
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    public_site_url: str = "http://localhost:5173"

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "svaneti"

    # Auth secrets
    jwt_secret: str = INSECURE_JWT_DEFAULT
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    argon2_time_cost: int = 3
    argon2_memory_kb: int = 65536
    argon2_parallelism: int = 2

    # Cookies
    cookie_domain: str = ""
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    csrf_secret: str = INSECURE_CSRF_DEFAULT

    # CORS
    cors_origins: str = "http://localhost:5173"

    # Media
    media_provider: str = "local"
    media_local_dir: str = "./backend/media_store"
    media_public_base: str = "/media"
    media_max_mb: int = 25
    media_allowed_image: str = "image/jpeg,image/png,image/webp,image/avif"
    media_allowed_video: str = "video/mp4,video/webm"

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    s3_endpoint: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_public_base: str = ""

    # Email
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@example.com"
    inquiry_notify_to: str = ""

    # Analytics
    ga_measurement_id: str = ""
    gsc_verification: str = ""
    meta_pixel_id: str = ""

    map_tiles_url: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"

    # Admin bootstrap
    admin_seed_email: str = "owner@example.com"
    admin_seed_password: str = "ChangeMe!Now123"
    force_password_change: bool = True

    # Feature flags
    feature_payments: bool = False
    seed_sample_reviews: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_image_mimes(self) -> set[str]:
        return {m.strip() for m in self.media_allowed_image.split(",") if m.strip()}

    @property
    def allowed_video_mimes(self) -> set[str]:
        return {m.strip() for m in self.media_allowed_video.split(",") if m.strip()}

    @property
    def sample_reviews_enabled(self) -> bool:
        return self.seed_sample_reviews and not self.is_production

    def validate_production(self) -> None:
        """Refuse to start in production with insecure defaults / missing config."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.jwt_secret == INSECURE_JWT_DEFAULT or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be a strong non-default value")
        if self.csrf_secret == INSECURE_CSRF_DEFAULT or len(self.csrf_secret) < 16:
            problems.append("CSRF_SECRET must be a strong non-default value")
        if not self.mongodb_uri:
            problems.append("MONGODB_URI is required")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if problems:
            raise RuntimeError("Insecure/invalid production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
