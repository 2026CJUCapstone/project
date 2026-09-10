"""Do not confuse a procfs mount's PID numbering with the caller's namespace."""
from pathlib import Path

import pytest

from app.services import worker_process as module


def kernel_files(monkeypatch, stat, boot):
    files = {'/proc/73/stat':stat, '/proc/sys/kernel/random/boot_id':boot}
    monkeypatch.setattr(Path, 'read_text', lambda path:files[path.as_posix()])


@pytest.fixture
def linux_proc(monkeypatch):
    links = {'/proc/self':'73', '/proc/self/ns/pid':'pid:[101]',
             '/proc/1/ns/pid':'pid:[101]', '/proc/self/ns/user':'user:[201]'}
    monkeypatch.setattr(module.sys, 'platform', 'linux')
    monkeypatch.setattr(module.os, 'getpid', lambda:73)
    monkeypatch.setattr(module.os, 'geteuid', lambda:1001, raising=False)
    monkeypatch.setattr(module.os, 'readlink', lambda path:links[str(path)])
    def read_text(path):
        path = path.as_posix()
        if path == '/proc/sys/kernel/random/boot_id':
            return '01234567-89ab-cdef-0123-456789abcdef\n'
        if path == '/proc/73/stat':
            return '73 (worker) S '+' '.join(['0']*18)+' 123\n'
        raise AssertionError(f'unexpected proc path: {path}')
    monkeypatch.setattr(Path, 'read_text', read_text)
    return links


def test_proc_mount_with_parent_pid_numbering_is_refused(linux_proc):
    linux_proc['/proc/self'] = '10573'
    with pytest.raises(ValueError, match='namespace'):
        module.local_namespace_token()


def test_proc_mount_with_other_init_namespace_is_refused_even_if_pid_number_matches(linux_proc):
    linux_proc['/proc/1/ns/pid'] = 'pid:[100]'
    with pytest.raises(ValueError, match='namespace'):
        module.local_namespace_token()


def test_equal_uid_in_other_user_namespace_has_different_scope(linux_proc):
    first = module.configured_scope()
    linux_proc['/proc/self/ns/user'] = 'user:[202]'
    assert module.configured_scope() != first


def test_same_proc_and_user_namespace_is_stable(linux_proc):
    first = module.local_namespace_token()
    assert module.local_namespace_token() == first
    assert 'pid:[101]' in first and 'user:[201]' in first and 'uid:1001' in first


@pytest.mark.parametrize('name,value', [('/proc/self','bad'),
    ('/proc/self/ns/pid','pid:101'), ('/proc/self/ns/user','user:201')])
def test_malformed_namespace_evidence_is_refused(linux_proc, name, value):
    linux_proc[name] = value
    with pytest.raises(ValueError, match='namespace'):
        module.local_namespace_token()


@pytest.mark.parametrize('changed', ['pid','state','ticks','boot','truncated'])
def test_malformed_kernel_identity_is_not_a_different_live_process(monkeypatch, changed):
    # Bind os locally: replacing the global os.name would break pathlib on Windows.
    from types import SimpleNamespace
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='posix'))
    pid, state, ticks = ('74' if changed == 'pid' else '73'), ('?' if changed == 'state' else 'S'), ('bad' if changed == 'ticks' else '123')
    stat = pid+' (name with ) parentheses) '+state+' '+' '.join(['0']*18)+' '+ticks
    if changed == 'truncated':
        stat = '73 (truncated) S'
    boot = 'malformed' if changed == 'boot' else '01234567-89ab-cdef-0123-456789abcdef'
    kernel_files(monkeypatch,stat,boot)
    with pytest.raises(ValueError, match='identity'):
        module.process_start_token(73)


def test_process_comm_parentheses_do_not_corrupt_start_token(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='posix'))
    stat = '73 (name with ) parentheses) S '+' '.join(['0']*18)+' 123'
    boot = '01234567-89ab-cdef-0123-456789abcdef'
    kernel_files(monkeypatch,stat,boot)
    assert module.process_start_token(73) == 'linux:'+boot+':123'


@pytest.mark.parametrize('state',['Z','X','x'])
@pytest.mark.parametrize('threads',['1','2','0','bad',''])
def test_dead_leader_is_absent_only_when_no_other_threads_can_run(monkeypatch,state,threads):
    from types import SimpleNamespace
    monkeypatch.setattr(module,'os',SimpleNamespace(name='posix'))
    fields=[state]+['0']*18+['123']
    fields[17]=threads
    kernel_files(monkeypatch,'73 (worker) '+' '.join(fields),'01234567-89ab-cdef-0123-456789abcdef')
    if threads=='1':
        with pytest.raises(ProcessLookupError):
            module.process_start_token(73)
    else:
        with pytest.raises((ValueError,OSError)) as error:
            module.process_start_token(73)
        assert not isinstance(error.value,ProcessLookupError)
