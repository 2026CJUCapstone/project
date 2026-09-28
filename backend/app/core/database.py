import os
import hashlib
import json
from contextlib import contextmanager
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "sqlite:///./compiler.db"
)

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine_kwargs = {"connect_args": {"check_same_thread": False}}
else:
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_size": int(os.getenv("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800")),
    }
engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
SCHEMA_MIGRATION_ID = "20260601_product_hardening"
PASSWORD_RESET_MIGRATION_ID = "20260601_password_reset"
QUEUE_AND_SUBMISSIONS_MIGRATION_ID = "20260602_queue_and_submissions"
PERFORMANCE_INDEX_MIGRATION_ID = "20260604_performance_indexes"


@contextmanager
def _connection(bind):
    # An explicit migration keeps every helper on the same transaction.
    if hasattr(bind, 'connect'):
        with bind.begin() as connection:
            yield connection
    else:
        yield bind


def _ensure_migration_table(bind) -> None:
    with _connection(bind) as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version VARCHAR PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )


def _add_column_if_missing(table_name: str, column_name: str, ddl: str, bind) -> None:
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return

    with _connection(bind) as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def _create_unique_index_if_missing(table_name: str, index_name: str, columns: list[str], bind) -> None:
    inspector = inspect(bind)
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
    with _connection(bind) as connection:
        connection.execute(text(f"CREATE UNIQUE INDEX {index_name} ON {table_name} ({column_expr})"))


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str], bind) -> None:
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in existing_indexes:
        return

    column_expr = ", ".join(columns)
    with _connection(bind) as connection:
        connection.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({column_expr})"))


