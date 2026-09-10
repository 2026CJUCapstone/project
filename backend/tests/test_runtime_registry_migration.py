"""The runtime registry is additive; existing worker lanes are not runtime facts."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, MetaData, String, Table, inspect, text

from app.core import database
import app.models.database  # Register current metadata before init_db creates new tables.
from tests.test_worker_schema_migration import legacy_execution_engine


def _create_v3_workers(engine):
    """Create the pre-runtime-registry worker schema with real lane evidence."""
    metadata = MetaData()
    workers = Table(
        "execution_workers",
        metadata,
        Column("runtime_id", String, nullable=False, default="", index=True),
        Column("id", String, primary_key=True),
        Column("pool_id", String, nullable=False, index=True),
        Column("deployment_sha", String, nullable=False),
        Column("sandbox_pool_id", String, nullable=False),
        Column("started_at", DateTime, nullable=False),
        Column("draining_at", DateTime, nullable=True),
    )
    metadata.create_all(engine)
    started_at = datetime(2030, 2, 3, 4, 5, 6)
    drained_at = datetime(2030, 2, 3, 5, 6, 7)
    with engine.begin() as connection:
        connection.execute(
            workers.insert(),
            [
                {
                    "id": uuid4().hex,
                    "runtime_id": "",
                    "pool_id": "webcompiler-blue",
                    "deployment_sha": "a" * 40,
                    "sandbox_pool_id": "shared-sandbox",
                    "started_at": started_at,
                    "draining_at": None,
                },
                {
                    "id": uuid4().hex,
                    "runtime_id": "b" * 32,
                    "pool_id": "webcompiler-green",
                    "deployment_sha": "c" * 40,
                    "sandbox_pool_id": "shared-sandbox",
                    "started_at": started_at,
                    "draining_at": drained_at,
                },
            ],
        )


def _timestamp(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.isoformat() if value is not None else None


def _worker_snapshot(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, runtime_id, pool_id, deployment_sha, sandbox_pool_id, "
                "started_at, draining_at FROM execution_workers ORDER BY id"
            )
        ).mappings()
        return [
            {
                "id": row["id"],
                "runtime_id": row["runtime_id"],
                "pool_id": row["pool_id"],
                "deployment_sha": row["deployment_sha"],
                "sandbox_pool_id": row["sandbox_pool_id"],
                "started_at": _timestamp(row["started_at"]),
                "draining_at": _timestamp(row["draining_at"]),
            }
            for row in rows
        ]


def _indexes_for(inspector, table, columns):
    return [
        index
        for index in inspector.get_indexes(table)
        if index.get("column_names") == columns
    ]


def test_runtime_registry_migration_preserves_v3_lanes_without_backfill(legacy_execution_engine):
    engine = legacy_execution_engine
    _create_v3_workers(engine)
    before = _worker_snapshot(engine)
    assert {row["runtime_id"] for row in before} == {"", "b" * 32}
    assert any(row["draining_at"] is None for row in before)
    assert any(row["draining_at"] is not None for row in before)

    database.init_db(engine)

    inspector = inspect(engine)
    runtime_columns = {
        column["name"]: column
        for column in inspector.get_columns("execution_runtimes")
    }
    assert {
        "id",
        "pool_id",
        "deployment_sha",
        "sandbox_pool_id",
        "registered_at",
        "draining_at",
    } <= set(runtime_columns)
    assert inspector.get_pk_constraint("execution_runtimes")["constrained_columns"] == ["id"]
    for name in ("pool_id", "deployment_sha", "sandbox_pool_id", "registered_at"):
        assert runtime_columns[name]["nullable"] is False
    assert isinstance(runtime_columns["registered_at"]["type"], DateTime)
    assert runtime_columns["draining_at"]["nullable"] is True
    assert len(_indexes_for(inspector, "execution_runtimes", ["pool_id"])) == 1
    assert inspector.get_foreign_keys("execution_runtimes") == []

    # A lane is neither proof that a runtime is active nor proof that it drained.
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM execution_runtimes")).all() == []
    assert _worker_snapshot(engine) == before
    assert len(_indexes_for(inspector, "execution_workers", ["runtime_id"])) == 1
    # The legacy runtime_id remains non-FK/unknown-compatible; the later
    # nullable process binding has its own independently verified FK.
    assert all('runtime_id' not in key['constrained_columns']
               for key in inspector.get_foreign_keys('execution_workers'))

    database.init_db(engine)

    inspector = inspect(engine)
    assert _worker_snapshot(engine) == before
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM execution_runtimes")).all() == []
    assert len(_indexes_for(inspector, "execution_runtimes", ["pool_id"])) == 1
    assert len(_indexes_for(inspector, "execution_workers", ["runtime_id"])) == 1
