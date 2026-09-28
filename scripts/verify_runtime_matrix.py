"""Actual sequential adapter checks, not approved contest performance evidence."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import stat
import sys

SOURCES = {
    'c': '#include <stdio.h>\nint main(void){puts("42");return 0;}\n',
    'cpp': '#include <iostream>\nint main(){std::cout<<42<<"\\n";}\n',
    'python': 'print(42)\n',
    'java': 'public class Main { public static void main(String[] a) { System.out.println(42); } }',
    'javascript': 'console.log(42);\n',
    'bpp': 'import std.io;\nfunc main() -> u64 { print_i64(42); print_nl(); return 0; }\n',
}


def cleanup_phase_containers(client, names, owner):
    """Best-effort owned cleanup; return bounded secondary error codes."""
    errors=[]
    try:
        remaining=client.containers.list(
            all=True,filters={'label':f'webcompiler.isolated-runtime-matrix={owner}'})
    except Exception as exc:
        errors.append('list:'+type(exc).__name__)
        remaining=[]
    for container in remaining:
        if container.name not in names:
            continue
        try:
            if container.labels.get('webcompiler.isolated-runtime-matrix') != owner:
                raise RuntimeError('Cleanup identity mismatch')
            container.remove(force=True)
        except Exception as exc:
            errors.append('remove:'+type(exc).__name__)
    try:
        client.close()
    except Exception as exc:
        errors.append('close:'+type(exc).__name__)
    return errors


def preserve_primary_cleanup_error(primary, errors, scope):
    if not errors:
        return
    message=f'{scope} cleanup incomplete: '+','.join(errors)
    if primary is not None:
        primary.add_note(message)
        return
    raise RuntimeError(message)


def verify_case_evidence(kind, expected, result, run_limit, phase_names):
    """Require witnesses, not just a broad verdict or a valid report prefix."""
    report = result['_resource_report']
    phases = [report['compile']]+[case['usage'] for case in report['cases']]
    expected_count = 3 if kind=='accepted' else 1 if kind=='compile_error' else 2
    if (result['verdict'] != expected or len(phases) != expected_count
            or len(phase_names) != expected_count or len(set(phase_names)) != expected_count
            or not all(p['treeReaped'] is True for p in phases)):
        raise ValueError('Verdict, exact phase count or tree cleanup mismatch')
    compiled = phases[0]
    if kind=='compile_error':
        if compiled['exitCode']==0 or compiled['failureReason'] is not None:
            raise ValueError('Expected syntax error, not compile resource failure')
        return phases
    if compiled['exitCode']!=0 or compiled['failureReason'] is not None:
        raise ValueError('Expected successful compilation')
    run = phases[-1]
    if any(case['verdict'] != expected for case in report['cases']):
        raise ValueError('Case verdict does not match expected outcome')
    if kind in ('accepted','wrong_answer'):
        if any(p['exitCode'] != 0 or p['failureReason'] is not None or p['oomKills'] != 0 for p in phases[1:]):
            raise ValueError('Output comparison requires clean execution')
    elif kind=='cpu':
        if (run['failureReason']!='time_limit_exceeded' or run['cpuUsec']<run_limit['cpuMs']*1000
                or run['wallNs']>=run_limit['wallMs']*1000000 or run['oomKills']):
            raise ValueError('CPU-only limit witness missing')
    elif kind=='wall':
        if (run['failureReason']!='time_limit_exceeded' or run['wallNs']<run_limit['wallMs']*1000000
                or run['cpuUsec']>=run_limit['cpuMs']*1000 or run['oomKills']):
            raise ValueError('Wall-only limit witness missing')
    elif kind=='oom':
        if run['failureReason']!='memory_limit_exceeded' or run['oomKills']<1:
            raise ValueError('Kernel OOM kill witness missing')
    elif kind=='output':
        if run['failureReason']!='output_limit_exceeded' or run['outputBytes']!=run_limit['outputBytes'] or run['oomKills']:
            raise ValueError('Output limit witness missing')
    elif kind=='pids':
        if (run['failureReason']!='process_limit_exceeded'
                or run.get('pidLimitHits',0)<1 or run['oomKills']):
            raise ValueError('PID limit witness missing')
    elif kind=='exit137':
        if run['exitCode']!=137 or run['failureReason'] is not None or run['oomKills']:
            raise ValueError('Voluntary exit 137 witness missing')
    else:
        raise ValueError('Unknown matrix case')
    return phases


def verify_child_options(options, root, image, owner):
    """Reject isolation regressions BEFORE sending a create request to Docker."""
    from app.models.judge_policy import StageLimits
    from app.services.measured_judge import phase_tmpfs
    from app.services.judge_runtime_registry import compile_argv, run_argv, LAUNCHER_PATH
    spec = json.loads(options['environment']['JUDGE_PHASE_SPEC'])
    limits = StageLimits.model_validate(spec['limits'])
    if spec['phase'] not in ('compile','run') or spec['version']!=2 or spec['stdin']!='/input/stdin':
        raise RuntimeError('Child phase specification mismatch')
    argv = compile_argv if spec['phase']=='compile' else run_argv
    language = next((lang for lang in SOURCES if argv(lang)==spec['argv']),None)
    if language is None: raise RuntimeError('Unrecognized child command')
    required = dict(image=image,network_disabled=True,read_only=True,init=False,
        entrypoint=['/usr/bin/python3','-I','-c'],command=[LAUNCHER_PATH.read_text(encoding='utf-8')],detach=True,
        cgroupns='private',ipc_mode='none',healthcheck={'test':['NONE']},user='0:0',
        mem_limit=limits.memory_bytes,memswap_limit=limits.memory_bytes,nano_cpus=1000000000,
        pids_limit=limits.pids,cap_drop=['ALL'],cap_add=['KILL','SETUID','SETGID'],
        security_opt=['no-new-privileges'],log_config={'Type':'none','Config':{}},
        ulimits=[{'Name':'nofile','Soft':64,'Hard':64}],
        tmpfs=phase_tmpfs(language,spec['phase'],limits))
    allowed_keys = set(required) | {'name', 'labels', 'volumes', 'environment'}
    if set(options) != allowed_keys:
        raise RuntimeError('Unreviewed child Docker option')
    if any(options.get(key)!=value for key,value in required.items()):
        raise RuntimeError('Child isolation contract mismatch')
    name_match = re.fullmatch(r'compiler-measured-([a-f0-9]{32})', options['name'])
    expected_labels = {
        'webcompiler.isolated-runtime-matrix': owner,
        'webcompiler.phase': name_match.group(1) if name_match else '',
    }
    if (not name_match or options['labels'] != expected_labels
            or set(options['environment']) != {'JUDGE_PHASE_SPEC'}
            or limits.memory_bytes>512*1024**2 or limits.pids>64 or limits.tmp_bytes>64*1024**2):
        raise RuntimeError('Child budget or ownership mismatch')
    mounts=options['volumes']
    expected={'/input','/source' if spec['phase']=='compile' else '/artifact'}
    if not limits.tmp_bytes: expected.add('/work')
    if {mount['bind'] for mount in mounts.values()}!=expected or len(mounts)!=len(expected):
        raise RuntimeError('Child mount targets mismatch')
    for path,mount in mounts.items():
        if root not in Path(path).resolve().parents or mount['mode']!='ro':
            raise RuntimeError('Non-test or writable host mount')


def verify_complete_matrix(results, language):
    expected={(lang,kind) for lang in SOURCES if language=='all' or lang==language
              for kind in ('accepted','wrong_answer','compile_error')}
    if language=='all': expected.update(('python',kind) for kind in ('cpu','wall','oom','output','pids','exit137'))
    if (len(results)!=len(expected) or {(r['language'],r['case']) for r in results}!=expected
            or not all(r['passed'] for r in results)):
        raise RuntimeError('Incomplete or failed runtime matrix')


def require_private_workspace(workspace, *, metadata=None):
    path=Path(workspace)
    try:
        current=metadata or path.lstat()
        root=path.resolve(strict=True)
    except (OSError,RuntimeError):
        raise RuntimeError('Private workspace is missing') from None
    jobs=root/'jobs'
    if (not stat.S_ISDIR(current.st_mode) or stat.S_ISLNK(current.st_mode)
            or stat.S_IMODE(current.st_mode)&0o077
            or jobs.exists() or jobs.is_symlink()):
        raise RuntimeError('Private empty workspace required')
    return root


def require_disposable_workspace(workspace, *, expected_parent=Path('/tmp'), metadata=None):
    """Apply the same empty/private and exact path gate to every matrix suite."""
    root=require_private_workspace(workspace,metadata=metadata)
    if (root.name!='work'
            or not re.fullmatch(r'webcompiler-launcher-test\.[A-Za-z0-9]+',root.parent.name)
            or root.parent.parent!=expected_parent):
        raise RuntimeError('Exact disposable workspace required')
    return root


async def verify(args):
    if os.environ.get('DATABASE_URL') != 'sqlite:///:memory:': raise RuntimeError('Isolated DB configuration required')
    root = require_disposable_workspace(args.workspace)
    from app.core.config import settings
    from app.services.compiler import DockerCompilerRunner
    from app.services.judge_policy import content_hash, test_suite_hash
    from app.services.judge_runtime_registry import TOOLCHAINS, launcher_digest, RuntimeRegistry
    from app.services.measured_judge import MeasuredSubmission
    from app.services.judging import judge_code
    from app.services.judge_metrics import validate_report
    versions = json.loads(Path('/versions.json').read_text())
    settings.SANDBOX_WORKDIR_ROOT = str(root/'jobs')
    settings.JUDGE_WORKER_CLASS = 'isolated-runtime-matrix'
    registry = root/'matrix-registry.json'
    registrations = [dict(language=lang, runtimeId='isolated-'+lang, runtimeVersion=versions[lang]['version'],
        imageDigest=args.image, workerClass=settings.JUDGE_WORKER_CLASS, toolchainProfile=TOOLCHAINS[lang],
        launcherDigest=launcher_digest()) for lang in SOURCES]
    with registry.open('x',encoding='utf-8') as file: json.dump(dict(version=1,runtimes=registrations),file)
    settings.JUDGE_RUNTIME_REGISTRY = str(registry)
    owner = {'webcompiler.isolated-runtime-matrix':args.owner}
    names = []; results = []
    compile_diagnostics = []
    class Session(MeasuredSubmission):
        async def _execute(self, **options):
            result = await super()._execute(**options)
            if result['exit_code'] != 0:
                compile_diagnostics.append(dict(stdout=result['stdout'][:4096], stderr=result['stderr'][:4096]))
            return result
    class Runner(DockerCompilerRunner):
        async def _allocate_container(self, create, **options):
            if len(names) >= 80 or options['image'] != args.image or options['labels'].get(next(iter(owner))) != args.owner:
                raise RuntimeError('Matrix phase creation boundary exceeded')
            verify_child_options(options,root,args.image,args.owner)
            names.append(options['name'])
            return await super()._allocate_container(create, **options)
        def measured_submission(self, body):
            return Session(self,body,RuntimeRegistry.load(settings.JUDGE_RUNTIME_REGISTRY),settings.JUDGE_WORKER_CLASS)
    runner = Runner(labels=owner)
    client = runner._get_client()
    async def check(lang, kind, source, expected, output='42', overrides=None):
        compile_limit = dict(cpuMs=8000,wallMs=10000,memoryBytes=512*1024**2,outputBytes=4096,pids=64,tmpBytes=64*1024**2)
        run_limit = dict(cpuMs=1000,wallMs=2000,memoryBytes=(512 if lang=='java' else 128)*1024**2,outputBytes=4096,pids=64,tmpBytes=16*1024**2)
        run_limit.update(overrides or {})
        profile = {k:v for k,v in next(r for r in registrations if r['language']==lang).items() if k!='language'}
        profile.update(compile=compile_limit,run=run_limit)
        sample = [dict(input='first\n',expected_output=output)]
        hidden = [dict(input='second\n',expected_output=output)]
        receipt = dict(kind='measured-v1',policyId='isolated-mechanics-not-publication',revision=1,
            policyHash=content_hash(profile),language=lang,testSuiteHash=test_suite_hash(sample,hidden),
            profile=profile,jobDeadlineMs=compile_limit['wallMs']+2*run_limit['wallMs']+5000,
            reservationBytes=max(compile_limit['memoryBytes'],run_limit['memoryBytes']))
        payload = dict(code=source,language=lang,sample=sample,hidden=hidden,judge_contract=receipt)
        started = len(names)
        compile_diagnostics.clear()
        try:
            result = await asyncio.wait_for(judge_code(runner,payload),timeout=30)
            report = result['_resource_report']; validate_report(report,payload)
            phases = verify_case_evidence(kind,expected,result,run_limit,names[started:])
            row = dict(language=lang,case=kind,expected=expected,verdict=result['verdict'],passed=True,
                phaseCount=len(phases),compileCount=1,phases=phases)
        except Exception as exc:
            row = dict(language=lang,case=kind,expected=expected,passed=False,error=str(exc)[:500],diagnostics=compile_diagnostics)
        remaining = client.containers.list(all=True, filters={'label':f'webcompiler.isolated-runtime-matrix={args.owner}'})
        # The controller carries the same owner but has no submitted-code label.
        leftovers = [c for c in remaining if c.name in names]
        if leftovers or list((root/'jobs').iterdir()): raise RuntimeError('Matrix cleanup incomplete; no next case')
        results.append(row); print(json.dumps(row),flush=True)
    try:
        for lang, source in SOURCES.items():
            if args.language != 'all' and lang != args.language: continue
            await check(lang,'accepted',source,'accepted')
            await check(lang,'wrong_answer',source,'wrong_answer',output='43')
            await check(lang,'compile_error','!! invalid syntax @@','compile_error')
        for kind, source, expected, limits in [
            ('cpu','while True: pass','time_limit_exceeded',dict(cpuMs=100)),
            ('wall','import time; time.sleep(5)','time_limit_exceeded',dict(wallMs=150)),
            ('oom','x=bytearray(384*1024**2)','memory_limit_exceeded',{}),
            ('output',"print('x'*65536)",'output_limit_exceeded',dict(outputBytes=1024)),
            ('pids','import os, time\nwhile True:\n p=os.fork()\n if p==0: time.sleep(5); os._exit(0)',
                'process_limit_exceeded',dict(pids=8)),
            ('exit137','import sys; sys.exit(137)','runtime_error',{}),
        ]:
            if args.language != 'all': break
            await check('python',kind,source,expected,overrides=limits)
        print(json.dumps(dict(scope='six-runtime adapter mechanics only; no DB-worker/benchmark acceptance',
            image=args.image,launcherDigest=launcher_digest(),count=len(results),passed=sum(r['passed'] for r in results),
            distinctPhaseContainers=len(set(names)),remainingSubmittedContainers=0,remainingJobDirectories=0)),flush=True)
        verify_complete_matrix(results,args.language)
    finally:
        primary=sys.exc_info()[1]
        errors=cleanup_phase_containers(client,names,args.owner)
        try:
            registry.unlink(missing_ok=True)
        except Exception as exc:
            errors.append('registry:'+type(exc).__name__)
        preserve_primary_cleanup_error(primary,errors,'runtime-matrix')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True); parser.add_argument('--owner',required=True)
    parser.add_argument('--workspace',required=True,type=Path); parser.add_argument('--execute',action='store_true')
    parser.add_argument('--language',choices=['all','bpp'],default='all')
    args=parser.parse_args()
    if not args.execute or sys.platform!='linux' or not re.fullmatch('sha256:[a-f0-9]{64}',args.image) or not re.fullmatch('[a-f0-9]{32}',args.owner):
        raise SystemExit('Explicit isolated Linux authorization and identities required')
    asyncio.run(verify(args))
