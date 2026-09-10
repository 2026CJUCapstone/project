"""Sandbox-operation migration is additive and initializer retries keep intent."""
import json
from datetime import datetime, timezone

from sqlalchemy import JSON, MetaData, Table, inspect, text

from app.initialize import RUNTIME_SCHEMA_VERSION, initialize
import app.models.database  # Register current metadata before initializer creates tables.
from tests.test_worker_schema_migration import (
    _create_legacy_execution_jobs,
    _execution_job_snapshot,
    legacy_execution_engine,
)


V7_SCHEMA_VERSION = "20260910_namespace_observation_v7"
PENDING_OPERATION = {
    "version": 1,
    "id": "a" * 32,
    "kind": "create",
    "lease_token": "b" * 32,
    "name": "compiler-" + "b" * 32 + "-" + "a" * 32,
    "container_id": None,
    "begun_at": datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc).isoformat(),
}


def _timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.isoformat() if value is not None else None


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _job_snapshot(engine, *, include_operation):
    columns = (
        "id, owner_key, quota_key, request_id, payload_hash, kind, payload, result, status, "
        "received_at, started_at, finished_at, lease_token, lease_until, worker_id, attempts"
    )
    if include_operation:
        columns += ", sandbox_operation"
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT {columns} FROM execution_jobs ORDER BY id")
        ).mappings()
        result = {}
        for row in rows:
            record = {
                "owner_key": row["owner_key"],
                "quota_key": row["quota_key"],
                "request_id": row["request_id"],
                "payload_hash": row["payload_hash"],
                "kind": row["kind"],
                "payload": _json(row["payload"]),
                "result": _json(row["result"]),
                "status": row["status"],
                "received_at": _timestamp(row["received_at"]),
                "started_at": _timestamp(row["started_at"]),
                "finished_at": _timestamp(row["finished_at"]),
                "lease_token": row["lease_token"],
                "lease_until": _timestamp(row["lease_until"]),
                "worker_id": row["worker_id"],
                "attempts": row["attempts"],
            }
            if include_operation:
                record["sandbox_operation"] = _json(row["sandbox_operation"])
            result[row["id"]] = record
        return result


def test_initializer_adds_nullable_sandbox_operation_and_preserves_pending_intent(
    legacy_execution_engine,
):
    """No migration or repeat initializer may infer that a pending Docker RPC settled."""
    engine = legacy_execution_engine
    _create_legacy_execution_jobs(engine)
    legacy_before = _execution_job_snapshot(engine, include_worker_id=False)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_migrations "
                "(version VARCHAR PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:version)"),
            {"version": V7_SCHEMA_VERSION},
        )

    initialize(bind=engine)

    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("execution_jobs")}
    assert columns["sandbox_operation"]["nullable"] is True
    assert isinstance(columns["sandbox_operation"]["type"], JSON)

    migrated = _job_snapshot(engine, include_operation=True)
    assert set(migrated) == {"queued", "running", "completed"}
    assert {
        job_id: {
            key: value
            for key, value in row.items()
            if key not in {"worker_id", "sandbox_operation"}
        }
        for job_id, row in migrated.items()
    } == legacy_before
    assert all(row["worker_id"] is None for row in migrated.values())
    assert all(row["sandbox_operation"] is None for row in migrated.values())

    jobs = Table("execution_jobs", MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            jobs.update().where(jobs.c.id == "running").values(sandbox_operation=PENDING_OPERATION)
        )
    pending_before_retry = _job_snapshot(engine, include_operation=True)
    assert pending_before_retry["running"]["sandbox_operation"] == PENDING_OPERATION

    # The v8 marker is additive. This only verifies schema history/data
    # preservation, not that a mixed-version online worker rollout is safe.
    assert RUNTIME_SCHEMA_VERSION == "20260910_execution_retention_v10"
    with engine.connect() as connection:
        versions = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
    assert {V7_SCHEMA_VERSION, RUNTIME_SCHEMA_VERSION} <= versions

    initialize(bind=engine)

    assert _job_snapshot(engine, include_operation=True) == pending_before_retry
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE version = :version"),
            {"version": RUNTIME_SCHEMA_VERSION},
        ).scalar_one() == 1
