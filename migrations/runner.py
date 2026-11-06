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


_MIGRATIONS = (
    (1, "create_base_schema", _create_base_schema),
    (2, "add_auth_checkout_and_inventory_columns", _add_model_columns),
    (3, "add_order_payment_columns", _add_order_payment_columns),
    (4, "add_custom_cake_order_details", _add_custom_cake_columns),
    (5, "add_customer_password_column", _add_customer_password_column),
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
