"""Private worker process identity shared with a separate health-check CLI.

This is process liveness evidence, not proof that claims or sandboxes drained.
The lock stays open for the lifetime of the worker; stale markers are never
accepted solely because their PID, hostname, or runtime ID was reused.
"""
from dataclasses import asdict, dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import tempfile
from uuid import uuid4

from app.core.config import settings

BOOT_ID_PATTERN = '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'

@dataclass(frozen=True)
class ProcessIdentity:
    epoch: str
    pid: int
    start_token: str
    hostname: str
    scope: str

    def __post_init__(self):
        if not isinstance(self.epoch,str) or not re.fullmatch('[a-f0-9]{32}',self.epoch) or self.epoch=='0'*32:
            raise ValueError('Invalid worker process epoch')
        if type(self.pid) is not int or self.pid < 1:
            raise ValueError('Invalid worker process PID')
        for value, pattern in ((self.start_token,'[a-z0-9:-]{1,160}'),
                (self.hostname,'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,252}'), (self.scope,'[a-f0-9]{64}')):
            if not isinstance(value,str) or not re.fullmatch(pattern,value):
                raise ValueError('Invalid worker process identity')


def process_start_token(pid):
    """Kernel creation time, not wall clock or a process-local random value."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        handle = kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            raise OSError('Worker process unavailable')
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            code = wintypes.DWORD()
            if not kernel.GetProcessTimes(handle,*(ctypes.byref(value) for value in times)):
                raise OSError('Worker process creation time unavailable')
            if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value != 259:
                raise OSError('Worker process has exited')
            return 'windows:'+str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    raw = Path(f'/proc/{pid}/stat').read_text()
    fields = raw.rsplit(')',1)[-1].split()
    if (not raw.startswith(f'{pid} (') or ')' not in raw or len(fields) < 20
            or fields[0] not in tuple('RSDZTtXxKWPI')
            or not re.fullmatch('[0-9]+',fields[19])):
        raise ValueError('Worker process kernel identity unavailable')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if not re.fullmatch(BOOT_ID_PATTERN,boot):
        raise ValueError('Worker process boot identity unavailable')
    if fields[0] in ('Z','X','x'):
        # /proc/<tgid>/stat describes the thread-group leader. pthread_exit
        # can leave that leader a zombie while other threads still execute.
        # Field20 is num_threads: only a lone dead leader proves this entire
        # group cannot run. Ambiguous/multi-thread state is not absence.
        if fields[17]!='1':
            raise OSError('Thread group termination is unproven')
        raise ProcessLookupError('Worker process has exited')
    return 'linux:'+boot+':'+fields[19]


def local_namespace_token():
    """Only Linux has an implemented, kernel-bound observation namespace."""
    if sys.platform != 'linux':
        return None
    namespace = os.readlink('/proc/self/ns/pid')
    user_namespace = os.readlink('/proc/self/ns/user')
    # procfs exposes the namespace that mounted it, not necessarily ours.
    # Validate both PID numbering and its init namespace before reading targets.
    if (os.readlink('/proc/self') != str(os.getpid())
            or os.readlink('/proc/1/ns/pid') != namespace):
        raise ValueError('Process namespace addressing mismatch')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if (not re.fullmatch(r'pid:\[[0-9]+\]',namespace)
            or not re.fullmatch(r'user:\[[0-9]+\]',user_namespace)
            or not re.fullmatch(BOOT_ID_PATTERN,boot)):
        raise ValueError('Process namespace identity unavailable')
    return 'linux:'+boot+':'+namespace+':'+user_namespace+':uid:'+str(os.geteuid())


def configured_scope():
    values = [settings.REDIS_KEY_PREFIX,settings.RUNTIME_POOL_ID,
              settings.DEPLOYMENT_SHA,settings.RUNTIME_INSTANCE_ID,
              settings.SANDBOX_POOL_ID,settings.SANDBOX_IMAGE,
              settings.WORKER_STATE_DIRECTORY,'process-scope-v3',local_namespace_token()]
    return hashlib.sha256(json.dumps(values,separators=(',',':')).encode()).hexdigest()


def state_directory():
    configured = getattr(settings,'WORKER_STATE_DIRECTORY','')
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            raise ValueError('Worker state directory must be absolute')
        return path
    return Path(tempfile.gettempdir())/('webcompiler-worker-'+configured_scope()[:32])


def _checked_directory(path, *, create=False):
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
        raise ValueError('Unsafe worker state directory')
    if os.name != 'nt' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('Worker state directory must be private and owned')


def _open_private(path, flags):
    if path.is_symlink():
        raise ValueError('Worker state symlink refused')
    fd = os.open(path,flags|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Unsafe worker state file')
        if os.name != 'nt' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('Worker state file must be private and owned')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _lock(fd):
    if os.name == 'nt':
        import msvcrt
        os.lseek(fd,0,os.SEEK_SET)
        msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)


def _read(directory):
    _checked_directory(directory)
    fd = _open_private(directory/'identity.json',os.O_RDONLY)
    with os.fdopen(fd,'rb') as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError('Worker identity too large')
    value = json.loads(raw)
    if not isinstance(value,dict) or set(value) != {'epoch','pid','start_token','hostname','scope'}:
        raise ValueError('Invalid worker identity fields')
    identity = ProcessIdentity(**value)
    if identity.scope != configured_scope() or identity.hostname != socket.gethostname():
        raise ValueError('Worker identity scope mismatch')
    return identity


class WorkerProcessState:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else state_directory()
        self.identity = None
        self._fd = None
        self.readiness_revoked = False

    def start(self):
        if self._fd is not None:
            raise RuntimeError('Worker identity already started')
        _checked_directory(self.directory,create=True)
        fd = _open_private(self.directory/'process.lock',os.O_RDWR|os.O_CREAT)
        temporary = None
        try:
            _lock(fd)
            target = self.directory/'identity.json'
            if target.exists() or target.is_symlink():
                _read(self.directory)  # Never replace foreign/malformed state.
            identity = ProcessIdentity(uuid4().hex,os.getpid(),process_start_token(os.getpid()),
                                       socket.gethostname(),configured_scope())
            temporary_fd, temporary = tempfile.mkstemp(prefix='.identity-',dir=self.directory)
            with os.fdopen(temporary_fd,'w',encoding='utf-8',newline='\n') as stream:
                json.dump(asdict(identity),stream,sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary,target)
            temporary = None
            self._fd, self.identity = fd, identity
            self.readiness_revoked = False
            return identity
        except BaseException:
            os.close(fd)
            raise
        finally:
            if temporary is not None:
                Path(temporary).unlink()  # Only the mkstemp file created above.

    def current(self):
        if self._fd is None or self.identity is None:
            raise RuntimeError('Worker identity not started')
        if _read(self.directory) != self.identity:
            raise RuntimeError('Worker process identity changed')
        if process_start_token(self.identity.pid) != self.identity.start_token:
            raise RuntimeError('Worker process identity expired')
        return self.identity

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def read_live_identity(directory=None):
    """CLI reads the worker's identity, not its own PID or random UUID."""
    directory = Path(directory) if directory is not None else state_directory()
    identity = _read(directory)
    if process_start_token(identity.pid) != identity.start_token:
        raise ValueError('Worker process no longer matches its marker')
    fd = _open_private(directory/'process.lock',os.O_RDWR)
    try:
        try:
            _lock(fd)
        except OSError as exc:
            if exc.errno not in (errno.EACCES,errno.EAGAIN):
                raise
            # Re-read after the liveness/lock checks; never combine two epochs.
            if _read(directory) != identity:
                raise ValueError('Worker identity changed during readiness probe')
            if process_start_token(identity.pid) != identity.start_token:
                raise ValueError('Worker process changed during readiness probe')
            return identity
        raise ValueError('Worker lifetime lock is not held')
    finally:
        os.close(fd)
