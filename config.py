import os
from datetime import timedelta
from urllib.parse import urlsplit

from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    IS_PRODUCTION = os.environ.get("RENDER", "") != ""
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
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://suren_user:suren_pass@localhost:5432/suren_pastries",
    )
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
    SUBADMIN_USERNAME = os.environ.get("SUBADMIN_USERNAME", "")
    SUBADMIN_PASSWORD = os.environ.get("SUBADMIN_PASSWORD", "")

    # The static frontend's origin, e.g. https://your-username.github.io
    # (no trailing slash). Used for CORS. Falls back to localhost so the
    # server-rendered pages still work fine if you run everything locally.
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

    # Cross-site cookies (GitHub Pages -> Render) require SameSite=None and
    # Secure. Both are only safe over HTTPS, which Render provides by
    # default — locally, IS_PRODUCTION stays False so cookies still work
    # over plain http://localhost.
    SESSION_COOKIE_SAMESITE = "None" if IS_PRODUCTION else "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    REMEMBER_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    ADMIN_SESSION_IDLE_TIMEOUT = timedelta(hours=2)
    ADMIN_MAX_LOGIN_FAILURES = 20
    CUSTOMER_OTP_TTL_SECONDS = 10 * 60
    CUSTOMER_OTP_DEBUG = os.environ.get("CUSTOMER_OTP_DEBUG", "false").lower() == "true"
    if IS_PRODUCTION and CUSTOMER_OTP_DEBUG:
        raise RuntimeError("CUSTOMER_OTP_DEBUG must be disabled in production.")
    CUSTOMER_OTP_SENDER = None
    ADMIN_RESET_KEY = os.environ.get("ADMIN_RESET_KEY", "")
    ADMIN_TOTP_SECRET = os.environ.get("ADMIN_TOTP_SECRET", "")

    # Business rules (also editable at runtime via the Admin > Content tab,
    # these are just the fallback defaults used to first seed the database)
    FREE_DELIVERY_THRESHOLD = 499
    DELIVERY_FEE = 40
    TAX_RATE = 0.05
