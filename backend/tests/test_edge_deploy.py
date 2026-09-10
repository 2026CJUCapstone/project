from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading

import pytest


ROOT=Path(__file__).resolve().parents[2]
for name in ('edge_transaction','edge_runtime','runtime_inventory','runtime_binding','sandbox_inventory','runtime_retirement','edge_deploy'):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
edge=sys.modules['edge_transaction']
adapter=sys.modules['edge_deploy']


def deployment(tmp_path,monkeypatch,*,initialize=True):
    (tmp_path/'.deploy').mkdir()
    cfg=adapter.Config(tmp_path,edge.Layout(18000,15173),(18001,15174),(18002,15175))
    deploy=adapter.Deployment(cfg,call=lambda _:pytest.fail('unexpected Docker call'))
    if initialize:
        deploy.store.initialize()
    if os.name!='posix':
        monkeypatch.setattr(deploy.store,'locked',nullcontext)
    # These routing/transaction fixtures have no application containers.
    # Dedicated inventory tests exercise the actual ownership boundary.
    monkeypatch.setattr(deploy,'capture_inventory',lambda _:True)
    monkeypatch.setattr(deploy,'verify_inventory',lambda _:True)
    return deploy


def test_readonly_preflight_refuses_legacy_projection_without_creating_state(tmp_path,monkeypatch):
    deploy=deployment(tmp_path,monkeypatch,initialize=False)
    deploy.projection.write_text('blue\n')
    with pytest.raises(edge.EdgeError,match='Legacy active-color'):
        deploy.preflight()
    assert not deploy.store.path.exists()
    assert deploy.projection.read_text()=='blue\n'


def test_readonly_preflight_never_stops_legacy_container(tmp_path,monkeypatch):
    deploy=deployment(tmp_path,monkeypatch,initialize=False)
    calls=[]
    def call(args):
        calls.append(args)
        return 'webcompiler-edge-frontend\n'
    deploy.call=call
    with pytest.raises(edge.EdgeError,match='nothing stopped'):
        deploy.preflight()
    assert calls==[['container','ls','-a','--format','{{.Names}}']]
    assert not deploy.store.path.exists()


def test_prepare_repairs_stale_projection_from_commit_without_reloading(tmp_path,monkeypatch):
    deploy=deployment(tmp_path,monkeypatch)
    blue=deploy.config.release('blue','a'*40)
    deploy.store.commit(blue)
    deploy.projection.write_text('green\n')
    monkeypatch.setattr(deploy,'preflight',lambda:{'State':{'Running':True}})
    deploy.transaction.observe=lambda:deploy.store.expected(blue)
    deploy.transaction.activate=lambda _:pytest.fail('clean committed recovery must not reload')
    monkeypatch.setattr(deploy,'verify',lambda release,**_:release==blue)
    assert deploy.prepare()=='blue'
    assert deploy.projection.read_text()=='blue\n'
    assert deploy.prepare()=='blue'


def test_failed_switch_preserves_old_projection_and_journals_candidate_for_drain(tmp_path,monkeypatch):
    deploy=deployment(tmp_path,monkeypatch)
    blue=deploy.config.release('blue','a'*40)
    deploy.store.commit(blue)
    deploy.project()
    monkeypatch.setattr(deploy,'preflight',lambda:None)
    gate=[]
    monkeypatch.setattr(deploy,'gate',lambda release:gate.append(release.color) or True)
    monkeypatch.setattr(deploy,'verify',lambda release,**kw:not (kw.get('edge') and release.color=='green'))
    activated=[]
    deploy.transaction.activate=lambda release:activated.append(release.color) or True
    deploy.candidate('green','b'*40)
    with pytest.raises(edge.EdgeError,match='committed route restored'):
        deploy.switch('green','b'*40)
    assert deploy.projection.read_text()=='blue\n'
    assert deploy.store.committed()==blue
    assert activated==['green','blue']
    assert gate==['green']  # Recovery of old service does not demand a new promotion.
    with pytest.raises(edge.EdgeError,match='drain/retirement'):
        deploy.candidate('green','b'*40)


def test_projection_write_failure_after_commit_never_reverts_new_authority(tmp_path,monkeypatch):
    deploy=deployment(tmp_path,monkeypatch)
    deploy.store.commit(deploy.config.release('blue','a'*40))
    deploy.project()
    monkeypatch.setattr(deploy,'preflight',lambda:{'State':{'Running':True}})
    monkeypatch.setattr(deploy,'gate',lambda _:True)
    monkeypatch.setattr(deploy,'verify',lambda *a,**kw:True)
    deploy.transaction.activate=lambda _:True
    original=deploy.store.write
    def fail_projection(path,value):
        if path==deploy.projection:
            raise OSError('injected projection write failure')
        return original(path,value)
    monkeypatch.setattr(deploy.store,'write',fail_projection)
    deploy.candidate('green','b'*40)
    with pytest.raises(OSError,match='projection write'):
        deploy.switch('green','b'*40)
    assert deploy.store.committed().color=='green'
    assert deploy.projection.read_text()=='blue\n'
    monkeypatch.setattr(deploy.store,'write',original)
    deploy.transaction.observe=lambda:deploy.store.expected(deploy.store.committed())
    assert deploy.prepare()=='green'
    with pytest.raises(edge.EdgeError,match='committed color'):
        deploy.candidate('green','b'*40)


