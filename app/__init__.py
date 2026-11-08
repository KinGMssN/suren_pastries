import base64
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import RLock
from time import monotonic, perf_counter
from urllib.parse import urlsplit

from flask import Flask, g, request, send_from_directory, session
from flask_cors import CORS
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import safe_join

from config import Config
from app.extensions import csrf, db, login_manager, limiter
from app.models import AdminUser


STATIC_FOLDER = Path(__file__).resolve().parent.parent / "public" / "static"
SITE_CONTENT_CACHE_TTL = 60
_site_content_cache_lock = RLock()
_site_content_cache = {"app": None, "expires_at": 0.0, "values": {}}


@lru_cache(maxsize=256)
def _fingerprint_static_file(path, modified_ns, size):
    with open(path, "rb") as asset:
        return hashlib.sha256(asset.read()).hexdigest()[:16]


def _static_asset_fingerprint(filename):
    path = safe_join(str(STATIC_FOLDER), filename)
    if path is None or not Path(path).is_file():
        raise FileNotFoundError(f"Static asset does not exist: {filename}")
    stat = Path(path).stat()
    return _fingerprint_static_file(path, stat.st_mtime_ns, stat.st_size)


def invalidate_site_content_cache():
    with _site_content_cache_lock:
        _site_content_cache["app"] = None
        _site_content_cache["expires_at"] = 0.0
        _site_content_cache["values"] = {}


