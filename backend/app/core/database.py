import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "sqlite:///./compiler.db"
)

engine_kwargs = {"connect_args": {"check_same_thread": False}} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
SCHEMA_MIGRATION_ID = "20260601_product_hardening"
PASSWORD_RESET_MIGRATION_ID = "20260601_password_reset"


def _ensure_migration_table() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version VARCHAR PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )


def _add_column_if_missing(table_name: str, column_name: str, ddl: str) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return

    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def _create_unique_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return

    column_set = set(columns)
    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in existing_indexes:
        return
    for index in inspector.get_indexes(table_name):
        if index.get("unique") and set(index.get("column_names") or []) == column_set:
            return
    for constraint in inspector.get_unique_constraints(table_name):
        if set(constraint.get("column_names") or []) == column_set:
            return

    column_expr = ", ".join(columns)
    with engine.begin() as connection:
        connection.execute(text(f"CREATE UNIQUE INDEX {index_name} ON {table_name} ({column_expr})"))


def migrate_schema() -> None:
    _ensure_migration_table()
    _add_column_if_missing("users", "role", "role VARCHAR DEFAULT 'user' NOT NULL")
    _add_column_if_missing("users", "email", "email VARCHAR")
    _add_column_if_missing("problems", "points", "points INTEGER DEFAULT 100 NOT NULL")
    _create_unique_index_if_missing("users", "ix_users_email_unique", ["email"])
    with engine.begin() as connection:
        applied = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE version = :version"),
            {"version": SCHEMA_MIGRATION_ID},
        ).first()
        if applied is None:
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": SCHEMA_MIGRATION_ID},
            )
        applied = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE version = :version"),
            {"version": PASSWORD_RESET_MIGRATION_ID},
        ).first()
        if applied is None:
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": PASSWORD_RESET_MIGRATION_ID},
            )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
