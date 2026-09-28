"""Host-side bounded controller for verify_measured_pipeline.py; explicit opt-in."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tarfile
import uuid

from verify_measured_launcher import capacity, command


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--image',required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--stored-data',action='store_true',help='One 9MB stored-input case in an isolated SQLite file')
    args=parser.parse_args();root=args.root.resolve()
    if not args.execute or root.parent!=Path('/tmp') or not re.fullmatch(r'webcompiler-launcher-test\.[A-Za-z0-9]+',root.name):
        raise SystemExit('Explicit isolated authorization and owned temporary directory required')
    if not re.fullmatch('sha256:[a-f0-9]{64}',args.image): raise SystemExit('Immutable image required')
    if command('image','inspect','--format={{.Id}}',args.image).decode().strip()!=args.image:
        raise SystemExit('Exact existing image required')
    before=capacity()
    source=root/'candidate';source.mkdir(mode=0o755)
    with tarfile.open(root/'measured-app-source.tar.gz',mode='r:gz') as archive:
        members=archive.getmembers()
        if len(members)>250 or sum(m.size for m in members)>8*1024**2: raise RuntimeError('Source archive cap')
        for member in members:
            name=Path(member.name)
            if name.is_absolute() or '..' in name.parts or name.parts[0]!='app' or not (member.isfile() or member.isdir()):
                raise RuntimeError('Invalid source archive')
        archive.extractall(source,filter='data')
    root.chmod(0o755)
    for path in source.rglob('*'): path.chmod(0o755 if path.is_dir() else 0o444)
    work=root/'work';work.mkdir(mode=0o777);work.chmod(0o777)
    owner=uuid.uuid4().hex;cid=None
    try:
        cid=command('create','--pull=never','--name','webcompiler-pipeline-controller-'+owner,
            '--label','webcompiler.isolated-pipeline-controller='+owner,
            '--network=none','--read-only','--user=0:0','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--memory='+('384m' if args.stored_data else '256m'),
            '--memory-swap='+('384m' if args.stored_data else '256m'),'--cpus=0.5','--pids-limit=48',
            '--no-healthcheck','--log-driver=none','--workdir=/candidate',
            '--mount',f'type=bind,src={source},dst=/candidate,readonly',
            '--mount',f'type=bind,src={root / "verify_measured_pipeline.py"},dst=/probe.py,readonly',
            '--mount',f'type=bind,src={work},dst={work}',
            '--mount','type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock',
            '-e','PYTHONPATH=/candidate','-e','PYTHONDONTWRITEBYTECODE=1',
            '-e','ENVIRONMENT=development','-e','SECRET_KEY=isolated-mechanics-not-production-secret-2026',
            '-e','DATABASE_URL=sqlite:///:memory:','-e','AUTO_INITIALIZE_DB=false',
            '-e','EMBEDDED_EXECUTION_WORKER=false','-e','REDIS_URL=',
            '--entrypoint=/opt/venv/bin/python',args.image,'/probe.py',
            '--image',args.image,'--owner',owner,'--workspace',str(work),'--execute',
            *(['--stored-data'] if args.stored_data else [])).decode().strip()
        if not re.fullmatch('[a-f0-9]{64}',cid): raise RuntimeError('Controller identity invalid')
        completed=subprocess.run(['docker','start','-a',cid],capture_output=True,timeout=50)
        if len(completed.stdout)+len(completed.stderr)>65536: raise RuntimeError('Oversized controller diagnostics')
        print(completed.stdout.decode('utf-8',errors='replace'))
        if completed.returncode:
            print(completed.stderr.decode('utf-8',errors='replace'))
            raise RuntimeError('Isolated application adapter failed')
        print(json.dumps(dict(before=before,after=capacity())))
    finally:
        # Validate exact owner labels on every target. Never touch other jobs.
        for label in ('webcompiler.isolated-measured-pipeline','webcompiler.isolated-pipeline-controller'):
            ids=command('ps','-aq','--filter',f'label={label}={owner}').decode().split()
            for identity in ids:
                labels=json.loads(command('inspect','--format={{json .Config.Labels}}',identity))
                if labels.get(label)!=owner: raise RuntimeError('Cleanup ownership mismatch')
            for identity in ids: command('rm','-f',identity)


if __name__=='__main__': main()
