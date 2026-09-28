"""Opt-in isolated compiler rebuild. No service mounts, network, or promotion.

Uses an existing, explicitly chosen sandbox image and cleans up its exact
container ID even after a timeout. Requires >=4 GiB available host memory.
"""
import argparse
import base64
import hashlib
import gzip
import json
import re
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = r'''
import base64, hashlib, json, pathlib, shutil, subprocess, time, sys
root = pathlib.Path('/tmp/exploration')
root.mkdir()
shutil.copytree('/opt/Bpp/src', root / 'src')
namespace = {'__name__': 'patch_library'}
exec(PATCHER, namespace)
source = root / 'src/ssa/dump.bpp'
source.write_text(namespace['patch_source'](source.read_text(), EXTENSION))
(root / 'bpp.toml').write_text('version=v13\nstd_root=src\nnasm_path=/usr/bin/nasm\nld_path=/usr/bin/ld\n')
compiler = '/usr/local/libexec/bpp/v13_stage1'
started = time.monotonic()
if CACHED_BINARY:
    candidate_bytes = base64.b64decode(CACHED_BINARY)
    assert hashlib.sha256(candidate_bytes).hexdigest() == CACHED_SHA
    (root / 'candidate').write_bytes(candidate_bytes)
    (root / 'candidate').chmod(0o700)
else:
    print('Building isolated compiler candidate', file=sys.stderr, flush=True)
    with (root / 'candidate.asm').open('w') as output:
        result = subprocess.run([compiler, '-asm', str(root / 'src/main.bpp')], cwd=root, stdout=output, stderr=subprocess.PIPE, timeout=700)
    if result.returncode: raise RuntimeError(str(result.returncode) + ': ' + result.stderr.decode()[-4000:])
    subprocess.run(['nasm', '-felf64', '-O1', str(root / 'candidate.asm'), '-o', str(root / 'candidate.o')], check=True, timeout=60)
    subprocess.run(['ld', str(root / 'candidate.o'), '-o', str(root / 'candidate')], check=True, timeout=30)
    print(json.dumps({'artifact': base64.b64encode((root / 'candidate').read_bytes()).decode()}), flush=True)
print('Candidate ready; validating actual outputs', file=sys.stderr, flush=True)
reports = []
cases = {
 'condition': 'func main() -> u64 { var score: u64 = 12; if (score > 10) { return 1; } return 0; }',
 'loop': 'func main() -> u64 { var index: u64 = 0; var total: u64 = 0; while (index < 4) { total = total + index; index = index + 1; } return total; }',
 'call': 'func increment(value: u64) -> u64 { return value + 1; }\nfunc main() -> u64 { var input: u64 = 4; var output: u64 = increment(input); return output; }',
}
if ONLY_GATE:
    gate_namespace = {'__name__': 'gate_library'}
    exec(GATE, gate_namespace)
    cases = {'gate': gate_namespace['SOURCE']}
for name, code in cases.items():
    path = root / 'main.bpp'
    path.write_text(code)
    for level in ('O0', 'O1'):
        print(name + ' ' + level, file=sys.stderr, flush=True)
        result = subprocess.run([str(root / 'candidate'), '--emit-json', '--source-map-user-only', '--ast-no-std', '-' + level, str(path)], cwd=root, capture_output=True, text=True, timeout=40)
        if result.returncode: raise RuntimeError(name + ': ' + result.stderr[-2000:])
        payload = json.loads(result.stdout)
        if ONLY_GATE: gate_namespace['validate'](payload, optimized=level == 'O1')
        functions = payload['views']['ssa']['ssa']['functions']
        functions = [fn for fn in functions if fn['name'] in ('main', 'increment') or fn['name'].endswith(('__main', '__increment'))]
        payload['views']['ssa']['ssa']['functions'] = functions
        assert functions and all(f['optimizationSummary']['version'] == 1 for f in functions)
        instructions = [i for f in functions for b in f['blocks'] for i in b['instructions']]
        assert instructions and all(i['valueFlow']['version'] == 1 for i in instructions)
        calls = [i['valueFlow'] for i in instructions if i.get('op') == 'call' or i.get('opcode') == 'call']
        if name in ('call', 'gate') and level == 'O0': assert calls and any(call['uses'] for call in calls), 'Actual call arguments missing'
        ir_result = subprocess.run([str(root / 'candidate'), '-dump-ir-json', '-' + level, str(path)], cwd=root, capture_output=True, text=True, timeout=40)
        assert ir_result.returncode == 0, ir_result.stderr[-2000:]
        ir_payload = json.loads(ir_result.stdout)
        assert ir_payload['ssa']['stage'] == 'ir'
        ir_payload['ssa']['functions'] = [fn for fn in ir_payload['ssa']['functions'] if fn['name'] in ('main', 'increment') or fn['name'].endswith(('__main', '__increment'))]
        with (root / 'example.asm').open('w') as output:
            subprocess.run([str(root / 'candidate'), '-asm', '-' + level, str(path)], cwd=root, stdout=output, check=True, timeout=40)
        subprocess.run(['nasm', '-felf64', str(root / 'example.asm'), '-o', str(root / 'example.o')], check=True, timeout=20)
        subprocess.run(['ld', str(root / 'example.o'), '-o', str(root / 'example')], check=True, timeout=20)
        executed = subprocess.run([str(root / 'example')], timeout=10)
        assert executed.returncode == {'condition': 1, 'loop': 6, 'call': 5, 'gate': 5}[name], (name, level, executed.returncode)
        reports.append({'case': name, 'level': level, 'instructions': len(instructions), 'calls': calls,
                        'summaries': [f['optimizationSummary'] for f in functions], 'source': code,
                        'unified': payload, 'ir': ir_payload})
        del result, ir_result, instructions
gate = {'__name__': 'gate_library'}
exec(GATE, gate)
path = root / 'main.bpp'
path.write_text(gate['SOURCE'])
for level in (() if ONLY_GATE else ('O0', 'O1')):
    result = subprocess.run([str(root / 'candidate'), '--emit-json', '--source-map-user-only', '--ast-no-std', '-' + level, str(path)], cwd=root, capture_output=True, text=True, timeout=60, check=True)
    gate['validate'](json.loads(result.stdout), optimized=level == 'O1')
print(json.dumps({'scope': 'gate-only' if ONLY_GATE else 'tutorials-and-gate', 'elapsedSeconds': round(time.monotonic() - started, 1), 'reports': reports}), flush=True)
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-host', required=True)
    parser.add_argument('--ssh-port', type=int, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--cache-directory', type=Path, help='Optional local build-artifact cache (not installed anywhere)')
    parser.add_argument('--recover-container', help='Recover output from this exact owned test container after a disconnected SSH session')
    parser.add_argument('--follow-recovery', action='store_true', help='Wait for this owned container to finish while recovering logs')
    parser.add_argument('--gate-only', action='store_true', help='Validate the combined branch/call build gate only, not the three tutorials')
    args = parser.parse_args()
    folder = ROOT / 'runtime/compiler-patches'
    script = 'PATCHER = ' + repr((folder / 'apply_exploration.py').read_text()) + '\n'
    script += 'EXTENSION = ' + repr((folder / 'exploration.bpp').read_text()) + '\n'
    script += 'GATE = ' + repr((ROOT / 'runtime/sandbox/verify_bpp_exploration.py').read_text()) + '\n'
    source_signature = hashlib.sha256(((folder / 'apply_exploration.py').read_text() + (folder / 'exploration.bpp').read_text() + args.image).encode()).hexdigest()
    cached = None
    if args.cache_directory:
        args.cache_directory.mkdir(parents=True, exist_ok=True)
        metadata_path = args.cache_directory / 'candidate.json'
        binary_path = args.cache_directory / 'candidate.bin'
        if metadata_path.is_file() and binary_path.is_file():
            metadata = json.loads(metadata_path.read_text())
            binary = binary_path.read_bytes()
            if metadata.get('sourceSignature') == source_signature and metadata.get('sha256') == hashlib.sha256(binary).hexdigest():
                cached = binary
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4', '-p', str(args.ssh_port), args.ssh_host]
    if args.recover_container:
        if not re.fullmatch('[a-f0-9]{12,64}', args.recover_container):
            raise ValueError('Expected exact container ID')
        label = subprocess.check_output(ssh + [f"docker inspect --format '{{{{index .Config.Labels \"webcompiler.test\"}}}}' {args.recover_container}"], text=True).strip()
        if label != 'exploration': raise ValueError('Not an owned exploration test container')
        result = subprocess.run(ssh + ['docker logs ' + ('--follow ' if args.follow_recovery else '') + args.recover_container], capture_output=True, encoding='utf-8', timeout=900 if args.follow_recovery else 60)
        if result.returncode: raise RuntimeError(result.stderr[-1000:])
        recovered = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        artifact = next((base64.b64decode(row['artifact']) for row in recovered if 'artifact' in row), None)
        if artifact and args.cache_directory:
            binary_path.write_bytes(artifact)
            metadata_path.write_text(json.dumps({'sourceSignature': source_signature, 'sha256': hashlib.sha256(artifact).hexdigest()}))
        report = next((row for row in recovered if 'reports' in row), None)
        if report:
            validate_report(report)
        else:
            print(json.dumps({'cachedArtifact': bool(artifact), 'reportAvailable': False, 'progress': result.stderr[-1500:]}))
        return
    script += 'CACHED_BINARY = ' + repr(base64.b64encode(cached).decode() if cached else None) + '\n'
    script += 'CACHED_SHA = ' + repr(hashlib.sha256(cached).hexdigest() if cached else None) + '\n'
    script += 'ONLY_GATE = ' + repr(args.gate_only) + '\n' + CONTAINER
    command = ['docker', 'create', '-i', '--network', 'none', '--read-only', '--cpus', '1',
               '--memory', '1g', '--memory-swap', '1g', '--pids-limit', '64', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,exec,nosuid,size=256m',
               '--user', '1000:1000', '--env', 'HOME=/tmp', '--label', 'webcompiler.test=exploration',
               '--entrypoint', 'python3', args.image, '-']
    payload_path = None
    remote = '''
