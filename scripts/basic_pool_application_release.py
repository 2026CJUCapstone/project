"""Guarded application-only release for the adopted basic production pool.

This path is intentionally narrower than a migration or runtime release.  It
requires the database, dependency, topology, launcher, and active sandbox
contracts to be unchanged.  A reviewed, non-deployed sandbox build gate may
exist in the source tree, but the operating sandbox image is reused exactly.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4


def _load(name: str):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Deployment helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b = _load("basic_pool_deploy")
m = _load("basic_pool_migration_release")
r = _load("runtime_secrets")
runtime = _load("basic_pool_runtime_release")
dependencies = _load("basic_pool_dependency_release")
# The migration helper loads its own copy of the base module.  Rebind it so
# every reused helper observes this release's configured ROOT/STATE/SHA.
m.b = b

APPLICATION_CONTRACTS = (
    "backend/app/models/database.py",
    "backend/app/core/database.py",
    "backend/app/core/bootstrap.py",
    "backend/app/core/config.py",
    "backend/app/initialize.py",
    "backend/Dockerfile",
    "backend/requirements.lock",
    "frontend/Dockerfile",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/nginx.conf",
    "docker-compose.yml",
    "docker-compose.lb.yml",
    "scripts/basic-lb.compose.yml",
    "scripts/basic-lb.production.compose.yml",
    "runtime/sandbox/run.sh",
    "runtime/bpp-ref.txt",
    "runtime/docker/Dockerfile",
)


def _runtime_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in (root / "runtime").rglob("*")
        if path.is_file()
    }


def check_application_contracts(previous: Path, candidate: Path, *, runtime_approval=None, dependency_approval=None) -> None:
    assert not (runtime_approval and dependency_approval), "Separate runtime and dependency approvals required"
    if dependency_approval:
        dependencies.validate_changes(previous, candidate)
    for relative in APPLICATION_CONTRACTS:
        if runtime_approval and relative in runtime.ALLOWED_CHANGES:
            continue
        if dependency_approval and relative in dependencies.ALLOWED_CHANGES:
            continue
        assert b.contract_bytes(previous / relative) == b.contract_bytes(candidate / relative), (
            "Application-only release contract changed: " + relative
        )
    assert m._marker(previous) == m._marker(candidate), "Schema marker changed"

    old_modules = {
        path.relative_to(previous / "backend/app").as_posix()
        for path in (previous / "backend/app").rglob("*.py")
    }
    new_modules = {
        path.relative_to(candidate / "backend/app").as_posix()
        for path in (candidate / "backend/app").rglob("*.py")
    }
    assert old_modules <= new_modules, "Removed backend module requires a clean image build"

    old_runtime = _runtime_files(previous)
    new_runtime = _runtime_files(candidate)
    assert (new_runtime == old_runtime if not runtime_approval else
            not old_runtime - new_runtime and new_runtime - old_runtime <= runtime.ALLOWED_CHANGES), "Runtime file-set change is not application-only"
    for relative in old_runtime:
        if runtime_approval and relative in runtime.ALLOWED_CHANGES:
            continue
        assert b.contract_bytes(previous / relative) == b.contract_bytes(candidate / relative), (
            "Active runtime contract changed: " + relative
        )
    for path in (candidate / "runtime").rglob("*.sh"):
        assert b"\r" not in path.read_bytes(), "Runtime shell files must use LF"


def prepare() -> None:
    assert not b.STATE.exists()
    m._assert_free_space(b.ROOT)
    old = json.loads(b.o.STATE.read_text())
    assert old["phase"] == "deployed"
    previous_sha = old["source_sha"]
    assert isinstance(previous_sha,str) and re.fullmatch(r"[0-9a-f]{40}",previous_sha)
    b.o.run("git","-C",str(b.PROD),"merge-base","--is-ancestor",previous_sha,b.SHA,timeout=30)
    previous = Path(old["functional_release_root"])
    assert previous.is_absolute() and previous.resolve() == previous and previous.is_dir()

    source = b.o.run("git", "-C", str(b.PROD), "archive", "--format=tar", b.SHA, timeout=60)
    (b.ROOT / "source.tar").write_bytes(source)
    b.extract(b.ROOT / "source.tar")
    runtime_approval = runtime.load_approval(b.PROD, previous, b.ROOT, previous_sha, b.SHA,
                                             old["env"]["SANDBOX_IMAGE"], b.o.inspect)
    dependency_approval = dependencies.load_approval(
        b.PROD, previous, b.ROOT, previous_sha, b.SHA,
        {"backend": old["backend_id"], "frontend": old["frontend_id"]}, b.o.inspect,
    )
    check_application_contracts(previous, b.ROOT, runtime_approval=runtime_approval,
                                dependency_approval=dependency_approval)
    # The adopted pool does not source the checkout's env files. Require a
    # complete private SMTP configuration before an application release, then
    # load it again immediately before candidate startup.
    runtime_values = r.load(b.PROD / ".deploy/runtime-secrets.env")
    r.mail_environment(runtime_values,required=True)

    deploy_dir = b.PROD / ".deploy"
    assert deploy_dir.resolve(strict=True) == deploy_dir
    bundle = Path(os.environ["WEBCOMPILER_FRONTEND_ARCHIVE"])
    assert bundle.is_absolute() and bundle.resolve(strict=True) == bundle
    assert bundle.parent == deploy_dir and bundle.is_file() and not bundle.is_symlink()
    assert bundle.stat().st_size <= 32 * 1024**2
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == os.environ["WEBCOMPILER_FRONTEND_SHA256"]
    shutil.copyfile(bundle, b.ROOT / "frontend-tested.tar.gz")
    b.extract(b.ROOT / "frontend-tested.tar.gz", "frontend-dist")
    marker = json.loads((b.ROOT / "frontend-dist/.well-known/webcompiler-release.json").read_text())
    assert marker == {"deployment_sha": b.SHA}
    assert (b.ROOT / "frontend-dist/index.html").is_file()

    bases = {
        "backend": old["backend_id"],
        "frontend": old["frontend_id"],
        "sandbox": old["env"]["SANDBOX_IMAGE"],
    }
    assert all(b.o.inspect(value)["Id"] == value for value in bases.values())
    ids = {
        role: b.o.inspect(b.PROJECT + "-" + role + "-1")["Id"]
        for role in ("worker", "frontend", "redis", "pgbouncer", "api-proxy")
    }
    ids.update({
        f"backend-{number}": b.o.inspect(b.PROJECT + f"-backend-{number}")["Id"]
        for number in (1, 2)
    })
    state = {
        "phase": "building",
        "sha": b.SHA,
        "old": old,
        "old_ids": ids,
        "bases": bases,
        "images": {"sandbox": runtime_approval["candidate_image"] if runtime_approval else bases["sandbox"]},
        "sandbox_reused": not bool(runtime_approval),
        "runtime_approval": runtime_approval,
        "dependency_approval": dependency_approval,
        "postgres_id": b.o.inspect("webcompiler-postgres")["Id"],
        "tags": [],
    }
    b.save(state)
    b.atomic_json(b.PROD / ".deploy/basic-pool-pending.json", {"root": str(b.ROOT)})
    if dependency_approval:
        state["images"].update(dependency_approval["images"])
        b.save(state)
        dependencies.verify_candidate(state, b.ROOT, b.o.run)
        state["phase"] = "built"
        b.save(state)
    else:
        m.build()


def _candidate_environment(state: dict) -> dict[str,str]:
    backend = b.PROJECT + "-backend-1"
    assert b.o.inspect(backend)["Id"] == state["old_ids"]["backend-1"]
    environment = m._container_environment(backend)
    assert environment.get("ENVIRONMENT") == "production"
    environment.update(
        ENVIRONMENT="production",
        DEPLOYMENT_SHA=b.SHA,
        RUNTIME_INSTANCE_ID=uuid4().hex,
        EMBEDDED_EXECUTION_WORKER="false",
    )
    environment.update(r.mail_environment(
        r.load(b.PROD / ".deploy/runtime-secrets.env"),required=True,
    ))
    return environment


def preflight_candidate_configuration(state: dict) -> None:
    """Validate production secrets and runtime identity without network access."""
    environment = _candidate_environment(state)
    env_file = b.ROOT / "candidate-preflight.env"
    m._write_env(env_file, environment)
    try:
        b.o.run(
            "docker", "run", "--rm", "--pull", "never", "--network", "none",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--memory", "256m", "--memory-swap", "256m", "--cpus", "0.5",
            "--pids-limit", "64", "--user", "10001:10001",
            "--tmpfs", "/tmp:size=16m,mode=1777,noexec,nosuid",
            "--env-file", str(env_file), state["images"]["backend"],
            "python", "-c",
            "from app.services.auth import validate_runtime_security; validate_runtime_security()",
            timeout=60,
        )
    finally:
        env_file.unlink(missing_ok=True)


def _smtp_preflight_network(state: dict) -> str:
    """Use only the adopted pool's verified bridge, never Docker's default."""
    backend = b.o.inspect(b.PROJECT + "-backend-1")
    assert backend["Id"] == state["old_ids"]["backend-1"]
    expected = b.PROJECT + "-net"
    networks = backend.get("NetworkSettings", {}).get("Networks", {})
    assert set(networks) == {expected}, "Unexpected operating API network"
    assert backend.get("HostConfig", {}).get("NetworkMode") == expected
    network = b.o.inspect(expected)
    assert network["Id"] == networks[expected]["NetworkID"]
    assert network["Name"] == expected and network["Driver"] == "bridge"
    assert network.get("Internal") is False and not network.get("Ingress", False)
    return expected


def preflight_candidate_smtp(state: dict) -> None:
    """Prove outbound TLS and authentication before entering maintenance."""
    environment = _candidate_environment(state)
    network = _smtp_preflight_network(state)
    env_file = b.ROOT / "candidate-smtp-preflight.env"
    m._write_env(env_file,environment)
    try:
        b.o.run(
            "docker","run","--rm","--pull","never","--network",network,
            "--read-only","--cap-drop","ALL","--security-opt","no-new-privileges",
            "--memory","256m","--memory-swap","256m","--cpus","0.5",
            "--pids-limit","64","--user","10001:10001",
            "--tmpfs","/tmp:size=16m,mode=1777,noexec,nosuid",
            "--env-file",str(env_file),state["images"]["backend"],
            "python","-c",
            "from app.services.email import verify_smtp_connection; verify_smtp_connection()",
            timeout=30,
        )
    finally:
        env_file.unlink(missing_ok=True)


def schema_markers(container: str) -> tuple[str, ...]:
    rows = b.o.sql(
        container,
        "SELECT version FROM schema_migrations ORDER BY version",
    ).splitlines()
    assert rows and all(row and len(row) <= 160 for row in rows)
    return tuple(rows)


def schema_inventory(container: str) -> str:
    value = b.o.sql(
        container,
        "SELECT md5(string_agg(value,E'\\n' ORDER BY value)) FROM ("
        "SELECT 'relation|'||n.nspname||'|'||c.relname||'|'||c.relkind::text value "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m') UNION ALL "
        "SELECT 'column|'||table_name||'|'||column_name||'|'||data_type||'|'||udt_name||'|'||"
        "is_nullable||'|'||coalesce(column_default,'') FROM information_schema.columns "
        "WHERE table_schema='public' UNION ALL "
        "SELECT 'constraint|'||conrelid::regclass::text||'|'||conname||'|'||contype::text||'|'||"
        "pg_get_constraintdef(oid,true) FROM pg_constraint "
        "WHERE connamespace='public'::regnamespace UNION ALL "
        "SELECT 'index|'||tablename||'|'||indexname||'|'||indexdef FROM pg_indexes "
        "WHERE schemaname='public' UNION ALL "
        "SELECT 'trigger|'||event_object_table||'|'||trigger_name||'|'||action_timing||'|'||"
        "event_manipulation||'|'||action_statement FROM information_schema.triggers "
        "WHERE trigger_schema='public') inventory",
    )
    assert re.fullmatch(r"[0-9a-f]{32}", value)
    return value


def candidate_readonly_smoke() -> None:
    spec = importlib.util.spec_from_file_location(
        "candidate_readonly_smoke", b.ROOT / "scripts/e2e_stack_test.py"
    )
    assert spec is not None and spec.loader is not None
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    app.FRONTEND_BASE_URL = "http://127.0.0.1:15176"
    for path in (
        "/api/v1/problems/?page=1&pageSize=1",
        "/api/v1/contests",
        "/api/v1/problems/leaderboard?limit=1",
    ):
        status, _value = app.request_json(app.FRONTEND_BASE_URL + path)
        assert status == 200, "Pre-public read-only smoke failed: " + path


def handle_rollout_failure(*, touched: bool) -> None:
    state = json.loads(b.STATE.read_text())
    state["phase"] = "failed"
    b.save(state)
    if touched and state.get("candidate_start_attempted") and not state.get("integrity_verified"):
        print(
            "Application release failed after candidate start; maintenance is retained for manual database review.",
            flush=True,
        )
        try:
            b.stop_current()
            state = json.loads(b.STATE.read_text())
            state["candidate_stopped_after_failed_integrity"] = True
            b.save(state)
        except BaseException:
            state = json.loads(b.STATE.read_text())
            state["candidate_stop_failed"] = True
            b.save(state)
        return
    print("Application release failed; recorded application rollback is starting.", flush=True)
    if touched:
        b.rollback()
    else:
        b.edge(state, state["edge_configs"])
        state["phase"] = "rolled-back"
        b.save(state)


def rollout() -> None:
    state = json.loads(b.STATE.read_text())
    assert state["phase"] == "built"
    if state.get("dependency_approval"):
        # Recheck payloads immediately before maintenance; the approval does
        # not relax the existing drain/backup/integrity/rollback procedure.
        dependencies.verify_candidate(state, b.ROOT, b.o.run)
    preflight_candidate_configuration(state)
    preflight_candidate_smtp(state)
    if not state["sandbox_reused"]:
        runtime.verify_candidate(state, b.o.run)
    current = json.loads(b.o.STATE.read_text())
    assert current["source_sha"] == state["old"]["source_sha"] and current["phase"] == "deployed"
    for role, container_id in state["old_ids"].items():
        name = b.PROJECT + "-" + role + ("" if role.startswith("backend-") else "-1")
        assert b.o.inspect(name)["Id"] == container_id
    assert b.o.inspect("webcompiler-postgres")["Id"] == state["postgres_id"]

    state["edge_ids"] = {
        role: b.o.inspect("webcompiler-edge-" + role)["Id"]
        for role in ("backend", "frontend")
    }
    state["edge_configs"] = {
        role: (b.PROD / ".deploy" / (role + "-edge.conf")).read_text()
        for role in state["edge_ids"]
    }
    assert "127.0.0.1:18003" in state["edge_configs"]["backend"]
    assert "127.0.0.1:15176" in state["edge_configs"]["frontend"]
    state["phase"] = "maintenance"
    b.save(state)
    maintenance = {
        role: "server { listen 127.0.0.1:" + port
        + "; add_header Retry-After 120 always; location / { return 503; } }\n"
        for role, port in (("backend", "18000"), ("frontend", "15173"))
    }
    touched = False
    try:
        b.edge(state, maintenance)
        touched = True
        b.stop_current()
        columns = m._columns("webcompiler-postgres")
        state["fingerprints"] = m._fingerprints("webcompiler-postgres", columns)
        state["columns"] = {key: list(value) for key, value in columns.items()}
        state["schema_markers"] = list(schema_markers("webcompiler-postgres"))
        state["schema_inventory"] = schema_inventory("webcompiler-postgres")
        b.save(state)
        m._dump(b.ROOT / "pre-update-production.dump", state["postgres_id"])

        environment = dict(state["old"]["env"])
        environment.update(r.mail_environment(
            r.load(b.PROD / ".deploy/runtime-secrets.env"),required=True,
        ))
        environment.update(
            DEPLOY_SHA=b.SHA,
            BASIC_LB_RUNTIME_ID=uuid4().hex,
            WEBCOMPILER_BACKEND_IMAGE=state["images"]["backend"],
            BASIC_LB_FRONTEND_IMAGE=state["images"]["frontend"],
            SANDBOX_IMAGE=state["images"]["sandbox"],
        )
        state["env"] = environment
        state["phase"] = "starting"
        state["candidate_start_attempted"] = True
        b.save(state)
        b.pc(environment, "up", "--no-build", "--pull", "never", "--no-deps", "-d", "backend", "worker", "frontend")
        b.ready(environment)
        candidate_readonly_smoke()
        assert m._columns("webcompiler-postgres") == columns
        assert schema_markers("webcompiler-postgres") == tuple(state["schema_markers"])
        assert schema_inventory("webcompiler-postgres") == state["schema_inventory"]
        assert m._fingerprints("webcompiler-postgres", columns) == state["fingerprints"]
        for role in ("redis", "pgbouncer", "api-proxy"):
            assert b.o.inspect(b.PROJECT + "-" + role + "-1")["Id"] == state["old_ids"][role]
        assert b.o.inspect("webcompiler-postgres")["Id"] == state["postgres_id"]
        assert environment["SANDBOX_IMAGE"] == (state["bases"]["sandbox"] if state["sandbox_reused"] else state["runtime_approval"]["candidate_image"])
        state["integrity_verified"] = True
        b.save(state)

        b.edge(state, state["edge_configs"])
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
        print(json.dumps({
            "phase": "deployed",
            "sha": b.SHA,
            "database_migrated": False,
            "sandbox": "reused" if state["sandbox_reused"] else "approved-runtime-update",
        }), flush=True)
    except BaseException:
        handle_rollout_failure(touched=touched)
        raise


def main() -> None:
    import fcntl

    assert os.environ.get("WEBCOMPILER_APPLICATION_RELEASE") == "approved"
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
        print(
            "Application release stopped: " + type(exc).__name__
            + ". Inspect the private release journal.",
            file=os.sys.stderr,
        )
        raise SystemExit(1)
