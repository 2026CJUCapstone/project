"""Isolated actual Docker adapter smoke, inside an existing backend image.

Only a fixed Python reference, one compile and two fresh-case containers. No
API, server initialization, migrations, queues or production data. Optional
--stored-data initializes only a disposable SQLite DB under the owned workspace.
Caller must supply a disposable shared directory and exact existing image ID.
The trusted controller alone sees Docker's socket; submitted children do not.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


async def verify(args):
    # Settings are supplied by the caller before importing the app. In-memory
    # SQLite is defensive: this test never opens sessions or initializes tables.
    if os.environ.get('DATABASE_URL')!='sqlite:///:memory:':
        raise RuntimeError('Only in-memory isolated database configuration permitted')
    from app.core.config import settings
    from app.services.compiler import DockerCompilerRunner
    from app.services.judge_policy import content_hash, test_suite_hash
    from app.services.judge_runtime_registry import TOOLCHAINS, launcher_digest
    from app.services.measured_judge import MeasuredSubmission
    from app.services.judging import judge_code

    root=args.workspace.resolve()
    if not root.is_dir() or root.name!='work' or not root.parent.name.startswith('webcompiler-launcher-test.'):
        raise RuntimeError('Exact disposable probe workspace required')
    settings.SANDBOX_WORKDIR_ROOT=str(root/'jobs')
    settings.JUDGE_WORKER_CLASS='isolated-mechanics'
    runtime=subprocess.check_output(['/usr/bin/python3','--version'],text=True,timeout=3).strip()
    stage=dict(cpuMs=1000,wallMs=2000,memoryBytes=128*1024**2,outputBytes=1024,pids=16,tmpBytes=16*1024**2)
    profile=dict(runtimeId='isolated-python',runtimeVersion=runtime,imageDigest=args.image,
        workerClass=settings.JUDGE_WORKER_CLASS,toolchainProfile=TOOLCHAINS['python'],launcherDigest=launcher_digest(),compile=stage.copy(),run=stage.copy())
    registration={k:profile[k] for k in ('runtimeId','runtimeVersion','imageDigest','workerClass','toolchainProfile')}
    registration.update(language='python',launcherDigest=launcher_digest())
    registry=root/'test-registry.json'
    with registry.open('x',encoding='utf-8') as file:
        json.dump(dict(version=1,runtimes=[registration]),file)
    settings.JUDGE_RUNTIME_REGISTRY=str(registry)
    source=("import errno,os,sys\n"
        "assert not os.path.exists('/source')\n"
        "assert not os.path.exists('/work/previous-case')\n"
        "open('/work/previous-case','w').write('new')\n"
        "try: open('/artifact/main.pyc','wb')\n"
        "except OSError as e: assert e.errno in (errno.EROFS,errno.EACCES,errno.EPERM)\n"
        "else: raise RuntimeError('artifact is writable')\n"
        "try: open('/dev/shm/unbudgeted','w')\n"
        "except OSError as e: assert e.errno in (errno.EROFS,errno.EACCES,errno.EPERM,errno.ENOENT)\n"
        "else: raise RuntimeError('unbudgeted shared tmpfs is writable')\n"
        "print(int(sys.stdin.read())*2)\n")
    sample=[dict(input='21\n',expected_output='42')]
    hidden=[dict(input='84\n',expected_output='168')]
    loader=None;stored_engine=None;input_bytes=3
    if args.stored_data:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models.database import User
        from app.services.judge_test_data import put_data
        from app.services.judge_test_manifest import materialize_case
        from app.services.measured_judge import finish_io
        import hashlib
        source=source.replace("print(int(sys.stdin.read())*2)","print(len(sys.stdin.buffer.read()))")
        sample=[dict(input='21\n',expected_output='3')]
        data=b'1000000\n'+b'-1000000 '*999999+b'-1000000\n'
        input_bytes=len(data);expected=str(input_bytes).encode()
        refs=[]
        stored_engine=create_engine('sqlite:///'+str(root/'isolated-test-data.db'),connect_args={'check_same_thread':False})
        Base.metadata.create_all(stored_engine)
        sessions=sessionmaker(bind=stored_engine)
        with sessions() as db:
            db.add(User(id='probe-admin',username='probe-admin',role='admin',hashed_password='not-a-login'))
            db.commit()
            for value in (data,expected):
                digest='sha256:'+hashlib.sha256(value).hexdigest()
                put_data(db,value,digest,'probe-admin');db.commit()
                refs.append(dict(digest=digest,byteCount=len(value),encoding='utf-8'))
        del data,expected,value
        hidden=[dict(kind='stored-v1',inputRef=refs[0],expectedOutputRef=refs[1])]
        async def loader(case):
            def read():
                with sessions() as db: return materialize_case(db,case)
            return await finish_io(read)
    contract=dict(kind='measured-v1',policyId='isolated-unpublished-fixture',revision=1,
        policyHash=content_hash({'scope':'not publication evidence','profile':profile}),language='python',
        testSuiteHash=test_suite_hash(sample,hidden),profile=profile,jobDeadlineMs=11000,
        reservationBytes=stage['memoryBytes'])
    if args.stored_data:
        from app.models.judge_test_manifest import test_data_buffer_bytes
        contract['testDataBufferBytes']=test_data_buffer_bytes(sample,hidden)
        contract['reservationBytes']+=contract['testDataBufferBytes']
    payload=dict(code=source,language='python',sample=sample,hidden=hidden,judge_contract=contract)
    owner={'webcompiler.isolated-measured-pipeline':args.owner}
    reports=[];names=[]
    class Session(MeasuredSubmission):
        async def _phase(self,*params):
            result=await super()._phase(*params)
            assert not list(self.directory.glob('input-*'))
            assert not list(self.directory.glob('empty-*'))
            reports.append(result['resource_usage'])
            return result
    class Runner(DockerCompilerRunner):
        async def _allocate_container(self,create,**options):
            if len(names)>=3 or options['image']!=args.image or options['labels'].get(next(iter(owner)))!=args.owner:
                raise RuntimeError('Isolated phase creation boundary exceeded')
            for path in options['volumes']:
                if root not in Path(path).resolve().parents:
                    raise RuntimeError('Non-test mount rejected')
            names.append(options['name'])
            return await super()._allocate_container(create,**options)
        def measured_submission(self,body):
            from app.services.judge_runtime_registry import RuntimeRegistry
            return Session(self,body,RuntimeRegistry.load(settings.JUDGE_RUNTIME_REGISTRY),settings.JUDGE_WORKER_CLASS)
    runner=Runner(labels=owner)
    client=runner._get_client()
    try:
        result=await asyncio.wait_for(judge_code(runner,payload,load_case=loader),timeout=35)
        assert result['verdict']=='accepted',result
        assert len(names)==3 and len(set(names))==3
        assert [r['phase'] for r in reports]==['compile','run','run']
        assert all(r['treeReaped'] and r['exitCode']==0 and r['failureReason'] is None for r in reports)
        # Metrics may coincidentally contain digits from a hidden answer. Check
        # actual diagnostic fields, not arbitrary substrings of trusted numbers.
        assert '168' not in json.dumps(result['details'])
        from app.services.judge_metrics import public_usage,validate_report
        raw=result['_resource_report']
        validate_report(raw,payload)
        assert raw['compile']==reports[0]
        assert [case['usage'] for case in raw['cases']]==reports[1:]
        summary=public_usage(raw)
        assert summary['run']['cpuMs']==sum(r['cpuUsec'] for r in reports[1:])/1000
        assert summary['run']['peakMemoryBytes']==max(r['peakMemoryBytes'] for r in reports[1:])
        assert 'cases' not in summary and 'testSuiteHash' not in summary
        assert list((root/'jobs').iterdir())==[]
        remaining=client.containers.list(all=True,filters={'label':[f'{k}={v}' for k,v in owner.items()]})
        assert not remaining
        print(json.dumps(dict(scope='actual Python adapter, not full worker/policy acceptance',image=args.image,
            runtime=runtime,launcherDigest=launcher_digest(),phases=reports,verdict=result['verdict'],
            compileCount=1,caseContainerCount=2,freshWorkspaces=True,readOnlyArtifact=True,
            storedData=args.stored_data,caseInputBytes=input_bytes,manifestBytes=len(json.dumps(hidden).encode()),
            phaseInputsReaped=True,remainingContainers=0,remainingJobDirectories=0),indent=2),flush=True)
    finally:
        remaining=client.containers.list(all=True,filters={'label':[f'{k}={v}' for k,v in owner.items()]})
        for container in remaining:
            if any(container.labels.get(k)!=v for k,v in owner.items()):
                raise RuntimeError('Isolated cleanup ownership mismatch')
        for container in remaining: container.remove(force=True)
        # Only this script's exclusive registry file, not a shared allowlist.
        registry.unlink(missing_ok=True)
        if stored_engine is not None: stored_engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--owner',required=True)
    parser.add_argument('--workspace',required=True,type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--stored-data',action='store_true')
    args=parser.parse_args()
    if not args.execute or sys.platform!='linux' or not re.fullmatch('sha256:[a-f0-9]{64}',args.image) or not re.fullmatch('[a-f0-9]{32}',args.owner):
        raise SystemExit('Explicit isolated Linux authorization and exact identities required')
    asyncio.run(verify(args))


if __name__=='__main__': main()
