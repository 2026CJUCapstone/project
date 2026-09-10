#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import socket
import shutil
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[1]


def read_test_port(key: str, default: int) -> int:
    value = os.environ.get(key, str(default))
    if not re.fullmatch(r'[0-9]+', value) or not 1024 <= int(value) <= 65535:
        raise ValueError(f'{key} must be a decimal port between 1024 and 65535')
    return int(value)


BACKEND_PORT = read_test_port('E2E_BACKEND_PORT', 18010)
FRONTEND_PORT = read_test_port('E2E_FRONTEND_PORT', 15180)
if BACKEND_PORT == FRONTEND_PORT:
    raise ValueError('E2E backend and frontend ports must differ')
BACKEND_BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_BASE_URL = f"http://127.0.0.1:{FRONTEND_PORT}"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "E2eStackAdminOnly-2026!"
E2E_NAMESPACE = f"webcompiler-e2e-{uuid4().hex}"
SANDBOX_IMAGE = f"{E2E_NAMESPACE}-sandbox:latest"
BACKEND_IMAGE = f"{E2E_NAMESPACE}-backend:latest"
FRONTEND_IMAGE = f"{E2E_NAMESPACE}-frontend:latest"
POSTGRES_DB = "compiler_e2e"
POSTGRES_USER = "compiler_e2e"
POSTGRES_PASSWORD = "compiler-e2e-only-password"
RUNTIME_DATABASE_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@pgbouncer:5432/{POSTGRES_DB}"
)
MIGRATION_DATABASE_URL = (
    f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@postgres:5432/{POSTGRES_DB}"
)
# This harness owns a fresh local project, not the caller's deployment context.
# Preserve only executable/temp paths and the explicitly selected bounded
# builder metadata. In particular, never inherit Compose files/profiles, shell
# startup hooks, application secrets, or a remote Docker context.
PROCESS_ENVIRONMENT_KEYS = (
    "PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "WINDIR",
    "DOCKER_CONFIG", "BUILDX_CONFIG",
    "WEBCOMPILER_BUILD_BUILDER", "WEBCOMPILER_BUILD_CONTAINER_ID",
    "WEBCOMPILER_BUILD_MEMORY_MB", "WEBCOMPILER_BUILD_CPU_MILLIS", "WEBCOMPILER_BUILD_PIDS",
    "WEBCOMPILER_WORKER_UID", "WEBCOMPILER_WORKER_GID", "WEBCOMPILER_DOCKER_GID",
)
ENV = {
    **{key: os.environ[key] for key in PROCESS_ENVIRONMENT_KEYS if key in os.environ},
    "DOCKER_HOST": "unix:///var/run/docker.sock",
    "COMPOSE_FILE": os.pathsep.join(str(ROOT_DIR / filename) for filename in
                                     ('docker-compose.yml', 'scripts/e2e-stack.compose.yml')),
    "COMPOSE_ENV_FILES": os.devnull,
    "COMPOSE_DISABLE_ENV_FILE": "1",
    "PYTHONUNBUFFERED": "1",
    "COMPOSE_PROJECT_NAME": E2E_NAMESPACE,
    "PROJECT_ROOT": str(ROOT_DIR),
    "ENVIRONMENT": "development",
    "SECRET_KEY": "e2e-stack-isolated-secret-key-not-for-production",
    "ADMIN_USERNAME": ADMIN_USERNAME,
    "ADMIN_PASSWORD": ADMIN_PASSWORD,
    "SANDBOX_IMAGE": SANDBOX_IMAGE,
    "WEBCOMPILER_POSTGRES_DB": POSTGRES_DB,
    "WEBCOMPILER_POSTGRES_USER": POSTGRES_USER,
    "WEBCOMPILER_POSTGRES_PASSWORD": POSTGRES_PASSWORD,
    "WEBCOMPILER_POSTGRES_HOST": "postgres",
    "WEBCOMPILER_POSTGRES_PORT": "5432",
    "WEBCOMPILER_DATABASE_HOST": "pgbouncer",
    "WEBCOMPILER_DATABASE_PORT": "5432",
    "WEBCOMPILER_DATABASE_URL": RUNTIME_DATABASE_URL,
    "WEBCOMPILER_MIGRATION_DATABASE_URL": MIGRATION_DATABASE_URL,
    "DATABASE_URL": RUNTIME_DATABASE_URL,
    "WEBCOMPILER_REDIS_URL": "redis://redis:6379/0",
    "REDIS_URL": "redis://redis:6379/0",
    "WEBCOMPILER_REDIS_KEY_PREFIX": E2E_NAMESPACE,
    "SANDBOX_POOL_ID": E2E_NAMESPACE,
    "WEBCOMPILER_BACKEND_IMAGE": BACKEND_IMAGE,
    "E2E_FRONTEND_IMAGE": FRONTEND_IMAGE,
    # The nonce-owned builder's cache is disposable after all three loaded
    # image IDs exist. Release it before stateful image pulls to avoid adding
    # their disk usage to the full build cache peak.
    "WEBCOMPILER_E2E_RELEASE_BUILD_CACHE": "1",
    "WEBCOMPILER_DATA_DIR": str(ROOT_DIR / ".data" / E2E_NAMESPACE),
    "SMTP_HOST": "",
    "SMTP_PORT": "587",
    "SMTP_USERNAME": "",
    "SMTP_PASSWORD": "",
    "SMTP_FROM": "",
    "SMTP_STARTTLS": "false",
    "WEBCOMPILER_SMTP_HOST": "",
    "WEBCOMPILER_SMTP_PORT": "587",
    "WEBCOMPILER_SMTP_USERNAME": "",
    "WEBCOMPILER_SMTP_PASSWORD": "",
    "WEBCOMPILER_SMTP_FROM": "",
    "WEBCOMPILER_SMTP_STARTTLS": "false",
    "WEBCOMPILER_BACKEND_PORT_MAPPING": f"127.0.0.1:{BACKEND_PORT}:8000",
    "WEBCOMPILER_FRONTEND_PORT_MAPPING": f"127.0.0.1:{FRONTEND_PORT}:8080",
}
OPENER = build_opener(HTTPCookieProcessor(CookieJar()))
_WORKSPACE_LOCK_FD: int | None = None


