import base64
import json
import logging
import secrets
from datetime import datetime

from flask import Flask, g, request, session
from flask_cors import CORS
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from config import Config
from app.extensions import csrf, db, login_manager, limiter
from app.models import AdminUser


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        try:
            db.session.execute(text(
                "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role "
                "VARCHAR(30) NOT NULL DEFAULT 'super_admin'"
            ))
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()

        for stmt in [
            "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP",
            "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE customers ADD COLUMN IF NOT EXISTS otp_hash VARCHAR(255)",
            "ALTER TABLE customers ADD COLUMN IF NOT EXISTS otp_expires_at TIMESTAMP",
            "ALTER TABLE customers ADD COLUMN IF NOT EXISTS otp_attempts INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                db.session.execute(text(stmt))
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
        db.create_all()
    
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
            "error": "Too many OTP requests. Please wait and try again later.",
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
            try:
                return SiteContent.get(key, default)
            except Exception:
                return default
        return {"content": content}

    # ── Security headers on every response ──
    @app.before_request
    def set_csp_nonce():
        g.csp_nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=(), payment=(), usb=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Reporting-Endpoints"] = 'csp-endpoint="/api/csp-report"'
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{g.csp_nonce}'; "
            f"style-src 'self' 'nonce-{g.csp_nonce}'; "
            "style-src-attr 'none'; "
            "font-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "frame-src 'none'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
            " upgrade-insecure-requests;"
            " report-to csp-endpoint;"
        )
        return response

    return app
