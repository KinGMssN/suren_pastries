import json
import logging
import secrets

from flask import Flask, g, request
from flask_cors import CORS
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from config import Config
from app.extensions import db, login_manager,limiter


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    with app.app_context():
        try:
            db.session.execute(text(
                "ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS role "
                "VARCHAR(30) NOT NULL DEFAULT 'super_admin'"
            ))
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
    
    CORS(
        app,
        supports_credentials=True,
        origins=[app.config["FRONTEND_ORIGIN"]],
    )

    from app.models import AdminUser

    with app.app_context():
        subadmin_username = app.config.get("SUBADMIN_USERNAME", "").strip()
        subadmin_password = app.config.get("SUBADMIN_PASSWORD", "")
        if subadmin_username and subadmin_password:
            try:
                subadmin = AdminUser.query.filter_by(username=subadmin_username).first()
                if subadmin is None:
                    subadmin = AdminUser(username=subadmin_username, role="menu_admin")
                    db.session.add(subadmin)
                subadmin.set_password(subadmin_password)
                subadmin.role = "menu_admin"
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()

    @login_manager.user_loader
    def load_user(user_id):
        return AdminUser.query.get(int(user_id))

    from app.blueprints.main import main_bp
    from app.blueprints.api import api_bp
    from app.blueprints.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")

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
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
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
            "style-src-attr 'unsafe-inline'; "
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
            " report-uri /api/csp-report;"
        )
        return response

    return app