import base64, gzip, pathlib, re, subprocess, sys
available = next(int(line.split()[1]) for line in pathlib.Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
if available < 4 * 1024 * 1024: raise RuntimeError('Less than 4 GiB free; isolated test postponed')
container = subprocess.check_output(COMMAND, text=True).strip()
if not re.fullmatch('[a-f0-9]{64}', container): raise RuntimeError('Unexpected container identity')
try:
    result = subprocess.run(['docker', 'start', '-ai', container], input=gzip.decompress(PAYLOAD_BYTES), stdout=sys.stdout.buffer, stderr=sys.stderr.buffer, timeout=1000)
    if result.returncode:
        state = subprocess.check_output(['docker', 'inspect', '--format', '{{json .State}}', container])
        sys.stderr.buffer.write(b'Container exit: ' + state)
    sys.exit(result.returncode)
finally:
    subprocess.run(['docker', 'rm', '-f', container], stdout=subprocess.DEVNULL, timeout=20)
'''.replace('COMMAND', repr(command))
    # Keep remote Python source small. Some SSH endpoints reset long stdin
    # scripts; SFTP is the intended transport for a compiled binary artifact.
    if not cached:
        remote = remote.replace('PAYLOAD_BYTES', 'base64.b64decode(' + repr(base64.b64encode(gzip.compress(script.encode())).decode()) + ')')
        result = subprocess.run(ssh + ['python3 -'], input=remote, encoding='utf-8', capture_output=True, timeout=1050)
    else:
        remote_folder = subprocess.check_output(ssh + ['mktemp -d /tmp/bpp-exploration.XXXXXXXX'], text=True).strip()
        if not re.fullmatch(r'/tmp/bpp-exploration\.[A-Za-z0-9]{8}', remote_folder):
            raise ValueError('Unexpected temporary test directory')
        payload_path = remote_folder + '/payload.gz'
        try:
            with tempfile.TemporaryDirectory(prefix='bpp-exploration-transport-') as transport:
                local_payload = Path(transport) / 'payload.gz'
                local_payload.write_bytes(gzip.compress(script.encode()))
                subprocess.run(['scp', '-q', '-l', '256', '-o', 'IPQoS=none', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=15', '-P', str(args.ssh_port), str(local_payload), f'{args.ssh_host}:{payload_path}'], check=True, timeout=240)
            remote = remote.replace('PAYLOAD_BYTES', 'pathlib.Path(' + repr(payload_path) + ').read_bytes()')
            result = subprocess.run(ssh + ['python3 -'], input=remote, encoding='utf-8', capture_output=True, timeout=1050)
        finally:
            cleanup = 'import pathlib; p=pathlib.Path(' + repr(payload_path) + '); p.unlink(missing_ok=True); p.parent.rmdir()'
            subprocess.run(ssh + ['python3 -'], input=cleanup, encoding='utf-8', capture_output=True, timeout=20, check=True)
    lines = result.stdout.splitlines()
    if lines and lines[0].startswith('{"artifact":'):
        artifact = base64.b64decode(json.loads(lines.pop(0))['artifact'])
        if args.cache_directory:
            binary_path.write_bytes(artifact)
            metadata_path.write_text(json.dumps({'sourceSignature': source_signature, 'sha256': hashlib.sha256(artifact).hexdigest()}))
    if result.returncode:
        raise RuntimeError(f'exit {result.returncode}: {result.stderr[-6000:]}')
    validate_report(json.loads('\n'.join(lines)))


def validate_report(report):
    import sys
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.services.compiler_graphs import build_bpp_pipeline_from_json
    for row in report['reports']:
        source = row.pop('source')
        parsed = build_bpp_pipeline_from_json(json.dumps(row.pop('unified')), source, 'main.bpp')
        ir = build_bpp_pipeline_from_json(json.dumps(row.pop('ir')), source, 'main.bpp', {'ir'})
        assert parsed['ssa']['optimizationSummaries'] and ir['ir']['instructions']
        assert all(block['instructionDetails'] for block in parsed['ssa']['blocks'] if block['instructions'])
        row['backendContract'] = 'passed'
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
