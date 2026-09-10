import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TRANSACTION_SPEC = importlib.util.spec_from_file_location(
    'edge_transaction', ROOT / 'scripts' / 'edge_transaction.py'
)
edge_transaction = importlib.util.module_from_spec(TRANSACTION_SPEC)
# Dataclasses resolve the defining module through sys.modules while executing.
sys.modules[TRANSACTION_SPEC.name] = edge_transaction
TRANSACTION_SPEC.loader.exec_module(edge_transaction)


Release = edge_transaction.Release
Layout = edge_transaction.Layout
acknowledgment = edge_transaction.acknowledgment
render = edge_transaction.render

SHA = 'a' * 40
GENERATION = 'b' * 32


def release(**overrides):
    values = {
        'color': 'blue',
        'sha': SHA,
        'api_port': 18080,
        'frontend_port': 18081,
        'generation': GENERATION,
        'runtime_id': '',
    }
    values.update(overrides)
    return Release(**values)


def layout(**overrides):
    values = {'api_port': 28080, 'frontend_port': 28081}
    values.update(overrides)
    return Layout(**values)


def test_release_accepts_valid_color_sha_generation_and_ports():
    result = release()
    assert result.color == 'blue'
    assert release(color='green').color == 'green'
    assert result.sha == SHA
    assert result.generation == GENERATION
    assert (result.api_port, result.frontend_port) == (18080, 18081)


@pytest.mark.parametrize('field,value', [
    ('color', 'red'),
    ('color', 'blue; proxy_pass http://evil'),
    ('sha', None),
    ('sha', 'a' * 39),
    ('sha', 'A' * 40),
    ('sha', 'a' * 39 + ';'),
    ('generation', None),
    ('generation', 'b' * 31),
    ('generation', 'B' * 32),
    ('generation', '0' * 32),
    ('generation', 'b' * 31 + ';'),
    ('api_port', 1023),
    ('api_port', 65536),
    ('api_port', True),
    ('frontend_port', 1023),
    ('frontend_port', 65536),
    ('frontend_port', '18081; proxy_pass http://evil'),
])
def test_release_rejects_one_invalid_field_at_a_time(field, value):
    with pytest.raises(ValueError):
        release(**{field: value})


def test_release_rejects_equal_upstream_ports():
    with pytest.raises(ValueError):
        release(frontend_port=18080)


@pytest.mark.parametrize('field,value', [
    ('api_port', 1023),
    ('api_port', 65536),
    ('api_port', False),
    ('api_port', '28080; proxy_pass http://evil'),
    ('frontend_port', 1023),
    ('frontend_port', 65536),
    ('frontend_port', True),
    ('frontend_port', '28081; proxy_pass http://evil'),
])
def test_layout_rejects_one_invalid_field_at_a_time(field, value):
    with pytest.raises(ValueError):
        layout(**{field: value})


def test_layout_rejects_equal_listener_ports():
    with pytest.raises(ValueError):
        layout(frontend_port=28080)


@pytest.mark.parametrize('field,value', [
    ('api_port', 18080),
    ('api_port', 18081),
    ('frontend_port', 18080),
    ('frontend_port', 18081),
])
def test_render_rejects_loopback_self_routing(field, value):
    with pytest.raises(ValueError):
        render(layout(**{field: value}), release())


def test_acknowledgment_describes_layout_release_and_template():
    current_layout = layout()
    current_release = release()
    info = acknowledgment(current_layout, current_release)

    assert info['generation'] == GENERATION
    assert info['release'] == {
        'color': 'blue',
        'sha': SHA,
        'api_port': 18080,
        'frontend_port': 18081,
        'generation': GENERATION,
        'runtime_id': '',
    }
    assert info['layout'] == {'api_port': 28080, 'frontend_port': 28081, 'trusted_ingress': ''}
    assert len(info['templateSha256']) == 64
    assert f"return 200 '{json.dumps(info, sort_keys=True)}';" in render(current_layout, current_release)


def test_render_uses_two_loopback_listeners_and_unix_only_configuration_ack():
    rendered = render(layout(), release())

    assert rendered.count('listen 127.0.0.1:') == 2
    assert 'listen 127.0.0.1:28080;' in rendered
    assert 'listen 127.0.0.1:28081;' in rendered
    assert rendered.count('listen unix:/status/control.sock;') == 1
    assert rendered.count('location = /configuration') == 3
    assert rendered.count('location = /configuration { return 200 ') == 1
    assert rendered.count('location = /configuration { return 404; }') == 2
    public_servers = rendered.split('listen 127.0.0.1:')[1:]
    assert all('location = /configuration { return 404; }' in server for server in public_servers)


def test_render_hides_generation_from_public_listeners():
    rendered = render(layout(), release())

    assert "location = /generation { return 200 '" in rendered
    assert rendered.count('location = /generation { return 404; }') == 2
    assert rendered.count('location = /_edge_generation { return 404; }') == 2


def test_render_caps_shutdown_and_disables_post_retry():
    rendered = render(layout(), release())

    assert rendered.count('worker_shutdown_timeout 150s;') == 1
    assert rendered.count('proxy_next_upstream off;') == 1


def test_render_routes_api_and_websocket_prefixes_to_expected_upstreams():
    rendered = render(layout(), release())

    expected_routes = [
        'location /webcompiler/api/ { proxy_pass http://color_api/api/; }',
        'location /api/ { proxy_pass http://color_api; }',
        'location /webcompiler/ws/terminal { proxy_pass http://color_api/ws/terminal; proxy_read_timeout 3600s; }',
        'location /ws/terminal { proxy_pass http://color_api; proxy_read_timeout 3600s; }',
    ]
    for route in expected_routes:
        assert rendered.count(route) == 2


def test_closed_bootstrap_renders_both_loopback_listeners_as_503():
    current_layout = layout()
    rendered = render(current_layout, None)

    assert 'upstream color_api' not in rendered
    assert 'upstream color_frontend' not in rendered
    assert rendered.count('listen 127.0.0.1:') == 2
    assert 'listen 127.0.0.1:28080;' in rendered
    assert 'listen 127.0.0.1:28081;' in rendered
    assert rendered.count('return 503;') == 2
    assert acknowledgment(current_layout, None)['release'] is None
