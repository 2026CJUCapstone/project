"""The v9 cleanup-journal migration is additive and idempotent."""

from datetime import datetime, timedelta
import json

from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, UniqueConstraint, inspect, text

from app.initialize import RUNTIME_SCHEMA_VERSION, initialize
import app.models.database  # Register current metadata before the initializer creates tables.
from tests.test_worker_schema_migration import legacy_execution_engine


V8_SCHEMA_VERSION = "20260910_sandbox_operation_v8"
JOB_ID = "legacy-v8-cleanup"
RECEIVED_AT = datetime(2030, 1, 2, 3, 4, 5)
LEASE_UNTIL = RECEIVED_AT + timedelta(seconds=120)
V8_PAYLOAD = {"source": "legacy", "stdin": "fixture-input"}
V8_OPERATION = {
    "version": 1,
    "id": "a" * 32,
    "kind": "create",
    "lease_token": "b" * 32,
    "name": "compiler-" + "b" * 32 + "-" + "a" * 32,
    "container_id": None,
    "begun_at": "2030-01-02T03:04:05+00:00",
}
CLEANUP_OPERATION = {
    "version": 1,
    "id": "c" * 32,
    "kind": "cleanup",
    "lease_token": "d" * 32,
    "name": "compiler-" + "d" * 32 + "-" + "c" * 32,
    "container_id": "e" * 64,
    "resolved_daemon_id": "daemon-v8",
    "begun_at": "2030-01-02T03:06:05+00:00",
}


def _create_v8_execution_jobs(engine):
    """Create the v8 shape without the v9 daemon ownership column."""
    metadata = MetaData()
    jobs = Table(
        "execution_jobs",
        metadata,
        Column("id", String, primary_key=True),
        Column("owner_key", String, nullable=False, index=True),
        Column("quota_key", String, nullable=False, index=True),
        Column("request_id", String, nullable=False),
        Column("payload_hash", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("payload", JSON, nullable=False),
        Column("result", JSON, nullable=True),
        Column("status", String, nullable=False, index=True),
        Column("received_at", DateTime, nullable=False, index=True),
        Column("started_at", DateTime, nullable=True),
        Column("finished_at", DateTime, nullable=True),
        Column("lease_token", String, nullable=True),
        Column("lease_until", DateTime, nullable=True, index=True),
        Column("worker_id", String, nullable=True, index=True),
        Column("sandbox_operation", JSON, nullable=True),
        Column("attempts", Integer, nullable=False),
        UniqueConstraint("owner_key", "request_id", name="uq_execution_owner_request"),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            jobs.insert().values(
                id=JOB_ID,
                owner_key="owner-v8",
                quota_key="quota-v8",
                request_id="request-v8",
                payload_hash="payload-hash-v8",
                kind="run",
                payload=V8_PAYLOAD,
                result=None,
                status="running",
                received_at=RECEIVED_AT,
                started_at=RECEIVED_AT,
                finished_at=None,
                lease_token="lease-v8",
                lease_until=LEASE_UNTIL,
                worker_id=None,
                sandbox_operation=V8_OPERATION,
                attempts=2,
            )
        )


def _decode_json(value):
    return json.loads(value) if isinstance(value, str) else value


def _timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.isoformat() if value is not None else None


def _job_snapshot(engine, *, include_daemon):
    columns = "payload, lease_token, lease_until, sandbox_operation"
    if include_daemon:
        columns += ", sandbox_daemon_id"
    with engine.connect() as connection:
        row = connection.execute(
            text(f"SELECT {columns} FROM execution_jobs WHERE id = :job_id"),
            {"job_id": JOB_ID},
        ).mappings().one()
    return {
        "payload": _decode_json(row["payload"]),
        "lease_token": row["lease_token"],
        "lease_until": _timestamp(row["lease_until"]),
        "sandbox_operation": _decode_json(row["sandbox_operation"]),
        **({"sandbox_daemon_id": row["sandbox_daemon_id"]} if include_daemon else {}),
    }


def test_v9_cleanup_journal_migration_preserves_v8_intent_and_is_idempotent(
    legacy_execution_engine,
):
    engine = legacy_execution_engine
    _create_v8_execution_jobs(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_migrations "
                "(version VARCHAR PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"),
            {"version": V8_SCHEMA_VERSION},
        )

    before_initialize = _job_snapshot(engine, include_daemon=False)
    assert before_initialize == {
        "payload": V8_PAYLOAD,
        "lease_token": "lease-v8",
        "lease_until": LEASE_UNTIL.isoformat(),
        "sandbox_operation": V8_OPERATION,
    }

    initialize(bind=engine)

    columns = {column["name"]: column for column in inspect(engine).get_columns("execution_jobs")}
    assert columns["sandbox_daemon_id"]["nullable"] is True
    assert isinstance(columns["sandbox_daemon_id"]["type"], String)
    assert isinstance(columns["sandbox_operation"]["type"], JSON)
    migrated = _job_snapshot(engine, include_daemon=True)
    assert migrated["sandbox_daemon_id"] is None
    assert {key: value for key, value in migrated.items() if key != "sandbox_daemon_id"} == before_initialize

    jobs = Table("execution_jobs", MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            jobs.update().where(jobs.c.id == JOB_ID).values(
                sandbox_daemon_id="daemon-v8",
                sandbox_operation=CLEANUP_OPERATION,
            )
        )
    cleanup_before_retry = _job_snapshot(engine, include_daemon=True)
    assert cleanup_before_retry["sandbox_daemon_id"] == "daemon-v8"
    assert cleanup_before_retry["sandbox_operation"] == CLEANUP_OPERATION
    assert cleanup_before_retry["payload"] == V8_PAYLOAD
    assert cleanup_before_retry["lease_token"] == "lease-v8"
    assert cleanup_before_retry["lease_until"] == LEASE_UNTIL.isoformat()

    initialize(bind=engine)

    assert _job_snapshot(engine, include_daemon=True) == cleanup_before_retry
    with engine.connect() as connection:
        versions = list(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
    assert versions.count(V8_SCHEMA_VERSION) == 1
    assert versions.count(RUNTIME_SCHEMA_VERSION) == 1
