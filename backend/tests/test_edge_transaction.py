from contextlib import nullcontext
from dataclasses import asdict, replace
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


spec=importlib.util.spec_from_file_location('edge_transaction',Path(__file__).resolve().parents[2]/'scripts/edge_transaction.py')
edge=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=edge
spec.loader.exec_module(edge)


def store_at(tmp_path,monkeypatch):
    store=edge.Store(tmp_path/'edge',edge.Layout(18000,15173))
    store.initialize()
    if os.name!='posix':
        # Windows tests cover ordering/state. Actual flock/fsync/modes are
        # exercised on the isolated Linux host, never mocked as integration.
        monkeypatch.setattr(store,'locked',nullcontext)
    return store


def releases():
    return (edge.Release('blue','a'*40,18001,15174,'b'*32),
            edge.Release('green','c'*40,18002,15175,'d'*32))


def test_commit_point_and_every_switch_failure_restores_committed_config(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    blue,green=releases()
    observed=[]
    def activate(release):
        assert (store.path/'state/pending.json').exists()
        assert (store.path/'config/nginx.conf').read_text()==edge.render(store.layout,release)
        observed.append(release)
        return True
    tx=edge.Transaction(store,activate,lambda _:True)
    tx.switch(blue,preflight=lambda _:True,postflight=lambda _:True)
    assert store.committed()==blue
    with pytest.raises(edge.EdgeError,match='committed route restored'):
        tx.switch(green,preflight=lambda _:True,postflight=lambda _:False)
    assert observed==[blue,green,blue]
    assert store.committed()==blue
    assert (store.path/'config/nginx.conf').read_text()==edge.render(store.layout,blue)
    assert not (store.path/'state/pending.json').exists()


def test_preflight_failure_never_writes_intent_or_touches_config(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    blue,_=releases()
    tx=edge.Transaction(store,lambda _:pytest.fail('must not activate'),lambda _:True)
    with pytest.raises(edge.EdgeError,match='preflight'):
        tx.switch(blue,preflight=lambda _:False,postflight=lambda _:True)
    assert not (store.path/'config/nginx.conf').exists()
    assert not (store.path/'state/pending.json').exists()


class Crash(BaseException):
    pass


@pytest.mark.parametrize('phase',['intent','install','activate','postflight','commit'])
def test_abrupt_interruption_recovers_authoritative_commit_not_candidate(tmp_path,monkeypatch,phase):
    store=store_at(tmp_path,monkeypatch)
    blue,green=releases()
    tx=edge.Transaction(store,lambda _:True,lambda _:True)
    tx.switch(blue,preflight=lambda _:True,postflight=lambda _:True)
    original_write,original_install=store.write,store.install
    def write(path,value):
        original_write(path,value)
        if (phase=='intent' and path.name=='pending.json') or (phase=='commit' and path.name=='committed.json'):
            raise Crash()
    def install(release):
        original_install(release)
        if phase=='install':
            raise Crash()
    def activate(_):
        if phase=='activate':
            raise Crash()
        return True
    def postflight(_):
        if phase=='postflight':
            raise Crash()
        return True
    monkeypatch.setattr(store,'write',write)
    monkeypatch.setattr(store,'install',install)
    with pytest.raises(Crash):
        edge.Transaction(store,activate,lambda _:True).switch(green,preflight=lambda _:True,postflight=postflight)
    monkeypatch.setattr(store,'write',original_write)
    monkeypatch.setattr(store,'install',original_install)
    expected=green if phase=='commit' else blue
    assert edge.Transaction(store,lambda release: release==expected,lambda _:True).recover()==expected
    assert store.committed()==expected
    assert (store.path/'config/nginx.conf').read_text()==edge.render(store.layout,expected)
    assert not (store.path/'state/pending.json').exists()
    assert not list(store.path.rglob('.write-*'))


def test_failed_first_deployment_recovers_closed_listener_not_unconfirmed_target(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    blue,_=releases()
    observed=[]
    def activate(release):
        observed.append(release)
        return True
    with pytest.raises(edge.EdgeError,match='committed route restored'):
        edge.Transaction(store,activate,lambda _:True).switch(blue,preflight=lambda _:True,postflight=lambda _:False)
    assert observed==[blue,None]
    assert store.committed() is None
    assert (store.path/'config/nginx.conf').read_text()==edge.render(store.layout,None)


def test_failed_rollback_retains_recovery_intent_and_refuses_next_unready_switch(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    blue,green=releases()
    edge.Transaction(store,lambda _:True,lambda _:True).switch(blue,preflight=lambda _:True,postflight=lambda _:True)
    with pytest.raises(edge.EdgeError,match='rollback is unconfirmed'):
        edge.Transaction(store,lambda _:False,lambda _:True).switch(green,preflight=lambda _:True,postflight=lambda _:True)
    assert (store.path/'state/pending.json').exists()
    assert store.committed()==blue
    with pytest.raises(edge.EdgeError,match='not acknowledged'):
        edge.Transaction(store,lambda _:False,lambda _:True).switch(green,preflight=lambda _:pytest.fail('must recover first'),postflight=lambda _:True)


def test_clean_recovery_observes_without_reload_and_dead_committed_app_keeps_intent(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    blue,green=releases()
    edge.Transaction(store,lambda _:True,lambda _:True).switch(blue,preflight=lambda _:True,postflight=lambda _:True)
    tx=edge.Transaction(store,lambda _:pytest.fail('clean recovery must not HUP'),lambda _:True,
                        observe=lambda:edge.acknowledgment(store.layout,blue))
    assert tx.recover()==blue
    wrong=edge.Transaction(store,lambda _:pytest.fail('unjournaled mismatch requires explicit repair'),lambda _:True,
                           observe=lambda:edge.acknowledgment(store.layout,green))
    with pytest.raises(edge.EdgeError,match='explicit repair'):
        wrong.recover()
    store.intent(green,'switch')
    with pytest.raises(edge.EdgeError,match='application postflight'):
        edge.Transaction(store,lambda _:True,lambda _:False).recover()
    assert (store.path/'state/pending.json').exists()


def test_recovery_after_tool_upgrade_restores_exact_committed_snapshot(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    blue,_=releases()
    tx=edge.Transaction(store,lambda _:True,lambda _:True)
    tx.switch(blue,preflight=lambda _:True,postflight=lambda _:True)
    original=(store.path/'config/nginx.conf').read_text()
    expected=store.expected(blue)
    store.intent(blue,'restore')
    monkeypatch.setattr(edge,'render',lambda *a:pytest.fail('must restore saved bytes, not a new renderer'))
    monkeypatch.setattr(edge,'acknowledgment',lambda *a:pytest.fail('must use saved acknowledgment'))
    assert tx.recover()==blue
    assert (store.path/'config/nginx.conf').read_text()==original
    assert store.expected(blue)==expected


def test_drain_journal_tracks_only_nonretained_real_targets(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    blue,green=releases()
    tx=edge.Transaction(store,lambda _:True,lambda _:True)
    tx.switch(blue,preflight=lambda _:True,postflight=lambda _:True)
    drains=store.path/'state/drains'
    assert list(drains.iterdir())==[]  # First success has no old runtime.
    with pytest.raises(edge.EdgeError,match='committed route restored'):
        tx.switch(green,preflight=lambda _:True,postflight=lambda _:False)
    record=store.read_json(next(drains.iterdir()))
    assert record['target']['release']==asdict(green)
    assert record['retained']['release']==asdict(blue)
    assert [item['release'] for item in record['retire']]==[asdict(green)]
    tx.switch(green,preflight=lambda _:True,postflight=lambda _:True)
    records=[store.read_json(path) for path in drains.iterdir()]
    success=next(item for item in records if item['phase']=='switch')
    assert success['retained']['release']==asdict(green)
    assert [item['release'] for item in success['retire']]==[asdict(blue)]


def test_drain_capacity_never_blocks_pending_or_clean_recovery(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    blue,green=releases()
    tx=edge.Transaction(store,lambda _:True,lambda _:True,observe=lambda:store.expected(store.committed()))
    tx.switch(blue,preflight=lambda _:True,postflight=lambda _:True)
    for number in range(64):
        store.write(store.path/'state/drains'/f'{number:032x}.json',{'fixture':number})
    store.intent(green,'switch')
    store.install(green)
    assert tx.recover()==blue
    assert tx.recover()==blue
    with pytest.raises(edge.EdgeError,match='verified drain'):
        tx.switch(green,preflight=lambda _:pytest.fail('capacity must fail before preflight'),postflight=lambda _:True)
    assert store.committed()==blue
    assert not (store.path/'state/pending.json').exists()


def test_corrupt_pending_is_preserved_and_never_activated(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    store.write(store.path/'state/pending.json',{'generation':'d'*32})
    tx=edge.Transaction(store,lambda _:pytest.fail('corrupt journal must not activate'),lambda _:True)
    with pytest.raises(edge.EdgeError,match='Invalid edge recovery intent'):
        tx.recover()
    assert store.read_json(store.path/'state/pending.json')=={'generation':'d'*32}


@pytest.mark.skipif(os.name!='posix',reason='Real POSIX ownership/lock/symlink operations required')
def test_real_lock_exclusion_and_symlink_records_fail_without_touching_target(tmp_path,monkeypatch):
    store=store_at(tmp_path,monkeypatch)
    with store.locked():
        with pytest.raises(BlockingIOError):
            with store.locked():
                pass
    sentinel=tmp_path/'sentinel'
    sentinel.write_text('do not touch')
    record=store.path/'state/committed.json'
    record.symlink_to(sentinel)
    with pytest.raises(OSError):
        store.committed()
    assert sentinel.read_text()=='do not touch'
    record.unlink()
    for item in (store.path,store.path/'config',store.path/'status',store.path/'state'):
        assert item.stat().st_mode & 0o777==0o700


def test_existing_unowned_or_wrong_layout_directory_is_not_adopted(tmp_path):
    path=tmp_path/'foreign'
    path.mkdir(mode=0o700)
    (path/'marker').write_text('preserve')
    with pytest.raises(edge.EdgeError,match='unowned'):
        edge.Store(path,edge.Layout(18000,15173)).initialize()
    assert (path/'marker').read_text()=='preserve'
    owned=edge.Store(tmp_path/'owned',edge.Layout(18000,15173))
    owned.initialize()
    with pytest.raises(edge.EdgeError,match='another layout'):
        edge.Store(owned.path,edge.Layout(18010,15173)).initialize()
