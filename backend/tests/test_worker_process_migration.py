"""Worker-process ownership is additive and never inferred from old lanes."""
import json
from datetime import datetime

import pytest
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, MetaData, String, Table, UniqueConstraint, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core import database
import app.models.database  # Register current metadata before init_db creates new tables.
from tests.test_api_lifecycle_migration import (
    ACTIVE_RUNTIME,
    DRAINED_AT,
    STARTED_AT,
    _create_v4_runtime_and_worker_fences,
)
from tests.test_worker_schema_migration import legacy_execution_engine


PROCESS_EPOCH = "e" * 32


def _create_v5_jobs(engine):
    """Create pre-worker-process claims, including durable lane ownership."""
    metadata = MetaData()
    Table("execution_workers", metadata, autoload_with=engine)
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
        Column("worker_id", String, ForeignKey("execution_workers.id"), nullable=True, index=True),
        Column("attempts", Integer, nullable=False),
        UniqueConstraint("owner_key", "request_id", name="uq_execution_owner_request"),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            jobs.insert(),
            [
                {
                    "id": "queued-legacy",
                    "owner_key": "owner-queued",
                    "quota_key": "quota-queued",
                    "request_id": "request-queued",
                    "payload_hash": "hash-queued",
                    "kind": "run",
                    "payload": {"source": "queued", "stdin": "one"},
                    "result": None,
                    "status": "queued",
                    "received_at": STARTED_AT,
                    "started_at": None,
                    "finished_at": None,
                    "lease_token": None,
                    "lease_until": None,
                    "worker_id": None,
                    "attempts": 0,
                },
                {
                    "id": "running-legacy",
                    "owner_key": "owner-running",
                    "quota_key": "quota-running",
                    "request_id": "request-running",
                    "payload_hash": "hash-running",
                    "kind": "run",
                    "payload": {"source": "running", "stdin": "two"},
                    "result": None,
                    "status": "running",
                    "received_at": STARTED_AT,
                    "started_at": STARTED_AT,
                    "finished_at": None,
                    "lease_token": "legacy-lease-token",
                    "lease_until": DRAINED_AT,
                    "worker_id": "known-active-lane",
                    "attempts": 1,
                },
                {
                    "id": "completed-legacy",
                    "owner_key": "owner-completed",
                    "quota_key": "quota-completed",
                    "request_id": "request-completed",
                    "payload_hash": "hash-completed",
                    "kind": "run",
                    "payload": {"source": "completed", "stdin": "three"},
                    "result": {"verdict": "accepted", "stdout": "3"},
                    "status": "completed",
                    "received_at": STARTED_AT,
                    "started_at": STARTED_AT,
                    "finished_at": DRAINED_AT,
                    "lease_token": None,
                    "lease_until": None,
                    "worker_id": "known-drained-lane",
                    "attempts": 1,
                },
            ],
        )


def _timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.isoformat() if value is not None else None


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _runtime_and_lane_snapshot(engine, *, include_process_id):
    lane_columns = "id, runtime_id, pool_id, deployment_sha, sandbox_pool_id, started_at, draining_at"
    if include_process_id:
        lane_columns += ", process_id"
    with engine.connect() as connection:
        runtimes = connection.execute(
            text(
                "SELECT id, pool_id, deployment_sha, sandbox_pool_id, registered_at, draining_at "
                "FROM execution_runtimes ORDER BY id"
            )
        ).mappings()
        lanes = connection.execute(
            text(f"SELECT {lane_columns} FROM execution_workers ORDER BY id")
        ).mappings()
        return {
            "runtimes": [
                {
                    "id": row["id"],
                    "pool_id": row["pool_id"],
                    "deployment_sha": row["deployment_sha"],
                    "sandbox_pool_id": row["sandbox_pool_id"],
                    "registered_at": _timestamp(row["registered_at"]),
                    "draining_at": _timestamp(row["draining_at"]),
                }
                for row in runtimes
            ],
            "lanes": [
                {
                    **{
                        name: row[name]
                        for name in ("id", "runtime_id", "pool_id", "deployment_sha", "sandbox_pool_id")
                    },
                    "started_at": _timestamp(row["started_at"]),
                    "draining_at": _timestamp(row["draining_at"]),
                    **({"process_id": row["process_id"]} if include_process_id else {}),
                }
                for row in lanes
            ],
        }


