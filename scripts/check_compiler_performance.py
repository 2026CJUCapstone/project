"""Opt-in isolated B++ latency/equivalence probe. Never promotes an image.

Uses an explicit existing image and pinned local compiler checkout. The source
archive is fetched on the host and every source file is verified against the
local git tree before one network-disabled, resource-bounded container runs.
"""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REF = "9859a2dc783c9346be2ab9447e1569218bcc5093"

PROBE = r'''
import hashlib, io, json, pathlib, subprocess, tarfile, time
root = pathlib.Path('/tmp/performance')
root.mkdir()
with tarfile.open('/input/source.tar.gz') as archive:
    members = {m.name.split('/', 1)[1]: m for m in archive.getmembers() if '/' in m.name and m.isfile()}
    for name, digest in MANIFEST.items():
        data = archive.extractfile(members[name]).read()
        assert hashlib.sha256(data).hexdigest() == digest, name
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
patch = {'__name__': 'library'}
exec(PATCHER, patch)
memory_patch = {'__name__': 'library'}
exec(PERFORMANCE_PATCHER, memory_patch)
memory_path = root / 'src/std/mem.bpp'
memory_path.write_text(memory_patch['patch_memory'](memory_path.read_text()))
io_path = root / 'src/std/io.bpp'
io_path.write_text(memory_patch['patch_capture'](io_path.read_text()))
emitter_path = root / 'src/emitter/emitter.bpp'
emitter_path.write_text(memory_patch['patch_empty_string'](emitter_path.read_text()))
for name, function in [('ssa/dump.bpp', 'patch_source'), ('main.bpp', 'patch_main'), ('codegen.bpp', 'patch_codegen')]:
    path = root / 'src' / name
    args = [path.read_text()]
    if function == 'patch_source': args.append(EXTENSION)
    path.write_text(patch[function](*args))
codegen_path = root / 'src/codegen.bpp'
codegen_path.write_text(memory_patch['patch_graph_scope'](codegen_path.read_text(), GRAPH_SCOPE))
main_path = root / 'src/main.bpp'
main_path.write_text(memory_patch['patch_native_json'](main_path.read_text()))
(root / 'bpp.toml').write_text('version=v13\nstd_root=src\nmodule_root=src\nnasm_path=/usr/bin/nasm\nld_path=/usr/bin/ld\n')
baseline = '/usr/local/libexec/bpp/v13_stage1'
candidate = str(root / 'candidate')
t = time.monotonic()
with (root / 'candidate.asm').open('w') as output:
    subprocess.run([baseline, '-asm', str(root / 'src/main.bpp')], cwd=root, stdout=output, check=True, timeout=240)
subprocess.run(['nasm', '-felf64', '-O1', str(root / 'candidate.asm'), '-o', str(root / 'candidate.o')], check=True, timeout=60)
subprocess.run(['ld', str(root / 'candidate.o'), '-o', candidate], check=True, timeout=15)
print(json.dumps({'buildSeconds': round(time.monotonic()-t, 3)}), flush=True)
if pathlib.Path('/output').is_dir():
    import shutil
    shutil.copy2(candidate, '/output/candidate')
    shutil.copytree(root/'src', '/output/src', dirs_exist_ok=True)
    print(json.dumps({'exportedCandidateSha256':hashlib.sha256(pathlib.Path(candidate).read_bytes()).hexdigest()}),flush=True)
gate = {'__name__': 'library'}
exec(GATE, gate)
latency = {'__name__': 'library'}
exec(LATENCY_CHECKS, latency)
reports = []
path = root / 'main.bpp'
for ending in ('lf', 'crlf'):
    source = gate['SOURCE'].replace('graph gate', '그래프 확인')
    if ending == 'crlf': source = source.replace('\n', '\r\n')
    path.write_bytes(source.encode())
    for level in ('O0', 'O1'):
        row = {'ending': ending, 'level': level, 'source': source, 'timings': []}
        for repeat in range(3):
            times = {}
            # Alternate order to reduce warm-cache bias. Native compilation
            # stays in both paths; the removed IR pass is timed separately.
            outputs = {}
            for name in (('baseline', 'candidate') if repeat % 2 == 0 else ('candidate', 'baseline')):
                compiler = baseline if name == 'baseline' else candidate
                t = time.monotonic()
                result = subprocess.run([compiler, '-'+level, '--emit-json', '--views', 'ast,ir,ssa,asm', '--source-map-user-only', '--ast-no-std', str(path)], cwd=root, capture_output=True, check=True, timeout=40)
                times[name+'Json'] = time.monotonic()-t
                assert len(result.stdout) <= 1048576
                outputs[name] = json.loads(result.stdout)
                gate['validate'](outputs[name], optimized=level == 'O1')
            assert latency['canonical_graphs'](outputs['baseline']) == latency['canonical_graphs'](outputs['candidate']), 'Output semantics changed'
            t = time.monotonic()
            dedicated = subprocess.run([baseline, '-'+level, '-dump-ir-json', '--source-map-user-only', str(path)], cwd=root, capture_output=True, check=True, timeout=40)
            times['dedicatedIr'] = time.monotonic()-t
            import copy
            dedicated_payload = copy.deepcopy(outputs['candidate'])
            dedicated_payload['views']['ir'] = json.loads(dedicated.stdout)
            assert latency['canonical_graphs'](outputs['candidate']) == latency['canonical_graphs'](dedicated_payload)
            t = time.monotonic()
            with (root / 'program.asm').open('wb') as out:
                subprocess.run([baseline, '-'+level, '-asm', str(path)], cwd=root, stdout=out, check=True, timeout=40)
            subprocess.run(['nasm','-felf64','-O1',str(root/'program.asm'),'-o',str(root/'program.o')], check=True, timeout=15)
            subprocess.run(['ld',str(root/'program.o'),'-o',str(root/'program')], check=True, timeout=10)
            times['native'] = time.monotonic()-t
            row['timings'].append(times)
        row['payload'] = outputs['candidate']
        reports.append(row)
        print(json.dumps({'case': ending+'/'+level, 'timings': row['timings']}), flush=True)
for source in ('func main() -> u64 { return missing_value; }', 'func broken() -> u64 { return missing_value; }\nfunc main() -> u64 { return 0; }'):
    path.write_text(source)
    for level in ('O0','O1'):
        r = subprocess.run([candidate, '-'+level, '--emit-json', '--views', 'ast,ir,ssa,asm', str(path)], cwd=root, capture_output=True, timeout=30)
        assert r.returncode != 0 and not r.stdout, 'Semantic error accepted'
native = {'__name__':'library'}
exec(NATIVE, native)
for name, (source, expected) in native['CASES'].items():
    for level in ('O0','O1'):
        result = native['check_case'](root, name, source, expected, compiler=candidate, optimization=level)
        assert result['passed'], result
print(json.dumps({'reports': reports, 'semanticRejectionCases':4, 'nativeCases':len(native['CASES'])*2}), flush=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh-host', required=True)
    parser.add_argument('--ssh-port', type=int, default=10022)
    parser.add_argument('--image', required=True)
    parser.add_argument('--compiler-checkout', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--export-candidate', action='store_true', help='Retain this public test binary/source in the isolated evidence directory, never install it')
    args = parser.parse_args()
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', args.image):
        raise ValueError('Use an immutable image ID')
    git = ['git', '-C', str(args.compiler_checkout)]
    names = subprocess.check_output(git + ['ls-tree', '-r', '--name-only', REF, 'src']).decode().splitlines()
    manifest = {name: hashlib.sha256(subprocess.check_output(git + ['show', REF+':'+name])).hexdigest() for name in names}
    script = 'MANIFEST='+repr(manifest)+'\n'
    for key, path in [('PATCHER','runtime/compiler-patches/apply_exploration.py'), ('PERFORMANCE_PATCHER','runtime/compiler-patches/apply_performance.py'), ('GRAPH_SCOPE','runtime/compiler-patches/graph_scope.bpp'), ('EXTENSION','runtime/compiler-patches/exploration.bpp'), ('GATE','runtime/sandbox/verify_bpp_exploration.py'), ('NATIVE','runtime/sandbox/verify_bpp_runtime.py'), ('LATENCY_CHECKS','runtime/sandbox/verify_bpp_latency.py')]:
        script += key+'='+repr((ROOT/path).read_text(encoding='utf-8'))+'\n'
    script += PROBE
    payload = gzip.compress(script.encode())
    ssh = ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','ServerAliveInterval=15','-p',str(args.ssh_port),args.ssh_host]
    folder = subprocess.check_output(ssh + ['mktemp -d /tmp/bpp-performance.XXXXXXXX'], text=True).strip()
    if not re.fullmatch(r'/tmp/bpp-performance\.[A-Za-z0-9]{8}', folder):
        raise ValueError('Unexpected temporary directory')
    print('Isolated evidence directory: '+folder, flush=True)
    for offset in range(0,len(payload),4096):
        chunk = base64.b64encode(payload[offset:offset+4096]).decode()
        transfer = f"import pathlib,base64\np=pathlib.Path({folder+'/probe.gz'!r})\nassert (p.stat().st_size if p.exists() else 0)=={offset}\nwith p.open('ab') as f:f.write(base64.b64decode({chunk!r}))\n"
        subprocess.run(ssh+['python3 -'], input=transfer, text=True, check=True, timeout=20)
    command = ['docker','create','-i','--network','none','--read-only','--cpus','1','--memory','1g','--memory-swap','1g','--pids-limit','64','--cap-drop','ALL','--security-opt','no-new-privileges','--user','1000:1000','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=256m,mode=1777','--mount',f'type=bind,src={folder},dst=/input,readonly','--label','webcompiler.test=performance','--entrypoint','python3',args.image,'-']
    if args.export_candidate:
        command[2:2] = ['--mount', f'type=bind,src={folder}/output,dst=/output']
    remote = f'''
