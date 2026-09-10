"""Static production shared-runtime regression checks; no Docker daemon required."""
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OVERLAY = PROJECT_ROOT / "docker-compose.shared-runtime.yml"
READY_OVERLAY = PROJECT_ROOT / "docker-compose.ready-lb.yml"
BASE_COMPOSE = PROJECT_ROOT / "docker-compose.yml"
DEPLOY = PROJECT_ROOT / "scripts" / "deploy_server.sh"
REDIS_HELPER = PROJECT_ROOT / "scripts" / "ensure_shared_redis.py"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"{service} service is missing from the shared-runtime overlay"
    return match.group("body")


def function_block(script: str, name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{(?P<body>.*?)^\}}",
        script,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"{name} function is missing"
    return match.group("body")


def workflow_step(workflow: str, name: str) -> str:
    match = re.search(
        rf"^      - name: {re.escape(name)}\n        run: \|\n(?P<body>.*?)(?=^      - name:|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"CI step {name!r} is missing"
    return match.group("body")


def test_production_overlay_excludes_color_local_stateful_dependencies():
    overlay = OVERLAY.read_text(encoding="utf-8")

    for service in ("postgres", "redis"):
        assert re.search(
            rf"^  {service}:\n    profiles: \[legacy-color-infra\]$",
            overlay,
            flags=re.MULTILINE,
        ), f"{service} must be disabled for a production color"

    for service in ("initialize", "pgbouncer", "backend", "worker"):
        runtime_service = service_block(overlay, service)
        dependency = re.search(
            r"^    depends_on:.*?(?=^    [A-Za-z0-9_-]+:|\Z)",
            runtime_service,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert dependency, f"{service} must override base color-local dependencies"
        assert not re.search(r"\b(?:postgres|redis)\b", dependency.group(0)), (
            f"{service} must not depend on a color-local PostgreSQL or Redis service"
        )

    assert "redis://redis:" not in overlay
    assert "@postgres:" not in overlay


def test_runtime_roles_share_one_required_redis_url_and_namespace():
    overlay = OVERLAY.read_text(encoding="utf-8")
    expected_url = "${WEBCOMPILER_REDIS_URL:?Set the shared Redis URL}"
    expected_prefix = "${WEBCOMPILER_REDIS_KEY_PREFIX:?Set a color-independent Redis namespace}"

    for service in ("initialize", "backend", "worker"):
        runtime_service = service_block(overlay, service)
        assert f"REDIS_URL: {expected_url}" in runtime_service
        assert f"REDIS_KEY_PREFIX: {expected_prefix}" in runtime_service


def test_production_roles_require_one_managed_postgres_credential_without_url_bypass():
    overlay = OVERLAY.read_text(encoding="utf-8")
    ready_overlay = READY_OVERLAY.read_text(encoding="utf-8")
    expected_password = "${WEBCOMPILER_POSTGRES_PASSWORD:?Set an explicit shared PostgreSQL credential}"

    for service in ("initialize", "pgbouncer", "backend", "worker"):
        assert expected_password in service_block(overlay, service)

    for service in ("backend", "worker"):
        runtime_service = service_block(ready_overlay, service)
        assert expected_password in runtime_service
        assert "WEBCOMPILER_DATABASE_URL" not in runtime_service

    assert "WEBCOMPILER_MIGRATION_DATABASE_URL" not in service_block(overlay, "initialize")


def test_runtime_readiness_pool_is_derived_from_the_actual_compose_project():
    overlay = OVERLAY.read_text(encoding="utf-8")
    expected_pool = "${COMPOSE_PROJECT_NAME:?Set the color project}"

    for service in ("backend", "worker"):
        runtime_service = service_block(overlay, service)
        assert f"RUNTIME_POOL_ID: {expected_pool}" in runtime_service


def test_reserved_runtime_instance_reaches_exact_candidate_roles_only():
    overlay = OVERLAY.read_text(encoding="utf-8")
    ready_overlay = READY_OVERLAY.read_text(encoding="utf-8")
    expected_instance = "${WEBCOMPILER_RUNTIME_INSTANCE_ID:?Set the reserved runtime instance}"

    for service in ("initialize", "backend", "worker"):
        assert f"RUNTIME_INSTANCE_ID: {expected_instance}" in service_block(overlay, service)
    for service in ("proxy-control-init", "proxy-controller"):
        assert f"RUNTIME_INSTANCE_ID: {expected_instance}" in service_block(ready_overlay, service)

    assert f"-{expected_instance}" in service_block(ready_overlay, "proxy_control")
    assert "${RUNTIME_INSTANCE_ID" not in overlay
    assert "${RUNTIME_INSTANCE_ID" not in ready_overlay


def test_managed_trusted_ingress_is_explicit_and_uses_the_transport_peer():
    ready_overlay = READY_OVERLAY.read_text(encoding="utf-8")
    api_cidrs = "${WEBCOMPILER_API_NETWORK_CIDRS:?Set the private API network CIDRs}"
    ingress_cidrs = "${WEBCOMPILER_PROXY_TRUSTED_INGRESS_CIDRS:?Set verified host-edge peer CIDRs}"

    assert f"TRUSTED_PROXY_CIDRS: {api_cidrs}" in service_block(ready_overlay, "backend")
    for service in ("proxy-control-init", "proxy-controller"):
        assert f"PROXY_TRUSTED_INGRESS_CIDRS: {ingress_cidrs}" in service_block(ready_overlay, service)

    # Compose replaces the image CMD, so this must be present in the actual
    # backend service command rather than only in backend/Dockerfile.
    assert '"--no-proxy-headers"' in service_block(
        BASE_COMPOSE.read_text(encoding="utf-8"), "backend"
    )


def test_production_compose_uses_the_shared_runtime_overlay_and_endpoint():
    deploy = DEPLOY.read_text(encoding="utf-8")
    compose = function_block(deploy, "compose_for_color")

    assert '-f "$SOURCE_ROOT/docker-compose.shared-runtime.yml"' in compose
    assert compose.index('docker-compose.deploy.yml') < compose.index('docker-compose.shared-runtime.yml')
    assert "--profile legacy-color-infra" not in compose
    assert 'managed_redis_url="redis://${WEBCOMPILER_SHARED_REDIS_NAME}:6379/0"' in deploy
    assert 'export WEBCOMPILER_REDIS_URL="${WEBCOMPILER_REDIS_URL:-$managed_redis_url}"' in deploy
    assert 'export WEBCOMPILER_REDIS_KEY_PREFIX="${WEBCOMPILER_REDIS_KEY_PREFIX:-$WEBCOMPILER_PROJECT_PREFIX}"' in deploy
    assert 'python3 "$SOURCE_ROOT/scripts/ensure_shared_redis.py"' in deploy


def test_ci_resolves_the_shared_runtime_overlay_for_both_deployment_colors():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    step = workflow_step(workflow, "Validate Shared Runtime Compose Overlay For Both Colors")

    for expected in (
        'COMPOSE_PROFILES=""',
        '--env-file /dev/null',
        '-f docker-compose.yml',
        '-f docker-compose.deploy.yml',
        '-f docker-compose.shared-runtime.yml',
        'config --format json > "$config"',
        'WEBCOMPILER_POSTGRES_PASSWORD="webcompiler-ci-shared-postgres-password-12345"',
        'WEBCOMPILER_DATABASE_URL="postgresql+psycopg2://caller:caller@external.invalid:5432/caller"',
        'WEBCOMPILER_MIGRATION_DATABASE_URL="postgresql+psycopg2://caller:caller@external.invalid:5432/caller"',
        'WEBCOMPILER_REDIS_URL="redis://webcompiler-redis:6379/0"',
        'WEBCOMPILER_REDIS_KEY_PREFIX="webcompiler-ci-shared"',
        'RUNTIME_POOL_ID="caller-pool-must-not-win"',
        'WEBCOMPILER_RUNTIME_INSTANCE_ID="11111111111111111111111111111111"',
        'RUNTIME_INSTANCE_ID="ffffffffffffffffffffffffffffffff"',
        'SANDBOX_POOL_ID="webcompiler-ci-shared-sandbox"',
        "validate_shared_runtime_color blue 18101 15174",
        "validate_shared_runtime_color green 18102 15175",
    ):
        assert expected in step

    # The workflow's inline Python checks the resolved Compose model, rather
    # than trusting that the overlay text alone describes active services.
    for expected in (
        'service not in services',
        'environment.get("REDIS_URL") == expected_url',
        'environment.get("REDIS_KEY_PREFIX") == expected_prefix',
        'environment.get("RUNTIME_POOL_ID") == expected_pool',
        'environment.get("RUNTIME_INSTANCE_ID") == expected_instance',
        'environment.get("RUNTIME_INSTANCE_ID") != caller_instance',
        'environment.get("SANDBOX_POOL_ID") == expected_sandbox_pool',
        'urlsplit(url)',
        'parsed.password == expected_password',
        '"postgres" not in dependencies and "redis" not in dependencies',
        'pooler.get("environment", {}).get("DB_HOST") == "webcompiler-postgres"',
    ):
        assert expected in step


def test_deploy_never_automatically_deletes_shared_runtime_resources():
    deploy = DEPLOY.read_text(encoding="utf-8")
    helper = REDIS_HELPER.read_text(encoding="utf-8")

    assert 'compose_for_color "$target_color" up --no-build -d' in deploy
    assert '--remove-orphans' not in deploy
    assert 'compose_for_color "$active_color" down' not in deploy
    assert 'stop_legacy_stack_if_present' not in deploy
    assert 'stop --timeout 150 frontend backend worker pgbouncer' not in deploy
    assert 'docker stop' not in deploy
    assert 'docker rm' not in deploy
    assert 'write_edge_configs' not in deploy
    assert 'write_active_color' not in deploy
    assert 'STATE_FILE' not in deploy
    assert "--volumes" not in deploy

    assert not re.search(
        r"\[\s*['\"](?:container|volume|network)['\"]\s*,\s*['\"](?:rm|remove|prune)['\"]",
        helper,
    )
    assert not re.search(r"\bdocker\s+(?:rm|volume\s+rm|network\s+rm)\b", helper)
    for destructive_command in ("FLUSHALL", "FLUSHDB", "shutdown", "--volumes"):
        assert destructive_command not in helper


def test_existing_runtime_redis_preflight_precedes_shared_setup_and_new_color():
    deploy = DEPLOY.read_text(encoding='utf-8')
    preflight = deploy.index('python3 "$PROJECT_ROOT/scripts/edge_deploy.py" preflight')
    prepare = deploy.index('active_color="$(python3 "$PROJECT_ROOT/scripts/edge_deploy.py" prepare)"')
    archive = deploy.index('SOURCE_ROOT="$(bash "$PROJECT_ROOT/scripts/materialize_deploy_source.sh")"')
    secrets = deploy.index('scripts/runtime_secrets.py" ensure --emit-exports')
    candidate = deploy.index('python3 "$SOURCE_ROOT/scripts/edge_deploy.py" candidate --color "$target_color"')
    redis_cutover = deploy.index('python3 "$SOURCE_ROOT/scripts/verify_shared_redis_cutover.py"')
    shared_postgres = deploy.index('\nensure_shared_postgres\n')
    compose = deploy.index('compose_for_color "$target_color" up --no-build -d')

    assert preflight < secrets < prepare < archive < candidate
    assert candidate < redis_cutover < shared_postgres < compose
    assert 'active_color="$(tr -d' not in deploy
    assert 'WEBCOMPILER_DEPLOY_ACTIVE_COLOR="$active_color"' in deploy