def run_command(*args: str) -> None:
    # The setup shell may outlive this Python process after cancellation. Keep
    # its ownership lock alive too, so recovery cannot race a late compose up.
    inherited = () if _WORKSPACE_LOCK_FD is None else (_WORKSPACE_LOCK_FD,)
    subprocess.run(args, cwd=ROOT_DIR, env=ENV, check=True, pass_fds=inherited)


TEST_SERVICE_BUDGETS = {
    # MiB, CPU, PIDs; includes the one-shot initializer for an upper bound.
    'postgres': (256, 0.25, 128), 'pgbouncer': (64, 0.125, 64),
    'redis': (96, 0.125, 64), 'initialize': (256, 0.25, 128),
    'backend': (384, 0.5, 128), 'worker': (512, 0.5, 128),
    'frontend': (64, 0.125, 64),
}

LANGUAGE_SMOKE_CODES = {
    'bpp': 'import emitln from std.io;\nfunc main() -> u64 { emitln("42"); return 0; }\n',
    'c': '#include <stdio.h>\nint main(void) { puts("42"); return 0; }\n',
    'cpp': '#include <iostream>\nint main() { std::cout << 42 << "\\n"; }\n',
    'python': 'print(42)\n',
    'java': 'public class Main { public static void main(String[] args) { System.out.println(42); } }\n',
    'javascript': 'console.log(42);\n',
}


def validate_test_workspace(root: Path) -> None:
    # docker_up creates a sandbox bind and can copy legacy data. Never invoke
    # it in a checkout that already has application/deployment state.
    for relative in ('.deploy', '.data', '.sandbox-work', '.env',
                     'bpp_project.db', 'backend/bpp_project.db'):
        target = root / relative
        if target.exists() or target.is_symlink():
            raise RuntimeError('E2E requires a fresh isolated checkout; existing state: ' + relative)


@contextmanager
def workspace_lock(root: Path, *, recovery: bool = False):
    global _WORKSPACE_LOCK_FD
    previous_descriptor = _WORKSPACE_LOCK_FD
    if os.name != 'posix':
        raise RuntimeError('Docker E2E requires an isolated Linux host')
    import fcntl
    if not recovery:
        validate_test_workspace(root)
    descriptor = os.open(root / '.e2e-stack.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('Invalid E2E workspace lock')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another E2E run owns this checkout') from exc
        # Recheck after locking; a predecessor may have created state while we
        # were opening the lock. Keep the lock inode rather than unlinking it.
        if not recovery:
            validate_test_workspace(root)
        _WORKSPACE_LOCK_FD = descriptor
        yield
    finally:
        _WORKSPACE_LOCK_FD = previous_descriptor
        os.close(descriptor)


def check_test_ports(ports: tuple[int, int]) -> None:
    # This is an early conflict check, not an atomic reservation until Docker
    # binds. A later race must fail Compose startup, never fall back to a peer.
    held = []
    try:
        for port in ports:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            held.append(listener)
            listener.bind(('127.0.0.1', port))
    except OSError as exc:
        raise RuntimeError('An E2E loopback port is already in use') from exc
    finally:
        for listener in held:
            listener.close()


def validate_test_budget(model: dict) -> None:
    def integer(value):
        # Compose JSON emits UnitBytes as decimal strings on current releases.
        # Accept that representation, not units, booleans, floats or coercions.
        if type(value) is int:
            return value
        if isinstance(value, str) and re.fullmatch(r'[0-9]{1,12}', value):
            return int(value)
        return 0

    services = model.get('services', {})
    if model.get('name') != E2E_NAMESPACE or set(services) != set(TEST_SERVICE_BUDGETS):
        raise RuntimeError('Unexpected E2E Compose project or services')
    for name, (memory, cpu, pids) in TEST_SERVICE_BUDGETS.items():
        service = services[name]
        if not (0 < integer(service.get('mem_limit')) <= memory * 1024 ** 2
                and integer(service.get('memswap_limit')) == integer(service.get('mem_limit'))
                and 0 < float(service.get('cpus', 0)) <= cpu
                and 0 < integer(service.get('pids_limit')) <= pids
                and service.get('restart') == 'no'):
            raise RuntimeError('Missing or excessive E2E resource limit: ' + name)


