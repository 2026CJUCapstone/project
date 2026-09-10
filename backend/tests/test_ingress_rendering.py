import json
import os
from pathlib import Path

import pytest

from app.proxy_initialize import initialize
from app.proxy_membership import Config
from app.services.api_proxy_config import render, render_managed
from app.services.trusted_ingress import nginx_ingress
from tests.test_edge_renderer import edge_transaction as edge


def test_trusted_nginx_hop_sanitizes_chain_and_preserves_transport_control_boundary():
    config = render_managed(['backend:8000'], 'a'*32, trusted_ingress='172.20.0.1/32')
    assert 'set_real_ip_from 172.20.0.1/32;' in config
    assert 'real_ip_header X-Forwarded-For;' in config and 'real_ip_recursive off;' in config
    assert 'geo $realip_remote_addr $webcompiler_trusted_peer' in config
    assert 'proxy_set_header X-Forwarded-For $remote_addr;' in config
    assert 'proxy_set_header X-Forwarded-Proto $webcompiler_client_scheme;' in config
    assert 'proxy_set_header Forwarded "";' in config
    assert 'proxy_add_x_forwarded_for' not in config
    protected = config.split('location = /_proxy_generation {', 1)[1]
    assert 'if ($webcompiler_control_peer = 0) { return 403; }' in protected
    assert 'geo $realip_remote_addr $webcompiler_control_peer' in config
    assert 'allow 127.0.0.1;' in protected and 'deny all;' in protected


def test_empty_trust_is_disabled_and_invalid_config_cannot_be_injected():
    assert nginx_ingress('') == ('', '$scheme')
    assert 'set_real_ip_from' not in render(['backend:8000'])
    for value in ('*', '0.0.0.0/0', '127.0.0.1; return 200;', 'unix:'):
        with pytest.raises(ValueError):
            render(['backend:8000'], trusted_ingress=value)
        with pytest.raises(ValueError):
            Config('backend', 8000, 'a'*40, ('172.20.0.0/24',), trusted_ingress=value)


def test_edge_trust_is_part_of_acknowledgment_and_immutable_owner_layout(tmp_path):
    layout = edge.Layout(18000, 15173, '127.0.0.1')
    assert layout.trusted_ingress == '127.0.0.1/32'
    release = edge.Release('blue', 'a'*40, 18001, 15174, 'b'*32)
    config = edge.render(layout, release)
    assert 'set_real_ip_from 127.0.0.1/32;' in config
    assert 'proxy_set_header X-Forwarded-Proto $webcompiler_client_scheme;' in config
    ack = edge.acknowledgment(layout, release)
    assert ack['layout']['trusted_ingress'] == '127.0.0.1/32'
    assert ack['templateSha256'] != edge.acknowledgment(edge.Layout(18000, 15173), release)['templateSha256']
    store = edge.Store(tmp_path/'edge', layout)
    store.initialize()
    with pytest.raises(edge.EdgeError, match='another layout'):
        edge.Store(store.path, edge.Layout(18000, 15173, '127.0.0.2')).initialize()


@pytest.mark.skipif(os.name != 'posix', reason='Actual private volume UID/GID required')
def test_proxy_initializer_preserves_and_refuses_changed_trust_policy(tmp_path):
    directory = tmp_path/'control'
    directory.mkdir()
    args = dict(uid=os.getuid(), gid=os.getgid(), trusted_ingress='172.20.0.1')
    initialize(directory, 'a'*40, 'audit-pool', **args)
    before = (directory/'nginx.conf').read_bytes()
    assert json.loads((directory/'owner.json').read_text())['trustedIngress'] == '172.20.0.1/32'
    initialize(directory, 'a'*40, 'audit-pool', **args)
    with pytest.raises(ValueError, match='another release'):
        initialize(directory, 'a'*40, 'audit-pool', **{**args, 'trusted_ingress':'172.20.0.2'})
    assert (directory/'nginx.conf').read_bytes() == before
