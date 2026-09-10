"""The v10 execution-retention migration is additive and idempotent."""

from datetime import datetime, timedelta
import json

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    inspect,
    text,
)

from app.initialize import RUNTIME_SCHEMA_VERSION, initialize
import app.models.database  # Register current metadata before the initializer creates tables.
from tests.test_worker_schema_migration import legacy_execution_engine


V9_SCHEMA_VERSION = "20260910_sandbox_cleanup_v9"
JOB_ID = "legacy-v9-retention"
RECEIVED_AT = datetime(2030, 1, 2, 3, 4, 5)
LEASE_UNTIL = RECEIVED_AT + timedelta(seconds=120)
PAYLOAD = {"source": "legacy-v9", "stdin": "fixture-input"}
RESULT = {"verdict": "accepted", "stdout": "fixture-output"}
SANDBOX_OPERATION = {
    "version": 1,
    "id": "a" * 32,
    "kind": "cleanup",
    "lease_token": "b" * 32,
    "name": "compiler-" + "b" * 32 + "-" + "a" * 32,
    "container_id": "c" * 64,
    "resolved_daemon_id": "daemon-v9",
    "begun_at": "2030-01-02T03:04:05+00:00",
}


def _create_v9_execution_jobs(engine):
    """Create the v9 queue shape without the v10 retention timestamp/index."""
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
        Column("sandbox_daemon_id", String, nullable=True),
        Column("attempts", Integer, nullable=False),
        UniqueConstraint("owner_key", "request_id", name="uq_execution_owner_request"),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            jobs.insert().values(
                id=JOB_ID,
                owner_key="owner-v9",
                quota_key="quota-v9",
                request_id="request-v9",
                payload_hash="payload-hash-v9",
                kind="run",
                payload=PAYLOAD,
                result=RESULT,
                status="completed",
                received_at=RECEIVED_AT,
                started_at=RECEIVED_AT,
                finished_at=RECEIVED_AT,
                lease_token="lease-v9",
                lease_until=LEASE_UNTIL,
                worker_id="worker-v9",
                sandbox_operation=SANDBOX_OPERATION,
                sandbox_daemon_id="daemon-v9",
                attempts=2,
            )
        )


def _decode_json(value):
    return json.loads(value) if isinstance(value, str) else value


def _timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.isoformat() if value is not None else None


def _job_snapshot(engine):
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, owner_key, quota_key, request_id, payload_hash, kind, payload, result, "
                "status, received_at, started_at, finished_at, lease_token, lease_until, worker_id, "
                "sandbox_operation, sandbox_daemon_id, content_expired_at "
                "FROM execution_jobs WHERE id = :job_id"
            ),
            {"job_id": JOB_ID},
        ).mappings().one()
    return {
        "id": row["id"],
        "owner_key": row["owner_key"],
        "quota_key": row["quota_key"],
        "request_id": row["request_id"],
        "payload_hash": row["payload_hash"],
        "kind": row["kind"],
        "payload": _decode_json(row["payload"]),
        "result": _decode_json(row["result"]),
        "status": row["status"],
        "received_at": _timestamp(row["received_at"]),
        "started_at": _timestamp(row["started_at"]),
        "finished_at": _timestamp(row["finished_at"]),
        "lease_token": row["lease_token"],
        "lease_until": _timestamp(row["lease_until"]),
        "worker_id": row["worker_id"],
        "sandbox_operation": _decode_json(row["sandbox_operation"]),
        "sandbox_daemon_id": row["sandbox_daemon_id"],
        "content_expired_at": _timestamp(row["content_expired_at"]),
    }


def _retention_indexes(engine):
    return [
        index
        for index in inspect(engine).get_indexes("execution_jobs")
        if index.get("name") == "ix_execution_content_retention"
    ]


def test_v10_execution_retention_migration_preserves_v9_jobs_and_is_idempotent(
    legacy_execution_engine,
):
    engine = legacy_execution_engine
    _create_v9_execution_jobs(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_migrations "
                "(version VARCHAR PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"),
            {"version": V9_SCHEMA_VERSION},
        )

    initialize(bind=engine)

    columns = {column["name"]: column for column in inspect(engine).get_columns("execution_jobs")}
    assert columns["content_expired_at"]["nullable"] is True
    assert isinstance(columns["content_expired_at"]["type"], DateTime)
    retention_indexes = _retention_indexes(engine)
    assert len(retention_indexes) == 1
    assert retention_indexes[0]["column_names"] == ["status", "content_expired_at", "finished_at"]

    migrated = _job_snapshot(engine)
    assert migrated == {
        "id": JOB_ID,
        "owner_key": "owner-v9",
        "quota_key": "quota-v9",
        "request_id": "request-v9",
        "payload_hash": "payload-hash-v9",
        "kind": "run",
        "payload": PAYLOAD,
        "result": RESULT,
        "status": "completed",
        "received_at": RECEIVED_AT.isoformat(),
        "started_at": RECEIVED_AT.isoformat(),
        "finished_at": RECEIVED_AT.isoformat(),
        "lease_token": "lease-v9",
        "lease_until": LEASE_UNTIL.isoformat(),
        "worker_id": "worker-v9",
        "sandbox_operation": SANDBOX_OPERATION,
        "sandbox_daemon_id": "daemon-v9",
        "content_expired_at": None,
    }

    with engine.connect() as connection:
        versions = list(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
    assert versions.count(V9_SCHEMA_VERSION) == 1
    assert versions.count(RUNTIME_SCHEMA_VERSION) == 1


    initialize(bind=engine)

    assert _job_snapshot(engine) == migrated
    retention_indexes = _retention_indexes(engine)
    assert len(retention_indexes) == 1
    assert retention_indexes[0]["column_names"] == ["status", "content_expired_at", "finished_at"]
    with engine.connect() as connection:
        versions = list(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
    assert versions.count(V9_SCHEMA_VERSION) == 1
    assert versions.count(RUNTIME_SCHEMA_VERSION) == 1


def test_queue_history_index_is_added_even_when_old_performance_migration_exists(legacy_execution_engine):
    engine = legacy_execution_engine
    initialize(bind=engine)
    with engine.begin() as connection:
        connection.execute(text('DROP INDEX ix_compile_queue_history_order'))
        connection.execute(text(
            "INSERT INTO compile_queue_jobs (id, kind, status, verdict, language, source_size_bytes, queued_at) "
            "VALUES ('old-public', 'run', 'completed', 'accepted', 'python', 10, :at)"
        ), {'at': RECEIVED_AT.isoformat()})
    for _ in range(2):
        initialize(bind=engine)
        indexes = [index for index in inspect(engine).get_indexes('compile_queue_jobs')
                   if index['name'] == 'ix_compile_queue_history_order']
        assert len(indexes) == 1
        assert indexes[0]['column_names'] == ['status', 'queued_at', 'id']
        with engine.connect() as connection:
            assert connection.execute(text('SELECT id FROM compile_queue_jobs')).scalars().all() == ['old-public']
