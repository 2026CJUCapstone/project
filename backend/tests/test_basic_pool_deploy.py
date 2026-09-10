"""No Docker/SSH: exercise contracts, archive boundary and rollback ordering."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def deploy(tmp_path, monkeypatch):
    value = module('basic_pool_deploy')
    monkeypatch.setattr(value, 'ROOT', tmp_path)
    return value


def test_bundle_exact_sha_and_replaces_stale_marker(tmp_path):
    package = module('package_deploy_frontend')
    source = tmp_path / 'dist'
    (source / '.well-known').mkdir(parents=True)
    (source / 'index.html').write_text('<html>test</html>')
    (source / '.well-known/webcompiler-release.json').write_text('old')
    archive = tmp_path / 'bundle.tar.gz'
    package.package(source, archive, 'a' * 40)
    with tarfile.open(archive) as tar:
        name = 'frontend-dist/.well-known/webcompiler-release.json'
        assert tar.getnames().count(name) == 1
        assert json.load(tar.extractfile(name)) == {'deployment_sha': 'a' * 40}


@pytest.mark.parametrize('name,kind', [('../outside', 'file'), ('/outside', 'file'), ('frontend-dist/link', 'link'), ('other/index.html', 'file')])
def test_archive_rejects_escape_link_or_wrong_prefix(deploy, tmp_path, name, kind):
    archive = tmp_path / 'bad.tar'
    with tarfile.open(archive, 'w') as tar:
        member = tarfile.TarInfo(name)
        if kind == 'link':
            member.type, member.linkname = tarfile.SYMTYPE, '/etc/passwd'
            tar.addfile(member)
        else:
            member.size = 1
            tar.addfile(member, io.BytesIO(b'x'))
    with pytest.raises(AssertionError):
        deploy.extract(archive, 'frontend-dist')
    assert not (tmp_path / 'frontend-dist').exists()


@pytest.mark.parametrize('changed', ['backend/requirements.lock', 'backend/app/models/database.py', 'frontend/nginx.conf', 'runtime/bpp-ref.txt'])
def test_dependency_schema_runtime_changes_fail_before_rollout(deploy, tmp_path, changed):
    before, after = tmp_path / 'before', tmp_path / 'after'
    for base in (before, after):
        for name in deploy.CONTRACTS + ['runtime/bpp-ref.txt', 'runtime/sandbox/run.sh']:
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'same\n')
    deploy.check_contracts(before, after)
    (after / changed).write_bytes(b'changed\n')
    with pytest.raises(AssertionError):
        deploy.check_contracts(before, after)


@pytest.mark.parametrize('edge_failure', [False, True])
def test_failed_candidate_rolls_back_before_error_propagates(deploy, tmp_path, monkeypatch, edge_failure):
    state = {'phase': 'built', 'old': {'source_sha': 'old'}, 'old_ids': {}, 'postgres_id': 'pg'}
    state_path = tmp_path / 'release-state.json'
    state_path.write_text(json.dumps(state))
    operator = tmp_path / 'operator-state.json'
    operator.write_text(json.dumps({'source_sha': 'old', 'phase': 'deployed'}))
    monkeypatch.setattr(deploy, 'STATE', state_path)
    monkeypatch.setattr(deploy, 'PROD', tmp_path)
    monkeypatch.setattr(deploy, 'PROJECT', 'fixture')
    deploy_dir = tmp_path / '.deploy'
    deploy_dir.mkdir()
    for role, port in [('backend', 18003), ('frontend', 15176)]:
        (deploy_dir / (role + '-edge.conf')).write_text('127.0.0.1:' + str(port))
    monkeypatch.setattr(deploy, 'o', SimpleNamespace(STATE=operator, inspect=lambda name: {'Id': 'pg'}))
    events = []
    monkeypatch.setattr(deploy, 'save', lambda s: (events.append('save:' + s['phase']), state_path.write_text(json.dumps(s))))
    def edge(*args):
        if 'maintenance' not in events:
            events.append('maintenance')
            if edge_failure: raise RuntimeError('fixture edge failure')
        else: events.append('restore-edge')
    monkeypatch.setattr(deploy, 'edge', edge)
    def fail():
        events.append('drain')
        raise RuntimeError('fixture drain failure')
    monkeypatch.setattr(deploy, 'stop_current', fail)
    monkeypatch.setattr(deploy, 'rollback', lambda: events.append('rollback'))
    with pytest.raises(RuntimeError, match='fixture'):
        deploy.rollout()
    assert events == (['save:maintenance', 'maintenance', 'save:failed', 'restore-edge', 'save:rolled-back'] if edge_failure else ['save:maintenance', 'maintenance', 'drain', 'save:failed', 'rollback'])


def test_rollback_uses_new_incarnation_without_restoring_database(deploy, tmp_path, monkeypatch):
    state = {'phase': 'failed', 'old': {'env': {'BASIC_LB_RUNTIME_ID': 'old', 'SANDBOX_IMAGE': 'prior'}}, 'edge_configs': {}}
    path = tmp_path / 'release-state.json'
    path.write_text(json.dumps(state))
    monkeypatch.setattr(deploy, 'STATE', path)
    events = []
    monkeypatch.setattr(deploy, 'stop_current', lambda: events.append('drain'))
    def compose(env, *args):
        assert env['BASIC_LB_RUNTIME_ID'] != 'old' and env['SANDBOX_IMAGE'] == 'prior'
        assert args == ('up', '--no-build', '--pull', 'never', '--no-deps', '-d', 'backend', 'worker', 'frontend')
        events.append('old-images')
    monkeypatch.setattr(deploy, 'pc', compose)
    monkeypatch.setattr(deploy, 'ready', lambda env: events.append('ready'))
    monkeypatch.setattr(deploy, 'edge', lambda *args: events.append('restore-edge'))
    monkeypatch.setattr(deploy, 'o', SimpleNamespace(save=lambda value: events.append('operator-save')))
    monkeypatch.setattr(deploy, 'save', lambda value: events.append(value['phase']))
    deploy.rollback()
    assert events == ['drain', 'old-images', 'ready', 'restore-edge', 'operator-save', 'rolled-back']


def test_basic_dispatch_precedes_every_managed_side_effect():
    script = (ROOT / 'scripts/deploy_server.sh').read_text()
    assert script.index('deploy_guard.sh') < script.index('basic-pool.json') < script.index('validate_ingress.py')
    assert 'exec python3 -I "$PROJECT_ROOT/scripts/basic_pool_deploy.py"' in script


@pytest.mark.parametrize('role,allowed', [('backend', 'backend/app/api.py'), ('frontend', 'frontend-dist/index.html'), ('sandbox', 'runtime/sandbox/run.sh')])
def test_build_context_never_contains_secret_journal(deploy, tmp_path, role, allowed):
    for name in ['backend/app/api.py', 'frontend-dist/index.html', 'runtime/sandbox/run.sh', 'release.json', 'release-state.json', 'pre-update-production.dump']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    context = deploy.build_context(role)
    assert (context / allowed).is_file()
    assert not (context / 'release-state.json').exists()
    assert not (context / 'pre-update-production.dump').exists()
    assert {str(p.relative_to(context)).replace('\\', '/') for p in context.rglob('*') if p.is_file()} == ({allowed, 'release.json'} if role == 'frontend' else {allowed})