def preflight() -> None:
    if os.name != 'posix':
        raise RuntimeError('Docker E2E requires an isolated Linux host')
    validate_test_workspace(ROOT_DIR)
    check_test_ports((BACKEND_PORT, FRONTEND_PORT))
    docker_socket = os.stat('/var/run/docker.sock')
    if not stat.S_ISSOCK(docker_socket.st_mode):
        raise RuntimeError('Expected the local Docker socket')
    ENV.update(WEBCOMPILER_WORKER_UID=str(os.getuid()),
               WEBCOMPILER_WORKER_GID=str(os.getgid()),
               WEBCOMPILER_DOCKER_GID=str(docker_socket.st_gid))
    rendered = subprocess.run(['docker', 'compose', 'config', '--format', 'json'],
        cwd=ROOT_DIR, env=ENV, capture_output=True, text=True, check=True, timeout=30)
    validate_test_budget(json.loads(rendered.stdout))


def docker(*args: str) -> str:
    return subprocess.run(['docker', *args], cwd=ROOT_DIR, env=ENV,
                          capture_output=True, text=True, check=True, timeout=180).stdout.strip()


def owned_resources() -> dict[str, list[dict]]:
    """Discover by nonce, then verify exact identity before any destructive call."""
    project_label = f'com.docker.compose.project={E2E_NAMESPACE}'
    selectors = {
        'container': ('ps', '-aq', '--no-trunc', '--filter', 'label=' + project_label),
        'sandbox': ('ps', '-aq', '--no-trunc', '--filter', 'label=webcompiler.pool=' + E2E_NAMESPACE),
        'volume': ('volume', 'ls', '-q', '--filter', 'label=' + project_label),
        'network': ('network', 'ls', '-q', '--no-trunc', '--filter', 'label=' + project_label),
    }
    result = {}
    for kind, command in selectors.items():
        rows = []
        for identifier in docker(*command).splitlines():
            inspect_kind = 'container' if kind == 'sandbox' else kind
            rows_from_inspect = json.loads(docker(inspect_kind, 'inspect', identifier))
            if len(rows_from_inspect) != 1:
                raise RuntimeError('Ambiguous E2E resource identity')
            row = rows_from_inspect[0]
            is_container = inspect_kind == 'container'
            labels = (row.get('Config', {}) if is_container else row).get('Labels') or {}
            if kind == 'sandbox':
                root = (ROOT_DIR / '.sandbox-work').resolve()
                mounts = row.get('Mounts', [])
                job = labels.get('webcompiler.job', '').replace('-', '')
                lease = labels.get('webcompiler.lease', '')
                owned = (labels.get('webcompiler.pool') == E2E_NAMESPACE
                         and re.fullmatch(r'[a-f0-9]{32}', job) and job != '0' * 32
                         and re.fullmatch(r'[a-f0-9]{32}', lease) and lease != '0' * 32
                         and 'webcompiler.runtime-version' not in labels
                         and any(m.get('Type') == 'bind'
                                 and Path(m.get('Source', '')).resolve().is_relative_to(root)
                                 for m in mounts))
            else:
                owned = labels.get('com.docker.compose.project') == E2E_NAMESPACE
                if kind == 'container':
                    owned = (owned and labels.get('com.docker.compose.service') in TEST_SERVICE_BUDGETS
                             and labels.get('com.docker.compose.project.working_dir') == str(ROOT_DIR))
                elif kind == 'volume':
                    owned = (owned and row.get('Name') in
                             {E2E_NAMESPACE + '_postgres_data', E2E_NAMESPACE + '_redis_data'})
                else:
                    owned = owned and row.get('Name') == E2E_NAMESPACE + '_default'
            actual_id = row.get('Name') if kind == 'volume' else row.get('Id')
            if not owned or actual_id != identifier:
                raise RuntimeError('Refusing non-owned E2E ' + kind)
            rows.append(row)
        result[kind] = rows
    return result


def test_image_tags() -> tuple[str, str, str]:
    return SANDBOX_IMAGE, BACKEND_IMAGE, FRONTEND_IMAGE