import gzip,hashlib,pathlib,re,subprocess,urllib.request
p=pathlib.Path({folder!r})
assert hashlib.sha256((p/'probe.gz').read_bytes()).hexdigest()=={hashlib.sha256(payload).hexdigest()!r}
available=next(int(x.split()[1]) for x in pathlib.Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
assert available>=4*1024*1024, 'Requires 4 GiB available memory'
urllib.request.urlretrieve('https://codeload.github.com/Creeper0809/Bpp/tar.gz/{REF}',p/'source.tar.gz')
p.chmod(0o755)
if {args.export_candidate!r}:
 (p/'output').mkdir()
 (p/'output').chmod(0o777)
container=subprocess.check_output({command!r},text=True).strip()
assert re.fullmatch('[a-f0-9]{{64}}',container)
try:
 with (p/'result.log').open('wb') as out, (p/'error.log').open('wb') as err:
  r=subprocess.run(['docker','start','-ai',container],input=gzip.decompress((p/'probe.gz').read_bytes()),stdout=out,stderr=err,timeout=900)
finally:
 subprocess.run(['docker','rm','-f',container],stdout=subprocess.DEVNULL,check=True,timeout=20)
print((p/'result.log').read_text())
if r.returncode: print((p/'error.log').read_text()[-5000:])
raise SystemExit(r.returncode)
'''
    result = subprocess.run(ssh+['python3 -'], input=remote, text=True, encoding='utf-8', capture_output=True, timeout=960)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.stdout, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(result.stdout[-6000:]+result.stderr[-2000:])
    report = next(json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"reports":'))
    import sys
    sys.path.insert(0,str(ROOT/'backend'))
    from app.services.compiler_graphs import build_bpp_pipeline_from_json
    for row in report['reports']:
        parsed = build_bpp_pipeline_from_json(json.dumps(row['payload']),row['source'],'main.bpp')
        assert all(key in parsed for key in ('ast','ir','ssa','asm'))
        assert any(item.get('sourceRanges') for item in parsed['ir']['instructions'])
    print(json.dumps({'passed':True,'cases':len(report['reports']),'report':str(args.output),'remoteEvidence':folder}))


if __name__ == '__main__':
    main()
