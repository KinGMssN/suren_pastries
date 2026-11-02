from datetime import timedelta

import pytest

from app import create_app
from app.extensions import db


class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-only-signing-key-not-used-in-production"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    FRONTEND_ORIGIN = "http://localhost"
    ADMIN_MAX_LOGIN_FAILURES = 5
    CUSTOMER_OTP_TTL_SECONDS = 600
    CUSTOMER_OTP_DEBUG = False
    ADMIN_SESSION_IDLE_TIMEOUT = timedelta(hours=2)
    FREE_DELIVERY_THRESHOLD = 499
    DELIVERY_FEE = 40
    TAX_RATE = 0.05


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.drop_all()
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
