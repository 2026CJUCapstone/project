"""Opt-in, bounded Linux cgroup evidence probe, NOT an application judge test.

Runs two sequential trusted Python workloads in existing immutable images.
No image pull/build, DB/queue/network/host mounts, or shared cgroup writes.
Requires explicit --execute; the caller must have isolated-test authorization.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid


def docker(*args, timeout=20):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Docker probe operation failed: ' + args[0])
    return result.stdout.strip()


def capacity():
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    free = shutil.disk_usage('/').free
    if memory['MemAvailable'] < 2 * 1024**3 or free < 4 * 1024**3:
        raise RuntimeError('Isolated probe capacity floor not met')
    return {'availableMemoryBytes': memory['MemAvailable'], 'freeDiskBytes': free}


def fields(path):
    raw = path.read_text()
    if len(raw) > 16384:
        raise RuntimeError('Unexpected cgroup counter size')
    values = {}
    for line in raw.splitlines():
        key, value = line.split()
        if not value.isascii() or not value.isdigit() or key in values:
            raise RuntimeError('Invalid cgroup counter')
        values[key] = int(value)
    return values


def read_cgroup(pid, container_id):
    entries = Path(f'/proc/{pid}/cgroup').read_text().splitlines()
    unified = [line[3:] for line in entries if line.startswith('0::')]
    if len(unified) != 1:
        raise RuntimeError('Unified cgroup v2 is required')
    relative = Path(unified[0].lstrip('/'))
    if '..' in relative.parts or relative.name not in (container_id, 'docker-' + container_id + '.scope'):
        raise RuntimeError('Refusing a cgroup not owned by this exact probe container')
    root = Path('/sys/fs/cgroup').resolve()
    group = (root / relative).resolve(strict=True)
    if root not in group.parents:
        raise RuntimeError('Cgroup path escaped its root')
    cpu = fields(group / 'cpu.stat')
    events = fields(group / 'memory.events')
    return dict(cpuUsageUsec=cpu['usage_usec'], peakMemoryBytes=int((group / 'memory.peak').read_text()),
                oomKills=events['oom_kill'], memoryMax=int((group / 'memory.max').read_text()),
                swapMax=int((group / 'memory.swap.max').read_text()),
                pidsMax=int((group / 'pids.max').read_text()))


def probe(image, mode):
    token = uuid.uuid4().hex
    container_id = None
    # The parent keeps the cgroup alive after its child exits. This demonstrates
    # the lifetime requirement; it is not a security-ready sandbox supervisor.
    child = ('x=bytearray(8*1024*1024); sum(range(1000000))' if mode == 'normal'
             else 'x=bytearray(256*1024*1024)')
    program = ('import subprocess,time; '
               'time.sleep(0.5); '
               f'subprocess.run(["python3","-c",{child!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); '
               'time.sleep(4)')
    started = time.monotonic()
    observations = []
    try:
        container_id = docker('create', '--pull=never', '--name', 'webcompiler-cgroup-probe-' + token,
            '--label', 'webcompiler.isolated-cgroup-probe=' + token,
            '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--user=65534:65534', '--memory=64m', '--memory-swap=64m', '--cpus=0.25',
            '--pids-limit=16', '--ulimit=nofile=64:64', '--tmpfs=/tmp:rw,noexec,nosuid,size=4m',
            '--log-driver=none', '--entrypoint=python3', image, '-c', program)
        if not re.fullmatch('[0-9a-f]{64}', container_id):
            raise RuntimeError('Unexpected container identity')
        docker('start', container_id)
        while time.monotonic() - started < 15:
            state = json.loads(docker('inspect', '--format={{json .State}}', container_id))
            if not state['Running']:
                break
            try:
                observations.append(read_cgroup(state['Pid'], container_id))
            except FileNotFoundError:
                # Exit raced the read. Do not substitute zero for missing data.
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError('Probe exceeded its 15-second safety deadline')
        if not observations or state['ExitCode'] != 0:
            raise RuntimeError('Probe parent failed or no trustworthy counters were obtained')
        last = observations[-1]
        assert last['memoryMax'] == 64 * 1024**2 and last['swapMax'] == 0 and last['pidsMax'] == 16
        assert last['cpuUsageUsec'] > 0 and last['peakMemoryBytes'] > 0
        if mode == 'oom':
            assert last['oomKills'] >= 1
        else:
            assert last['oomKills'] == 0
        return {'mode': mode, 'elapsedSeconds': round(time.monotonic() - started, 3),
                'samples': len(observations), 'counters': last,
                'dockerOOMKilled': state['OOMKilled'], 'containerExitCode': state['ExitCode']}
    finally:
        if container_id and re.fullmatch('[0-9a-f]{64}', container_id):
            actual = json.loads(docker('inspect', '--format={{json .Config.Labels}}', container_id))
            if actual.get('webcompiler.isolated-cgroup-probe') != token:
                raise RuntimeError('Cleanup identity changed; refusing removal')
            docker('rm', '-f', container_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='Existing exact sha256 image ID, never a tag')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if os.name != 'posix' or not re.fullmatch('sha256:[0-9a-f]{64}', args.image):
        raise SystemExit('Requires Linux and an exact immutable image ID')
    if not args.execute:
        raise SystemExit('No actions performed; explicit --execute is required')
    if docker('image', 'inspect', '--format={{.Id}}', args.image) != args.image:
        raise SystemExit('Exact existing image is unavailable')
    report = {'scope': 'isolated cgroup mechanics only; not application TLE/MLE acceptance',
              'image': args.image, 'kernel': os.uname().release, 'before': capacity()}
    report['probes'] = []
    for mode in ('normal', 'oom'):
        capacity()
        report['probes'].append(probe(args.image, mode))
    report['after'] = capacity()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