def _claim_snapshot(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, owner_key, quota_key, request_id, payload_hash, kind, payload, result, status, "
                "received_at, started_at, finished_at, lease_token, lease_until, worker_id, attempts "
                "FROM execution_jobs ORDER BY id"
            )
        ).mappings()
        return [
            {
                "id": row["id"],
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
            for row in rows
        ]


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


def test_worker_process_migration_keeps_legacy_runtime_lanes_and_claims_unowned(
    legacy_execution_engine,
):
    engine = legacy_execution_engine
    _create_v4_runtime_and_worker_fences(engine)
    _create_v5_jobs(engine)
    before_fences = _runtime_and_lane_snapshot(engine, include_process_id=False)
    before_claims = _claim_snapshot(engine)

    database.init_db(engine)

    inspector = inspect(engine)
    process_columns = {
        column["name"]: column
        for column in inspector.get_columns("worker_processes")
    }
    assert set(process_columns) == {
        "id",
        "runtime_id",
        "pid",
        "start_token",
        "hostname",
        "scope",
        "started_at",
        "draining_at",
        "stopped_at",
    }
    assert inspector.get_pk_constraint("worker_processes")["constrained_columns"] == ["id"]
    for name in ("runtime_id", "pid", "start_token", "hostname", "scope", "started_at"):
        assert process_columns[name]["nullable"] is False
    assert process_columns["draining_at"]["nullable"] is True
    assert process_columns["stopped_at"]["nullable"] is True
    assert isinstance(process_columns["pid"]["type"], Integer)
    assert isinstance(process_columns["started_at"]["type"], DateTime)
    assert len(_indexes_for(inspector, "worker_processes", ["runtime_id"])) == 1
    assert _has_foreign_key(
        inspector,
        "worker_processes",
        ["runtime_id"],
        "execution_runtimes",
        ["id"],
    )

    lane_columns = {
        column["name"]: column
        for column in inspector.get_columns("execution_workers")
    }
    assert lane_columns["process_id"]["nullable"] is True
    assert len(_indexes_for(inspector, "execution_workers", ["process_id"])) == 1
    assert _has_foreign_key(
        inspector,
        "execution_workers",
        ["process_id"],
        "worker_processes",
        ["id"],
    )

    after_fences = _runtime_and_lane_snapshot(engine, include_process_id=True)
    assert {
        "runtimes": after_fences["runtimes"],
        "lanes": [
            {key: value for key, value in lane.items() if key != "process_id"}
            for lane in after_fences["lanes"]
        ],
    } == before_fences
    assert all(lane["process_id"] is None for lane in after_fences["lanes"])
    assert _claim_snapshot(engine) == before_claims
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM worker_processes")).all() == []

    database.init_db(engine)
    assert _runtime_and_lane_snapshot(engine, include_process_id=True) == after_fences
    assert _claim_snapshot(engine) == before_claims
    assert len(_indexes_for(inspect(engine), "worker_processes", ["runtime_id"])) == 1
    assert len(_indexes_for(inspect(engine), "execution_workers", ["process_id"])) == 1

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO worker_processes "
                "(id, runtime_id, pid, start_token, hostname, scope, started_at, draining_at, stopped_at) "
                "VALUES (:id, :runtime_id, :pid, :start_token, :hostname, :scope, :started_at, NULL, NULL)"
            ),
            {
                "id": PROCESS_EPOCH,
                "runtime_id": ACTIVE_RUNTIME,
                "pid": 4321,
                "start_token": "test:4321",
                "hostname": "worker-host",
                "scope": "f" * 64,
                "started_at": STARTED_AT.isoformat(),
            },
        )
        connection.execute(
            text("UPDATE execution_workers SET process_id=:process_id WHERE id='known-active-lane'"),
            {"process_id": PROCESS_EPOCH},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE execution_workers SET process_id='missing-process' WHERE id='legacy-lane'")
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO worker_processes "
                    "(id, runtime_id, pid, start_token, hostname, scope, started_at) "
                    "VALUES ('unknown-process', 'missing-runtime', 1, 'token', 'host', 'scope', CURRENT_TIMESTAMP)"
                )
            )

    database.init_db(engine)
    lanes = _runtime_and_lane_snapshot(engine, include_process_id=True)["lanes"]
    assert {lane["id"]: lane["process_id"] for lane in lanes} == {
        "known-active-lane": PROCESS_EPOCH,
        "known-drained-lane": None,
        "legacy-lane": None,
    }
    assert _claim_snapshot(engine) == before_claims
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, runtime_id, pid, start_token, hostname, scope, started_at, draining_at, stopped_at "
                "FROM worker_processes"
            )
        ).mappings()
        assert [
            {
                "id": row["id"],
                "runtime_id": row["runtime_id"],
                "pid": row["pid"],
                "start_token": row["start_token"],
                "hostname": row["hostname"],
                "scope": row["scope"],
                "started_at": _timestamp(row["started_at"]),
                "draining_at": _timestamp(row["draining_at"]),
                "stopped_at": _timestamp(row["stopped_at"]),
            }
            for row in rows
        ] == [
            {
                "id": PROCESS_EPOCH,
                "runtime_id": ACTIVE_RUNTIME,
                "pid": 4321,
                "start_token": "test:4321",
                "hostname": "worker-host",
                "scope": "f" * 64,
                "started_at": STARTED_AT.isoformat(),
                "draining_at": None,
                "stopped_at": None,
            }
        ]
