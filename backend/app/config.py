import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _normalize_database_url(url):
    if not url:
        return url
    if url.startswith("postgresql+psycopg://") or url.startswith("postgresql+psycopg3://"):
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(
        os.getenv(
            "DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'database' / 'lost_found.db'}",
        )
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))
    STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "item-images")
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    ITEMS_PER_PAGE = int(os.getenv("ITEMS_PER_PAGE", "9"))
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_TIME_LIMIT = None
    NOTIFICATION_MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.55"))
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
    SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "no-reply@lostfound.local")
    SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", SENDGRID_FROM_EMAIL)
    SENDGRID_BASE_URL = os.getenv("SENDGRID_BASE_URL", "https://api.sendgrid.com/v3")
    SENDGRID_TIMEOUT = int(os.getenv("SENDGRID_TIMEOUT", "10"))


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
