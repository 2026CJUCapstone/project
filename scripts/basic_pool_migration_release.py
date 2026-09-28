"""One-shot, migration-aware release for the adopted basic production pool.

This script is deliberately not wired into automatic deployment.  It accepts
only the already-adopted pool, rehearses the additive migration on a restored
production dump, enters maintenance, creates a fresh backup, migrates the live
database, and then replaces only the application containers.  Failure rolls
the application images and runtime marker back; it never restores a dump over
the live database automatically.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from urllib.request import urlopen
from uuid import uuid4


def _load_base():
    path = Path(__file__).with_name("basic_pool_deploy.py")
    spec = importlib.util.spec_from_file_location("basic_pool_deploy", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Deployment helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b = _load_base()

MIN_FREE_BYTES = 3 * 1024**3
BUSINESS_TABLES = (
    "users",
    "problems",
    "comments",
    "code_projects",
    "submissions",
    "user_problem_scores",
    "contests",
    "contest_problems",
    "contest_participants",
    "contest_submissions",
    "password_reset_tokens",
    "admin_audit_events",
    "compile_queue_jobs",
    "execution_jobs",
    "problem_learning_records",
)
MIGRATED_BUSINESS_COLUMNS = {"problems": {"judge_policy"}}
UNCHANGED_CONTRACTS = (
    "backend/Dockerfile",
    "backend/requirements.lock",
    "frontend/Dockerfile",
    "frontend/package.json",
    "frontend/package-lock.json",
    "docker-compose.yml",
    "docker-compose.lb.yml",
    "scripts/basic-lb.compose.yml",
    "scripts/basic-lb.production.compose.yml",
    "runtime/docker/Dockerfile",
    "runtime/sandbox/run.sh",
    "runtime/bpp-ref.txt",
)
EXPECTED_RUNTIME_ADDITIONS: set[str] = set()
RUNTIME_MARKER = re.compile(r"^RUNTIME_SCHEMA_VERSION\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)


def _assert_free_space(path: Path) -> None:
    assert shutil.disk_usage(path).free >= MIN_FREE_BYTES, "Insufficient bounded release space"


def _marker(source_root: Path) -> str:
    text = (source_root / "backend/app/initialize.py").read_text(encoding="utf-8")
    match = RUNTIME_MARKER.search(text)
    assert match and re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", match.group(1))
    return match.group(1)


def _contract(path: Path) -> bytes:
    return b.contract_bytes(path)


def check_migration_contracts(previous: Path, candidate: Path) -> None:
    for relative in UNCHANGED_CONTRACTS:
        assert _contract(previous / relative) == _contract(candidate / relative), (
            "Unreviewed dependency/topology/runtime change: " + relative
        )
    old_runtime = {
        p.relative_to(previous).as_posix()
        for p in (previous / "runtime").rglob("*")
        if p.is_file()
    }
    new_runtime = {
        p.relative_to(candidate).as_posix()
        for p in (candidate / "runtime").rglob("*")
        if p.is_file()
    }
    assert new_runtime - old_runtime == EXPECTED_RUNTIME_ADDITIONS
    assert not old_runtime - new_runtime
    old_modules = {
        p.relative_to(previous / "backend/app").as_posix()
        for p in (previous / "backend/app").rglob("*.py")
    }
    new_modules = {
        p.relative_to(candidate / "backend/app").as_posix()
        for p in (candidate / "backend/app").rglob("*.py")
    }
    assert old_modules <= new_modules, "Removed backend module requires a clean-image review"
    assert _marker(previous) != _marker(candidate), "Migration release requires a new runtime marker"
    for path in (candidate / "runtime").rglob("*.sh"):
        assert b"\r" not in path.read_bytes(), "Runtime shell files must use LF"


def prepare() -> None:
    assert not b.STATE.exists()
    _assert_free_space(b.ROOT)
    old = json.loads(b.o.STATE.read_text())
    assert old["phase"] == "deployed"
    previous = Path(old["functional_release_root"])
    assert previous.is_absolute() and previous.resolve() == previous and previous.is_dir()
    source = b.o.run("git", "-C", str(b.PROD), "archive", "--format=tar", b.SHA, timeout=60)
    (b.ROOT / "source.tar").write_bytes(source)
    b.extract(b.ROOT / "source.tar")
    check_migration_contracts(previous, b.ROOT)
    deploy_dir = b.PROD / ".deploy"
    assert deploy_dir.resolve(strict=True) == deploy_dir
    bundle = Path(os.environ["WEBCOMPILER_FRONTEND_ARCHIVE"])
    assert bundle.is_absolute() and bundle.resolve(strict=True) == bundle
    assert bundle.parent == deploy_dir and bundle.is_file() and not bundle.is_symlink()
    assert bundle.stat().st_size <= 32 * 1024**2
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == os.environ["WEBCOMPILER_FRONTEND_SHA256"]
    shutil.copyfile(bundle, b.ROOT / "frontend-tested.tar.gz")
    b.extract(b.ROOT / "frontend-tested.tar.gz", "frontend-dist")
    release = json.loads((b.ROOT / "frontend-dist/.well-known/webcompiler-release.json").read_text())
    assert release == {"deployment_sha": b.SHA}
    assert (b.ROOT / "frontend-dist/index.html").is_file()
    bases = {
        "backend": old["backend_id"],
        "frontend": old["frontend_id"],
        "sandbox": old["env"]["SANDBOX_IMAGE"],
    }
    assert all(b.o.inspect(value)["Id"] == value for value in bases.values())
    ids = {role: b.o.inspect(b.PROJECT + "-" + role + "-1")["Id"] for role in ("worker", "frontend", "redis", "pgbouncer", "api-proxy")}
    ids.update({f"backend-{number}": b.o.inspect(b.PROJECT + f"-backend-{number}")["Id"] for number in (1, 2)})
    state = {
        "phase": "building",
        "sha": b.SHA,
        "old": old,
        "old_ids": ids,
        "bases": bases,
        "images": {"sandbox": bases["sandbox"]},
        "sandbox_reused": True,
        "old_marker": _marker(previous),
        "new_marker": _marker(b.ROOT),
        "postgres_id": b.o.inspect("webcompiler-postgres")["Id"],
        "tags": [],
    }
    b.save(state)
    b.atomic_json(b.PROD / ".deploy/basic-pool-pending.json", {"root": str(b.ROOT)})
    build()


def _build(role: str, dockerfile: str, inputs: tuple[str, ...], base_id: str) -> str:
    _assert_free_space(b.ROOT)
    context = Path(tempfile.mkdtemp(prefix="build-" + role + "-", dir=b.ROOT))
    for relative in inputs:
        source = b.ROOT / relative
        target = context / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)
    file = context / "Dockerfile"
    file.write_text(
        "FROM " + base_id + "\n"
        + 'LABEL io.webcompiler.release.owner="' + str(b.ROOT) + '" '
        + 'org.opencontainers.image.revision="' + b.SHA + '"\n'
        + dockerfile,
        encoding="utf-8",
    )
    tag = "webcompiler-migration-" + role + ":" + b.SHA
    state = json.loads(b.STATE.read_text())
    if tag not in state["tags"]:
        state["tags"].append(tag)
        b.save(state)
    output = b.o.run(
        "docker", "build", "--pull=false", "--network", "none",
        "--memory", "2g", "--memory-swap", "2g", "--cpu-quota", "100000",
        "--cpu-period", "100000", "-t", tag, "-f", str(file), str(context),
        env={**b.o.BASEENV, "DOCKER_BUILDKIT": "0"}, timeout=360,
    )
    (b.ROOT / (role + "-build.log")).write_bytes(output)
    return b.o.inspect(tag)["Id"]


def build() -> None:
    state = json.loads(b.STATE.read_text())
    assert state["phase"] == "building"
    state["images"]["backend"] = _build(
        "backend",
        "COPY backend/app /app/app\n",
        ("backend/app",),
        state["bases"]["backend"],
    )
    b.save(state)
    source_config = (b.ROOT / "frontend/nginx.conf").read_text(encoding="utf-8")
    assert source_config.count("server backend:8000 resolve;") == 1
    production_config = source_config.replace(
        "server backend:8000 resolve;", "server api-proxy:8080 resolve;"
    )
    (b.ROOT / "frontend-production.conf").write_text(
        production_config, encoding="utf-8", newline="\n"
    )
    state["images"]["frontend"] = _build(
        "frontend",
        "COPY frontend-production.conf /etc/nginx/conf.d/default.conf\n"
        "COPY frontend-dist /usr/share/nginx/html\n",
        ("frontend-production.conf", "frontend-dist"),
        state["bases"]["frontend"],
    )
    b.o.run(
        "docker", "run", "--rm", "--pull", "never", "--network", "none",
        "--entrypoint", "nginx", state["images"]["frontend"], "-t", timeout=30,
    )
    state["phase"] = "built"
    b.save(state)
    print(json.dumps({"phase": "built", "sha": b.SHA, "sandbox": "reused" if state.get("sandbox_reused", True) else "approved-runtime-update"}), flush=True)


def _columns(container: str) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for table in BUSINESS_TABLES:
        rows = b.o.sql(
            container,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='" + table + "' ORDER BY ordinal_position",
        ).splitlines()
        assert rows and all(re.fullmatch(r"[a-z_][a-z0-9_]*", value) for value in rows)
        result[table] = tuple(rows)
    return result


def _fingerprints(container: str, columns: dict[str, tuple[str, ...]]) -> dict[str, str]:
    values = {}
    for table, names in columns.items():
        selection = ",".join('"' + name + '"' for name in names)
        values[table] = b.o.sql(
            container,
            "SELECT count(*)::text || ':' || md5(coalesce(string_agg(j,E'\\n' ORDER BY j),'')) "
            "FROM (SELECT row_to_json(t)::text j FROM (SELECT " + selection + " FROM " + table + ") t) q",
        )
    return values


def _preserved_columns(columns: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    return {
        table: tuple(
            name for name in names if name not in MIGRATED_BUSINESS_COLUMNS.get(table, set())
        )
        for table, names in columns.items()
    }


def _problem_policy_snapshot(container: str) -> dict[str, dict]:
    rows = b.o.sql(
        container,
        "SELECT json_build_object('id',id,'policy',judge_policy,'review',publication_review_required)::text "
        "FROM problems ORDER BY id",
    ).splitlines()
    return {row["id"]: row for row in (json.loads(value) for value in rows)}


def _assert_compatibility_policy_migration(before: dict[str, dict], after: dict[str, dict]) -> None:
    assert set(after) == set(before)
    migrated = 0
    already_compatible = 0
    for problem_id, old in before.items():
        new = after[problem_id]
        eligible = (
            problem_id not in {"__notice__", "__free__"}
            and old["policy"] is None
            and old["review"] is None
        )
        if eligible:
            assert new["policy"] == {"kind": "compatibility-v1"}
            migrated += 1
        else:
            assert new["policy"] == old["policy"]
            if (
                problem_id not in {"__notice__", "__free__"}
                and old["policy"] == {"kind": "compatibility-v1"}
                and old["review"] is None
            ):
                already_compatible += 1
        assert new["review"] == old["review"]
    assert migrated > 0 or already_compatible > 0, (
        "Production rehearsal must exercise or verify the compatibility migration"
    )


def _dump(path: Path, postgres_id: str) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        result = subprocess.run(
            ["docker", "exec", postgres_id, "pg_dump", "-U", "compiler", "-d", "compiler", "-Fc"],
            stdout=stream,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    assert result.returncode == 0 and path.stat().st_size > 0, "Backup failed"
    b.o.run("docker", "exec", "-i", postgres_id, "pg_restore", "--list", data=path.read_bytes(), timeout=60)


def _rehearse_public_quality_cleanup(container: str) -> None:
    """Apply the exact cleanup only to the disposable restored rehearsal DB."""
    script = b.ROOT / "scripts/public_quality_v27.sql"
    assert script.is_file() and script.stat().st_size <= 64 * 1024
    b.o.run(
        "docker", "exec", "-i", container,
        "psql", "-v", "ON_ERROR_STOP=1", "-U", "compiler", "-d", "compiler",
        data=script.read_bytes(), timeout=60,
    )
    assert b.o.sql(
        container,
        "SELECT "
        "(SELECT count(*) FROM users WHERE public_profile_enabled=false AND username ~ '^(debug_|report_|test123$|testtok_|ui_)')"
        "||':'||(SELECT count(*) FROM contests WHERE published=false AND id IN "
        "('436e5826-b411-4ecb-a960-d1b3a54b2db9','d1eef831-4729-4dbb-83d3-8c1178a722fd'))"
        "||':'||(SELECT count(*) FROM problems WHERE deleted_at IS NOT NULL AND id IN "
        "('5aec67d0-ce85-4378-b299-d24ed3cc8fd2','da83f02e-639f-4c0c-8bf2-00b813052dda',"
        "'9ec2f010-c970-487f-ba82-dee241db8d05','2172fd0d-bf11-485f-9a95-61f4a1ca3a83'))"
        "||':'||(SELECT count(*) FROM comments WHERE id='system-community-guide-v1' AND content LIKE '%챌린지%')",
    ) == "7:2:4:0"


def _write_env(path: Path, environment: dict[str, str]) -> None:
    assert all("\n" not in str(value) and "\r" not in str(value) for value in environment.values())
    assert all(re.fullmatch(r"[A-Z][A-Z0-9_]*", key) for key in environment)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        for key, value in sorted(environment.items()):
            stream.write(key + "=" + str(value) + "\n")


def _container_environment(container: str) -> dict[str, str]:
    entries = b.o.inspect(container)["Config"]["Env"]
    assert isinstance(entries, list)
    environment: dict[str, str] = {}
    for entry in entries:
        key, separator, value = entry.partition("=")
        assert separator and re.fullmatch(r"[A-Z][A-Z0-9_]*", key)
        assert key not in environment
        environment[key] = value
    return environment


def _run_initialize(image: str, network: str, env_file: Path) -> None:
    b.o.run(
        "docker", "run", "--rm", "--pull", "never", "--network", network,
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--memory", "512m", "--memory-swap", "512m", "--cpus", "0.5", "--pids-limit", "128",
        "--tmpfs", "/tmp:size=64m,mode=1777,noexec,nosuid", "--env-file", str(env_file),
        image, "python", "-m", "app.initialize", "--skip-bootstrap", timeout=180,
    )


def _wait_for_stable_postgres(container: str, timeout_seconds: int = 90) -> None:
    """Wait past the entrypoint's temporary init server and final restart."""
    deadline = time.monotonic() + timeout_seconds
    consecutive_ready = 0
    while True:
        result = subprocess.run(
            ["docker", "exec", container, "pg_isready", "-U", "compiler", "-d", "compiler"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            consecutive_ready += 1
            if consecutive_ready >= 3:
                return
        else:
            consecutive_ready = 0
        assert time.monotonic() < deadline, "Rehearsal PostgreSQL did not become stably ready"
        time.sleep(1)


def rehearse(state: dict) -> None:
    dump = b.ROOT / "rehearsal-source.dump"
    _dump(dump, state["postgres_id"])
    columns = _preserved_columns(_columns("webcompiler-postgres"))
    suffix = uuid4().hex[:12]
    network = "webcompiler-migration-" + suffix
    postgres = "webcompiler-migration-postgres-" + suffix
    password = secrets.token_urlsafe(24)
    env_file = b.ROOT / "rehearsal.env"
    backend_container = b.PROJECT + "-backend-1"
    assert b.o.inspect(backend_container)["Id"] == state["old_ids"]["backend-1"]
    environment = _container_environment(backend_container)
    environment.update(
        DATABASE_URL=f"postgresql+psycopg2://compiler:{password}@{postgres}:5432/compiler",
        ENVIRONMENT="production",
        DEPLOYMENT_SHA=b.SHA,
        RUNTIME_INSTANCE_ID=uuid4().hex,
        AUTO_INITIALIZE_DB="false",
        EMBEDDED_EXECUTION_WORKER="false",
    )
    _write_env(env_file, environment)
    created_network = created_postgres = False
    try:
        b.o.run("docker", "network", "create", "--internal", "--label", "io.webcompiler.release.owner=" + str(b.ROOT), network)
        created_network = True
        b.o.run(
            "docker", "run", "-d", "--pull", "never", "--name", postgres, "--network", network,
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "70:70",
            "--memory", "512m", "--memory-swap", "512m", "--cpus", "0.5", "--pids-limit", "128",
            "--log-driver", "none",
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,nodev,size=768m,uid=70,gid=70,mode=0700",
            "--tmpfs", "/var/run/postgresql:rw,noexec,nosuid,nodev,size=16m,uid=70,gid=70,mode=0700",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
            "--label", "io.webcompiler.release.owner=" + str(b.ROOT),
            "-e", "POSTGRES_DB=compiler", "-e", "POSTGRES_USER=compiler", "-e", "POSTGRES_PASSWORD=" + password,
            b.o.inspect("webcompiler-postgres")["Config"]["Image"],
        )
        created_postgres = True
        _wait_for_stable_postgres(postgres)
        b.o.run("docker", "exec", "-i", postgres, "pg_restore", "-U", "compiler", "-d", "compiler", "--no-owner", data=dump.read_bytes(), timeout=180)
        # Production remains live while the rehearsal dump is restored, so its
        # rows may legitimately change after pg_dump's snapshot.  The restored
        # snapshot is the stable baseline for proving that both old and new
        # initializers preserve every column except the explicitly reviewed
        # legacy judge-policy migration, which is verified row by row below.
        before = _fingerprints(postgres, columns)
        policies_before = _problem_policy_snapshot(postgres)
        _run_initialize(state["images"]["backend"], network, env_file)
        _run_initialize(state["images"]["backend"], network, env_file)
        assert _fingerprints(postgres, columns) == before
        _assert_compatibility_policy_migration(
            policies_before, _problem_policy_snapshot(postgres)
        )
        old_env = b.ROOT / "rehearsal-old.env"
        old_environment = dict(environment)
        old_environment["DEPLOYMENT_SHA"] = state["old"]["source_sha"]
        _write_env(old_env, old_environment)
        _run_initialize(state["bases"]["backend"], network, old_env)
        assert b.o.sql(postgres, "SELECT count(*) FROM schema_migrations WHERE version='" + state["old_marker"] + "'") == "1"
        _run_initialize(state["images"]["backend"], network, env_file)
        assert b.o.sql(postgres, "SELECT count(*) FROM schema_migrations WHERE version='" + state["new_marker"] + "'") == "1"
        assert _fingerprints(postgres, columns) == before
        _rehearse_public_quality_cleanup(postgres)
        state["rehearsal"] = {"passed": True, "business_fingerprints": before}
        b.save(state)
    finally:
        env_file.unlink(missing_ok=True)
        (b.ROOT / "rehearsal-old.env").unlink(missing_ok=True)
        cleanup_errors = []
        if created_postgres:
            result = subprocess.run(
                ["docker", "rm", "-f", postgres],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode:
                cleanup_errors.append("container")
        if created_network:
            result = subprocess.run(
                ["docker", "network", "rm", network],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode:
                cleanup_errors.append("network")
        if cleanup_errors:
            failed = json.loads(b.STATE.read_text())
            failed["phase"] = "failed"
            failed["prelive_cleanup_failed"] = cleanup_errors
            b.save(failed)
            raise RuntimeError("Rehearsal cleanup requires recorded operator recovery")
    dump.unlink()
    directory = os.open(b.ROOT, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    _assert_free_space(b.ROOT)


def _compose_initialize(environment: dict[str, str]) -> None:
    b.pc(
        environment,
        "run", "--rm", "--pull", "never", "--no-deps", "initialize",
        "python", "-m", "app.initialize", "--skip-bootstrap",
    )


def _replace_once(value: str, needle: str, replacement: str) -> str:
    assert value.count(needle) == 1, "Unexpected edge proxy template"
    return value.replace(needle, replacement)


def candidate_edge_configs(current: dict[str, str]) -> dict[str, str]:
    if "limit_conn_zone " in current["backend"] or "limit_conn_zone " in current["frontend"]:
        expected_counts = {
            "backend": {
                "limit_conn_zone ": 2,
                "client_max_body_size 16m;": 1,
                "client_max_body_size 512k;": 1,
                "proxy_request_buffering off;": 1,
                "limit_conn judge_upload_ip 2;": 1,
                "limit_conn judge_upload_total 8;": 1,
                "location ^~ /api/v1/admin/judge-test-data/ {": 1,
            },
            "frontend": {
                "limit_conn_zone ": 2,
                "client_max_body_size 16m;": 2,
                "client_max_body_size 512k;": 2,
                "proxy_request_buffering off;": 2,
                "limit_conn judge_upload_ip 2;": 2,
                "limit_conn judge_upload_total 8;": 2,
                "location ^~ /webcompiler/api/v1/admin/judge-test-data/ {": 1,
                "location ^~ /api/v1/admin/judge-test-data/ {": 1,
            },
        }
        for role, patterns in expected_counts.items():
            for pattern, expected in patterns.items():
                assert current[role].count(pattern) == expected, (
                    "Existing edge hardening differs from the reviewed contract: " + role
                )
        assert current["backend"].count(
            "proxy_pass http://127.0.0.1:18003/api/v1/admin/judge-test-data/;"
        ) == 1
        assert current["frontend"].count(
            "proxy_pass http://127.0.0.1:18003/api/v1/admin/judge-test-data/;"
        ) == 2
        return dict(current)

    zones = (
        "limit_conn_zone $binary_remote_addr zone=judge_upload_ip:64k;\n"
        "limit_conn_zone $server_name zone=judge_upload_total:32k;\n\n"
    )
    assert "limit_conn_zone " not in current["backend"]
    assert "limit_conn_zone " not in current["frontend"]
    backend_upload = """    location ^~ /api/v1/admin/judge-test-data/ {
        client_max_body_size 16m;
        limit_conn judge_upload_ip 2;
        limit_conn judge_upload_total 8;
        limit_conn_status 429;
        client_body_timeout 10s;
        proxy_request_buffering off;
        proxy_next_upstream off;
        proxy_pass http://127.0.0.1:18003/api/v1/admin/judge-test-data/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    }

"""
    frontend_upload = """    location ^~ /webcompiler/api/v1/admin/judge-test-data/ {
        client_max_body_size 16m;
        limit_conn judge_upload_ip 2;
        limit_conn judge_upload_total 8;
        limit_conn_status 429;
        client_body_timeout 10s;
        proxy_request_buffering off;
        proxy_next_upstream off;
        proxy_pass http://127.0.0.1:18003/api/v1/admin/judge-test-data/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    }

"""
    backend = _replace_once(
        current["backend"],
        "    location /api/ {\n",
        backend_upload + "    location /api/ {\n        client_max_body_size 512k;\n",
    )
    frontend = _replace_once(
        current["frontend"],
        "    location /webcompiler/api/ {\n",
        frontend_upload + "    location /webcompiler/api/ {\n        client_max_body_size 512k;\n",
    )
    frontend = _replace_once(
        frontend,
        "    location /api/ {\n",
        backend_upload + "    location /api/ {\n        client_max_body_size 512k;\n",
    )
    return {"backend": zones + backend, "frontend": zones + frontend}


def _stop_failed_candidate(state: dict) -> None:
    """Stop a failed candidate without requiring its failed process to exit zero."""
    environment = state.get("env") or state["old"]["env"]
    b.pc(environment, "stop", "--timeout", "150", "backend")
    for role in ("backend-1", "backend-2"):
        row = b.o.inspect(b.PROJECT + "-" + role)["State"]
        assert row.get("Running") is False
        assert row.get("OOMKilled") is False
        assert row.get("Dead", False) is False
        assert type(row.get("ExitCode")) is int

    deadline = time.monotonic() + 120
    while b.unsettled():
        assert time.monotonic() < deadline, "Accepted candidate jobs have not drained"
        time.sleep(1)

    b.pc(environment, "stop", "--timeout", "150", "worker", "frontend")
    for role in ("worker-1", "frontend-1"):
        row = b.o.inspect(b.PROJECT + "-" + role)["State"]
        assert row.get("Running") is False
        assert row.get("OOMKilled") is False
        assert row.get("Dead", False) is False
        assert type(row.get("ExitCode")) is int
    assert b.unsettled() == 0
    assert not b.o.run(
        "docker", "ps", "-q", "--filter", "label=webcompiler.pool=" + b.PROJECT + "-production"
    ).strip()


def rollback() -> None:
    state = json.loads(b.STATE.read_text())
    assert state["phase"] == "failed"
    _stop_failed_candidate(state)
    old_environment = dict(state["old"]["env"])
    old_environment["BASIC_LB_RUNTIME_ID"] = uuid4().hex
    _compose_initialize(old_environment)
    b.pc(old_environment, "up", "--no-build", "--pull", "never", "--no-deps", "-d", "backend", "worker", "frontend")
    b.ready(old_environment)
    b.edge(state, state["edge_configs"])
    old = state["old"]
    old["env"] = old_environment
    b.o.save(old)
    state["phase"] = "rolled-back"
    b.save(state)
    print("Previous application images and runtime marker restored; live database dump was not overwritten.", flush=True)


def rollout() -> None:
    state = json.loads(b.STATE.read_text())
    assert state["phase"] == "built"
    rehearse(state)
    state = json.loads(b.STATE.read_text())
    assert state.get("rehearsal", {}).get("passed") is True
    current = json.loads(b.o.STATE.read_text())
    assert current["source_sha"] == state["old"]["source_sha"] and current["phase"] == "deployed"
    for role, container_id in state["old_ids"].items():
        name = b.PROJECT + "-" + role + ("" if role.startswith("backend-") else "-1")
        assert b.o.inspect(name)["Id"] == container_id
    assert b.o.inspect("webcompiler-postgres")["Id"] == state["postgres_id"]
    state["edge_ids"] = {role: b.o.inspect("webcompiler-edge-" + role)["Id"] for role in ("backend", "frontend")}
    state["edge_configs"] = {role: (b.PROD / ".deploy" / (role + "-edge.conf")).read_text() for role in state["edge_ids"]}
    assert "127.0.0.1:18003" in state["edge_configs"]["backend"]
    assert "127.0.0.1:15176" in state["edge_configs"]["frontend"]
    state["candidate_edge_configs"] = candidate_edge_configs(state["edge_configs"])
    _assert_free_space(b.ROOT)
    state["phase"] = "maintenance"
    b.save(state)
    maintenance = {
        role: "server { listen 127.0.0.1:" + port + "; add_header Retry-After 120 always; location / { return 503; } }\n"
        for role, port in (("backend", "18000"), ("frontend", "15173"))
    }
    touched = False
    try:
        b.edge(state, maintenance)
        touched = True
        b.stop_current()
        columns = _preserved_columns(_columns("webcompiler-postgres"))
        state["fingerprints"] = _fingerprints("webcompiler-postgres", columns)
        state["columns"] = {key: list(value) for key, value in columns.items()}
        policies_before = _problem_policy_snapshot("webcompiler-postgres")
        b.save(state)
        _dump(b.ROOT / "pre-update-production.dump", state["postgres_id"])
        environment = dict(state["old"]["env"])
        environment.update(
            DEPLOY_SHA=b.SHA,
            BASIC_LB_RUNTIME_ID=uuid4().hex,
            WEBCOMPILER_BACKEND_IMAGE=state["images"]["backend"],
            BASIC_LB_FRONTEND_IMAGE=state["images"]["frontend"],
            SANDBOX_IMAGE=state["images"]["sandbox"],
        )
        state["env"] = environment
        state["phase"] = "migrating"
        b.save(state)
        _compose_initialize(environment)
        _compose_initialize(environment)
        assert _fingerprints("webcompiler-postgres", columns) == state["fingerprints"]
        _assert_compatibility_policy_migration(
            policies_before, _problem_policy_snapshot("webcompiler-postgres")
        )
        state["phase"] = "starting"
        b.save(state)
        b.pc(environment, "up", "--no-build", "--pull", "never", "--no-deps", "-d", "backend", "worker", "frontend")
        b.ready(environment)
        assert _fingerprints("webcompiler-postgres", columns) == state["fingerprints"]
        for role in ("redis", "pgbouncer", "api-proxy"):
            assert b.o.inspect(b.PROJECT + "-" + role + "-1")["Id"] == state["old_ids"][role]
        assert b.o.inspect("webcompiler-postgres")["Id"] == state["postgres_id"]
        b.edge(state, state["candidate_edge_configs"])
        current.update(
            env=environment,
            source_sha=b.SHA,
            backend_id=state["images"]["backend"],
            frontend_id=state["images"]["frontend"],
            functional_release_root=str(b.ROOT),
            functional_previous_sha=state["old"]["source_sha"],
        )
        b.o.save(current)
        state["phase"] = "deployed"
        b.save(state)
        print(json.dumps({"phase": "deployed", "sha": b.SHA, "database_migrated": True, "sandbox": "reused"}), flush=True)
    except BaseException:
        state = json.loads(b.STATE.read_text())
        state["phase"] = "failed"
        b.save(state)
        print("Migration release failed; maintenance retained until recorded rollback completes.", flush=True)
        if touched:
            rollback()
        else:
            b.edge(state, state["edge_configs"])
        raise


def main() -> None:
    import fcntl

    assert os.environ.get("WEBCOMPILER_MIGRATION_RELEASE") == "approved"
    assert os.environ.get("WEBCOMPILER_DEPLOY_LOCK_HELD") == "1"
    project_root = Path(os.environ["PROJECT_ROOT"]).resolve()
    assert Path(os.readlink("/proc/self/fd/9")) == project_root / ".deploy/deploy.lock"
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
    b.configure(project_root, os.environ["DEPLOY_SHA"])
    assert b.o.run("git", "-C", str(b.PROD), "rev-parse", "HEAD").decode().strip() == b.SHA
    try:
        prepare()
        rollout()
    except BaseException:
        if b.STATE.exists():
            state = json.loads(b.STATE.read_text())
            if state.get("phase") in ("building", "built"):
                state["phase"] = "rolled-back"
                state["prelive_failure"] = True
                b.save(state)
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Migration release stopped: " + type(exc).__name__ + ". Inspect the private release journal.", file=os.sys.stderr)
        raise SystemExit(1)
