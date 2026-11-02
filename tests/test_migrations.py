from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db
from migrations.runner import upgrade

from conftest import TestConfig


def test_app_factory_does_not_create_or_migrate_database_tables():
    application = create_app(TestConfig)
    with application.app_context():
        assert inspect(db.engine).get_table_names() == []


def test_versioned_migrations_create_schema_and_are_idempotent(app):
    with app.app_context():
        assert upgrade() == [
            "create_base_schema",
            "add_auth_checkout_and_inventory_columns",
        ]
        assert upgrade() == []
        versions = db.session.execute(
            text("SELECT version FROM schema_migrations ORDER BY version")
        ).scalars().all()
        assert versions == [1, 2]
        assert "stock_quantity" in {
            column["name"] for column in inspect(db.engine).get_columns("menu_items")
        }
        assert "idempotency_key" in {
            column["name"] for column in inspect(db.engine).get_columns("orders")
        }


def test_column_migration_upgrades_legacy_tables(app):
    with app.app_context():
        db.drop_all()
        with db.engine.begin() as connection:
            for table in (
                "admin_users",
                "customers",
                "delivery_people",
                "orders",
                "menu_items",
            ):
                connection.execute(text(
                    f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)'
                ))

        assert upgrade() == [
            "create_base_schema",
            "add_auth_checkout_and_inventory_columns",
        ]
        inspector = inspect(db.engine)
        expected = {
            "admin_users": {
                "role",
                "failed_login_attempts",
                "locked_until",
                "session_version",
            },
            "customers": {"otp_hash", "otp_expires_at", "otp_attempts"},
            "delivery_people": {"password_hash"},
            "orders": {"idempotency_key"},
            "menu_items": {"stock_quantity"},
        }
        for table, columns in expected.items():
            actual = {column["name"] for column in inspector.get_columns(table)}
            assert columns <= actual
        assert any(
            index.get("unique")
            and index.get("column_names") == ["idempotency_key"]
            for index in inspector.get_indexes("orders")
        )
