import hashlib
import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('deploy_dispatch',ROOT/'scripts/dispatch_deploy.py')
dispatch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dispatch)


def environment():
    return {'DEPLOY_SHA':'a'*40,'DEPLOY_HOST':'test.example.invalid','DEPLOY_PORT':'10022',
            'DEPLOY_USER':'fixture','DEPLOY_PATH':"/test/fixture's checkout",'DEPLOY_REPO':'https://github.com/test/fixture.git',
            'DEPLOY_KNOWN_HOSTS':'[test.example.invalid]:10022 ssh-ed25519 fixture-key',
            'GITHUB_TOKEN':"fixture-token'never-log-me"}


def test_one_ssh_with_pinned_identity_and_stdin_only_quoted_payload():
    env = environment()
    calls = []
    def run(command,**kwargs):
        calls.append((command,kwargs))
        if command[0] == 'ssh-keygen':
            assert command[2] == '[test.example.invalid]:10022'
            known = Path(command[-1])
            assert known.read_text().strip() == env['DEPLOY_KNOWN_HOSTS']
        else:
            assert command[0] == 'ssh' and command[-1] == 'bash -s'
            assert 'StrictHostKeyChecking=yes' in command
            assert 'GlobalKnownHostsFile=/dev/null' in command
            assert 'UpdateHostKeys=no' in command
            assert 'BatchMode=yes' in command
            assert command[1:3] == ['-F','/dev/null']
            assert env['GITHUB_TOKEN'] not in ' '.join(command)
            assert env['DEPLOY_PATH'] not in ' '.join(command)
            payload = kwargs['input']
            assert "'\"'\"'" in payload  # POSIX single quote escape, not interpolation
            assert 'export RUN_DEPLOY_SCRIPT=1' in payload
            assert 'DEPLOY_BRANCH=' not in payload
            assert 'git clean' not in '\n'.join(line for line in payload.splitlines() if not line.startswith('#'))
        return SimpleNamespace(returncode=0)
    dispatch.dispatch(env,run=run)
    assert [command[0] for command,_ in calls] == ['ssh-keygen','ssh']
    assert not Path(calls[0][0][-1]).exists()  # scoped private temp file removed


def test_missing_exact_host_key_blocks_ssh():
    calls = []
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1)
    with pytest.raises(dispatch.DeployConfigurationError,match='exact host and port'):
        dispatch.dispatch(environment(),run=run)
    assert len(calls) == 1 and calls[0][0] == 'ssh-keygen'


def test_frontend_archive_uses_a_dedicated_binary_ssh_stream(tmp_path):
    archive_bytes = b'frontend archive fixture\x00\xff\n'
    archive = tmp_path/'frontend.tar.gz'
    archive.write_bytes(archive_bytes)
    env = environment()
    env['DEPLOY_FRONTEND_ARCHIVE'] = str(archive)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == 'ssh-keygen':
            return SimpleNamespace(returncode=0)
        assert command[0] == 'ssh'
        if kwargs.get('text') is not True:
            assert kwargs['input'] == archive_bytes
            assert 'cat >"$TMP_PATH"' in command[-1]
            assert 'base64' not in command[-1]
            return SimpleNamespace(returncode=0)

        payload = kwargs['input']
        digest = hashlib.sha256(archive_bytes).hexdigest()
        assert command[-1] == 'bash -s'
        assert archive_bytes not in payload.encode()
        assert f'frontend-upload-{"a" * 40}-{digest}.tar.gz' in payload
        assert f'export WEBCOMPILER_FRONTEND_SHA256={digest}' in payload
        return SimpleNamespace(returncode=0)

    dispatch.dispatch(env, run=run)
    assert [command[0] for command, _ in calls] == ['ssh-keygen', 'ssh', 'ssh']
    sync = (ROOT/'scripts/sync_remote_repo.sh').read_text()
    assert sync.index('flock -n 9') < sync.index('expected_frontend=')
    assert 'sha256sum "$WEBCOMPILER_FRONTEND_UPLOAD"' in sync
    assert 'export WEBCOMPILER_FRONTEND_ARCHIVE=' in sync


def test_failed_deploy_removes_uploaded_frontend(tmp_path):
    archive = tmp_path/'frontend.tar.gz'
    archive.write_bytes(b'frontend')
    env = environment()
    env['DEPLOY_FRONTEND_ARCHIVE'] = str(archive)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == 'ssh-keygen':
            return SimpleNamespace(returncode=0)
        if len(calls) == 3:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)

    with pytest.raises(subprocess.CalledProcessError):
        dispatch.dispatch(env, run=run)
    assert [command[0] for command, _ in calls] == ['ssh-keygen', 'ssh', 'ssh', 'ssh']
    cleanup_command, cleanup_kwargs = calls[-1]
    assert 'rm -f --' in cleanup_command[-1]
    assert cleanup_kwargs['check'] is False
    assert cleanup_kwargs['stdout'] is subprocess.DEVNULL
    assert cleanup_kwargs['stderr'] is subprocess.DEVNULL


