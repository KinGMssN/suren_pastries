from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, inspect, text

from app.extensions import db


_migration_metadata = MetaData()
_schema_migrations = Table(
    "schema_migrations",
    _migration_metadata,
    Column("version", Integer, primary_key=True),
    Column("name", String(120), nullable=False),
    Column("applied_at", DateTime, nullable=False),
)

_ADDITIONAL_COLUMNS = {
    "admin_users": {
        "role": "VARCHAR(30) NOT NULL DEFAULT 'super_admin'",
        "failed_login_attempts": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "TIMESTAMP NULL",
        "session_version": "INTEGER NOT NULL DEFAULT 0",
    },
    "customers": {
        "otp_hash": "VARCHAR(255) NULL",
        "otp_expires_at": "TIMESTAMP NULL",
        "otp_attempts": "INTEGER NOT NULL DEFAULT 0",
    },
    "delivery_people": {
        "password_hash": "VARCHAR(255) NULL",
    },
    "orders": {
        "idempotency_key": "VARCHAR(64) NULL",
    },
    "menu_items": {
        "stock_quantity": "INTEGER NULL",
    },
}


def _create_base_schema():
    db.create_all()


def _add_model_columns(connection):
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    for table_name, columns in _ADDITIONAL_COLUMNS.items():
        if table_name not in existing_tables:
            raise RuntimeError(
                f"Cannot migrate missing table {table_name!r}; base schema migration failed."
            )
        existing_columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        for column_name, definition in columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(
                f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'
            ))
            existing_columns.add(column_name)

    has_unique_idempotency_key = any(
        index.get("unique")
        and index.get("column_names") == ["idempotency_key"]
        for index in inspector.get_indexes("orders")
    ) or any(
        constraint.get("column_names") == ["idempotency_key"]
        for constraint in inspector.get_unique_constraints("orders")
    )
    if not has_unique_idempotency_key:
        connection.execute(text(
            "CREATE UNIQUE INDEX uq_orders_idempotency_key "
            "ON orders (idempotency_key)"
        ))


def _add_order_payment_columns(connection):
    inspector = inspect(connection)
    if "orders" not in set(inspector.get_table_names()):
        raise RuntimeError(
            "Cannot migrate missing table 'orders'; base schema migration failed."
        )
    existing_columns = {
        column["name"] for column in inspector.get_columns("orders")
    }
    columns = {
        "payment_status": "VARCHAR(20) NOT NULL DEFAULT 'not_required'",
        "razorpay_order_id": "VARCHAR(80) NULL",
        "razorpay_payment_id": "VARCHAR(80) NULL",
    }
    for column_name, definition in columns.items():
        if column_name in existing_columns:
            continue
        connection.execute(text(
            f'ALTER TABLE "orders" ADD COLUMN "{column_name}" {definition}'
        ))


def _add_custom_cake_columns(connection):
    inspector = inspect(connection)
    if "orders" not in set(inspector.get_table_names()):
        raise RuntimeError(
            "Cannot migrate missing table 'orders'; base schema migration failed."
        )
    existing_columns = {
        column["name"] for column in inspector.get_columns("orders")
    }
    columns = {
        "custom_cake_details": "TEXT NULL",
        "quote_confirmed": "BOOLEAN NOT NULL DEFAULT FALSE",
    }
    for column_name, definition in columns.items():
        if column_name in existing_columns:
            continue
        connection.execute(text(
            f'ALTER TABLE "orders" ADD COLUMN "{column_name}" {definition}'
        ))


def _add_customer_password_column(connection):
    inspector = inspect(connection)
    if "customers" not in set(inspector.get_table_names()):
        raise RuntimeError(
            "Cannot migrate missing table 'customers'; base schema migration failed."
        )
    existing_columns = {
        column["name"] for column in inspector.get_columns("customers")
    }
    if "password_hash" not in existing_columns:
        connection.execute(text(
            'ALTER TABLE "customers" ADD COLUMN "password_hash" VARCHAR(255) NULL'
        ))


