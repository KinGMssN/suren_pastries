import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy.pool import NullPool

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    IS_VERCEL = bool(os.environ.get("VERCEL"))
    IS_PRODUCTION = IS_VERCEL or os.environ.get("FLASK_ENV") == "production"
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if IS_PRODUCTION and (
        not SECRET_KEY or len(SECRET_KEY.encode("utf-8")) < 32
    ):
        raise RuntimeError(
            "SECRET_KEY must be configured with at least 32 bytes in production."
        )
    SECRET_KEY = SECRET_KEY or os.urandom(32)

    # SQLAlchemy's psycopg3 dialect is explicit so existing deployment URLs
    # without a driver suffix continue to work after the driver migration.
    database_url = os.environ.get("DATABASE_URL")
    if IS_VERCEL and not database_url:
        raise RuntimeError(
            "DATABASE_URL must point to an external database on Vercel; "
            "serverless filesystems are not persistent."
        )
    if IS_VERCEL and not database_url.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        raise RuntimeError("DATABASE_URL must use PostgreSQL on Vercel.")
    database_url = database_url or (
        "sqlite:///" + (Path(basedir) / "local.db").as_posix()
    )
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    if SQLALCHEMY_DATABASE_URI.startswith("postgresql+psycopg://"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "poolclass": NullPool,
            "pool_pre_ping": True,
            "connect_args": {"prepare_threshold": None},
        }

    REDIS_URL = os.environ.get("REDIS_URL", "")
    if IS_PRODUCTION and not REDIS_URL:
        raise RuntimeError("REDIS_URL must be configured for production rate limiting.")
    RATELIMIT_STORAGE_URI = REDIS_URL or "memory://"
    RATELIMIT_SWALLOW_ERRORS = False
    RATELIMIT_IN_MEMORY_FALLBACK_ENABLED = bool(REDIS_URL)
    PERF_LOG = os.environ.get("PERF_LOG") == "1"
    PERF_SLOW_QUERY_MS = float(os.environ.get("PERF_SLOW_QUERY_MS", "100"))

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
    SUBADMIN_USERNAME = os.environ.get("SUBADMIN_USERNAME", "")
    SUBADMIN_PASSWORD = os.environ.get("SUBADMIN_PASSWORD", "")

    # Falls back to localhost for local development.
    FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5000")
    PUBLIC_SITE_URL = os.environ.get("PUBLIC_SITE_URL", "").strip().rstrip("/")
    if PUBLIC_SITE_URL:
        public_site = urlsplit(PUBLIC_SITE_URL)
        if (
            public_site.scheme not in {"http", "https"}
            or not public_site.netloc
            or public_site.path
            or public_site.query
            or public_site.fragment
            or public_site.username
            or public_site.password
        ):
            raise RuntimeError(
                "PUBLIC_SITE_URL must be an absolute site origin without a path."
            )

    # Production deployments use HTTPS; local development can use plain HTTP.
    SESSION_COOKIE_SAMESITE = "None" if IS_PRODUCTION else "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    REMEMBER_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    ADMIN_SESSION_IDLE_TIMEOUT = timedelta(hours=2)
    ADMIN_MAX_LOGIN_FAILURES = 20
    ADMIN_RESET_KEY = os.environ.get("ADMIN_RESET_KEY", "")
    ADMIN_TOTP_SECRET = os.environ.get("ADMIN_TOTP_SECRET", "")
    RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

    # Business rules (also editable at runtime via the Admin > Content tab,
    # these are just the fallback defaults used to first seed the database)
    FREE_DELIVERY_THRESHOLD = 499
    DELIVERY_FEE = 40
    TAX_RATE = 0.05
