"""Real file locks and a separate CLI interpreter observe one live epoch."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.services import worker_process as module
from app.services.worker_process import WorkerProcessState, read_live_identity


def test_separate_interpreter_reads_held_identity_and_rejects_closed_lock(tmp_path):
    directory = tmp_path/'worker'
    state = WorkerProcessState(directory)
    identity = state.start()
    script = ('import sys; from app.services.worker_process import read_live_identity; '
              'print(read_live_identity(sys.argv[1]).epoch)')
    try:
        assert state.current() == identity
        result = subprocess.run([sys.executable,'-c',script,str(directory)],
            cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == identity.epoch
        with pytest.raises(OSError):
            WorkerProcessState(directory).start()
        assert state.current() == identity
    finally:
        state.close()
    result = subprocess.run([sys.executable,'-c',script,str(directory)],
        cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
    assert result.returncode != 0
    assert directory.joinpath('identity.json').is_file()  # Stale evidence is preserved.
    restarted = WorkerProcessState(directory)
    try:
        assert restarted.start().epoch != identity.epoch
    finally:
        restarted.close()


def test_changed_process_start_time_is_rejected_even_with_same_pid(tmp_path, monkeypatch):
    state = WorkerProcessState(tmp_path/'worker')
    identity = state.start()
    try:
        monkeypatch.setattr(module,'process_start_token',lambda pid:identity.start_token+'1')
        with pytest.raises((ValueError,RuntimeError),match='(expired|marker)'):
            read_live_identity(state.directory)
        with pytest.raises(RuntimeError,match='expired'):
            state.current()
    finally:
        state.close()


@pytest.mark.parametrize('contents', [b'{}',b'null',b'[]',b'not-json',b'x'*4097])
def test_malformed_marker_is_not_overwritten_or_accepted(tmp_path, contents):
    directory = tmp_path/'worker'
    directory.mkdir(mode=0o700)
    marker = directory/'identity.json'
    marker.write_bytes(contents)
    marker.chmod(0o600)
    with pytest.raises((ValueError,TypeError)):
        WorkerProcessState(directory).start()
    assert marker.read_bytes() == contents
    with pytest.raises((ValueError,TypeError)):
        read_live_identity(directory)


def test_identity_scope_mismatch_cannot_be_adopted(tmp_path, monkeypatch):
    state = WorkerProcessState(tmp_path/'worker')
    state.start()
    state.close()
    original = (state.directory/'identity.json').read_bytes()
    monkeypatch.setattr(module,'configured_scope',lambda:'f'*64)
    with pytest.raises(ValueError,match='scope mismatch'):
        WorkerProcessState(state.directory).start()
    assert (state.directory/'identity.json').read_bytes() == original


def test_unexpected_lock_error_is_not_liveness_evidence(tmp_path, monkeypatch):
    import errno
    state = WorkerProcessState(tmp_path/'worker')
    state.start()
    def unsupported(fd):
        raise OSError(errno.ENOSYS,'fixture unsupported lock')
    try:
        monkeypatch.setattr(module,'_lock',unsupported)
        with pytest.raises(OSError,match='unsupported'):
            read_live_identity(state.directory)
    finally:
        state.close()


def test_exit_between_initial_pid_check_and_lock_probe_is_rejected(tmp_path, monkeypatch):
    import errno
    state = WorkerProcessState(tmp_path/'worker')
    identity = state.start()
    tokens = iter((identity.start_token,identity.start_token+'1'))
    def held(fd):
        raise OSError(errno.EAGAIN,'fixture replacement process owns lock')
    try:
        monkeypatch.setattr(module,'process_start_token',lambda pid:next(tokens))
        monkeypatch.setattr(module,'_lock',held)
        with pytest.raises(ValueError,match='changed during'):
            read_live_identity(state.directory)
    finally:
        state.close()


@pytest.mark.skipif(os.name=='nt',reason='POSIX ownership/mode and unprivileged symlinks')
@pytest.mark.parametrize('kind',['directory','marker','lock','hardlink','permissions'])
def test_unsafe_state_is_refused_without_touching_target(tmp_path, kind):
    directory = tmp_path/'worker'
    directory.mkdir(mode=0o700)
    target = tmp_path/'preserve'
    target.write_text('keep')
    target.chmod(0o600)
    if kind == 'directory':
        real = tmp_path/'actual'
        directory.rename(real)
        directory.symlink_to(real,target_is_directory=True)
    elif kind == 'marker':
        (directory/'identity.json').symlink_to(target)
    elif kind == 'lock':
        (directory/'process.lock').symlink_to(target)
    elif kind == 'hardlink':
        os.link(target,directory/'process.lock')
    else:
        directory.chmod(0o755)
    with pytest.raises((OSError,ValueError)):
        WorkerProcessState(directory).start()
    assert target.read_text() == 'keep'
