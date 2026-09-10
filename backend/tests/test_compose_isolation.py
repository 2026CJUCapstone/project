"""Static compose regression checks; no YAML parser dependency is required."""
import re
from pathlib import Path


COMPOSE = Path(__file__).resolve().parents[2] / 'docker-compose.yml'


def service_block(compose: str, service: str) -> str:
    match = re.search(
        rf'^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)',
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f'{service} service is missing'
    return match.group('body')


def assert_runtime_environment_is_explicitly_disabled(compose: str, service: str) -> None:
    for name in ('AUTO_INITIALIZE_DB', 'EMBEDDED_EXECUTION_WORKER'):
        assert re.search(rf'{name}:\s*[\'\"]?false[\'\"]?', compose), f'{name} must be false'
    assert '<<: *backend-environment' in service or 'environment: *backend-environment' in service


def assert_initializer_gate(service: str) -> None:
    assert re.search(
        r'initialize:\s*(?:\n\s+|\{\s*)condition:\s*service_completed_successfully',
        service,
    )


def test_compose_separates_api_from_docker_and_repository_mounts():
    compose = COMPOSE.read_text(encoding='utf-8')
    backend = service_block(compose, 'backend')

    assert 'volumes:' not in backend
    assert '/var/run/docker.sock' not in backend
    assert '${PROJECT_ROOT}' not in backend
    assert_runtime_environment_is_explicitly_disabled(compose, backend)
    assert_initializer_gate(backend)


def test_compose_limits_docker_and_filesystem_access_to_the_worker():
    compose = COMPOSE.read_text(encoding='utf-8')
    worker = service_block(compose, 'worker')

    assert '/var/run/docker.sock:/var/run/docker.sock' in worker
    assert 'type: bind' in worker
    assert re.search(r'source:\s*\$\{PROJECT_ROOT[^}]*\}/\.sandbox-work', worker)
    assert re.search(r'target:\s*\$\{PROJECT_ROOT[^}]*\}/\.sandbox-work', worker)
    assert 'ports:' not in worker
    assert_runtime_environment_is_explicitly_disabled(compose, worker)
    assert_initializer_gate(worker)


def test_compose_runs_database_initialization_once_before_runtime_services():
    initialize = service_block(COMPOSE.read_text(encoding='utf-8'), 'initialize')

    assert re.search(r'command:\s*\[\s*[\'\"]python[\'\"]\s*,\s*[\'\"]-m[\'\"]\s*,\s*[\'\"]app\.initialize[\'\"]\s*\]', initialize)
    assert re.search(r'DATABASE_URL:.*@postgres:5432/', initialize)


def test_backend_image_anchor_and_runtime_privileges_are_hardened():
    compose = COMPOSE.read_text(encoding='utf-8')
    image_anchor = compose.split('services:', maxsplit=1)[0]
    initialize = service_block(compose, 'initialize')
    backend = service_block(compose, 'backend')
    worker = service_block(compose, 'worker')

    for setting in ('read_only: true', 'cap_drop: [ALL]', 'security_opt: [no-new-privileges:true]',
                    'tmpfs: ["/tmp:size=64m,mode=1777"]', 'max-size: "10m"', 'max-file: "3"'):
        assert setting in image_anchor
    assert 'user: "10001:10001"' in initialize
    assert 'user: "10001:10001"' in backend
    assert 'user: "${WEBCOMPILER_WORKER_UID:?Set sandbox directory owner UID}:${WEBCOMPILER_WORKER_GID:?Set sandbox directory owner GID}"' in worker
    assert 'group_add: ["${WEBCOMPILER_DOCKER_GID:?Set Docker socket group GID}"]' in worker
    for service in (initialize, backend, worker):
        memory = re.search(r'mem_limit:\s*(\S+)', service)
        assert memory
        assert re.search(rf'memswap_limit:\s*{re.escape(memory.group(1))}', service)