@pytest.mark.parametrize('archive_factory, message', [
    (lambda path: path/'missing.tar.gz', 'Frontend archive is missing'),
    (lambda path: path/'directory', 'Frontend archive is unreadable'),
])
def test_frontend_archive_path_errors_are_fixed_configuration_errors(tmp_path, archive_factory, message):
    archive = archive_factory(tmp_path)
    if archive.name == 'directory':
        archive.mkdir()
    env = environment()
    env['DEPLOY_FRONTEND_ARCHIVE'] = str(archive)
    with pytest.raises(dispatch.DeployConfigurationError, match=message):
        dispatch.dispatch(env, run=lambda *args, **kwargs: pytest.fail('Process must not start'))


def test_frontend_archive_oversize_is_rejected_before_process_start(tmp_path):
    archive = tmp_path/'oversize.tar.gz'
    archive.write_bytes(b'x' * (dispatch.MAX_FRONTEND_ARCHIVE_BYTES + 1))
    env = environment()
    env['DEPLOY_FRONTEND_ARCHIVE'] = str(archive)
    with pytest.raises(dispatch.DeployConfigurationError, match='Frontend archive is too large'):
        dispatch.dispatch(env, run=lambda *args, **kwargs: pytest.fail('Process must not start'))


@pytest.mark.parametrize('key,value',[
    ('DEPLOY_SHA','main'),('DEPLOY_SHA','a'*39),('DEPLOY_HOST','-oProxyCommand=evil'),
    ('DEPLOY_USER','user;evil'),('DEPLOY_PORT','0'),('DEPLOY_PORT','65536'),
    ('DEPLOY_PORT','22;evil'),('DEPLOY_REPO','ext::evil'),('DEPLOY_PATH','/'),
    ('DEPLOY_KNOWN_HOSTS',''),
])
def test_invalid_config_fails_before_process_start(key,value):
    env = environment()
    env[key] = value
    with pytest.raises(dispatch.DeployConfigurationError):
        dispatch.dispatch(env,run=lambda *a,**k:pytest.fail('Process must not start'))


def test_workflow_checks_ci_before_ssh_and_never_cancels_active_deployment():
    workflow = (ROOT/'.github/workflows/deploy-webcompiler.yml').read_text()
    assert 'actions: read' in workflow
    assert 'cancel-in-progress: false' in workflow
    assert 'environment: production' in workflow
    pre_checkout = workflow[:workflow.index('- name: Checkout')]
    assert "github.ref == 'refs/heads/main'" in pre_checkout
    assert "github.event.workflow_run.event == 'push'" in pre_checkout
    assert "github.event.workflow_run.head_branch == 'main'" in pre_checkout
    assert 'github.event.workflow_run.head_repository.full_name == github.repository' in pre_checkout
    assert workflow.index('python3 scripts/verify_deploy_ci.py') < workflow.index('Start SSH Agent')
    assert workflow.count('python3 scripts/dispatch_deploy.py') == 1
    assert 'ssh-keyscan' not in workflow and 'DEPLOY_BRANCH' not in workflow
    assert 'WEBCOMPILER_DEPLOY_KNOWN_HOSTS' in workflow
    deploy = (ROOT/'scripts/deploy_server.sh').read_text()
    assert deploy.index('scripts/deploy_guard.sh') < deploy.index('runtime-secrets.env')
    assert '--env-file /dev/null' in deploy and '--project-directory "$SOURCE_ROOT"' in deploy
    assert 'WEBCOMPILER_BACKEND_IMAGE="$WEBCOMPILER_PROJECT_PREFIX-backend:$DEPLOY_SHA"' in deploy
    assert 'SANDBOX_IMAGE="compiler-sandbox:$DEPLOY_SHA"' in deploy
    assert 'BPP_REF="$pinned_bpp_ref"' in deploy
    assert 'WEBCOMPILER_ENABLE_SANDBOX_UPDATER:-0' in deploy
    compiler_ref = (ROOT/'runtime/bpp-ref.txt').read_text().strip()
    assert len(compiler_ref) == 40 and all(c in '0123456789abcdef' for c in compiler_ref)


def test_main_never_prints_sensitive_subprocess_repr(monkeypatch,capsys):
    monkeypatch.setattr(dispatch,'dispatch',lambda env:(_ for _ in ()).throw(
        subprocess.CalledProcessError(1,['ssh','sensitive-test-token'])))
    assert dispatch.main() == 1
    assert capsys.readouterr().err == 'SSH deployment failed\n'
