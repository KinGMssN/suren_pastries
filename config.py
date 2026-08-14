import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

    # PostgreSQL connection string, e.g.
    # postgresql://suren_user:suren_pass@localhost:5432/suren_pastries
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql://suren_user:suren_pass@localhost:5432/suren_pastries",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    # Set this on Render, visit /api/bootstrap?key=<this value> once to seed
    # the database without needing shell access.
    SEED_KEY = os.environ.get("SEED_KEY", "")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me-now")

    # The static frontend's origin, e.g. https://your-username.github.io
    # (no trailing slash). Used for CORS. Falls back to localhost so the
    # server-rendered pages still work fine if you run everything locally.
    FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5000")

    # Cross-site cookies (GitHub Pages -> Render) require SameSite=None and
    # Secure. Both are only safe over HTTPS, which Render provides by
    # default — locally, IS_PRODUCTION stays False so cookies still work
    # over plain http://localhost.
    IS_PRODUCTION = os.environ.get("RENDER", "") != ""
    SESSION_COOKIE_SAMESITE = "None" if IS_PRODUCTION else "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    REMEMBER_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    # Business rules (also editable at runtime via the Admin > Content tab,
    # these are just the fallback defaults used to first seed the database)
    FREE_DELIVERY_THRESHOLD = 499
    DELIVERY_FEE = 40
    TAX_RATE = 0.05