def verify_started_stack() -> None:
    resources = owned_resources()
    rows = resources['container']
    services = {row['Config']['Labels']['com.docker.compose.service']: row for row in rows}
    if len(rows) != len(TEST_SERVICE_BUDGETS) or set(services) != set(TEST_SERVICE_BUDGETS):
        raise RuntimeError('Expected exactly the seven owned E2E services')
    for name, (memory, cpu, pids) in TEST_SERVICE_BUDGETS.items():
        row = services[name]
        limits, state = row.get('HostConfig', {}), row.get('State', {})
        if (limits.get('Memory') != memory * 1024**2
                or limits.get('MemorySwap') != memory * 1024**2
                or limits.get('NanoCpus') != int(cpu * 1_000_000_000)
                or limits.get('PidsLimit') != pids
                or limits.get('RestartPolicy', {}).get('Name') != 'no'
                or state.get('OOMKilled') is not False):
            raise RuntimeError('Actual E2E resource limits differ: ' + name)
        if name == 'initialize':
            if state.get('Running') is not False or state.get('ExitCode') != 0:
                raise RuntimeError('E2E initializer did not complete successfully')
        elif state.get('Running') is not True:
            raise RuntimeError('E2E service is not running: ' + name)
    for service, internal, published in (('backend', '8000/tcp', BACKEND_PORT),
                                         ('frontend', '8080/tcp', FRONTEND_PORT)):
        bindings = services[service]['HostConfig'].get('PortBindings')
        if bindings != {internal: [{'HostIp': '127.0.0.1', 'HostPort': str(published)}]}:
            raise RuntimeError('Actual E2E listener does not match its loopback port: ' + service)
    print('Actual seven-service E2E memory/swap/CPU/PID/restart caps and loopback bindings verified')


def image_exists(tag: str) -> bool:
    # A daemon/permission error must not be confused with an absent image.
    return bool(docker('image', 'ls', '-q', '--filter', 'reference=' + tag))


