"""The development import path must use the explicit initialization contract."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCHEMA_VERSION = "20260910_execution_retention_v10"

# Keep these imports self-contained even when a developer or the CI host has a
# deployment environment exported.  In particular, no inherited URL may point
# this regression test at a shared database or Redis instance.
_ISOLATED_ENVIRONMENT = {
    "DATABASE_URL",
    "REDIS_URL",
    "REDIS_KEY_PREFIX",
    "WEBCOMPILER_REDIS_URL",
    "WEBCOMPILER_REDIS_KEY_PREFIX",
    "ENVIRONMENT",
    "AUTO_INITIALIZE_DB",
    "EMBEDDED_EXECUTION_WORKER",
    "RUNTIME_POOL_ID",
    "RUNTIME_INSTANCE_ID",
    "DEPLOYMENT_SHA",
    "SECRET_KEY",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "ADMIN_NICKNAME",
    "SANDBOX_POOL_ID",
    "DOCKER_HOST",
    "PGOPTIONS",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_POOL_RECYCLE_SECONDS",
}

_IMPORT_MAIN = """
from app.core.database import engine
try:
    import app.main
finally:
    # SQLite retains a Windows file handle until the engine is disposed.
    engine.dispose()
"""


def _environment(database: Path, **overrides: str) -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name in _ISOLATED_ENVIRONMENT or name.startswith("WEBCOMPILER_"):
            environment.pop(name, None)
    environment.update({
        "PYTHONPATH": str(BACKEND_ROOT),
        "DATABASE_URL": "sqlite:///" + database.as_posix(),
        "ENVIRONMENT": "development",
        "REDIS_URL": "",
        "REDIS_KEY_PREFIX": "development-initialization-test",
        "RUNTIME_POOL_ID": "local",
        "RUNTIME_INSTANCE_ID": "",
        "DEPLOYMENT_SHA": "",
        "EMBEDDED_EXECUTION_WORKER": "false",
        "ADMIN_USERNAME": "development-init-admin",
        "ADMIN_NICKNAME": "Development Init Admin",
        "ADMIN_PASSWORD": "development-initialization-test-password",
        "SANDBOX_POOL_ID": "development-initialization-test",
    })
    environment.update(overrides)
    return environment


def _import_main(database: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_MAIN],
        cwd=BACKEND_ROOT,
        env=_environment(database, **overrides),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _tables(database: Path) -> set[str]:
    if not database.exists():
        return set()
    with sqlite3.connect(database) as connection:
        return {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}


def _initialized_snapshot(database: Path) -> dict[str, object]:
    with sqlite3.connect(database) as connection:
        assert 'sandbox_operation' in {row[1] for row in connection.execute('PRAGMA table_info(execution_jobs)')}
        assert 'sandbox_daemon_id' in {row[1] for row in connection.execute('PRAGMA table_info(execution_jobs)')}
        marker_count = connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = ?",
            (RUNTIME_SCHEMA_VERSION,),
        ).fetchone()[0]
        admin = connection.execute(
            "SELECT username, nickname, hashed_password, role, auth_version "
            "FROM users WHERE username = ?",
            ("development-init-admin",),
        ).fetchall()
        boards = connection.execute(
            "SELECT id, creator_id, title, difficulty, points FROM problems "
            "WHERE id IN ('__notice__', '__free__') ORDER BY id"
        ).fetchall()
        guide = connection.execute(
            "SELECT id, problem_id, user_id, content FROM comments "
            "WHERE id = 'system-community-guide-v1'"
        ).fetchall()
    return {
        "marker_count": marker_count,
        "admin": admin,
        "boards": boards,
        "guide": guide,
    }


def test_default_development_import_initializes_runtime_schema_and_preserves_bootstrap(tmp_path):
    database = tmp_path / "development-default.db"

    first = _import_main(database)
    assert first.returncode == 0, first.stderr
    before = _initialized_snapshot(database)
    assert before["marker_count"] == 1
    assert len(before["admin"]) == 1
    assert len(before["boards"]) == 2
    assert len(before["guide"]) == 1

    # A new interpreter exercises the module-import initialization branch
    # again; importing from sys.modules in this test process would not.
    second = _import_main(database)
    assert second.returncode == 0, second.stderr
    assert _initialized_snapshot(database) == before


def test_auto_initialize_db_false_leaves_a_fresh_development_database_uninitialized(tmp_path):
    database = tmp_path / "development-disabled.db"

    result = _import_main(database, AUTO_INITIALIZE_DB="false")

    assert result.returncode == 0, result.stderr
    assert _tables(database) == set()


def test_production_auto_initialization_is_refused_before_touching_database(tmp_path):
    database = tmp_path / "production-refused.db"

    result = _import_main(
        database,
        ENVIRONMENT="production",
        AUTO_INITIALIZE_DB="true",
        RUNTIME_INSTANCE_ID="1" * 32,
        DEPLOYMENT_SHA="a" * 40,
        SECRET_KEY="s" * 32,
        ADMIN_PASSWORD="p" * 16,
    )

    assert result.returncode != 0
    assert "Production schema changes require python -m app.initialize" in result.stderr
    assert _tables(database) == set()
