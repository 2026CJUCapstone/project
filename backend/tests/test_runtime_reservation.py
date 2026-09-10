"""A durable build reservation is separate from routing and worker identities."""
import json

import pytest

from tests.test_edge_deploy import adapter, edge, deployment


def test_candidate_is_stable_across_retry_and_new_adapter_process(tmp_path,monkeypatch):
    deploy=deployment(tmp_path,monkeypatch)
    first=deploy.candidate('blue','a'*40)
    assert first.runtime_id and first.runtime_id!=first.generation
    other=adapter.Deployment(deploy.config,call=deploy.call)
    if __import__('os').name!='posix':
        from contextlib import nullcontext
        monkeypatch.setattr(other.store,'locked',nullcontext)
    assert other.candidate('blue','a'*40)==first
    for color,sha in [('green','a'*40),('blue','b'*40)]:
        with pytest.raises(edge.EdgeError,match='Unfinished candidate'):
            other.candidate(color,sha)
    assert other.reserved()==first


def test_switch_requires_exact_existing_reservation_and_uses_it(tmp_path,monkeypatch):
    deploy=deployment(tmp_path,monkeypatch)
    monkeypatch.setattr(deploy,'preflight',lambda:None)
    with pytest.raises(edge.EdgeError,match='reserved candidate'):
        deploy.switch('blue','a'*40)
    first=deploy.candidate('blue','a'*40)
    with pytest.raises(edge.EdgeError,match='reserved candidate'):
        deploy.switch('blue','b'*40)
    gates=[]
    monkeypatch.setattr(deploy,'gate',lambda target:gates.append(target) or True)
    monkeypatch.setattr(deploy,'verify',lambda *a,**kw:True)
    deploy.transaction.activate=lambda target:True
    assert deploy.switch('blue','a'*40)=='blue'
    assert gates==[first,first] and deploy.store.committed()==first
    # The reservation survives commit; cleanup crash cannot mint another ID.
    assert deploy.reserved()==first
    second=deploy.candidate('green','a'*40)
    assert second.runtime_id!=first.runtime_id and second.generation!=first.generation


def test_failed_preflight_keeps_reservation_but_failed_switch_blocks_rebuild(tmp_path,monkeypatch):
    deploy=deployment(tmp_path,monkeypatch)
    monkeypatch.setattr(deploy,'preflight',lambda:None)
    reserved=deploy.candidate('blue','a'*40)
    monkeypatch.setattr(deploy,'gate',lambda _:False)
    with pytest.raises(edge.EdgeError,match='preflight failed'):
        deploy.switch('blue','a'*40)
    assert deploy.candidate('blue','a'*40)==reserved
    monkeypatch.setattr(deploy,'gate',lambda _:True)
    monkeypatch.setattr(deploy,'verify',lambda target,**kw:target is None or not kw.get('edge'))
    deploy.transaction.activate=lambda target:True
    with pytest.raises(edge.EdgeError,match='committed route restored'):
        deploy.switch('blue','a'*40)
    assert deploy.reserved()==reserved
    with pytest.raises(edge.EdgeError,match='drain/retirement'):
        deploy.candidate('blue','a'*40)


@pytest.mark.parametrize('mutation',['runtime','ports','shape','symlink'])
def test_candidate_never_replaces_untrusted_existing_reservation(tmp_path,monkeypatch,mutation):
    deploy=deployment(tmp_path,monkeypatch)
    deploy.candidate('blue','a'*40)
    path=deploy.store.path/'state'/'candidate.json'
    data=json.loads(path.read_text())
    if mutation=='runtime':
        data['release']['runtime_id']=''
    elif mutation=='ports':
        data['release']['api_port']=19999
    elif mutation=='shape':
        data['extra']='unexpected'
    else:
        import os
        if os.name!='posix':
            pytest.skip('POSIX owned-file/symlink test')
        foreign=tmp_path/'foreign'
        foreign.write_text(path.read_text())
        path.unlink()
        path.symlink_to(foreign)
        with pytest.raises((OSError,edge.EdgeError)):
            deploy.candidate('blue','a'*40)
        assert path.is_symlink() and foreign.read_text()==json.dumps(data,sort_keys=True)
        return
    deploy.store.write(path,data)
    before=path.read_bytes()
    with pytest.raises(edge.EdgeError):
        deploy.candidate('blue','a'*40)
    assert path.read_bytes()==before