def create_app(config_class=Config):
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_class)
    app.config.setdefault(
        "RATELIMIT_STORAGE_URI",
        app.config.get("REDIS_URL") or os.environ.get("REDIS_URL") or "memory://",
    )
    app.config.setdefault("RATELIMIT_SWALLOW_ERRORS", False)
    app.config.setdefault(
        "RATELIMIT_IN_MEMORY_FALLBACK_ENABLED",
        bool(app.config.get("REDIS_URL") or os.environ.get("REDIS_URL")),
    )

    def serve_static_file(filename):
        response = send_from_directory(STATIC_FOLDER, filename)
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable"
        )
        return response

    app.add_url_rule(
        "/static/<path:filename>",
        endpoint="static",
        view_func=serve_static_file,
    )

    @app.url_defaults
    def fingerprint_static_urls(endpoint, values):
        if endpoint == "static" and values.get("filename"):
            values.setdefault("v", _static_asset_fingerprint(values["filename"]))

    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)

    if app.config.get("PERF_LOG"):
        slow_query_threshold_ms = app.config.get("PERF_SLOW_QUERY_MS", 100)
        with app.app_context():
            engine = db.engine

        @event.listens_for(engine, "before_cursor_execute")
        def start_query_timer(
            connection, _cursor, _statement, _parameters, _context, _executemany
        ):
            connection.info.setdefault("perf_query_starts", []).append(perf_counter())

        @event.listens_for(engine, "after_cursor_execute")
        def log_slow_query(
            connection, _cursor, statement, _parameters, _context, _executemany
        ):
            started_at = connection.info["perf_query_starts"].pop()
            duration_ms = (perf_counter() - started_at) * 1000
            if duration_ms >= slow_query_threshold_ms:
                app.logger.warning(
                    "slow_query duration_ms=%.1f statement=%s",
                    duration_ms,
                    statement,
                )

        @event.listens_for(engine, "handle_error")
        def clear_failed_query_timer(exception_context):
            connection = exception_context.connection
            if connection is not None:
                starts = connection.info.get("perf_query_starts")
                if starts:
                    starts.pop()

        @app.before_request
        def start_request_timer():
            g.perf_request_started_at = perf_counter()

        @app.after_request
        def log_request_duration(response):
            started_at = getattr(g, "perf_request_started_at", None)
            if started_at is not None:
                app.logger.info(
                    "request_timing method=%s endpoint=%s status=%s duration_ms=%.1f",
                    request.method,
                    request.endpoint or "unknown",
                    response.status_code,
                    (perf_counter() - started_at) * 1000,
                )
            return response

    CORS(
        app,
        supports_credentials=True,
        origins=[app.config["FRONTEND_ORIGIN"]],
    )

    @login_manager.user_loader
    def load_user(user_id):
        user = AdminUser.query.get(int(user_id))
        if not user or session.get("admin_session_version") != (user.session_version or 0):
            return None
        return user

    from app.blueprints.main import main_bp
    from app.blueprints.api import api_bp
    from app.blueprints.admin import admin_bp

    app.register_blueprint(main_bp)
    csrf.exempt(api_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.cli.command("db-upgrade")
    def db_upgrade_command():
        from migrations.runner import upgrade

        applied = upgrade()
        if applied:
            print(f"Applied database migrations: {', '.join(applied)}")
        else:
            print("Database schema is already up to date.")

    for rule in app.url_map.iter_rules():
        if not rule.endpoint.startswith("api."):
            rule.methods.discard("OPTIONS")
            rule.provide_automatic_options = False

    @app.get("/.well-known/security.txt")
    def security_txt():
        return (
            "Contact: mailto:security@surenpastries.in\n"
            "Expires: 2027-09-15T00:00:00.000Z\n"
            "Preferred-Languages: en\n"
        )

    @app.before_request
    def expire_idle_admin_session():
        last_activity = session.get("admin_last_activity")
        if last_activity is None:
            return
        now = datetime.utcnow().timestamp()
        if now - last_activity > app.config["ADMIN_SESSION_IDLE_TIMEOUT"].total_seconds():
            session.clear()
            return
        session["admin_last_activity"] = now

    @app.before_request
    def reset_site_content_request_cache():
        g.site_content_values = None

    @app.after_request
    def audit_admin_action(response):
        from flask_login import current_user
        if current_user.is_authenticated and (request.path.startswith("/admin") or request.path.startswith("/api/admin")):
            try:
                from app.models import AuditLog
                db.session.add(AuditLog(
                    admin_user_id=current_user.id,
                    username=current_user.username,
                    method=request.method,
                    path=request.path,
                    status_code=response.status_code,
                ))
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
        return response

    @app.errorhandler(429)
    def handle_rate_limit(_error):
        return {
            "ok": False,
            "error": "Too many requests. Please wait and try again later.",
        }, 429

    @app.post("/api/csp-report")
    def receive_csp_report():
        payload = request.get_json(silent=True) or {}
        if not payload:
            try:
                payload = json.loads(request.get_data(as_text=True) or "{}")
            except json.JSONDecodeError:
                payload = {}
        report = payload.get("csp-report", payload)
        if isinstance(report, dict):
            logging.getLogger("csp").warning(
                "CSP violation: document=%s directive=%s blocked=%s",
                report.get("document-uri", ""),
                report.get("violated-directive", ""),
                report.get("blocked-uri", ""),
            )
        return "", 204

    from app.models import SiteContent

    @app.context_processor
    def inject_site_content():
        def content(key, default=""):
            content_values = getattr(g, "site_content_values", None)
            if content_values is None:
                now = monotonic()
                with _site_content_cache_lock:
                    if (
                        _site_content_cache["app"] is not app
                        or now >= _site_content_cache["expires_at"]
                    ):
                        _site_content_cache["values"] = dict(
                            db.session.query(SiteContent.key, SiteContent.value).all()
                        )
                        _site_content_cache["app"] = app
                        _site_content_cache["expires_at"] = (
                            now + SITE_CONTENT_CACHE_TTL
                        )
                    content_values = _site_content_cache["values"]
                g.site_content_values = content_values
            return content_values.get(key, default)
        public_canonical_endpoints = {
            "main.index",
            "main.home",
            "main.menu",
            "main.customized_cake",
            "main.about",
            "main.privacy",
            "main.refund_policy",
            "main.terms",
            "main.cookies",
        }
        public_site_url = app.config.get("PUBLIC_SITE_URL", "")
        canonical_url = None
        if public_site_url and request.endpoint in public_canonical_endpoints:
            path = "/home" if request.endpoint == "main.index" else request.path
            canonical_url = public_site_url + path
        return {"content": content, "canonical_url": canonical_url}

    # ── Security headers on every response ──
    @app.before_request
    def set_csp_nonce():
        g.csp_nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")

    @app.before_request
    def validate_api_request_origin():
        if not request.path.startswith("/api/") or request.method not in {
            "POST", "PUT", "PATCH", "DELETE"
        }:
            return

        source = request.headers.get("Origin") or request.headers.get("Referer")
        parsed_source = urlsplit(source or "")
        if (
            parsed_source.scheme not in {"http", "https"}
            or not parsed_source.netloc
            or parsed_source.username
            or parsed_source.password
        ):
            return {"error": "A valid request origin is required."}, 403

        request_origin = f"{parsed_source.scheme.lower()}://{parsed_source.netloc.lower()}"
        configured_origin = urlsplit(app.config["FRONTEND_ORIGIN"])
        allowed_origins = {
            f"{configured_origin.scheme.lower()}://{configured_origin.netloc.lower()}",
            request.host_url.rstrip("/").lower(),
        }
        if request_origin not in allowed_origins:
            return {"error": "Request origin is not allowed."}, 403

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=(), payment=(), usb=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = (
            "same-origin-allow-popups"
            if request.endpoint == "main.track"
            else "same-origin"
        )
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Reporting-Endpoints"] = 'csp-endpoint="/api/csp-report"'
        script_sources = f"'self' 'nonce-{g.csp_nonce}'"
        style_sources = f"'self' 'nonce-{g.csp_nonce}'"
        image_sources = "'self' data:"
        connect_sources = "'self'"
        frame_sources = "'none'"
        if request.endpoint == "main.track":
            script_sources += " https://checkout.razorpay.com"
            style_sources = "'self' 'unsafe-inline'"
            connect_sources += " https://api.razorpay.com https://checkout.razorpay.com"
            frame_sources = "https://api.razorpay.com https://checkout.razorpay.com"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src {script_sources}; "
            f"style-src {style_sources}; "
            "style-src-attr 'unsafe-inline'; "
            "font-src 'self'; "
            f"img-src {image_sources}; "
            f"connect-src {connect_sources}; "
            "object-src 'none'; "
            f"frame-src {frame_sources}; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
            " upgrade-insecure-requests;"
            " report-to csp-endpoint;"
        )
        return response

    return app
