"""Adversarial cleanup protocol tests, not actual Docker runtime evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


def load_script():
    source = Path(__file__).resolve().parents[2] / 'scripts/e2e_stack_test.py'
    spec = importlib.util.spec_from_file_location('e2e_cleanup_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(script, tmp_path):
    script.ROOT_DIR = tmp_path
    ns = script.E2E_NAMESPACE
    return {
        'container': [{'Id': 'a' * 64, 'Config': {'Labels': {
            'com.docker.compose.project': ns, 'com.docker.compose.service': 'worker',
            'com.docker.compose.project.working_dir': str(tmp_path)}}}],
        'sandbox': [{'Id': 'b' * 64, 'Config': {'Labels': {
            'webcompiler.pool': ns, 'webcompiler.job': '1' * 32, 'webcompiler.lease': '2' * 32}},
            'Mounts': [{'Type': 'bind', 'Source': str(tmp_path / '.sandbox-work' / 'job')}]}],
        'volume': [{'Name': ns + '_postgres_data', 'Labels': {'com.docker.compose.project': ns}}],
        'network': [{'Id': 'c' * 64, 'Name': ns + '_default',
                     'Labels': {'com.docker.compose.project': ns}}],
    }


class FakeDocker:
    def __init__(self, script, rows):
        self.script, self.rows, self.calls = script, copy.deepcopy(rows), []
        self.tags = set(script.test_image_tags())

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == 'ps':
            kind = 'sandbox' if 'webcompiler.pool=' in args[-1] else 'container'
            return '\n'.join(row['Id'] for row in self.rows[kind])
        if args[:2] in {('volume', 'ls'), ('network', 'ls')}:
            key = 'Name' if args[0] == 'volume' else 'Id'
            return '\n'.join(row[key] for row in self.rows[args[0]])
        if args[1] == 'inspect':
            rows = [row for group in self.rows.values() for row in group
                    if row.get('Id', row.get('Name')) == args[-1]]
            return json.dumps(rows)
        if args[:2] == ('image', 'ls'):
            return 'image-id' if args[-1].split('=', 1)[1] in self.tags else ''
        if args[:2] == ('image', 'rm'):
            self.tags.remove(args[-1])
            return ''
        if args[:2] == ('container', 'stop'):
            return ''
        if args[1] == 'rm':
            for kind in self.rows:
                self.rows[kind] = [r for r in self.rows[kind]
                                   if r.get('Id', r.get('Name')) != args[-1]]
            return ''
        raise AssertionError(args)


def test_cleanup_stops_worker_then_removes_only_exact_ids_and_nonce_tags(tmp_path, monkeypatch):
    script = load_script()
    fake = FakeDocker(script, fixture(script, tmp_path))
    monkeypatch.setattr(script, 'docker', fake)
    monkeypatch.setattr(script, 'settle_producers', lambda: None)
    script.cleanup_owned_stack()
    script.cleanup_owned_stack()  # A completed/recovered run is idempotent.
    changes = [c for c in fake.calls if len(c) > 1 and c[1] in {'stop', 'rm'}]
    assert changes[0] == ('container', 'rm', '-f', 'b' * 64)
    assert ('container', 'rm', '-f', 'b' * 64) in changes
    assert {c[-1] for c in changes if c[0] == 'image'} == set(script.test_image_tags())
    assert not any(fake.rows.values()) and not fake.tags
    assert not any('prune' in c or '--volumes' in c or '--remove-orphans' in c for c in fake.calls)


@pytest.mark.parametrize('kind,mutation', [
    ('container', lambda r: r['Config']['Labels'].update({'com.docker.compose.project': 'production'})),
    ('container', lambda r: r['Config']['Labels'].update({'com.docker.compose.service': 'unknown'})),
    ('container', lambda r: r['Config']['Labels'].update({'com.docker.compose.project.working_dir': '/other'})),
    ('sandbox', lambda r: r['Config']['Labels'].update({'webcompiler.pool': 'production'})),
    ('sandbox', lambda r: r['Config']['Labels'].update({'webcompiler.job': '0' * 32})),
    ('sandbox', lambda r: r['Config']['Labels'].update({'webcompiler.lease': 'invalid'})),
    ('sandbox', lambda r: r['Mounts'][0].update({'Source': '/production/work'})),
    ('volume', lambda r: r.update(Name='production-postgres')),
    ('network', lambda r: r.update(Name='production-default')),
])
def test_bad_identity_is_rejected_before_any_destructive_command(tmp_path, monkeypatch, kind, mutation):
    script = load_script()
    rows = fixture(script, tmp_path)
    mutation(rows[kind][0])
    fake = FakeDocker(script, rows)
    monkeypatch.setattr(script, 'docker', fake)
    monkeypatch.setattr(script, 'settle_producers', lambda: None)
    with pytest.raises(RuntimeError, match='non-owned'):
        script.cleanup_owned_stack()
    assert not any(c[1] in {'rm', 'stop'} for c in fake.calls)


def test_daemon_error_is_not_image_absence(monkeypatch):
    script = load_script()
    def fail(*args):
        raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(script, 'docker', fail)
    with pytest.raises(subprocess.CalledProcessError):
        script.image_exists(script.SANDBOX_IMAGE)


def test_resource_collision_never_records_ownership(tmp_path, monkeypatch):
    script = load_script()
    fake = FakeDocker(script, fixture(script, tmp_path))
    monkeypatch.setattr(script, 'docker', fake)
    with pytest.raises(RuntimeError, match='refusing to adopt'):
        script.record_ownership()
    assert not (tmp_path / '.e2e-stack-owner.json').exists()


def test_setup_records_before_mutation_and_cleanup_runs_on_failure(monkeypatch):
    script = load_script()
    calls = []
    monkeypatch.setattr(script, 'preflight', lambda: calls.append('preflight'))
    monkeypatch.setattr(script, 'record_ownership', lambda: calls.append('record'))
    def failed_setup(*args):
        calls.append('start')
        raise RuntimeError('build failed')
    monkeypatch.setattr(script, 'run_command', failed_setup)
    monkeypatch.setattr(script, 'cleanup_owned_stack', lambda: calls.append('cleanup'))
    with pytest.raises(RuntimeError, match='build failed'):
        script.exercise_stack()
    assert calls == ['preflight', 'record', 'start', 'cleanup']


def test_setup_subprocess_inherits_the_workspace_lock(monkeypatch):
    script = load_script()
    monkeypatch.setattr(script, '_WORKSPACE_LOCK_FD', 47)
    calls = []
    monkeypatch.setattr(script.subprocess, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    script.run_command('bash', 'scripts/docker_up.sh')
    assert calls[0][1]['pass_fds'] == (47,)
    assert calls[0][1]['env'] is script.ENV
