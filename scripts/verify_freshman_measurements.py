"""One bounded A--J reference pass for one runtime; never approves a policy.

The inputs are deterministic maximum/boundary descriptors, NOT a final reviewed
contest suite. Uses the real adapter directly, without DB/queue/API integration.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone

from verify_runtime_matrix import (cleanup_phase_containers,preserve_primary_cleanup_error,
                                   require_disposable_workspace,verify_child_options)

LANGUAGES=('c','cpp','python','java','javascript','bpp')
LETTERS=tuple('ABCDEFGHIJ')
DRAFT_CASE_COUNTS=dict(zip(LETTERS,(5,12,7,5,7,6,7,7,11,12)))
DRAFT_SAMPLE_COUNTS=dict(zip(LETTERS,(2,3,2,2,3,2,2,2,4,4)))
DRAFT_B_COVERAGE=frozenset({
    'b-exhaustive-triple-1-6-1','b-exhaustive-triple-6-1-1',
    'b-exhaustive-triple-1-2-3','b-exhaustive-triple-3-2-1',
    'b-exhaustive-triple-2-3-1','b-exhaustive-triple-1-2-6',
})
FROZEN_DRAFT_HASH='sha256:e5213ca9d1aaf3691c91db22aa021870b532b653c015c58c4bf90fff8a8539fc'
DRAFT_DIAGNOSTIC_RUN_WALL_MS=8000


def bpp_diagnostic_sources(base):
    """Fixed reductions, not replacement reference solutions or acceptance data."""
    original=reference_path(base,'bpp','G').read_text(encoding='utf-8')
    prefix='import std.io;\n'
    def program(body):
        return prefix+'func main() -> u64 { '+body+' return 0; }\n'
    finish='print_u64(frequencies[duration]); print_nl();'
    sources={
        'G-original':original,
        'array-initialize':program('var frequencies: [1001]u64; var duration: u64 = 0; while (duration <= 1000) { frequencies[duration] = 0; duration += 1; } print_u64(duration); print_nl();'),
        'array-compound-variable':program('var frequencies: [1001]u64; var duration: u64 = 1000; frequencies[duration] = 0; frequencies[duration] += 1; '+finish+' frequencies[duration] -= 1; '+finish),
        'array-compound-constant':program('var frequencies: [1001]u64; var duration: u64 = 1000; frequencies[1000] = 0; frequencies[1000] += 1; '+finish+' frequencies[1000] -= 1; '+finish),
        'array-loop-bounded':program('var frequencies: [1001]u64; var duration: u64 = 1000; frequencies[duration] = 1; var guard: u64 = 0; while (frequencies[duration] > 0 && guard < 3) { frequencies[duration] -= 1; guard += 1; } print_u64(guard); print_nl(); '+finish),
        'pointer-parameter':'import std.io;\nfunc read_value(value: *i64) -> i64 { return *value; }\nfunc main() -> u64 { var value: i64 = 42; print_i64(read_value(&value)); print_nl(); return 0; }\n',
    }
    expected={'G-original':'1000\n','array-initialize':'1001\n',
        'array-compound-variable':'1\n0\n','array-compound-constant':'1\n0\n',
        'array-loop-bounded':'1\n0\n','pointer-parameter':'42\n'}
    return [(name,source.encode(),[dict(input='1\n1000\n',expected_output=expected[name])])
            for name,source in sources.items()]


def sha(data):
    return 'sha256:'+hashlib.sha256(data).hexdigest()


def reference_path(base,language,letter):
    if language not in LANGUAGES or letter not in LETTERS:
        raise ValueError('Fixed reference identity required')
    relative=f'java/{letter}/Main.java' if language=='java' else f'{language}/{letter}.'+{
        'c':'c','cpp':'cpp','python':'py','javascript':'js','bpp':'bpp'}[language]
    path=base/'solutions'/relative
    if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:
        raise ValueError('Missing or oversized authored reference')
    return path


def cases_for(letter):
    from tools.freshman_contest.a_i import validate
    from tools.freshman_contest.banks import validate as validate_j
    from tools.freshman_contest.stress_cases import iter_cases
    from tools.freshman_contest.banks_stress_cases import iter_cases as iter_j
    if letter not in LETTERS: raise ValueError('Unknown problem')
    cases=[];identities=[]
    for case in (iter_j() if letter=='J' else iter_cases(letter)):
        (validate_j(case.input_text) if letter=='J' else validate(letter,case.input_text))
        input_data=case.input_text.encode();expected=case.expected_output.encode()
        if len(cases)>=10 or len(input_data)>16*1024**2 or len(expected)>512*1024:
            raise ValueError('Measurement case budget exceeded')
        cases.append(dict(input=case.input_text,expected_output=case.expected_output))
        identities.append(dict(name=case.name,inputBytes=len(input_data),inputHash=sha(input_data),
                               expectedBytes=len(expected),expectedHash=sha(expected)))
    if not cases or len({row['name'] for row in identities})!=len(cases):
        raise ValueError('Empty or duplicate case descriptors')
    return cases,identities


def draft_cases_for(letter,base):
    """Materialize the separate, frozen *draft* suite; never reinterpret old runs."""
    from tools.freshman_contest.a_i import validate
    from tools.freshman_contest.banks import validate as validate_j
    from tools.freshman_contest.stress_cases import iter_cases
    from tools.freshman_contest.coverage_cases import iter_coverage_cases
    from tools.freshman_contest.banks_stress_cases import iter_cases as iter_j
    if letter not in LETTERS: raise ValueError('Unknown problem')
    manifest_path=base/'corpus-manifest-draft-v2.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size>128*1024:
        raise ValueError('Missing or oversized draft corpus manifest')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('version')!=1 or manifest.get('status')!='draft-unapproved'
            or set(manifest.get('problems',{}))!=set(LETTERS)
            or set(manifest.get('sampleData',{}))!=set(LETTERS)):
        raise ValueError('Invalid draft corpus identity')
    declared=manifest.get('manifestHash')
    unsigned={key:value for key,value in manifest.items() if key!='manifestHash'}
    if (declared!=FROZEN_DRAFT_HASH or
            declared!=sha(json.dumps(unsigned,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())):
        raise ValueError('Draft corpus manifest hash mismatch')
    for name in ('a_i.py','banks.py','stress_cases.py','coverage_cases.py','banks_stress_cases.py'):
        source=base/name
        if source.is_symlink() or not source.is_file() or source.stat().st_size>256*1024:
            raise ValueError('Missing or oversized draft corpus source')
        if manifest.get('sources',{}).get(name)!=sha(source.read_bytes()):
            raise ValueError('Draft corpus generator source changed')
    samples=manifest['sampleData'][letter]
    if len(samples)!=DRAFT_SAMPLE_COUNTS[letter]:
        raise ValueError('Draft sample membership changed')
    hidden=[]
    if letter=='J':
        descriptors=[(case,'banks-stress-v1') for case in iter_j()]
    else:
        descriptors=[(case,'stress-v1') for case in iter_cases(letter)]
        descriptors.extend((case,'coverage-v1') for case in iter_coverage_cases(letter)
                           if letter!='B' or case.name in DRAFT_B_COVERAGE)
    material=[]
    for sample in samples:
        if not isinstance(sample,dict) or set(sample)!= {'name','input','expected_output'}:
            raise ValueError('Invalid draft sample')
        material.append((sample['name'],'sample','statement-example-v1',sample['input'],sample['expected_output']))
    material.extend((case.name,'hidden',provenance,case.input_text,case.expected_output)
                    for case,provenance in descriptors)
    identities=[];sample_payload=[];hidden_payload=[]
    for name,visibility,provenance,input_text,expected in material:
        (validate_j(input_text) if letter=='J' else validate(letter,input_text))
        input_data=input_text.encode();expected_data=expected.encode()
        if len(input_data)>16*1024**2 or len(expected_data)>512*1024:
            raise ValueError('Draft case byte budget exceeded')
        identities.append(dict(name=name,visibility=visibility,provenance=provenance,
                               inputBytes=len(input_data),inputHash=sha(input_data),
                               expectedBytes=len(expected_data),expectedHash=sha(expected_data)))
        (sample_payload if visibility=='sample' else hidden_payload).append(
            dict(input=input_text,expected_output=expected))
    if (len(identities)!=DRAFT_CASE_COUNTS[letter]
            or len({row['name'] for row in identities})!=len(identities)
            or identities!=manifest['problems'][letter]):
        raise ValueError('Draft corpus cases differ from frozen manifest')
    return sample_payload,hidden_payload,identities,declared


def validate_reference_result(result,payload,phase_names):
    from app.services.judge_metrics import validate_report
    report=result['_resource_report'];validate_report(report,payload)
    phases=[report['compile']]+[case['usage'] for case in report['cases']]
    count=len(payload['sample'])+len(payload['hidden'])
    if (result['verdict']!='accepted' or len(phases)!=count+1
            or len(phase_names)!=count+1 or len(set(phase_names))!=count+1
            or any(case['verdict']!='accepted' for case in report['cases'])
            or any(p['exitCode']!=0 or p['failureReason'] is not None or p['oomKills']!=0
                   or p['treeReaped'] is not True for p in phases)):
        raise ValueError('Reference did not cleanly pass every case exactly once')
    return phases


async def verify(args):
    if os.environ.get('DATABASE_URL')!='sqlite:///:memory:':
        raise RuntimeError('In-memory isolated DB configuration required')
    root=require_disposable_workspace(args.workspace)
    from app.core.config import settings
    from app.services.compiler import DockerCompilerRunner
    from app.services.judge_policy import content_hash,test_suite_hash
    from app.services.judge_runtime_registry import TOOLCHAINS,launcher_digest,RuntimeRegistry
    from app.services.measured_judge import MeasuredSubmission
    from app.services.judging import judge_code
    versions=json.loads(Path('/versions.json').read_text())
    candidate=getattr(args,'candidate',False)
    draft=getattr(args,'draft_corpus',False)
    if draft and getattr(args,'diagnostic',False):
        raise ValueError('Draft corpus and B++ diagnostics are distinct suites')
    if candidate and (args.language!='bpp' or getattr(args,'diagnostic',False)):
        raise ValueError('Candidate overlay only for full B++ reference suite')
    candidate_identity=None
    if candidate:
        from bpp_candidate_overlay import overlay_identity,bind_base_identity
        candidate_identity=bind_base_identity(overlay_identity(root.parent),args.image,versions['bpp'])
    settings.SANDBOX_WORKDIR_ROOT=str(root/'jobs')
    settings.JUDGE_WORKER_CLASS='isolated-freshman-measurements'
    registry=root/'reference-registry.json'
    entry=dict(language=args.language,runtimeId='isolated-'+args.language,runtimeVersion=versions[args.language]['version'],
               imageDigest=args.image,workerClass=settings.JUDGE_WORKER_CLASS,toolchainProfile=TOOLCHAINS[args.language],
               launcherDigest=launcher_digest())
    if candidate:
        entry.update(runtimeId='isolated-bpp-candidate',runtimeVersion='binary-sha256:'+candidate_identity['binarySha256'])
    with registry.open('x',encoding='utf-8') as file: json.dump(dict(version=1,runtimes=[entry]),file)
    settings.JUDGE_RUNTIME_REGISTRY=str(registry)
    names=[];diagnostics=[];rows=[];bindings=[];artifacts=[];corpus_hash=None
    class Session(MeasuredSubmission):
        async def _execute(self,**options):
            result=await super()._execute(**options)
            if candidate and result['exit_code']==0 and not result['failure_reason']:
                from bpp_candidate_overlay import plain_bytes,digest
                artifacts.append(digest(plain_bytes(self.artifact/'program',32*1024**2)))
            if result['exit_code']!=0 or getattr(args,'diagnostic',False):
                diagnostics.append(dict(stdout=result['stdout'][:4096],stderr=result['stderr'][:4096]))
            return result
    class Runner(DockerCompilerRunner):
        async def _allocate_container(self,create,**options):
            if len(names)>=110: raise RuntimeError('Reference pass container ceiling')
            verify_child_options(options,root,args.image,args.owner)
            if candidate:
                from bpp_candidate_overlay import attach_overlay,verify_overlay_options
                options=attach_overlay(options,root.parent,args.image)
                binding=verify_overlay_options(options,root,args.image,args.owner)
                bindings.append({**binding,'containerName':options['name'],'manifestSha256':candidate_identity['manifestSha256']})
            names.append(options['name'])
            return await super()._allocate_container(create,**options)
        def measured_submission(self,payload):
            return Session(self,payload,RuntimeRegistry.load(settings.JUDGE_RUNTIME_REGISTRY),settings.JUDGE_WORKER_CLASS)
    runner=Runner(labels={'webcompiler.isolated-runtime-matrix':args.owner})
    client=runner._get_client()
    diagnostic=getattr(args,'diagnostic',False)
    if diagnostic and args.language!='bpp': raise ValueError('B++ diagnostic only')
    base=Path('/candidate/tools/freshman_contest')
    def entries():
        if diagnostic:
            for name,source,cases in bpp_diagnostic_sources(base):
                identities=[dict(name=f'{name}-{i}',inputBytes=len(case['input'].encode()),inputHash=sha(case['input'].encode()),
                    expectedBytes=len(case['expected_output'].encode()),expectedHash=sha(case['expected_output'].encode()))
                    for i,case in enumerate(cases)]
                yield name,source,[],cases,identities,None
        else:
            for letter in LETTERS:
                if draft:
                    sample,hidden,identities,manifest_hash=draft_cases_for(letter,base)
                else:
                    hidden,identities=cases_for(letter)
                    sample=[];manifest_hash=None
                yield letter,reference_path(base,args.language,letter).read_bytes(),sample,hidden,identities,manifest_hash
    try:
        for letter,source,sample,hidden,identities,manifest_hash in entries():
            cases=sample+hidden
            if draft:
                if corpus_hash is not None and corpus_hash!=manifest_hash:
                    raise ValueError('Draft corpus identity changed during pass')
                corpus_hash=manifest_hash
            compile_limits=dict(cpuMs=8000,wallMs=10000,memoryBytes=512*1024**2,outputBytes=512*1024,pids=64,tmpBytes=64*1024**2)
            # The frozen draft has up to 12 cases per problem. Its diagnostic
            # wall cap must fit the existing 120-second receipt ceiling even
            # for B/J: 10s compile + 12*8s run + 5s cleanup = 111s.
            run_limits=dict(cpuMs=1000 if diagnostic else 5000,
                wallMs=3000 if diagnostic else DRAFT_DIAGNOSTIC_RUN_WALL_MS if draft else 10000,
                memoryBytes=512*1024**2,outputBytes=512*1024,pids=64,tmpBytes=16*1024**2)
            profile={k:v for k,v in entry.items() if k!='language'}
            profile.update(compile=compile_limits,run=run_limits)
            contract=dict(kind='measured-v1',policyId='isolated-reference-'+letter,revision=1,
                policyHash=content_hash(profile),language=args.language,testSuiteHash=test_suite_hash(sample,hidden),
                profile=profile,jobDeadlineMs=compile_limits['wallMs']+len(cases)*run_limits['wallMs']+5000,
                reservationBytes=512*1024**2)
            payload=dict(language=args.language,code=source.decode('utf-8'),sample=sample,hidden=hidden,judge_contract=contract)
            row=dict(letter=letter,language=args.language,repetition=args.repetition,sourceHash=sha(source),
                     cases=identities,contract=contract,startedAt=datetime.now(timezone.utc).isoformat())
            if draft: row['corpusManifestHash']=manifest_hash
            if candidate: row['candidateOverlay']=candidate_identity
            started=len(names);diagnostics.clear();artifacts.clear();result=None
            try:
                # The host has a finite suite-specific watchdog derived from
                # these frozen receipt deadlines. Neither that watchdog nor the
                # diagnostic caps below are approved contest limits.
                result=await asyncio.wait_for(judge_code(runner,payload),timeout=contract['jobDeadlineMs']/1000)
                phases=validate_reference_result(result,payload,names[started:])
                if candidate:
                    from bpp_candidate_overlay import verify_bindings
                    if len(artifacts)!=1: raise ValueError('Expected exactly one compiled candidate artifact')
                    verify_bindings(bindings[started:],names[started:],candidate_identity['manifestSha256'],artifacts[0])
                    row['compiledArtifactSha256']=artifacts[0]
                row.update(passed=True,verdict=result['verdict'],phases=phases)
            except Exception as exc:
                row.update(passed=False,error=str(exc)[:1000],diagnostics=diagnostics.copy())
                if result is not None:
                    row.update(verdict=result['verdict'],report=result.get('_resource_report'))
            remaining=client.containers.list(all=True,filters={'label':f'webcompiler.isolated-runtime-matrix={args.owner}'})
            if any(c.name in names for c in remaining) or list((root/'jobs').iterdir()):
                raise RuntimeError('Unconfirmed reference cleanup; refusing next problem')
            row['finishedAt']=datetime.now(timezone.utc).isoformat()
            if candidate: row['candidateContainerBindings']=bindings[started:]
            rows.append(row);print(json.dumps(row),flush=True)
            del cases,sample,hidden,payload,result
        scope=('B++ candidate overlay A-J draft corpus measurement; NOT immutable-image acceptance'
               if candidate and draft else
               'B++ candidate overlay A-J descriptor measurement; NOT immutable-image acceptance'
               if candidate else 'B++ diagnostic reductions; NOT acceptance' if diagnostic else
               'A-J frozen draft corpus measurement; NOT final policy approval or DB-worker acceptance'
               if draft else 'A-J descriptor reference measurement; NOT final policy approval or DB-worker acceptance')
        print(json.dumps(dict(scope=scope,corpusManifestHash=corpus_hash if draft else None,
            language=args.language,repetition=args.repetition,problemCount=len(rows),passed=sum(r['passed'] for r in rows),
            phaseContainers=len(names),remainingSubmittedContainers=0,remainingJobDirectories=0)),flush=True)
        expected_names=[name for name,_,_ in bpp_diagnostic_sources(base)] if diagnostic else list(LETTERS)
        if [r['letter'] for r in rows]!=expected_names or not all(r['passed'] for r in rows):
            raise RuntimeError('At least one reference problem failed')
    finally:
        primary=sys.exc_info()[1]
        errors=cleanup_phase_containers(client,names,args.owner)
        try:
            registry.unlink(missing_ok=True)
        except Exception as exc:
            errors.append('registry:'+type(exc).__name__)
        preserve_primary_cleanup_error(primary,errors,'freshman-reference')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True);parser.add_argument('--owner',required=True)
    parser.add_argument('--workspace',required=True,type=Path);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--language',required=True,choices=LANGUAGES)
    parser.add_argument('--repetition',type=int,choices=range(1,11),default=1)
    parser.add_argument('--diagnostic',action='store_true')
    parser.add_argument('--candidate',action='store_true')
    parser.add_argument('--draft-corpus',action='store_true')
    args=parser.parse_args()
    if not args.execute or sys.platform!='linux' or not re.fullmatch('sha256:[a-f0-9]{64}',args.image) or not re.fullmatch('[a-f0-9]{32}',args.owner):
        raise SystemExit('Explicit isolated Linux authorization and immutable identities required')
    asyncio.run(verify(args))
