"""Actual Redis CAS and delayed thread publication, only isolated test keys."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from uuid import uuid4

import pytest
from redis import Redis

from app.services import runtime_health as health
from tests.test_runtime_readiness import Engine

pytestmark = pytest.mark.skipif(not os.getenv('TEST_REDIS_URL'),reason='Explicit isolated Redis URL required')


@pytest.fixture
def store(monkeypatch,tmp_path):
    client = Redis.from_url(os.environ['TEST_REDIS_URL'],decode_responses=True,
                            socket_timeout=2,socket_connect_timeout=2)
    prefix = 'audit-process-'+uuid4().hex
    monkeypatch.setattr(health.settings,'REDIS_KEY_PREFIX',prefix)
    monkeypatch.setattr(health.settings,'RUNTIME_POOL_ID','local')
    monkeypatch.setattr(health.settings,'RUNTIME_INSTANCE_ID','')
    monkeypatch.setattr(health.settings,'DEPLOYMENT_SHA','')
    monkeypatch.setattr(health.settings,'WORKER_STATE_DIRECTORY',str(tmp_path/'worker-state'))
    monkeypatch.setattr(health.settings,'ENVIRONMENT','development')
    monkeypatch.setattr(health,'engine',Engine())  # Schema predicate only; Redis protocol is real.
    monkeypatch.setattr(health,'get_redis',lambda:client)
    assert health._process_state is None
    try:
        yield client
    finally:
        health.stop_worker_process()
        keys = list(client.scan_iter(match=prefix+':*'))
        if keys:
            client.delete(*keys)
        client.close()


def test_legacy_or_unowned_stale_markers_never_make_api_ready(store):
    expiry = store.time()[0]+30
    legacy = health.worker_health_key().replace(':workers-v2:',':workers:')
    store.zadd(legacy,{'old-hostname':expiry})
    store.zadd(health.worker_health_key(),{'host:'+'a'*32:expiry})
    assert not health.dependencies_ready()
    health.start_worker_process()
    identity = health._owned_identity()
    assert not health.dependencies_ready()
    health.report_worker_ready()
    assert health.dependencies_ready()
    # A newer owner invalidates old ready data even if ZREM was omitted by
    # an external fault; reads require one coherent owner+epoch observation.
    store.hset(health.worker_owners_key(),health.process_slot(identity),'b'*32)
    assert not health.dependencies_ready()
    with pytest.raises(RuntimeError,match='fenced'):
        health.report_worker_ready()


def test_separate_cli_cannot_reuse_old_epoch_before_new_probe(store):
    env = dict(os.environ,ENVIRONMENT='development',REDIS_URL=os.environ['TEST_REDIS_URL'],
        REDIS_KEY_PREFIX=health.settings.REDIS_KEY_PREFIX,RUNTIME_POOL_ID='local',
        RUNTIME_INSTANCE_ID='',DEPLOYMENT_SHA='',
        WORKER_STATE_DIRECTORY=health.settings.WORKER_STATE_DIRECTORY,
        SANDBOX_POOL_ID=health.settings.SANDBOX_POOL_ID,SANDBOX_IMAGE=health.settings.SANDBOX_IMAGE)
    def cli():
        return subprocess.run([sys.executable,'-m','app.readiness'],
            cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,timeout=10).returncode
    health.start_worker_process()
    old = health._owned_identity()
    assert cli() == 1
    health.report_worker_ready()
    assert cli() == 0
    health.stop_worker_process()
    assert cli() == 1
    health.start_worker_process()
    new = health._owned_identity()
    assert old.epoch != new.epoch
    store.zadd(health.worker_health_key(),{health.process_slot(old)+':'+old.epoch:store.time()[0]+30})
    assert cli() == 1 and not health.dependencies_ready()
    health.report_worker_ready()
    health._withdraw(old,revoke=True)  # Late old-process cleanup cannot revoke B.
    assert cli() == 0 and health.dependencies_ready()


def test_final_revoke_waits_for_threaded_publish_and_fences_delayed_replay(store,monkeypatch):
    entered, release, stopping = Event(), Event(), Event()
    published_args = []
    class DelayedClient:
        def __getattr__(self,name):
            return getattr(store,name)
        def eval(self,*args):
            if 'ZADD' in args[0]:
                published_args.append(args)
                entered.set()
                assert release.wait(10)
            return store.eval(*args)
    health.start_worker_process()
    identity = health._owned_identity()
    monkeypatch.setattr(health,'get_redis',lambda:DelayedClient())
    def stop():
        stopping.set()
        health.stop_worker_process()
    with ThreadPoolExecutor(2) as executor:
        report = executor.submit(health.report_worker_ready)
        try:
            assert entered.wait(5)
            stop_future = executor.submit(stop)
            assert stopping.wait(5)
            assert not stop_future.done()
        finally:
            release.set()
        report.result(timeout=10)
        stop_future.result(timeout=10)
    assert not health.dependencies_ready()
    assert store.hget(health.worker_owners_key(),health.process_slot(identity)) == 'revoked:'+identity.epoch
    assert store.eval(*published_args[0]) == 0
    assert not health._register(store,identity)
    with pytest.raises(RuntimeError,match='not initialized'):
        health.report_worker_ready()
    assert not health.dependencies_ready()


def test_redis_key_loss_requires_registration_and_fresh_publication(store):
    health.start_worker_process()
    health.report_worker_ready()
    assert health.dependencies_ready()
    store.delete(health.worker_health_key(),health.worker_owners_key())
    assert not health.dependencies_ready()
    health.ensure_worker_process_registered()
    assert not health.dependencies_ready()
    health.report_worker_ready()
    assert health.dependencies_ready()


def test_partial_owner_loss_cannot_revive_leftover_ready_entry_before_probe(store):
    health.start_worker_process()
    health.report_worker_ready()
    assert health.dependencies_ready()
    store.delete(health.worker_owners_key())
    assert store.zcard(health.worker_health_key()) == 1
    assert not health.dependencies_ready()
    health.ensure_worker_process_registered()
    assert not health.dependencies_ready()
    assert store.zcard(health.worker_health_key()) == 0
    health.report_worker_ready()
    assert health.dependencies_ready()


def test_revoke_before_long_claim_drain_keeps_lifetime_lock_but_forbids_publication(store):
    health.start_worker_process()
    identity = health._owned_identity()
    health.report_worker_ready()
    assert health.this_worker_ready()
    health.revoke_worker_readiness()
    assert health._owned_identity() == identity
    assert health._process_state._fd is not None
    assert not health.this_worker_ready() and not health.dependencies_ready()
    for operation in (health.report_worker_ready,health.ensure_worker_process_registered):
        with pytest.raises(RuntimeError,match='revoked'):
            operation()
    health.revoke_worker_readiness()
    assert not health.dependencies_ready()
