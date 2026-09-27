"""Explicit fixed compiler-source experiment using one existing image only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid
from verify_measured_launcher import capacity,command

IMAGE='sha256:7a3aa3717f2c62f60ff52f680335ebee414151136d6f836382b1b543a43c5db1'


def probe_budget(mode):
    # A single import needed 61.7 CPU seconds; 100s did not bound full frontend
    # cost. This separate stage0 budget is not a contestant time/memory policy.
    if mode=='stage0': return dict(memory='1g',timeout=760,minimumAvailable=4*1024**3)
    if mode=='fixedpoint': return dict(memory='1g',timeout=1500,minimumAvailable=4*1024**3)
    if mode in ('selfhost','frontend','frontend-reduction','regressions'):
        return dict(memory='512m',timeout=240,minimumAvailable=2*1024**3)
    raise ValueError('Unknown bounded probe mode')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--mode',choices=('selfhost','frontend','frontend-reduction','stage0','regressions','fixedpoint'),default='selfhost')
    args=parser.parse_args();root=args.root.resolve()
    if not args.execute or args.root!=root or root.parent!=Path('/tmp') or not re.fullmatch(r'webcompiler-launcher-test\.[A-Za-z0-9]+',root.name):
        raise SystemExit('Exact disposable root and explicit opt-in required')
    before=capacity();token=uuid.uuid4().hex
    budget=probe_budget(args.mode)
    if before['availableMemoryBytes']<budget['minimumAvailable']:
        raise RuntimeError('Candidate build memory safety floor not met')
    if command('image','inspect','--format={{.Id}}',IMAGE).decode().strip()!=IMAGE:
        raise RuntimeError('Exact existing image required')
    root.chmod(0o755)
    extras=('stage0','verify_bpp_runtime.py','G.bpp','J.bpp') if args.mode=='regressions' else ('stage0',) if args.mode=='fixedpoint' else ()
    for name in ('compiler.tar.gz','probe_bpp_candidate.py',*extras):
        path=root/name
        if path.is_symlink() or not path.is_file(): raise RuntimeError('Plain probe input required')
        path.chmod(0o555 if name=='stage0' else 0o444)
    extra_mounts=[]
    for name in extras:
        extra_mounts.extend(['--mount',f'type=bind,src={root/name},dst=/input/{name},readonly'])
    output=root/'output';output.mkdir(mode=0o777);output.chmod(0o777)
    cid=None
    try:
        cid=command('create','--pull=never','--name','webcompiler-native-candidate-'+token,
            '--label','webcompiler.isolated-native-candidate='+token,'--network=none','--read-only',
            '--user=65534:65534','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--memory='+budget['memory'],'--memory-swap='+budget['memory'],'--cpus=1','--pids-limit=32',
            '--ulimit=nofile=64:64','--log-driver=none','--no-healthcheck',
            '--tmpfs=/work:rw,exec,nosuid,nodev,size=128m,mode=1777',
            '--tmpfs=/tmp:rw,exec,nosuid,nodev,size=16m,mode=1777',
            '--mount',f'type=bind,src={root/"compiler.tar.gz"},dst=/input/compiler.tar.gz,readonly',
            '--mount',f'type=bind,src={root/"probe_bpp_candidate.py"},dst=/probe.py,readonly',
            '--mount',f'type=bind,src={output},dst=/output',
            *extra_mounts,
            '--entrypoint=/usr/bin/python3',IMAGE,'-I','/probe.py','--mode',args.mode).decode().strip()
        if not re.fullmatch('[a-f0-9]{64}',cid): raise RuntimeError('Container identity invalid')
        report=dict(scope='isolated native candidate build, not a deployed or approved runtime',
            mode=args.mode,image=IMAGE,before=before,budget=budget,owner=token,containerId=cid,
            scriptSha256=hashlib.sha256((root/'probe_bpp_candidate.py').read_bytes()).hexdigest())
        try:
            result=subprocess.run(['docker','start','-a',cid],capture_output=True,timeout=budget['timeout'])
            report.update(exitCode=result.returncode,stdout=result.stdout.decode(errors='replace'),
                          stderr=result.stderr.decode(errors='replace'),timedOut=False)
        except subprocess.TimeoutExpired as exc:
            command('stop','--time=1',cid,timeout=10)
            report.update(exitCode=124,timedOut=True,stdout=(exc.stdout or b'').decode(errors='replace'))
        state=json.loads(command('inspect','--format={{json .State}}',cid))
        report['containerState']={key:state.get(key) for key in ('Status','Running','OOMKilled','ExitCode','Error')}
        report['after']=capacity()
        with (root/'candidate-report.json').open('x',encoding='utf-8') as file: json.dump(report,file,indent=2)
        print(json.dumps(report),flush=True)
        if report['exitCode']: raise RuntimeError('Candidate build failed; no promotion')
    finally:
        if cid:
            labels=json.loads(command('inspect','--format={{json .Config.Labels}}',cid))
            if labels.get('webcompiler.isolated-native-candidate')!=token: raise RuntimeError('Cleanup ownership mismatch')
            command('rm','-f',cid)


if __name__=='__main__': main()
