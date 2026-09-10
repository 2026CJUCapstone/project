import importlib.util
import re
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'render_api_proxy.py'
LB_COMPOSE = Path(__file__).resolve().parents[2] / 'docker-compose.lb.yml'
SPEC = importlib.util.spec_from_file_location('render_api_proxy', SCRIPT)
assert SPEC and SPEC.loader
render_api_proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_api_proxy)


def compose_service(compose: str, service: str) -> str:
    match = re.search(
        rf'^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)',
        compose,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f'{service} service is missing'
    return match.group('body')


def test_proxy_renderer_uses_distinct_least_conn_upstreams_and_safe_headers():
    config = render_api_proxy.render(['api-one:8000', 'api-two:8001'])

    assert 'least_conn;' in config
    assert 'server api-one:8000 max_fails=1 fail_timeout=2s;' in config
    assert 'server api-two:8001 max_fails=1 fail_timeout=2s;' in config
    assert 'proxy_set_header Upgrade $http_upgrade;' in config
    assert 'proxy_set_header Connection $connection_upgrade;' in config
    assert 'client_header_timeout 10s;' in config
    assert 'client_body_timeout 10s;' in config
    for path in ('/tmp/client_body', '/tmp/proxy_temp', '/tmp/fastcgi', '/tmp/uwsgi', '/tmp/scgi'):
        assert path in config
    assert 'proxy_set_header X-Forwarded-For $remote_addr;' in config
    assert '$proxy_add_x_forwarded_for' not in config
    assert 'X-Audit-Upstream' not in config


def test_proxy_renderer_exposes_diagnostic_upstream_only_when_requested():
    config = render_api_proxy.render(['api-one:8000'], diagnostic_header=True)

    assert 'add_header X-Audit-Upstream $upstream_addr always;' in config


def test_proxy_renderer_uses_docker_dns_only_when_explicitly_requested():
    config = render_api_proxy.render(['api-one:8000'], resolve_docker=True)

    assert 'resolver 127.0.0.11 valid=1s ipv6=off; resolver_timeout 2s;' in config
    assert 'server api-one:8000 max_fails=1 fail_timeout=2s resolve;' in config


def test_load_balancer_compose_keeps_backends_private_and_proxy_minimal():
    compose = LB_COMPOSE.read_text(encoding='utf-8')
    backend = compose_service(compose, 'backend')
    proxy = compose_service(compose, 'api-proxy')

    assert 'ports: !reset []' in backend
    assert 'replicas: ${WEBCOMPILER_API_REPLICAS:-2}' in backend
    assert 'user: "10001:10001"' in proxy
    for setting in ('read_only: true', 'cap_drop: [ALL]', 'security_opt: [no-new-privileges:true]',
                    'tmpfs: ["/tmp:size=32m,mode=1777,noexec,nosuid"]'):
        assert setting in proxy
    assert '/var/run/docker.sock' not in proxy
    assert '${WEBCOMPILER_API_PROXY_PORT_MAPPING:-127.0.0.1:18000:8080}' in proxy
    assert 'http://127.0.0.1:8080/ready' in proxy
    assert '"wget", "-q", "-O", "/dev/null"' in proxy
    for setting in ('mem_limit: 96m', 'memswap_limit: 96m', 'cpus: 0.25', 'pids_limit: 64'):
        assert setting in proxy


def test_load_balancer_renderer_contract_uses_docker_dns_for_backend_replicas():
    config = render_api_proxy.render(['backend:8000'], resolve_docker=True)

    assert 'resolver 127.0.0.11 valid=1s ipv6=off; resolver_timeout 2s;' in config
    assert 'server backend:8000 max_fails=1 fail_timeout=2s resolve;' in config


def test_proxy_renderer_retries_a_fresh_peer_generation_only_for_safe_reads():
    config = render_api_proxy.render(['backend:8000'], resolve_docker=True)

    assert config.count('error_page 502 504 = @fresh_read;') == 1
    assert 'location @fresh_read {' in config
    assert "if ($request_method !~ ^(GET|HEAD)$) { return 502; }" in config
    assert "if ($http_upgrade != '') { return 502; }" in config
    assert 'proxy_next_upstream_tries 2;' in config
    assert 'proxy_next_upstream_non_idempotent' not in config
    assert 'proxy_intercept_errors' not in config


@pytest.mark.parametrize('endpoint', [
    'api:8000\nserver attacker:80;',
    'api:8000; add_header X-Injected yes;',
    'api:8000/evil',
    'api:8000{',
    'api:0',
    'api:65536',
    '',
])
def test_proxy_renderer_rejects_injectable_or_invalid_endpoints(endpoint):
    with pytest.raises(ValueError):
        render_api_proxy.render([endpoint])


def test_proxy_renderer_rejects_empty_duplicate_and_oversized_upstream_lists():
    with pytest.raises(ValueError):
        render_api_proxy.render([])
    with pytest.raises(ValueError):
        render_api_proxy.render(['api:8000', 'api:8000'])
    with pytest.raises(ValueError):
        render_api_proxy.render([f'api-{index}:8000' for index in range(33)])
