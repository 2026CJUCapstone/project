import importlib.util
import os
import subprocess
from pathlib import Path
import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "e2e_stack_test.py"
BUILD_SCRIPT = SCRIPT.with_name("build_sandbox_image.sh")


def load_script():
    spec = importlib.util.spec_from_file_location("isolated_e2e_stack_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_e2e_stack_overrides_caller_database_redis_and_project(monkeypatch):
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "production-project")
    monkeypatch.setenv("WEBCOMPILER_DATABASE_URL", "postgresql://production")
    monkeypatch.setenv("WEBCOMPILER_MIGRATION_DATABASE_URL", "postgresql://production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://production")
    monkeypatch.setenv("WEBCOMPILER_REDIS_URL", "redis://production")
    monkeypatch.setenv("REDIS_URL", "redis://production")
    monkeypatch.setenv("WEBCOMPILER_POSTGRES_HOST", "production-db")
    monkeypatch.setenv("WEBCOMPILER_POSTGRES_PORT", "6432")
    monkeypatch.setenv("WEBCOMPILER_BACKEND_IMAGE", "production-backend")
    monkeypatch.setenv("SANDBOX_POOL_ID", "production-pool")
    monkeypatch.setenv("WEBCOMPILER_DATA_DIR", "/production/data")
    monkeypatch.setenv("SMTP_HOST", "smtp.production.example")
    monkeypatch.setenv("SMTP_PASSWORD", "production-secret")
    monkeypatch.setenv("WEBCOMPILER_SMTP_HOST", "smtp.production.example")

    script = load_script()

    assert script.ENV["COMPOSE_PROJECT_NAME"].startswith("webcompiler-e2e-")
    assert script.ENV["COMPOSE_PROJECT_NAME"] != "production-project"
    assert "@pgbouncer:5432/compiler_e2e" in script.ENV["WEBCOMPILER_DATABASE_URL"]
    assert "@postgres:5432/compiler_e2e" in script.ENV["WEBCOMPILER_MIGRATION_DATABASE_URL"]
    assert script.ENV["DATABASE_URL"] == script.ENV["WEBCOMPILER_DATABASE_URL"]
    assert script.ENV["WEBCOMPILER_REDIS_URL"] == "redis://redis:6379/0"
    assert script.ENV["REDIS_URL"] == "redis://redis:6379/0"
    assert script.ENV["WEBCOMPILER_REDIS_KEY_PREFIX"] == script.E2E_NAMESPACE
    assert script.ENV["SANDBOX_IMAGE"] == f"{script.E2E_NAMESPACE}-sandbox:latest"
    assert script.ENV["WEBCOMPILER_POSTGRES_HOST"] == "postgres"
    assert script.ENV["WEBCOMPILER_POSTGRES_PORT"] == "5432"
    assert script.ENV["WEBCOMPILER_BACKEND_IMAGE"] == f"{script.E2E_NAMESPACE}-backend:latest"
    assert script.ENV["WEBCOMPILER_E2E_RELEASE_BUILD_CACHE"] == "1"
    assert script.ENV["SANDBOX_POOL_ID"] == script.E2E_NAMESPACE
    assert Path(script.ENV["WEBCOMPILER_DATA_DIR"]).parts[-2:] == (
        ".data", script.E2E_NAMESPACE)
    assert all(
        script.ENV[name] == ""
        for name in (
            "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM",
            "WEBCOMPILER_SMTP_HOST", "WEBCOMPILER_SMTP_USERNAME",
            "WEBCOMPILER_SMTP_PASSWORD", "WEBCOMPILER_SMTP_FROM",
        )
    )
    assert script.ENV["SMTP_PORT"] == script.ENV["WEBCOMPILER_SMTP_PORT"] == "587"
    assert script.ENV["SMTP_STARTTLS"] == script.ENV["WEBCOMPILER_SMTP_STARTTLS"] == "false"
    assert script.ADMIN_USERNAME == "admin"
    assert script.ENV.get("WEBCOMPILER_WORKER_UID") == os.environ.get("WEBCOMPILER_WORKER_UID")


def test_sandbox_builder_uses_runtime_image_name_with_legacy_fallback():
    source = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'SANDBOX_IMAGE="${SANDBOX_IMAGE:-${SANDBOX_IMAGE_TAG:-compiler-sandbox}}"' in source
    assert '-t "$SANDBOX_IMAGE"' in source


def test_e2e_does_not_inherit_compose_overrides_or_remote_docker(monkeypatch):
    for key, value in {
        "COMPOSE_FILE": "/production/compose.yml",
        "COMPOSE_ENV_FILES": "/production/secrets.env",
        "COMPOSE_PROFILES": "production",
        "DOCKER_CONTEXT": "production",
        "DOCKER_HOST": "ssh://production",
        "DOCKER_TLS_VERIFY": "1",
        "WEBCOMPILER_FRONTEND_IMAGE": "production-frontend",
        "PASSWORD_RESET_BASE_URL": "https://production.example",
    }.items():
        monkeypatch.setenv(key, value)
    script = load_script()
    assert script.ENV["COMPOSE_FILE"] == os.pathsep.join(str(script.ROOT_DIR / name)
        for name in ('docker-compose.yml', 'scripts/e2e-stack.compose.yml'))
    assert script.ENV["COMPOSE_ENV_FILES"] == os.devnull
    assert script.ENV["COMPOSE_DISABLE_ENV_FILE"] == "1"
    assert script.ENV["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    for forbidden in ("COMPOSE_PROFILES", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY",
                      "WEBCOMPILER_FRONTEND_IMAGE", "PASSWORD_RESET_BASE_URL"):
        assert forbidden not in script.ENV


def test_e2e_preserves_bound_builder_but_not_shell_hooks_or_compiler_overrides(monkeypatch):
    preserved = {
        'WEBCOMPILER_BUILD_BUILDER': 'audit-build-test',
        'WEBCOMPILER_BUILD_CONTAINER_ID': 'a' * 64,
        'WEBCOMPILER_BUILD_MEMORY_MB': '2048',
        'WEBCOMPILER_BUILD_CPU_MILLIS': '1000',
        'WEBCOMPILER_BUILD_PIDS': '512',
        'BUILDX_CONFIG': '/tmp/audit/buildx',
    }
    forbidden = ('BASH_ENV', 'ENV', 'PYTHONPATH', 'LD_PRELOAD',
                 'BPP_REF', 'BPP_BOOTSTRAP_URL', 'ARBITRARY_APP_SECRET')
    for key, value in preserved.items():
        monkeypatch.setenv(key, value)
    for key in forbidden:
        monkeypatch.setenv(key, 'caller-value-must-not-leak')
    script = load_script()
    assert all(script.ENV[key] == value for key, value in preserved.items())
    assert all(key not in script.ENV for key in forbidden)


def test_e2e_cleanup_failure_is_not_silently_discarded(monkeypatch):
    script = load_script()
    monkeypatch.setattr(script, 'preflight', lambda: None)
    monkeypatch.setattr(script, 'record_ownership', lambda: None)
    calls = []
    def command(*args):
        calls.append(args)
        if args[-1] == 'scripts/docker_up.sh':
            raise RuntimeError('setup did not finish')
        raise subprocess.CalledProcessError(17, args)
    monkeypatch.setattr(script, 'run_command', command)
    monkeypatch.setattr(script, 'cleanup_owned_stack', lambda: command('owned-cleanup'))
    with pytest.raises(subprocess.CalledProcessError) as failure:
        script.exercise_stack()
    assert failure.value.returncode == 17
    assert calls == [('bash', 'scripts/docker_up.sh'), ('owned-cleanup',)]