def record_ownership() -> None:
    if any(owned_resources().values()) or any(image_exists(tag) for tag in test_image_tags()):
        raise RuntimeError('E2E nonce already has resources; refusing to adopt them')
    # O_EXCL retains the original record across cancellation/recovery. A new
    # run needs a fresh checkout, never overwrites ownership from its predecessor.
    path = ROOT_DIR / '.e2e-stack-owner.json'
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump({'version': 1, 'root': str(ROOT_DIR), 'namespace': E2E_NAMESPACE}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    sync_workspace_directory()


def sync_workspace_directory() -> None:
    descriptor = os.open(ROOT_DIR, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def checkpoint_path(name: str) -> Path:
    if name not in {'setup-complete', 'producers-settled'}:
        raise ValueError('Unknown E2E lifecycle checkpoint')
    return ROOT_DIR / ('.e2e-stack-' + name + '.json')


def checkpoint_exists(name: str) -> bool:
    try:
        descriptor = os.open(checkpoint_path(name), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    with os.fdopen(descriptor, 'r', encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 4096):
            raise RuntimeError('Invalid E2E lifecycle checkpoint')
        if json.load(stream) != {'version': 1, 'root': str(ROOT_DIR), 'namespace': E2E_NAMESPACE}:
            raise RuntimeError('E2E lifecycle checkpoint has another owner')
    return True


def record_checkpoint(name: str) -> None:
    if checkpoint_exists(name):
        return
    descriptor = os.open(checkpoint_path(name), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump({'version': 1, 'root': str(ROOT_DIR), 'namespace': E2E_NAMESPACE}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    sync_workspace_directory()


def restore_ownership() -> bool:
    global E2E_NAMESPACE, SANDBOX_IMAGE, BACKEND_IMAGE, FRONTEND_IMAGE
    path = ROOT_DIR / '.e2e-stack-owner.json'
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        if any((ROOT_DIR / name).exists() for name in ('.data', '.sandbox-work')):
            raise RuntimeError('E2E state exists without ownership; manual investigation required')
        return False  # Preflight failed before this checkout owned anything.
    with os.fdopen(descriptor, 'r', encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 4096):
            raise RuntimeError('Invalid E2E ownership record')
        record = json.load(stream)
    namespace = record.get('namespace', '')
    if (record.get('version') != 1 or record.get('root') != str(ROOT_DIR)
            or not isinstance(namespace, str)
            or not re.fullmatch(r'webcompiler-e2e-[a-f0-9]{32}', namespace)):
        raise RuntimeError('Invalid E2E ownership scope')
    E2E_NAMESPACE = namespace
    SANDBOX_IMAGE, BACKEND_IMAGE, FRONTEND_IMAGE = (
        f'{namespace}-{role}:latest' for role in ('sandbox', 'backend', 'frontend'))
    ENV.update(COMPOSE_PROJECT_NAME=namespace, SANDBOX_POOL_ID=namespace,
               WEBCOMPILER_REDIS_KEY_PREFIX=namespace, SANDBOX_IMAGE=SANDBOX_IMAGE,
               WEBCOMPILER_BACKEND_IMAGE=BACKEND_IMAGE, E2E_FRONTEND_IMAGE=FRONTEND_IMAGE,
               WEBCOMPILER_DATA_DIR=str(ROOT_DIR / '.data' / namespace))
    return True


def settle_producers() -> None:
    if checkpoint_exists('producers-settled'):
        return
    if not checkpoint_exists('setup-complete'):
        # Child/process absence is insufficient: a previously accepted daemon
        # build/create request can still complete. Retain the namespace and
        # evidence, fail CI, and never remove its builder as if cleanup passed.
        raise RuntimeError('E2E setup has no durable completion acknowledgment; resources quarantined')
    resources = owned_resources()
    # Stop HTTP acceptance before draining the worker. Do not delete the DB:
    # it is the authority for possibly unresolved Docker mutation requests.
    for service in ('frontend', 'backend', 'worker'):
        rows = [row for row in resources['container']
                if row['Config']['Labels']['com.docker.compose.service'] == service]
        if len(rows) != 1:
            raise RuntimeError('Cannot prove E2E producer exit: ' + service)
        for row in rows:
            docker('container', 'stop', '--time', '150', row['Id'])
            current = json.loads(docker('container', 'inspect', row['Id']))
            # Pinned Uvicorn 0.52 re-raises SIGTERM after graceful shutdown;
            # Docker records this as 128+15. The dedicated Python worker does
            # not do this, and must still exit 0. OOM/SIGKILL is never accepted.
            accepted_exits = (0, 143) if service == 'backend' else (0,)
            if (len(current) != 1 or current[0].get('Id') != row['Id']
                    or current[0].get('State', {}).get('Running') is not False
                    or current[0]['State'].get('OOMKilled') is not False
                    or current[0]['State'].get('ExitCode') not in accepted_exits):
                raise RuntimeError('E2E producer did not exit cleanly; resources quarantined')
    databases = [row for row in resources['container']
                 if row['Config']['Labels']['com.docker.compose.service'] == 'postgres']
    if len(databases) != 1:
        raise RuntimeError('E2E operation journal is unavailable; resources quarantined')
    # JSON(none_as_null=True) stores no outstanding operation as SQL NULL.
    # Even a terminal row with a retained lease/intent must prevent deletion.
    query = ("BEGIN READ ONLY; SET LOCAL statement_timeout='5s'; "
             "SELECT (SELECT count(*) FROM execution_jobs WHERE "
             "status NOT IN ('completed','failed') OR sandbox_operation IS NOT NULL "
             "OR lease_token IS NOT NULL OR lease_until IS NOT NULL OR finished_at IS NULL) + "
             "(SELECT count(*) FROM execution_workers WHERE draining_at IS NULL) + "
             "(SELECT CASE WHEN count(*) = 0 THEN 1 ELSE 0 END FROM execution_workers); COMMIT;")
    remaining = docker('exec', databases[0]['Id'], 'psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1',
                       '-U', POSTGRES_USER, '-d', POSTGRES_DB, '-Atc', query)
    if remaining.strip() != '0':
        raise RuntimeError('E2E has unresolved jobs or Docker mutations; resources quarantined')
    record_checkpoint('producers-settled')


def cleanup_owned_stack() -> None:
    settle_producers()
    resources = owned_resources()
    for kind in ('sandbox', 'container'):
        for row in resources[kind]:
            docker('container', 'rm', '-f', row['Id'])
    # Re-discover before removing storage. Fail rather than claiming cleanup
    # if a worker or a previously unknown sandbox survived.
    remaining = owned_resources()
    if remaining['container'] or remaining['sandbox']:
        raise RuntimeError('E2E containers survived cleanup')
    for row in remaining['volume']:
        docker('volume', 'rm', row['Name'])
    for row in remaining['network']:
        docker('network', 'rm', row['Id'])
    for tag in test_image_tags():
        if image_exists(tag):
            # Remove only our nonce tag, never force an image ID that might be
            # shared with another build. Base images and builder are not ours.
            docker('image', 'rm', tag)
    if any(owned_resources().values()) or any(image_exists(tag) for tag in test_image_tags()):
        raise RuntimeError('E2E resources survived cleanup')
    for target in (ROOT_DIR / '.sandbox-work', ROOT_DIR / '.data' / E2E_NAMESPACE):
        # Root was fresh before ownership was recorded. On Linux rmtree uses
        # fd-relative traversal; refuse symlinked parents or top-level targets.
        if (target.is_symlink() or target.parent.is_symlink()
                or not target.resolve().is_relative_to(ROOT_DIR.resolve())):
            raise RuntimeError('Refusing redirected E2E work directory')
        if target.exists():
            if not shutil.rmtree.avoids_symlink_attacks:
                raise RuntimeError('Safe E2E work directory removal requires Linux')
            shutil.rmtree(target)
    print('E2E owned containers, volumes, network, image tags and work directories removed')


def request_json(url: str, *, method: str = "GET", payload: dict | None = None,
                 headers: dict[str, str] | None = None,
                 timeout: float = 20.0) -> tuple[int, dict]:
    body = json.dumps(payload).encode() if payload is not None else None
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with OPENER.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} returned {exc.code}: {detail}") from exc


def post_json(url: str, payload: dict,
              headers: dict[str, str] | None = None) -> tuple[int, dict]:
    return request_json(url, method="POST", payload=payload, headers=headers)


def wait_for_json(url: str, timeout: float = 90.0) -> dict:
    deadline, last_error = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        try:
            status, payload = request_json(url, timeout=5)
            if status == 200:
                return payload
        except Exception as exc:  # noqa: BLE001 - readiness is retried
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for loopback service {url}: {last_error}")


def poll_execution(execution_id: str, *, headers: dict[str, str] | None = None,
                   timeout: float = 300.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, receipt = request_json(
            f"{FRONTEND_BASE_URL}/api/v1/executions/{execution_id}", headers=headers)
        if status != 200:
            raise RuntimeError(f"Execution lookup returned {status}: {receipt}")
        state = receipt.get("status")
        if state in {"completed", "failed", "canceled"}:
            result = receipt.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"Terminal execution omitted its result: {receipt}")
            return result
        if state not in {"queued", "running"}:
            raise RuntimeError(f"Unknown execution state: {receipt}")
        time.sleep(0.5)
    raise RuntimeError(
        f"Execution {execution_id} remains pending after {timeout:.0f}s; it was not resubmitted")


def submit_execution(path: str, payload: dict,
                     headers: dict[str, str] | None = None) -> dict:
    request_headers = {"X-Request-ID": str(uuid4()), **(headers or {})}
    status, receipt = post_json(FRONTEND_BASE_URL + path, payload, request_headers)
    if status != 202 or not receipt.get("id"):
        raise RuntimeError(f"Expected 202 receipt, got {status}: {receipt}")
    return poll_execution(receipt["id"], headers=headers)


def login(username: str, password: str) -> dict[str, str]:
    status, payload = post_json(
        f"{FRONTEND_BASE_URL}/api/v1/auth/login",
        {"username": username, "password": password})
    # FastAPI serializes schemas.Token's CamelModel aliases on the wire.
    token = payload.get("accessToken")
    if (status != 200 or not isinstance(token, str) or not token.strip()
            or payload.get("tokenType") != "bearer"):
        # Never include a login response in diagnostics: even an unexpected
        # response shape can contain a valid credential.
        raise RuntimeError(f"Login response did not match the public token contract (status {status})")
    return {"Authorization": f"Bearer {token}"}


def fetch_text(url: str) -> str:
    with OPENER.open(url, timeout=10) as response:
        return response.read().decode()


def wait_for_condition(path: str, predicate, *, headers: dict, timeout: float = 180) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, value = request_json(FRONTEND_BASE_URL + path, headers=headers)
        if status != 200:
            raise RuntimeError('Unexpected E2E poll status: ' + str(status))
        if predicate(value):
            return value
        time.sleep(1)
    raise RuntimeError('E2E condition timed out: ' + path)


def exercise_practice(problem_id: str, solver_headers: dict) -> dict:
    _, baseline = request_json(FRONTEND_BASE_URL + '/api/v1/auth/me', headers=solver_headers)

    def submit() -> tuple[dict, dict]:
        status, receipt = post_json(
            FRONTEND_BASE_URL + '/api/v1/problems/' + problem_id + '/submit',
            {'code': LANGUAGE_SMOKE_CODES['bpp'], 'language': 'bpp'},
            {'X-Request-ID': str(uuid4()), **solver_headers})
        if status != 202 or not receipt.get('id') or not receipt.get('executionId'):
            raise RuntimeError('Practice submission omitted its durable receipt')
        return receipt, poll_execution(receipt['executionId'], headers=solver_headers)

    first_receipt, first = submit()
    duplicate_receipt, duplicate = submit()
    first_value, duplicate_value = first.get('value') or {}, duplicate.get('value') or {}
    expected_total = baseline['totalScore'] + 20
    if (first_receipt['id'] == duplicate_receipt['id']
            or first_receipt['executionId'] == duplicate_receipt['executionId']):
        raise RuntimeError('Independent practice submissions reused a receipt')
    for result, value in ((first, first_value), (duplicate, duplicate_value)):
        if (not result.get('ok') or value.get('gradingPassed') is not True
                or value.get('gradingCompleted') is not True
                or value.get('verdict') != 'accepted' or value.get('totalScore') != expected_total):
            raise RuntimeError('Practice grading/score result failed')
    # SubmissionResponse carries totalScore, not the separate leaderboard-score
    # endpoint's awardedPoints/alreadySolved. Verify the per-submission awards
    # through the actual history API and independently check account/progress.
    _, history = request_json(FRONTEND_BASE_URL + '/api/v1/problems/submissions?mine=true&problemId=' + problem_id,
                              headers=solver_headers)
    rows = {row['id']: row for row in history['submissions']}
    if (history.get('filteredTotal') != 2 or len(history['submissions']) != 2
            or set(rows) != {first_receipt['id'], duplicate_receipt['id']}
            or rows[first_receipt['id']]['awardedPoints'] != 20
            or rows[duplicate_receipt['id']]['awardedPoints'] != 0
            or any(row.get('userId') != baseline['id'] or row.get('problemId') != problem_id
                   or row.get('verdict') != 'accepted' for row in rows.values())):
        raise RuntimeError('Practice score ledger did not award exactly once')
    _, account = request_json(FRONTEND_BASE_URL + '/api/v1/auth/me', headers=solver_headers)
    _, problem = request_json(FRONTEND_BASE_URL + '/api/v1/problems/' + problem_id, headers=solver_headers)
    if (account['totalScore'] != expected_total or problem.get('solved') is not True
            or problem.get('bestAwardedPoints') != 20):
        raise RuntimeError('Practice account/progress disagrees with the score ledger')
    print('Actual practice solve and duplicate-score protection passed', flush=True)
    return {'awardedPoints': rows[first_receipt['id']]['awardedPoints'],
            'duplicateAwardedPoints': rows[duplicate_receipt['id']]['awardedPoints']}


def exercise_contest(admin_headers: dict, solver_headers: dict, suffix: str) -> dict:
    _, baseline = request_json(FRONTEND_BASE_URL + '/api/v1/auth/me', headers=solver_headers)
    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    problem = {'title': 'E2E private problem ' + suffix, 'description': 'Print 42',
               'difficulty': 'iron5', 'tags': ['e2e'], 'points': 17,
               'testCases': [{'input': '', 'expectedOutput': '42'}],
               'hiddenTestCases': [{'input': '', 'expectedOutput': '42'}]}
    status, created = post_json(FRONTEND_BASE_URL + '/api/v1/contests', {
        'title': 'E2E contest ' + suffix, 'description': 'Isolated integration fixture',
        'startsAt': start.isoformat(), 'endsAt': (start + timedelta(minutes=1)).isoformat(),
        'published': False, 'problems': [{'points': 500, 'newProblem': problem}],
    }, admin_headers)
    if status != 201:
        raise RuntimeError('Contest creation did not return 201')
    path = '/api/v1/contests/' + created['id']
    _, manage = request_json(FRONTEND_BASE_URL + path + '/manage', headers=admin_headers)
    start = datetime.fromisoformat(manage['serverTime'].replace('Z', '+00:00')) + timedelta(seconds=10)
    status, published = request_json(FRONTEND_BASE_URL + path, method='PUT', headers=admin_headers,
        payload={key: manage[key] for key in ('title', 'description', 'problems')} | {
            'published': True, 'startsAt': start.isoformat(),
            'endsAt': (start + timedelta(seconds=60)).isoformat()})
    if status != 200 or published['state'] != 'upcoming':
        raise RuntimeError('Contest publication failed')
    source_id = published['problems'][0]['problemId']
    try:
        request_json(FRONTEND_BASE_URL + '/api/v1/problems/' + source_id, headers=solver_headers)
    except RuntimeError as exc:
        if not isinstance(exc.__cause__, HTTPError) or exc.__cause__.code not in (403, 404):
            raise
    else:
        raise RuntimeError('Private contest problem leaked before start')
    status, joined = post_json(FRONTEND_BASE_URL + path + '/join', {}, solver_headers)
    if status != 200 or not joined['joined'] or joined['problems']:
        raise RuntimeError('Contest join/pre-start visibility failed')
    running = wait_for_condition(path, lambda value: value['state'] == 'running',
                                 headers=solver_headers, timeout=30)
    problem_id = running['problems'][0]['id']  # Publication recreates this ID.
    submit_path = FRONTEND_BASE_URL + path + '/problems/' + problem_id + '/submit'
    payload = {'language': 'bpp', 'code': LANGUAGE_SMOKE_CODES['bpp'], 'requestId': str(uuid4())}
    status, receipt = post_json(submit_path, payload, solver_headers)
    retry_status, retry = post_json(submit_path, payload, solver_headers)
    if status != 202 or retry_status != 202 or retry['id'] != receipt['id']:
        raise RuntimeError('Contest idempotent submission did not retain its receipt')
    graded = wait_for_condition(path + '/submissions/' + receipt['id'],
        lambda value: value['status'] not in ('queued', 'running'), headers=solver_headers)
    if graded['status'] != 'completed' or graded['verdict'] != 'accepted':
        raise RuntimeError('Contest real grading failed: ' + json.dumps(graded))
    board = wait_for_condition(path + '/scoreboard', lambda value: value['pendingCount'] == 0
        and any(row['userId'] == baseline['id'] and row['totalPoints'] == 500 for row in value['rows']),
        headers=solver_headers)
    row = next(row for row in board['rows'] if row['userId'] == baseline['id'])
    if row['rank'] != 1 or row['problems'][0]['verdict'] != 'accepted':
        raise RuntimeError('Contest scoreboard did not reflect the solve')
    wait_for_condition(path, lambda value: value['state'] == 'finished', headers=solver_headers)
    _, public = request_json(FRONTEND_BASE_URL + '/api/v1/problems/' + source_id, headers=solver_headers)
    _, account = request_json(FRONTEND_BASE_URL + '/api/v1/auth/me', headers=solver_headers)
    if (public.get('solved') is not True or public.get('bestAwardedPoints') != 17
            or public.get('hiddenTestCases') or account['totalScore'] != baseline['totalScore'] + 17):
        raise RuntimeError('Contest finalization/publication/general score failed')
    return {'points': row['totalPoints'], 'generalScoreDelta': 17, 'state': 'finished',
            'sameReceiptOnRetry': True, 'hiddenTestsPrivate': True}


def exercise_stack() -> int:
    # Before the try/finally: a failed preflight owns no stack to tear down.
    preflight()
    record_ownership()
    suffix = uuid4().hex[:12]
    username, password = f"ci_solver_{suffix}", f"CiSolver-{suffix}!"
    code = LANGUAGE_SMOKE_CODES['bpp']
    try:
        run_command("bash", "scripts/docker_up.sh")
        record_checkpoint('setup-complete')
        verify_started_stack()
        backend_ready = wait_for_json(f"{BACKEND_BASE_URL}/ready")
        frontend_health = wait_for_json(f"{FRONTEND_BASE_URL}/health")
        if backend_ready.get("status") != "ready" or frontend_health.get("status") != "ok":
            raise RuntimeError("Stack readiness failed")
        if '<div id="root"></div>' not in fetch_text(FRONTEND_BASE_URL + "/"):
            raise RuntimeError("Frontend index did not load")

        compiled = submit_execution("/api/v1/compiler/compile", {
            "code": code, "language": "bpp",
            "options": {"optimize": False, "target": "all"}})
        compiled_value = compiled.get("value") or {}
        if not compiled.get("ok") or compiled_value.get("success") is not True:
            raise RuntimeError(f"Compile failed: {compiled}")
        invalid = submit_execution("/api/v1/compiler/compile", {
            "code": "func main( -> u64 { return 0; }", "language": "bpp",
            "options": {"optimize": False, "target": "all"}})
        invalid_value = invalid.get("value") or {}
        if (not invalid.get("ok") or invalid_value.get("success") is not False
                or not invalid_value.get("errors")):
            raise RuntimeError(f"Compile diagnostics failed: {invalid}")
        print('Actual B++ compile and invalid-code diagnostics passed', flush=True)
        language_outputs = {}
        for language, example in LANGUAGE_SMOKE_CODES.items():
            ran = submit_execution("/api/v1/compiler/run", {"code": example, "language": language})
            ran_value = ran.get("value") or {}
            if (not ran.get("ok") or ran_value.get("exit_code") != 0
                    or ran_value.get("stdout", "").strip() != "42"):
                raise RuntimeError(f"{language} run failed: {ran}")
            language_outputs[language] = ran_value['stdout'].strip()
            print('Actual language execution passed: ' + language + ' => 42', flush=True)

        status, registered = post_json(FRONTEND_BASE_URL + "/api/v1/auth/register", {
            "username": username, "email": f"{username}@example.test", "password": password})
        if status != 200:
            raise RuntimeError(f"Registration failed: {registered}")
        solver_headers = login(username, password)
        admin_headers = login(ADMIN_USERNAME, ADMIN_PASSWORD)
        status, problem = post_json(FRONTEND_BASE_URL + "/api/v1/problems/", {
            "title": f"E2E durable grading {suffix}", "difficulty": "iron5",
            "tags": ["e2e"], "description": "Isolated CI fixture", "points": 20,
            "testCases": [{"input": "", "expectedOutput": "42"}],
            "hiddenTestCases": [{"input": "", "expectedOutput": "42"}],
        }, admin_headers)
        if status != 200 or not problem.get("id"):
            raise RuntimeError(f"Problem creation failed: {problem}")

        practice_result = exercise_practice(problem['id'], solver_headers)
        contest_result = exercise_contest(admin_headers, solver_headers, suffix)

        print(json.dumps({
            "backend_ready": backend_ready, "frontend_health": frontend_health,
            "compile_success": compiled_value.get("success"),
            "invalid_compile_errors": len(invalid_value.get("errors", [])),
            "language_stdout": language_outputs,
            "practice_awarded_points": practice_result['awardedPoints'],
            "duplicate_awarded_points": practice_result['duplicateAwardedPoints'],
            "contest": contest_result,
        }, ensure_ascii=True, indent=2))
        return 0
    finally:
        # A passing exercise with failed cleanup is not a passing E2E run.
        # Preserve the cleanup exception (and Python's original error context)
        # so CI cannot silently leave an active test stack behind.
        cleanup_owned_stack()


def main() -> int:
    if sys.argv[1:] == ['--cleanup']:
        with workspace_lock(ROOT_DIR, recovery=True):
            if restore_ownership():
                cleanup_owned_stack()
        return 0
    if sys.argv[1:]:
        raise ValueError('Usage: e2e_stack_test.py [--cleanup]')
    with workspace_lock(ROOT_DIR):
        return exercise_stack()


if __name__ == "__main__":
    sys.exit(main())
