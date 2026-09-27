import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
SPEC = importlib.util.spec_from_file_location('ci_image_security_contract', ROOT/'scripts/ci_image_security.py')
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)
COMMIT = 'c'*40
COMPILER = 'b'*40
IDS = {role: 'sha256:'+str(index)*64 for index, role in enumerate(ci.ROLES, 1)}


@pytest.mark.parametrize('error,expected', [(ci.ScanError('Image OS inventory was not detected'), 'Image OS inventory was not detected'), (subprocess.CalledProcessError(1, ['tool', 'private-credential']), 'CalledProcessError')])
def test_main_reports_fixed_validation_reason_but_not_subprocess_secrets(monkeypatch, capsys, error, expected):
    monkeypatch.setattr(sys, 'argv', ['ci_image_security.py', '--commit', COMMIT, '--trivy', 'scanner', '--output-dir', 'output', '--cache-dir', 'cache'])
    def fail(**kwargs):
        raise error
    monkeypatch.setattr(ci, 'build_and_scan', fail)
    assert ci.main() == 2
    assert capsys.readouterr().out.strip() == 'Application image security failed: ' + expected


def test_builds_real_contexts_with_no_service_start_or_mutable_tag():
    for role in ci.ROLES:
        command = ci.build_command(role, COMMIT, COMPILER, 'bounded', Path('id'))
        assert command[:5] == ['docker', 'buildx', 'build', '--builder', 'bounded']
        assert '--load' in command and '--iidfile' in command
        assert 'io.webcompiler.source-sha='+COMMIT in command
        assert 'io.webcompiler.image-role='+role in command
        assert not {'--push', '--tag', 'run', 'up'} & set(command)
        context = ROOT/('runtime' if role == 'sandbox' else role)
        assert command[-1] == str(context)
        if role == 'sandbox': assert 'BPP_REF='+COMPILER in command
        if role == 'frontend':
            assert 'ENVIRONMENT=production' in command and 'DEPLOY_SHA='+COMMIT in command
            assert 'FRONTEND_API_UPSTREAM=api-proxy:8080' in command


@pytest.mark.parametrize('failure', [None, 'head', 'dirty', 'untracked', 'build', 'budget', 'id', 'duplicate', 'compiler', 'scan', 'policy'])
def test_application_pipeline_binds_every_role_and_failures_cannot_publish_success(tmp_path, monkeypatch, failure):
    (tmp_path/'runtime').mkdir()
    (tmp_path/'runtime/bpp-ref.txt').write_text(COMPILER)
    monkeypatch.setattr(ci, 'ROOT', tmp_path)
    for key, value in {'WEBCOMPILER_BUILD_BUILDER': 'bounded', 'WEBCOMPILER_BUILD_CONTAINER_ID': 'a'*64}.items():
        monkeypatch.setenv(key, value)
    output = tmp_path/'evidence'
    built, scanned, checks = [], [], []
    def verify(config):
        checks.append(config.container_id)
        if failure == 'budget' and len(checks) == 3:
            raise ci.ScanError('budget drift')
    monkeypatch.setattr(ci, 'verify', verify)
    def command(args, **kwargs):
        if args[:2] == ['git', 'diff']:
            if failure == 'dirty': raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0)
        assert args[:3] == ['docker', 'buildx', 'build']
        role = args[args.index('--iidfile')+1].split('/')[-1].split('\\')[-1].split('.')[0]
        built.append(role)
        assert kwargs['check'] and kwargs['timeout'] == 2400
        if failure == 'build': raise subprocess.CalledProcessError(1, args)
        image_id = 'mutable:tag' if failure == 'id' else IDS['backend'] if failure == 'duplicate' else IDS[role]
        Path(args[args.index('--iidfile')+1]).write_text(image_id)
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(ci.subprocess, 'run', command)
    def capture(args, **kwargs):
        if args[:2] == ['git', 'status']: return '?? frontend/foreign.ts' if failure == 'untracked' else ''
        if args[0] == 'git': return ('d'*40 if failure == 'head' else COMMIT)+'\n'
        assert args == ['docker', 'image', 'inspect', IDS['sandbox']]
        return json.dumps([{'Id': IDS['sandbox'], 'Config': {'Labels': {'io.bpp.ref': 'wrong' if failure == 'compiler' else COMPILER}}}])
    monkeypatch.setattr(ci.subprocess, 'check_output', capture)
    def scan(**kwargs):
        role = kwargs['role']
        scanned.append(role)
        assert kwargs['source'] == 'docker' and kwargs['scope'] == 'application'
        assert kwargs['target'] == IDS[role] and kwargs['commit'] == COMMIT
        if failure == 'scan': raise ci.ScanError('scanner failed')
        kwargs['output'].mkdir()
        (kwargs['output']/'manifest.json').write_text('fixture evidence')
        return {'policyPassed': failure != 'policy' or role != 'backend'}
    monkeypatch.setattr(ci, 'run_scan', scan)
    args = dict(commit=COMMIT, trivy='tool', output=output, cache=tmp_path/'cache')
    if failure in {None, 'policy'}:
        receipt = ci.build_and_scan(**args)
        assert built == scanned == list(ci.ROLES)
        assert len(checks) == 7
        assert receipt['policyPassed'] is (failure is None)
        assert receipt['compilerCommit'] == COMPILER
        assert all(item['manifestSha256'] for item in receipt['roles'].values())
        assert json.loads((output/'application-images.json').read_text()) == receipt
    else:
        with pytest.raises((ci.ScanError, subprocess.CalledProcessError)): ci.build_and_scan(**args)
        assert not (output/'application-images.json').exists()
        if failure in {'head', 'dirty', 'untracked'}: assert not built
        if failure in {'build', 'budget', 'id'}: assert not scanned
        if failure == 'duplicate': assert scanned == ['backend']
        if failure == 'compiler': assert scanned == ['backend', 'frontend']