def migrate_schema(bind=None) -> None:
    bind = bind if bind is not None else engine
    _ensure_migration_table(bind)
    _add_column_if_missing("users", "auth_version", "auth_version INTEGER DEFAULT 0 NOT NULL", bind)
    _add_column_if_missing("users", "role", "role VARCHAR DEFAULT 'user' NOT NULL", bind)
    _add_column_if_missing("users", "email", "email VARCHAR", bind)
    _add_column_if_missing("users", "public_profile_enabled", "public_profile_enabled BOOLEAN DEFAULT TRUE NOT NULL", bind)
    _add_column_if_missing("problems", "public_id", "public_id VARCHAR(32)", bind)
    _add_column_if_missing("problems", "points", "points INTEGER DEFAULT 100 NOT NULL", bind)
    _add_column_if_missing("problems", "deleted_at", "deleted_at TIMESTAMP", bind)
    _add_column_if_missing("problems", "judge_policy", "judge_policy JSON", bind)
    _add_column_if_missing("problems", "publication_review_required", "publication_review_required BOOLEAN", bind)
    _add_column_if_missing("problems", "publication_approved_at", "publication_approved_at TIMESTAMP", bind)
    if "problems" in inspect(bind).get_table_names():
        compatibility = json.dumps({"kind": "compatibility-v1"}, separators=(",", ":"))
        with _connection(bind) as connection:
            value = "CAST(:policy AS JSON)" if connection.dialect.name == "postgresql" else ":policy"
            connection.execute(text(
                "UPDATE problems SET judge_policy = " + value + " "
                "WHERE judge_policy IS NULL AND publication_review_required IS NULL "
                "AND id NOT IN ('__notice__', '__free__')"
            ), {"policy": compatibility})
    _add_column_if_missing('submissions', 'resource_report', 'resource_report JSON', bind)
    _add_column_if_missing('contest_submissions', 'resource_report', 'resource_report JSON', bind)
    _add_column_if_missing('contest_submissions', 'public_id', 'public_id VARCHAR(32)', bind)
    _add_column_if_missing('contest_rejudge_applications', 'preview_hash', 'preview_hash VARCHAR', bind)
    _add_column_if_missing('contest_rejudge_applications', 'review_provenance', 'review_provenance JSON', bind)
    _add_column_if_missing('contest_rejudge_applications', 'legacy_resolution_provenance', 'legacy_resolution_provenance JSON', bind)
    _add_column_if_missing('contest_rejudge_batches', 'review_basis', 'review_basis JSON', bind)
    _add_column_if_missing('contest_rejudge_batches', 'submission_set_hash', 'submission_set_hash VARCHAR', bind)
    _add_column_if_missing('contest_rejudge_batches', 'shard_count', 'shard_count INTEGER', bind)
    _add_column_if_missing('contest_rejudge_batches', 'source_bytes', 'source_bytes INTEGER', bind)
    _add_column_if_missing('contest_rejudge_items', 'shard_id', 'shard_id VARCHAR REFERENCES contest_rejudge_shards(id)', bind)
    _add_column_if_missing('contest_rejudge_items', 'candidate_receipt_hash', 'candidate_receipt_hash VARCHAR', bind)
    _create_index_if_missing('contest_rejudge_items', 'ix_contest_rejudge_items_shard_id', ['shard_id'], bind)
    _add_column_if_missing('execution_jobs', 'resource_reservation', 'resource_reservation JSON', bind)
    _add_column_if_missing('execution_jobs', 'public_id', 'public_id VARCHAR(32)', bind)
    _add_column_if_missing("contests", "scoreboard_revision", "scoreboard_revision INTEGER DEFAULT 0 NOT NULL", bind)
    _add_column_if_missing("code_projects", "revision", "revision VARCHAR DEFAULT 'legacy' NOT NULL", bind)
    _add_column_if_missing('execution_jobs', 'quota_key', 'quota_key VARCHAR', bind)
    _add_column_if_missing('execution_jobs', 'worker_id', 'worker_id VARCHAR REFERENCES execution_workers(id)', bind)
    _add_column_if_missing('execution_jobs', 'sandbox_operation', 'sandbox_operation JSON', bind)
    _add_column_if_missing('execution_jobs', 'sandbox_daemon_id', 'sandbox_daemon_id VARCHAR', bind)
    _add_column_if_missing('execution_jobs', 'content_expired_at', 'content_expired_at TIMESTAMP', bind)
    _create_index_if_missing('execution_jobs', 'ix_execution_content_retention', ['status', 'content_expired_at', 'finished_at'], bind)
    _create_index_if_missing('execution_jobs', 'ix_execution_jobs_worker_id', ['worker_id'], bind)
    _add_column_if_missing('execution_workers', 'runtime_id', "runtime_id VARCHAR NOT NULL DEFAULT ''", bind)
    _create_index_if_missing('execution_workers', 'ix_execution_workers_runtime_id', ['runtime_id'], bind)
    _add_column_if_missing('execution_workers', 'process_id', 'process_id VARCHAR REFERENCES worker_processes(id)', bind)
    _create_index_if_missing('execution_workers', 'ix_execution_workers_process_id', ['process_id'], bind)
    if 'execution_jobs' in inspect(bind).get_table_names():
        with _connection(bind) as connection:
            connection.execute(text('UPDATE execution_jobs SET quota_key = owner_key WHERE quota_key IS NULL'))
            rows = connection.execute(text(
                "SELECT id FROM execution_jobs WHERE public_id IS NULL OR public_id = ''"
            )).scalars().all()
            for job_id in rows:
                digest = hashlib.sha256(f"public-job:{job_id}".encode("utf-8")).hexdigest()[:16]
                connection.execute(
                    text("UPDATE execution_jobs SET public_id = :public_id WHERE id = :id"),
                    {"public_id": f"job_{digest}", "id": job_id},
                )
        _create_index_if_missing('execution_jobs', 'ix_execution_jobs_quota_key', ['quota_key'], bind)
        _create_unique_index_if_missing('execution_jobs', 'ix_execution_jobs_public_id', ['public_id'], bind)
    _create_index_if_missing("problems", "ix_problems_deleted_at", ["deleted_at"], bind)
    if "problems" in inspect(bind).get_table_names():
        with _connection(bind) as connection:
            rows = connection.execute(text("SELECT id FROM problems WHERE public_id IS NULL OR public_id = ''")).scalars().all()
            for problem_id in rows:
                digest = hashlib.sha256(f"public-problem:{problem_id}".encode("utf-8")).hexdigest()[:16]
                connection.execute(
                    text("UPDATE problems SET public_id = :public_id WHERE id = :id"),
                    {"public_id": f"p_{digest}", "id": problem_id},
                )
        _create_unique_index_if_missing("problems", "ix_problems_public_id", ["public_id"], bind)
    _create_index_if_missing("users", "ix_users_public_profile_enabled", ["public_profile_enabled"], bind)
    _create_index_if_missing(
        "problems",
        "ix_problems_publication_gate",
        ["publication_review_required", "publication_approved_at"],
        bind,
    )
    _add_column_if_missing("submissions", "verdict", "verdict VARCHAR DEFAULT 'system_error' NOT NULL", bind)
    for submission_table in ('submissions', 'contest_submissions'):
        _add_column_if_missing(submission_table, 'execution_job_id', 'execution_job_id VARCHAR REFERENCES execution_jobs(id)', bind)
        _create_unique_index_if_missing(submission_table, f'ix_{submission_table}_execution_job', ['execution_job_id'], bind)
    if 'contest_submissions' in inspect(bind).get_table_names():
        with _connection(bind) as connection:
            rows = connection.execute(text(
                "SELECT id FROM contest_submissions WHERE public_id IS NULL OR public_id = ''"
            )).scalars().all()
            for submission_id in rows:
                digest = hashlib.sha256(
                    f"public-receipt:{submission_id}".encode("utf-8")
                ).hexdigest()[:16]
                connection.execute(
                    text("UPDATE contest_submissions SET public_id = :public_id WHERE id = :id"),
                    {"public_id": f"submission_{digest}", "id": submission_id},
                )
        _create_unique_index_if_missing(
            'contest_submissions', 'ix_contest_submissions_public_id', ['public_id'], bind
        )
    _add_column_if_missing("comments", "updated_at", "updated_at TIMESTAMP", bind)
    _create_unique_index_if_missing("users", "ix_users_email_unique", ["email"], bind)
    with _connection(bind) as connection:
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
        applied = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE version = :version"),
            {"version": QUEUE_AND_SUBMISSIONS_MIGRATION_ID},
        ).first()
        if applied is None:
            connection.execute(
                text("UPDATE submissions SET verdict = CASE "
                     "WHEN status = 'Accepted' THEN 'accepted' "
                     "WHEN status = 'SampleFailed' THEN 'wrong_answer' "
                     "WHEN status = 'Rejected' THEN 'wrong_answer' "
                     "ELSE verdict END WHERE verdict = 'system_error'"),
            )
            connection.execute(
                text("UPDATE comments SET updated_at = created_at WHERE updated_at IS NULL"),
            )
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": QUEUE_AND_SUBMISSIONS_MIGRATION_ID},
            )
    _create_index_if_missing("compile_queue_jobs", "ix_compile_queue_history_order", ["status", "queued_at", "id"], bind)
    applied_indexes = None
    with _connection(bind) as connection:
        applied_indexes = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE version = :version"),
            {"version": PERFORMANCE_INDEX_MIGRATION_ID},
        ).first()
    if applied_indexes is None:
        _create_index_if_missing("problems", "ix_problems_difficulty_created_at", ["difficulty", "created_at"], bind)
        _create_index_if_missing("submissions", "ix_submissions_problem_created_at", ["problem_id", "created_at"], bind)
        _create_index_if_missing("submissions", "ix_submissions_user_created_at", ["user_id", "created_at"], bind)
        _create_index_if_missing("submissions", "ix_submissions_verdict_created_at", ["verdict", "created_at"], bind)
        _create_index_if_missing("compile_queue_jobs", "ix_compile_queue_jobs_status_queued_at", ["status", "queued_at"], bind)
        _create_index_if_missing("compile_queue_jobs", "ix_compile_queue_jobs_verdict_queued_at", ["verdict", "queued_at"], bind)
        _create_index_if_missing("compile_queue_jobs", "ix_compile_queue_jobs_problem_queued_at", ["problem_id", "queued_at"], bind)
        _create_index_if_missing("compile_queue_jobs", "ix_compile_queue_jobs_user_queued_at", ["user_id", "queued_at"], bind)
        _create_index_if_missing("comments", "ix_comments_problem_created_at", ["problem_id", "created_at"], bind)
        with _connection(bind) as connection:
            connection.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": PERFORMANCE_INDEX_MIGRATION_ID},
            )


@contextmanager
def schema_transaction(bind=None):
    """One direct database connection serializes all DDL/bootstrap work."""
    bind = bind if bind is not None else engine
    with bind.connect() as connection:
        try:
            if connection.dialect.name == 'sqlite':
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            else:
                connection.begin()
                connection.execute(text("SELECT pg_advisory_xact_lock(736421905)"))
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def init_db(connection=None) -> None:
    if connection is None:
        with schema_transaction() as connection:
            init_db(connection)
        return
    Base.metadata.create_all(bind=connection)
    migrate_schema(connection)
    Base.metadata.create_all(bind=connection)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
