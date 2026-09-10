"""API lifecycle tables are additive and never infer process activity from lanes."""
from datetime import datetime

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core import database
import app.models.database  # Register current metadata before init_db creates new tables.
from tests.test_worker_schema_migration import legacy_execution_engine


ACTIVE_RUNTIME = "a" * 32
DRAINED_RUNTIME = "b" * 32
STARTED_AT = datetime(2030, 3, 4, 5, 6, 7)
DRAINED_AT = datetime(2030, 3, 4, 6, 7, 8)


def _create_v4_runtime_and_worker_fences(engine):
    """The pre-API-lifecycle schema has runtime/lane evidence but no API facts."""
    metadata = MetaData()
    runtimes = Table(
        "execution_runtimes",
        metadata,
        Column("id", String, primary_key=True),
        Column("pool_id", String, nullable=False, index=True),
        Column("deployment_sha", String, nullable=False),
        Column("sandbox_pool_id", String, nullable=False),
        Column("registered_at", DateTime, nullable=False),
        Column("draining_at", DateTime, nullable=True),
    )
    workers = Table(
        "execution_workers",
        metadata,
        Column("runtime_id", String, nullable=False, index=True),
        Column("id", String, primary_key=True),
        Column("pool_id", String, nullable=False, index=True),
        Column("deployment_sha", String, nullable=False),
        Column("sandbox_pool_id", String, nullable=False),
        Column("started_at", DateTime, nullable=False),
        Column("draining_at", DateTime, nullable=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            runtimes.insert(),
            [
                {
                    "id": ACTIVE_RUNTIME,
                    "pool_id": "webcompiler-blue",
                    "deployment_sha": "c" * 40,
                    "sandbox_pool_id": "shared-sandbox",
                    "registered_at": STARTED_AT,
                    "draining_at": None,
                },
                {
                    "id": DRAINED_RUNTIME,
                    "pool_id": "webcompiler-green",
                    "deployment_sha": "d" * 40,
                    "sandbox_pool_id": "shared-sandbox",
                    "registered_at": STARTED_AT,
                    "draining_at": DRAINED_AT,
                },
            ],
        )
        connection.execute(
            workers.insert(),
            [
                {
                    "id": "legacy-lane",
                    "runtime_id": "",
                    "pool_id": "webcompiler-blue",
                    "deployment_sha": "c" * 40,
                    "sandbox_pool_id": "shared-sandbox",
                    "started_at": STARTED_AT,
                    "draining_at": None,
                },
                {
                    "id": "known-active-lane",
                    "runtime_id": ACTIVE_RUNTIME,
                    "pool_id": "webcompiler-blue",
                    "deployment_sha": "c" * 40,
                    "sandbox_pool_id": "shared-sandbox",
                    "started_at": STARTED_AT,
                    "draining_at": None,
                },
                {
                    "id": "known-drained-lane",
                    "runtime_id": DRAINED_RUNTIME,
                    "pool_id": "webcompiler-green",
                    "deployment_sha": "d" * 40,
                    "sandbox_pool_id": "shared-sandbox",
                    "started_at": STARTED_AT,
                    "draining_at": DRAINED_AT,
                },
            ],
        )


def _timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.isoformat() if value is not None else None


def _fence_snapshot(engine):
    with engine.connect() as connection:
        runtimes = connection.execute(
            text(
                "SELECT id, pool_id, deployment_sha, sandbox_pool_id, registered_at, draining_at "
                "FROM execution_runtimes ORDER BY id"
            )
        ).mappings()
        workers = connection.execute(
            text(
                "SELECT id, runtime_id, pool_id, deployment_sha, sandbox_pool_id, started_at, draining_at "
                "FROM execution_workers ORDER BY id"
            )
        ).mappings()
        return {
            "runtimes": [
                {
                    **{name: row[name] for name in ("id", "pool_id", "deployment_sha", "sandbox_pool_id")},
                    "registered_at": _timestamp(row["registered_at"]),
                    "draining_at": _timestamp(row["draining_at"]),
                }
                for row in runtimes
            ],
            "workers": [
                {
                    **{
                        name: row[name]
                        for name in ("id", "runtime_id", "pool_id", "deployment_sha", "sandbox_pool_id")
                    },
                    "started_at": _timestamp(row["started_at"]),
                    "draining_at": _timestamp(row["draining_at"]),
                }
                for row in workers
            ],
        }


def _indexes_for(inspector, table, columns):
    return [
        index
        for index in inspector.get_indexes(table)
        if index.get("column_names") == columns
    ]


def _has_foreign_key(inspector, table, columns, referred_table, referred_columns):
    return any(
        foreign_key.get("constrained_columns") == columns
        and foreign_key.get("referred_table") == referred_table
        and foreign_key.get("referred_columns") == referred_columns
        for foreign_key in inspector.get_foreign_keys(table)
    )


def test_api_lifecycle_migration_adds_empty_tables_without_rewriting_runtime_or_worker_fences(
    legacy_execution_engine,
):
    engine = legacy_execution_engine
    _create_v4_runtime_and_worker_fences(engine)
    before = _fence_snapshot(engine)

    database.init_db(engine)

    inspector = inspect(engine)
    process_columns = {
        column["name"]: column
        for column in inspector.get_columns("api_processes")
    }
    request_columns = {
        column["name"]: column
        for column in inspector.get_columns("active_api_requests")
    }
    assert set(process_columns) == {
        "id",
        "runtime_id",
        "pid",
        "start_token",
        "hostname",
        "scope",
        "started_at",
        "stopped_at",
    }
    assert set(request_columns) == {"id", "process_id", "kind", "started_at"}
    assert inspector.get_pk_constraint("api_processes")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("active_api_requests")["constrained_columns"] == ["id"]
    for name in ("runtime_id", "pid", "start_token", "hostname", "scope", "started_at"):
        assert process_columns[name]["nullable"] is False
    assert process_columns["stopped_at"]["nullable"] is True
    for name in ("process_id", "kind", "started_at"):
        assert request_columns[name]["nullable"] is False
    assert isinstance(process_columns["pid"]["type"], Integer)
    assert isinstance(process_columns["started_at"]["type"], DateTime)
    assert isinstance(request_columns["started_at"]["type"], DateTime)
    assert len(_indexes_for(inspector, "api_processes", ["runtime_id"])) == 1
    assert len(_indexes_for(inspector, "active_api_requests", ["process_id"])) == 1
    assert _has_foreign_key(
        inspector,
        "api_processes",
        ["runtime_id"],
        "execution_runtimes",
        ["id"],
    )
    assert _has_foreign_key(
        inspector,
        "active_api_requests",
        ["process_id"],
        "api_processes",
        ["id"],
    )
    assert len(_indexes_for(inspector, "execution_runtimes", ["pool_id"])) == 1
    assert len(_indexes_for(inspector, "execution_workers", ["runtime_id"])) == 1
    assert _fence_snapshot(engine) == before

    # Existing runtime/lane records are not evidence that an API process or an
    # HTTP/WebSocket request is alive, so this migration must not backfill them.
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM api_processes")).all() == []
        assert connection.execute(text("SELECT id FROM active_api_requests")).all() == []

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO api_processes "
                "(id, runtime_id, pid, start_token, hostname, scope, started_at, stopped_at) "
                "VALUES (:id, :runtime_id, :pid, :start_token, :hostname, :scope, :started_at, NULL)"
            ),
            {
                "id": "api-process",
                "runtime_id": ACTIVE_RUNTIME,
                "pid": 1234,
                "start_token": "test:1234",
                "hostname": "api-worker",
                "scope": "e" * 64,
                "started_at": STARTED_AT.isoformat(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO active_api_requests (id, process_id, kind, started_at) "
                "VALUES (:id, :process_id, :kind, :started_at)"
            ),
            {
                "id": "active-http",
                "process_id": "api-process",
                "kind": "http",
                "started_at": STARTED_AT.isoformat(),
            },
        )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO api_processes "
                    "(id, runtime_id, pid, start_token, hostname, scope, started_at) "
                    "VALUES ('unknown-runtime', 'missing-runtime', 1, 'token', 'host', 'scope', CURRENT_TIMESTAMP)"
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO active_api_requests (id, process_id, kind, started_at) "
                    "VALUES ('unknown-process', 'missing-process', 'websocket', CURRENT_TIMESTAMP)"
                )
            )

    database.init_db(engine)

    inspector = inspect(engine)
    assert _fence_snapshot(engine) == before
    assert len(_indexes_for(inspector, "api_processes", ["runtime_id"])) == 1
    assert len(_indexes_for(inspector, "active_api_requests", ["process_id"])) == 1
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM api_processes ORDER BY id")).all() == [("api-process",)]
        assert connection.execute(text("SELECT id FROM active_api_requests ORDER BY id")).all() == [("active-http",)]