def _add_dashboard_export_tracking(connection):
    inspector = inspect(connection)
    if "orders" not in set(inspector.get_table_names()):
        raise RuntimeError(
            "Cannot migrate missing table 'orders'; base schema migration failed."
        )
    existing_columns = {
        column["name"] for column in inspector.get_columns("orders")
    }
    if "updated_at" not in existing_columns:
        connection.execute(text(
            'ALTER TABLE "orders" ADD COLUMN "updated_at" TIMESTAMP NULL'
        ))
        existing_columns.add("updated_at")
    if "created_at" in existing_columns:
        connection.execute(text(
            "UPDATE orders SET updated_at = created_at WHERE updated_at IS NULL"
        ))
    from app.models import DashboardExportLog

    DashboardExportLog.__table__.create(connection, checkfirst=True)


def _add_performance_indexes(connection):
    indexes = (
        ("ix_menu_items_category_id", "menu_items", "category_id"),
        ("ix_menu_items_available_special", "menu_items", "is_available, is_special"),
        ("ix_categories_sort_order", "categories", "sort_order"),
        ("ix_orders_customer_id", "orders", "customer_id"),
        ("ix_orders_delivery_person_id", "orders", "delivery_person_id"),
        ("ix_orders_customer_phone", "orders", "customer_phone"),
        ("ix_orders_status_created_at", "orders", "status, created_at"),
        ("ix_orders_created_at", "orders", "created_at"),
        ("ix_order_items_order_id", "order_items", "order_id"),
        ("ix_order_items_menu_item_id", "order_items", "menu_item_id"),
        ("ix_customer_addresses_customer_id", "customer_addresses", "customer_id"),
        ("ix_audit_logs_admin_user_id", "audit_logs", "admin_user_id"),
        ("ix_audit_logs_created_at", "audit_logs", "created_at"),
        ("ix_deleted_records_deleted_by_user_id", "deleted_records", "deleted_by_user_id"),
    )
    existing_tables = set(inspect(connection).get_table_names())
    for name, table_name, columns in indexes:
        if table_name not in existing_tables:
            raise RuntimeError(
                f"Cannot index missing table {table_name!r}; base schema migration failed."
            )
        existing_columns = {
            column["name"] for column in inspect(connection).get_columns(table_name)
        }
        if not set(columns.replace(" ", "").split(",")).issubset(existing_columns):
            continue
        if name not in {
            index["name"] for index in inspect(connection).get_indexes(table_name)
        }:
            connection.execute(text(
                f"CREATE INDEX {name} ON {table_name} ({columns})"
            ))


_MIGRATIONS = (
    (1, "create_base_schema", _create_base_schema),
    (2, "add_auth_checkout_and_inventory_columns", _add_model_columns),
    (3, "add_order_payment_columns", _add_order_payment_columns),
    (4, "add_custom_cake_order_details", _add_custom_cake_columns),
    (5, "add_customer_password_column", _add_customer_password_column),
    (6, "add_dashboard_export_tracking", _add_dashboard_export_tracking),
    (7, "add_performance_indexes", _add_performance_indexes),
)


def upgrade():
    _migration_metadata.create_all(bind=db.engine, checkfirst=True)
    with db.engine.connect() as connection:
        versions = set(connection.execute(
            _schema_migrations.select().with_only_columns(_schema_migrations.c.version)
        ).scalars())

    applied = []
    for version, name, migration in _MIGRATIONS:
        if version in versions:
            continue
        if version == 1:
            migration()
        else:
            with db.engine.begin() as connection:
                migration(connection)
        with db.engine.begin() as connection:
            connection.execute(
                _schema_migrations.insert().values(
                    version=version,
                    name=name,
                    applied_at=datetime.utcnow(),
                )
            )
        applied.append(name)
    return applied
