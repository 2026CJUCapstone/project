"""One measured phase in a private Linux PID/cgroup namespace.

NOT a host command runner. Must be container PID 1, uid 0, with private
read-only cgroup v2, no network, no-new-privileges and only KILL/SETUID/SETGID
capabilities. Child runs as 65534 with a fresh environment. The worker reads
root-only /control files through Docker, never trusts child stdout as metadata.
The parent stays alive briefly so the worker can copy artifacts/counters before
the container and its tmpfs disappear. Missing report is infrastructure failure.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import sys
import time


CONTROL = Path('/control')
CGROUP = Path('/sys/fs/cgroup')
UID = 65534
POLL_SECONDS = 0.005
CLEANUP_SECONDS = 2
COLLECTION_SECONDS = 30


def positive(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('Invalid integer limit')
    return value


def validate_spec(raw):
    if not isinstance(raw, dict) or set(raw) != {'version','phase','argv','stdin','limits'}:
        raise ValueError('Invalid phase specification')
    if type(raw['version']) is not int or raw['version'] != 1 or raw['phase'] not in ('compile','run'):
        raise ValueError('Unsupported phase')
    argv = raw['argv']
    if (not isinstance(argv,list) or not 1 <= len(argv) <= 40
            or any(not isinstance(s,str) or not s or len(s)>8192 or '\x00' in s for s in argv)
            or not argv[0].startswith('/')):
        raise ValueError('Trusted absolute command required')
    if raw['stdin'] not in ('/dev/null','/input/stdin'):
        raise ValueError('Unexpected stdin path')
    limits = raw['limits']
    bounds = {'cpuMs':300000,'wallMs':600000,'memoryBytes':8*1024**3,
              'outputBytes':16*1024**2,'pids':256,'tmpBytes':8*1024**3}
    if not isinstance(limits,dict) or set(limits) != set(bounds):
        raise ValueError('Exact phase limits required')
    for name, maximum in bounds.items():
        if name == 'tmpBytes' and type(limits[name]) is int and limits[name] == 0:
            continue
        positive(limits[name], maximum)
    if limits['tmpBytes'] > limits['memoryBytes'] or limits['pids'] < 2:
        raise ValueError('Phase needs supervisor/child PID and bounded temporary space')
    return raw


def fields(path):
    raw = path.read_text(encoding='ascii')
    if len(raw)>16384:
        raise ValueError('Oversized counter')
    result = {}
    for line in raw.splitlines():
        key, value = line.split()
        if key in result or not value.isascii() or not value.isdigit():
            raise ValueError('Invalid counter')
        result[key] = int(value)
    return result


def counters(root=CGROUP):
    cpu = fields(root/'cpu.stat')
    events = fields(root/'memory.events')
    peak = (root/'memory.peak').read_text(encoding='ascii').strip()
    if not peak.isascii() or not peak.isdigit():
        raise ValueError('Missing peak memory counter')
    return {'cpuUsec':cpu['usage_usec'],'peakMemoryBytes':int(peak),
            'oomKills':events['oom_kill'], 'oomEvents':events['oom']}


def inspect_environment(limits):
    # This check is mandatory before any kill(-1), including on failure paths.
    if sys.platform != 'linux' or os.getpid()!=1 or os.geteuid()!=0:
        raise RuntimeError('Requires root PID 1 in a private Linux container')
    own = Path('/proc/self/cgroup').read_text().strip()
    if own != '0::/':
        raise RuntimeError('Private cgroup v2 namespace required')
    status = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    expected_caps = (1<<5) | (1<<6) | (1<<7)  # KILL, SETGID, SETUID only
    if (int(status['CapEff'].strip(),16) != expected_caps
            or int(status['CapBnd'].strip(),16) != expected_caps
            or status['NoNewPrivs'].strip() != '1'):
        raise RuntimeError('Unexpected privilege profile')
    if not os.statvfs(CGROUP).f_flag & os.ST_RDONLY:
        raise RuntimeError('Cgroup mount must be read-only')
    if int((CGROUP/'memory.max').read_text()) != limits['memoryBytes']:
        raise RuntimeError('Memory limit mismatch')
    if int((CGROUP/'memory.swap.max').read_text()) != 0:
        raise RuntimeError('Swap must be disabled')
    if int((CGROUP/'pids.max').read_text()) != limits['pids']:
        raise RuntimeError('PID limit mismatch')
    quota, period = (CGROUP/'cpu.max').read_text().split()
    if int(quota)!=int(period):
        raise RuntimeError('Measured lane must allocate exactly one CPU')
    info = CONTROL.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o700:
        raise RuntimeError('Root-only report directory required')
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(4,0,0,0,0) != 0:  # PR_SET_DUMPABLE=0; do not expose parent state.
        raise RuntimeError('Cannot protect supervisor state')


def kill_children():
    if os.getpid()!=1 or os.geteuid()!=0:
        raise RuntimeError('Refusing non-container process cleanup')
    try:
        os.kill(-1,signal.SIGKILL)
    except ProcessLookupError:
        pass


def drain_waits(leader, leader_status):
    while True:
        try:
            pid,status = os.waitpid(-1,os.WNOHANG)
        except ChildProcessError:
            return leader_status, True
        if pid==0:
            return leader_status, False
        if pid==leader:
            leader_status = status


def resource_reason(start, current, elapsed_ns, limits, previous=None):
    if current['cpuUsec']<start['cpuUsec'] or current['oomKills']<start['oomKills']:
        raise RuntimeError('Cgroup counter regressed')
    # Proven OOM takes precedence over simultaneous lower-priority events.
    if current['oomKills']>start['oomKills']:
        return 'memory_limit_exceeded'
    if previous:
        return previous
    if current['cpuUsec']-start['cpuUsec'] >= limits['cpuMs']*1000:
        return 'time_limit_exceeded'
    if elapsed_ns >= limits['wallMs']*1_000_000:
        return 'time_limit_exceeded'
    return None


def run_phase(spec):
    import resource  # Linux-only, kept out of pure parser/metric unit imports.
    limits = spec['limits']
    inspect_environment(limits)
    if spec['phase']=='compile':
        artifact=Path('/work/artifact')
        artifact.mkdir(mode=0o777)
        artifact.chmod(0o777)
        # JS syntax-check produces no object file. Preserve exactly the source
        # that was checked; the worker's registry decides which toolchain runs.
        source=Path('/source/main.js')
        if source.is_file():
            with source.open('rb') as handle: code=handle.read(200001)
            if len(code)>200000: raise RuntimeError('Oversized source')
            (artifact/'main.js').write_bytes(code)
            (artifact/'main.js').chmod(0o444)
    # Capture bounded output in root-only files. Child output is never parsed
    # as a frame and the child cannot edit result.json or these diagnostic files.
    out_file = open(CONTROL/'stdout','xb', buffering=0)
    err_file = open(CONTROL/'stderr','xb', buffering=0)
    input_fd = os.open(spec['stdin'],os.O_RDONLY | os.O_NOFOLLOW)
    if not stat.S_ISREG(os.fstat(input_fd).st_mode) and spec['stdin']!='/dev/null':
        raise RuntimeError('Regular stdin file required')
    out_r,out_w = os.pipe()
    err_r,err_w = os.pipe()
    leader = None
    selector = selectors.DefaultSelector()
    baseline = counters()
    started = time.monotonic_ns()
    try:
        leader = os.fork()
        if leader==0:
            try:
                os.dup2(input_fd,0); os.dup2(out_w,1); os.dup2(err_w,2)
                os.closerange(3, int(resource.getrlimit(resource.RLIMIT_NOFILE)[0]))
                os.setgroups([])
                os.setresgid(UID,UID,UID)
                os.setresuid(UID,UID,UID)
                os.umask(0o022)  # Compiler artifacts must be readable after tree reap.
                os.chdir('/work')
                resource.setrlimit(resource.RLIMIT_CORE,(0,0))
                os.execve(spec['argv'][0],spec['argv'],{
                    'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':'/work','TMPDIR':'/work',
                    'LANG':'C.UTF-8','LC_ALL':'C.UTF-8'})
            except BaseException:
                # 127 cannot authenticate an infrastructure failure; it remains
                # an ordinary nonzero command exit, not a fabricated OOM/TLE.
                os._exit(127)
        os.close(input_fd); input_fd=None
        os.close(out_w); out_w=None
        os.close(err_w); err_w=None
        for fd,destination in ((out_r,out_file),(err_r,err_file)):
            os.set_blocking(fd,False)
            selector.register(fd,selectors.EVENT_READ,destination)
        leader_status = None
        reason = None
        total_output = 0
        stopping_at = None
        end_ns = None
        while True:
            leader_status, no_children = drain_waits(leader,leader_status)
            now = time.monotonic_ns()
            current = counters()
            reason = resource_reason(baseline,current,(end_ns or now)-started,limits,reason)
            if reason or leader_status is not None:
                if stopping_at is None:
                    stopping_at=now
                    end_ns=now
                kill_children()  # Includes reparented/detached grandchildren.
            for key,_ in selector.select(POLL_SECONDS):
                try:
                    chunk=os.read(key.fd,65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                available=max(0,limits['outputBytes']-total_output)
                kept=chunk[:available]
                key.data.write(kept)
                total_output += len(kept)
                if len(chunk)>available:
                    reason=reason or 'output_limit_exceeded'
            if no_children and not selector.get_map():
                break
            if stopping_at is not None and now-stopping_at>CLEANUP_SECONDS*1_000_000_000:
                raise RuntimeError('Process tree cleanup not confirmed')
        if leader_status is None:
            raise RuntimeError('No leader termination evidence')
        final = counters()
        # CPU includes every child/thread up through proven tree termination;
        # peak includes this small supervisor and output tmpfs, never RSS sums.
        wall_ns=(end_ns or time.monotonic_ns())-started
        reason=resource_reason(baseline,final,wall_ns,limits,reason)
        return {'version':1,'phase':spec['phase'],'exitCode':os.waitstatus_to_exitcode(leader_status),
                'failureReason':reason,'cpuUsec':final['cpuUsec']-baseline['cpuUsec'],
                'wallNs':wall_ns,'peakMemoryBytes':final['peakMemoryBytes'],
                'oomKills':final['oomKills']-baseline['oomKills'],
                'outputBytes':total_output,'treeReaped':True}
    finally:
        if leader:
            kill_children()
        selector.close()
        for fd in (input_fd,out_r,out_w,err_r,err_w):
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
        out_file.close(); err_file.close()


def main():
    try:
        raw=os.environ.pop('JUDGE_PHASE_SPEC')
        if len(raw)>65536:
            raise ValueError('Oversized phase specification')
        spec=validate_spec(json.loads(raw))
        result=run_phase(spec)
        with open(CONTROL/'result.json','x',encoding='ascii') as output:
            json.dump(result,output,separators=(',',':'))
        # This is the supervisor's original stdout, NOT the child's pipe. The
        # child replaced fd 1/2 and closed every other inherited descriptor.
        # Signal readiness without spawning a counter-polluting exec process.
        print(json.dumps(result,separators=(',',':')),flush=True)
        # A completed report is the collection handshake. This grace period is
        # not execution time. The worker must remove the exact container sooner.
        time.sleep(COLLECTION_SECONDS)
        return 0
    except BaseException:
        # No report => fail closed. Never publish raw paths/input/spec in logs.
        return 72


if __name__=='__main__':
    sys.exit(main())
