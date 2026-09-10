"""Real child IO is bounded before parsing secret-bearing Docker inspect."""
import sys

import pytest

from tests.test_edge_deploy import adapter, edge


@pytest.mark.parametrize('case',['success','oversize','timeout','exit'])
def test_bounded_cli_reader_owns_and_reaps_its_child(monkeypatch,case):
    namespace = adapter.bounded_docker.__globals__
    process_module = namespace['subprocess']
    create = process_module.Popen
    children = []
    scripts = {'success':'print("[]")','oversize':'print("fixture-secret"*10000)',
        'timeout':'import time; time.sleep(60)','exit':'import sys; print("fixture-secret"); sys.exit(2)'}
    def spawn(args,**options):
        assert args==['docker','container','inspect','a'*64]
        child = create([sys.executable,'-c',scripts[case]],**options)
        children.append(child)
        return child
    monkeypatch.setattr(process_module,'Popen',spawn)
    monkeypatch.setitem(namespace,'MAX_RAW_BYTES',4096)
    if case=='success':
        assert adapter.bounded_docker(['container','inspect','a'*64],timeout=2).strip()=='[]'
    else:
        with pytest.raises(edge.EdgeError) as error:
            adapter.bounded_docker(['container','inspect','a'*64],timeout=.2 if case=='timeout' else 2)
        assert 'fixture-secret' not in str(error.value)
    assert len(children)==1 and children[0].poll() is not None


def test_inventory_reader_refuses_mutating_docker_commands_before_launch(monkeypatch):
    monkeypatch.setattr(adapter.bounded_docker.__globals__['subprocess'],'Popen',
        lambda *a,**kw:pytest.fail('No child should launch'))
    with pytest.raises(edge.EdgeError,match='Read-only'):
        adapter.bounded_docker(['container','stop','a'*64])