@pytest.mark.parametrize('case',['success','missing','wrong-release','rejected'])
def test_color_gate_requires_one_exact_controller_and_successful_two_peer_gate(tmp_path,monkeypatch,case):
    deploy=deployment(tmp_path,monkeypatch)
    release=deploy.config.release('green','b'*40)
    identity='f'*64
    def call(args):
        if args[:2]==['container','ls']:
            assert 'label=com.docker.compose.project=webcompiler-green' in args
            assert 'label=com.docker.compose.service=proxy-controller' in args
            return '' if case=='missing' else identity+'\n'
        assert args==['container','inspect',identity]
        sha='a'*40 if case=='wrong-release' else release.sha
        return json.dumps([{'Id':identity,'State':{'Running':True},
                            'Config':{'Env':['DEPLOYMENT_SHA='+sha,'PROXY_POOL_ID=webcompiler-green',
                                             'RUNTIME_INSTANCE_ID='+release.runtime_id]}}])
    deploy.call=call
    executions=[]
    def run(args,**kwargs):
        executions.append(args)
        assert kwargs=={'capture_output':True,'timeout':70}
        from types import SimpleNamespace
        return SimpleNamespace(returncode=1 if case=='rejected' else 0)
    monkeypatch.setattr(adapter.subprocess,'run',run)
    if case=='success':
        assert deploy.gate(release) is True
    else:
        with pytest.raises(edge.EdgeError):
            deploy.gate(release)
    if case in ('missing','wrong-release'):
        assert executions==[]
    else:
        assert executions==[['docker','exec',identity,'python','-m','app.proxy_promotion',
                             '--release',release.sha,'--pool','webcompiler-green','--runtime',release.runtime_id]]


@pytest.mark.parametrize('failed', ['sha','ready','marker','listener'])
def test_app_verification_checks_both_edge_listeners_and_independent_static_marker(tmp_path,monkeypatch,failed):
    deploy=deployment(tmp_path,monkeypatch)
    release=deploy.config.release('green','b'*40)
    paths=[]
    def probe(port,path):
        paths.append((port,path))
        if path=='/health':
            sha='a'*40 if failed=='sha' else release.sha
            if failed=='listener' and port==deploy.config.layout.frontend_port:
                sha='a'*40
            return 200,{'status':'ok','deploymentSha':sha,'runtimeInstanceId':release.runtime_id}
        if path=='/ready':
            return (503,{'status':'unavailable'}) if failed=='ready' else (200,{'status':'ready'})
        return 200,{'deployment_sha':'non-release' if failed=='marker' else release.sha}
    deploy.probe=probe
    monkeypatch.setattr(adapter,'wait_postflight',lambda check,**kw:check())
    assert deploy.verify(release,edge=True) is False
    if failed=='marker':
        assert paths==[(18000,'/health'),(18000,'/ready'),(15173,'/health'),(15173,'/ready'),
                       (15173,'/webcompiler/.well-known/webcompiler-release.json')]


@pytest.mark.parametrize('header,body,expected',[
    ('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 15',b'{"status":"ok"}',(200,{'status':'ok'})),
    ('HTTP/1.1 503 Unavailable\r\nContent-Length: 3',b'bad',(503,None)),
    ('HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2',b'{}',None),
    ('HTTP/1.1 200 OK\r\nContent-Length: 2\r\ncontent-length: 2',b'{}',None),
    ('HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 2',b'{}',None),
    ('HTTP/1.1 200 OK\r\nContent-Length: 9999',b'{}',None),
])
def test_real_loopback_probe_framing_and_bounds(header,body,expected):
    with socket.socket() as server:
        server.bind(('127.0.0.1',0))
        server.listen(1)
        server.settimeout(3)
        errors=[]
        def respond():
            try:
                client,_=server.accept()
                with client:
                    client.settimeout(3)
                    request=client.recv(4096)
                    assert request.startswith(b'GET /health HTTP/1.1\r\n')
                    client.sendall(header.encode()+b'\r\n\r\n'+body)
            except Exception as error:
                errors.append(error)
        thread=threading.Thread(target=respond)
        thread.start()
        try:
            if expected is None:
                with pytest.raises((edge.EdgeError,ValueError)):
                    adapter.loopback_json(server.getsockname()[1],'/health')
            else:
                assert adapter.loopback_json(server.getsockname()[1],'/health')==expected
        finally:
            thread.join(4)
            assert not thread.is_alive()
        assert not errors
