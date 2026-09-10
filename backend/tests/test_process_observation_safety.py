"""Observer infrastructure failures and stale active markers are not absence."""
import errno
from pathlib import Path
from uuid import uuid4

import pytest

from app.services import process_observation as observer
from app.services import worker_process as worker
from app.services.worker_process import ProcessIdentity, WorkerProcessState, read_live_identity
from tests.test_process_namespace import linux_proc


@pytest.mark.parametrize('path', ['/proc/self','/proc/self/ns/pid','/proc/1/ns/pid',
    '/proc/self/ns/user','/proc/sys/kernel/random/boot_id'])
@pytest.mark.parametrize('error', [errno.EACCES,errno.ENOENT,errno.EIO])
def test_namespace_io_failure_is_unknown_without_target_probe(linux_proc, monkeypatch, path, error):
    readlink, readtext = worker.os.readlink, Path.read_text
    def read_link(value):
        if str(value) == path:
            raise OSError(error,'fixture namespace read failure',path)
        return readlink(value)
    def read_text(value):
        if value.as_posix() == path:
            raise OSError(error,'fixture boot read failure',path)
        return readtext(value)
    def unexpected(_pid):
        pytest.fail('Target PID must not be probed after namespace failure')
    monkeypatch.setattr(worker.os,'readlink',read_link)
    monkeypatch.setattr(Path,'read_text',read_text)
    monkeypatch.setattr(observer,'process_start_token',unexpected)
    identity = ProcessIdentity(uuid4().hex,73,'linux:boot:123','fixture','a'*64)
    assert observer.local_process_state(identity) == 'unknown'


def test_stale_scope_rejects_active_marker_and_separate_reader(tmp_path, monkeypatch):
    state = WorkerProcessState(tmp_path/'owned-marker')
    identity = state.start()
    try:
        before = (state.directory/'identity.json').read_bytes()
        monkeypatch.setattr(worker,'configured_scope',lambda:'a'*64 if identity.scope != 'a'*64 else 'b'*64)
        with pytest.raises((ValueError,RuntimeError),match='(scope|marker)'):
            state.current()
        with pytest.raises((ValueError,RuntimeError),match='(scope|marker)'):
            read_live_identity(state.directory)
        assert (state.directory/'identity.json').read_bytes() == before
    finally:
        state.close()
