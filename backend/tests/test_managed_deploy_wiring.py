"""Caller contracts alongside actual Docker/UDS tests, not a rollout substitute."""
from pathlib import Path

from tests.test_shared_runtime_config import function_block


ROOT = Path(__file__).resolve().parents[2]


def test_deploy_uses_transactional_edge_adapter_and_orders_gates():
    deploy = (ROOT/'scripts/deploy_server.sh').read_text()
    compose = function_block(deploy,'compose_for_color')
    overlays = ['docker-compose.yml','docker-compose.deploy.yml','docker-compose.shared-runtime.yml',
                'docker-compose.lb.yml','docker-compose.ready-lb.yml']
    positions = [compose.index(name) for name in overlays]
    assert positions == sorted(positions)
    assert 'WEBCOMPILER_API_PROXY_PORT_MAPPING="127.0.0.1:${backend_port}:8080"' in compose
    assert 'WEBCOMPILER_BACKEND_PORT_MAPPING=' not in compose
    assert 'COMPOSE_PROFILES=""' in compose
    pool_gate = function_block(deploy,'wait_for_color_pool')
    assert 'exec -T proxy-controller' in pool_gate
    assert ('app.proxy_promotion --release "$DEPLOY_SHA" --pool "$WEBCOMPILER_PROJECT_PREFIX-$color" '
            '--runtime "$WEBCOMPILER_RUNTIME_INSTANCE_ID"') in pool_gate

    preflight = deploy.index('python3 "$PROJECT_ROOT/scripts/edge_deploy.py" preflight')
    prepare = deploy.index('active_color="$(python3 "$PROJECT_ROOT/scripts/edge_deploy.py" prepare)"')
    archive = deploy.index('SOURCE_ROOT="$(bash "$PROJECT_ROOT/scripts/materialize_deploy_source.sh")"')
    secrets = deploy.index('scripts/runtime_secrets.py" ensure --emit-exports')
    candidate_assignment = ('WEBCOMPILER_RUNTIME_INSTANCE_ID="$(python3 '
                            '"$SOURCE_ROOT/scripts/edge_deploy.py" candidate --color "$target_color")"')
    candidate = deploy.index(candidate_assignment)
    instance_validation = deploy.index('[[ "$WEBCOMPILER_RUNTIME_INSTANCE_ID" =~ ^[0-9a-f]{32}$')
    instance_export = deploy.index('export WEBCOMPILER_RUNTIME_INSTANCE_ID')
    shared_postgres = deploy.index('\nensure_shared_postgres\n')
    network = deploy.index('scripts/ensure_api_network.py')
    sandbox = deploy.index('bash "$SOURCE_ROOT/scripts/build_sandbox_image.sh"')
    compose_up = deploy.index('compose_for_color "$target_color" up --no-build -d')
    compose_build = deploy.index('compose_for_color "$target_color" build --builder "$WEBCOMPILER_BUILD_BUILDER"')
    builder_gate = deploy.index('WEBCOMPILER_BUILD_CONTAINER_ID="$(python3')
    assert builder_gate < preflight
    assert sandbox < compose_build < compose_up
    assert 'up --build' not in deploy
    switch = deploy.index('actual_active_color="$(python3 "$SOURCE_ROOT/scripts/edge_deploy.py" switch --color "$target_color")"')

    assert preflight < secrets < prepare < archive < candidate
    assert candidate < instance_validation < instance_export < shared_postgres < network < sandbox < compose_up < switch
    assert ('WEBCOMPILER_API_NETWORK_CIDRS="$(COMPOSE_PROJECT_NAME="$WEBCOMPILER_PROJECT_PREFIX-$target_color" '
            in deploy)
    assert deploy.index('WEBCOMPILER_API_NETWORK_CIDRS="$(COMPOSE_PROJECT_NAME="$WEBCOMPILER_PROJECT_PREFIX-$target_color"') < compose_up
    assert 'COMPOSE_PROJECT_NAME="$WEBCOMPILER_PROJECT_PREFIX-$color"' in compose
    assert '-p "$WEBCOMPILER_PROJECT_PREFIX-$color"' in compose
    assert deploy.index('wait_for_color_pool "$target_color"') < switch
    assert deploy.count('wait_for_color_pool "$target_color"') == 1
    assert '[[ "$target_color" == "$active_color" ]]' in deploy
    assert deploy.index('[[ "$target_color" == "$active_color" ]]') < shared_postgres
    assert deploy.index('explicit database URL overrides require') < shared_postgres

    edge_deploy = (ROOT/'scripts/edge_deploy.py').read_text()
    preflight_adapter = edge_deploy[
        edge_deploy.index('    def preflight(self):'):edge_deploy.index('    def prepare(self):')
    ]
    assert 'self.store.inspect_existing()' in preflight_adapter
    assert 'self.read_projection()' in preflight_adapter
    assert 'self.runtime.preflight()' in preflight_adapter
    for mutation in ('self.store.initialize()', 'self.runtime.launch_committed()',
                     'self.transaction.recover()', 'self.store.write(', 'self.project()'):
        assert mutation not in preflight_adapter

    prepare_adapter = edge_deploy[
        edge_deploy.index('    def prepare(self):'):edge_deploy.index('    def verify(self,release')
    ]
    assert 'self.transaction.recover()' in prepare_adapter
    assert 'return self.project()' in prepare_adapter

    switch_adapter = edge_deploy[edge_deploy.index('    def switch(self,color,sha):'):]
    assert 'def before(target):' in switch_adapter
    assert 'def after(target):' in switch_adapter
    assert 'self.verify(target,edge=True) and self.gate(target)' in switch_adapter
    assert 'self.transaction.switch(release,preflight=before,postflight=after)' in switch_adapter

    for obsolete in (
        'write_edge_configs',
        'write_active_color',
        'active_color="$(tr -d',
        'stop_legacy_stack_if_present',
        'compose_for_color "$active_color" down',
        'docker stop',
        'docker rm',
        'STATE_FILE',
    ):
        assert obsolete not in deploy


def test_frontend_build_only_accepts_known_proxy_routes_and_refreshes_dns():
    dockerfile = (ROOT/'frontend/Dockerfile').read_text()
    nginx = (ROOT/'frontend/nginx.conf').read_text()
    assert 'ARG FRONTEND_API_UPSTREAM=backend:8000' in dockerfile
    assert 'FROM nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6' in dockerfile
    assert 'case "$FRONTEND_API_UPSTREAM" in' in dockerfile
    assert '*) exit 2' in dockerfile
    assert 'server api-proxy:8080 resolve;' in dockerfile
    assert 'resolver 127.0.0.11 valid=1s ipv6=off;' in nginx
    assert 'zone frontend_api 64k;' in nginx


def test_managed_backend_does_not_enable_uvicorn_proxy_headers():
    compose = (ROOT/'docker-compose.yml').read_text()
    backend = compose[compose.index('  backend:\n'):compose.index('  worker:\n')]
    assert '"--no-proxy-headers"' in backend


def test_ci_resolves_actual_five_overlay_color_graphs():
    workflow = (ROOT/'.github/workflows/ci.yml').read_text()
    assert 'RUN_SHARED_REDIS_INTEGRATION=1 python3 backend/tests/test_shared_runtime_live.py -v' in workflow
