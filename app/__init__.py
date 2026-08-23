from flask import Flask
from flask_cors import CORS

from config import Config
from app.extensions import db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    # The frontend now lives on a different origin (GitHub Pages), so the
    # browser needs explicit permission to send/receive the admin session
    # cookie cross-site. FRONTEND_ORIGIN is set in Render's environment,
    # e.g. https://your-username.github.io
    CORS(
        app,
        supports_credentials=True,
        origins=[app.config["FRONTEND_ORIGIN"]],
    )

    from app.models import AdminUser

    @login_manager.user_loader
    def load_user(user_id):
        return AdminUser.query.get(int(user_id))

    from app.blueprints.main import main_bp
    from app.blueprints.api import api_bp
    from app.blueprints.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from app.models import SiteContent

    @app.context_processor
    def inject_site_content():
        def content(key, default=""):
            try:
                return SiteContent.get(key, default)
            except Exception:
                return default
        return {"content": content}

    return app
