"""Aggregate local reference evidence without approving contest limits.

Inputs are retained reports from the trusted isolated probe, not authenticated
host attestations. Duplicate/mixed runs cannot inflate the repetition count.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

LANGUAGES=('c','cpp','python','java','javascript','bpp')
LETTERS=tuple('ABCDEFGHIJ')
FROZEN_DRAFT_HASH='sha256:e5213ca9d1aaf3691c91db22aa021870b532b653c015c58c4bf90fff8a8539fc'
HISTORICAL_DRAFT_HASH='sha256:12f0c6f989b9736b0f5784fe29de2400b7cf06bc71d63330629f74a24d20b764'
FROZEN_DRAFT_COUNTS={
    HISTORICAL_DRAFT_HASH:dict(zip(LETTERS,(5,12,7,5,7,6,7,7,10,12))),
    FROZEN_DRAFT_HASH:dict(zip(LETTERS,(5,12,7,5,7,6,7,7,11,12))),
}
CONTROLLER_TIMEOUT_SECONDS={'freshman':520,'freshman-draft':842}


def digest(value,prefix=False):
    if not isinstance(value,str) or not re.fullmatch(('sha256:' if prefix else '')+'[a-f0-9]{64}',value):
        raise ValueError('Invalid evidence digest')
    return value


def _draft_identity(manifest):
    if (not isinstance(manifest,dict) or manifest.get('version')!=1
            or manifest.get('status')!='draft-unapproved'
            or set(manifest.get('problems',{}))!=set(LETTERS)):
        raise ValueError('An exact frozen draft corpus manifest is required')
    declared=digest(manifest.get('manifestHash'),True)
    if {letter:len(manifest['problems'][letter]) for letter in LETTERS}!=FROZEN_DRAFT_COUNTS.get(declared):
        raise ValueError('An exact frozen draft corpus manifest is required')
    unsigned={key:value for key,value in manifest.items() if key!='manifestHash'}
    actual='sha256:'+hashlib.sha256(json.dumps(unsigned,ensure_ascii=False,
        sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    if declared!=actual:
        raise ValueError('Draft corpus manifest hash mismatch')
    return declared


def _controller_evidence(report,suite,language):
    """Require the hardened host watchdog and verified post-run cleanup envelope."""
    timeout=CONTROLLER_TIMEOUT_SECONDS[suite]
    basis=report.get('controllerTimeoutBasis')
    elapsed=report.get('controllerElapsedSeconds')
    cleanup=report.get('cleanup')
    capacities=(report.get('capacityBefore'),report.get('capacityBeforeCleanup'),
                report.get('capacityAfterCleanup'))
    if (report.get('version')!=1 or report.get('language')!=language
            or report.get('controllerTimeoutSeconds')!=timeout
            or basis!={'kind':'frozen-suite-inner-deadlines-plus-reviewed-overhead',
                       'frozenInnerDeadlineSeconds':timeout-60,
                       'reviewedNonJobOverheadSeconds':60}
            or isinstance(elapsed,bool) or not isinstance(elapsed,(int,float))
            or not 0<=elapsed<=timeout
            or not isinstance(cleanup,dict) or cleanup.get('complete') is not True
            or cleanup.get('errors')!=[] or cleanup.get('remaining')!=[]
            or cleanup.get('attempted') is not True
            or not isinstance(cleanup.get('removed'),list) or not cleanup['removed']
            or any(not isinstance(value,str) or not re.fullmatch('[a-f0-9]{12,64}',value)
                   for value in cleanup['removed'])
            or any(not isinstance(capacity,dict)
                   or any(type(capacity.get(key)) is not int or capacity[key]<0
                          for key in ('availableMemoryBytes','freeDiskBytes'))
                   for capacity in capacities)):
        raise ValueError('Missing or invalid hardened controller/cleanup evidence')


def _phase_limits(profile,phase):
    limits=profile.get(phase)
    positive=('cpuMs','wallMs','memoryBytes','outputBytes','pids')
    if (not isinstance(limits,dict)
            or any(type(limits.get(key)) is not int or limits[key]<=0 for key in positive)
            or type(limits.get('tmpBytes')) is not int or limits['tmpBytes']<0):
        raise ValueError('Invalid frozen phase limits')
    return limits


def _within_phase_limits(usage,limits):
    return (usage['cpuUsec']<limits['cpuMs']*1000
            and usage['wallNs']<limits['wallMs']*1000000
            and usage['peakMemoryBytes']<=limits['memoryBytes']
            and usage['outputBytes']<=limits['outputBytes'])


def _contract_limits(contract,language,image,case_count):
    if (not isinstance(contract,dict) or contract.get('kind')!='measured-v1'
            or not isinstance(contract.get('policyId'),str) or not contract['policyId']
            or type(contract.get('revision')) is not int or contract['revision']<1
            or contract.get('language')!=language):
        raise ValueError('Invalid frozen measurement contract')
    digest(contract.get('policyHash'),True);digest(contract.get('testSuiteHash'),True)
    profile=contract.get('profile')
    if not isinstance(profile,dict) or profile.get('imageDigest')!=image:
        raise ValueError('Contract runtime identity mismatch')
    compile_limits=_phase_limits(profile,'compile')
    run_limits=_phase_limits(profile,'run')
    expected_deadline=compile_limits['wallMs']+case_count*run_limits['wallMs']+5000
    if (contract.get('jobDeadlineMs')!=expected_deadline
            or contract.get('reservationBytes')!=max(
                compile_limits['memoryBytes'],run_limits['memoryBytes'])):
        raise ValueError('Frozen measurement deadline or reservation mismatch')
    return compile_limits,run_limits


def summarize(paths,*,suite='freshman',manifest=None):
    if suite not in ('freshman','freshman-draft'):
        raise ValueError('Only installed-image reference suites can be summarized')
    draft_hash=_draft_identity(manifest) if suite=='freshman-draft' else None
    runs={};identity=None;problem_cases={};sources={};contracts={};artifacts=[]
    for path in paths:
        path=Path(path)
        if path.stat().st_size>1024**2: raise ValueError('Oversized report')
        data=path.read_bytes();report=json.loads(data)
        if report.get('suite')!=suite or report.get('timedOut') is not False or report.get('controllerExitCode')!=0:
            raise ValueError('Incomplete or failed measurement report')
        current=(digest(report['runtimeImage'],True),digest(report['sourceArchiveSha256']),
                 digest(report['referenceArchiveSha256']),json.dumps(report['host'],sort_keys=True),
                 json.dumps(report['scriptsSha256'],sort_keys=True))
        if identity is not None and current!=identity: raise ValueError('Mixed source, runtime, probe or host evidence')
        identity=current
        records=[json.loads(line) for line in report['stdout'].splitlines() if line.strip()]
        if len(records)!=11: raise ValueError('Expected ten problem records and one summary')
        rows,summary=records[:-1],records[-1]
        language=summary.get('language');repetition=summary.get('repetition')
        if draft_hash is not None and summary.get('corpusManifestHash')!=draft_hash:
            raise ValueError('Draft corpus summary identity mismatch')
        if language not in LANGUAGES or type(repetition) is not int or not 1<=repetition<=10 or report['repetition']!=repetition:
            raise ValueError('Invalid runtime repetition identity')
        if ([r.get('letter') for r in rows]!=list(LETTERS) or summary.get('passed')!=10 or summary.get('problemCount')!=10
                or summary.get('remainingSubmittedContainers')!=0 or summary.get('remainingJobDirectories')!=0):
            raise ValueError('Incomplete pass or cleanup')
        _controller_evidence(report,suite,language)
        phase_count=0
        for row in rows:
            letter=row['letter'];key=(language,letter,repetition)
            if key in runs: raise ValueError('Duplicate runtime/problem/repetition')
            if row.get('language')!=language or row.get('repetition')!=repetition or row.get('passed') is not True or row.get('verdict')!='accepted':
                raise ValueError('Reference failure or inconsistent row identity')
            digest(row['sourceHash'],True)
            source_key=(language,letter)
            if source_key in sources and sources[source_key]!=row['sourceHash']: raise ValueError('Reference changed between repetitions')
            sources[source_key]=row['sourceHash']
            cases=row['cases']
            if not 1<=len(cases)<=(200 if draft_hash else 10) or len({case['name'] for case in cases})!=len(cases): raise ValueError('Invalid cases')
            if draft_hash is not None and (row.get('corpusManifestHash')!=draft_hash
                    or cases!=manifest['problems'][letter]):
                raise ValueError('Measured cases differ from frozen draft corpus')
            for case in cases:
                digest(case['inputHash'],True);digest(case['expectedHash'],True)
                if any(type(case[k]) is not int or case[k]<0 for k in ('inputBytes','expectedBytes')):
                    raise ValueError('Invalid case sizes')
            case_identity=json.dumps(cases,sort_keys=True)
            if letter in problem_cases and problem_cases[letter]!=case_identity: raise ValueError('Different cases across runtimes/repetitions')
            problem_cases[letter]=case_identity
            contract=row['contract']
            compile_limits,run_limits=_contract_limits(
                contract,language,report['runtimeImage'],len(cases))
            contract_identity=json.dumps(contract,sort_keys=True)
            if source_key in contracts and contracts[source_key]!=contract_identity: raise ValueError('Changed diagnostic limits between repetitions')
            contracts[source_key]=contract_identity
            phases=row['phases'];phase_count+=len(phases)
            if len(phases)!=len(cases)+1 or [p['phase'] for p in phases]!=['compile']+['run']*len(cases):
                raise ValueError('Incomplete compile-once/case measurement')
            for phase in phases:
                if phase['exitCode']!=0 or phase['failureReason'] is not None or phase['oomKills']!=0 or phase['treeReaped'] is not True:
                    raise ValueError('Failed or unreaped phase')
                if (any(type(phase[k]) is not int or phase[k]<0
                        for k in ('cpuUsec','wallNs','peakMemoryBytes','outputBytes'))
                        or phase['peakMemoryBytes']==0):
                    raise ValueError('Invalid measurements')
            if (not _within_phase_limits(phases[0],compile_limits)
                    or any(not _within_phase_limits(phase,run_limits) for phase in phases[1:])):
                raise ValueError('Accepted measurement exceeds its frozen phase limits')
            runs[key]=row
        if summary['phaseContainers']!=phase_count: raise ValueError('Container count does not match measurements')
        artifacts.append(dict(path=str(path),sha256=hashlib.sha256(data).hexdigest()))
    if not runs: raise ValueError('No complete reports')
    output=[]
    for language in LANGUAGES:
        for letter in LETTERS:
            rows=[runs[(language,letter,r)] for r in range(1,11) if (language,letter,r) in runs]
            if not rows: continue
            compiled=[r['phases'][0] for r in rows]
            executed=[p for r in rows for p in r['phases'][1:]]
            stats=lambda phases: dict(maxCpuUsec=max(p['cpuUsec'] for p in phases),
                maxWallNs=max(p['wallNs'] for p in phases),peakMemoryBytes=max(p['peakMemoryBytes'] for p in phases),
                minCpuUsec=min(p['cpuUsec'] for p in phases),minWallNs=min(p['wallNs'] for p in phases))
            # Per-case variation, not min/max across differently sized inputs.
            case_stats=[dict(name=rows[0]['cases'][i]['name'],**stats([r['phases'][i+1] for r in rows]))
                        for i in range(len(rows[0]['cases']))]
            output.append(dict(language=language,letter=letter,repetitions=len(rows),
                repetitionIndices=[r['repetition'] for r in rows],caseCount=len(case_stats),compile=stats(compiled),run=stats(executed),cases=case_stats))
    missing=[dict(language=lang,letter=letter,repetitions=[r for r in range(1,11) if (lang,letter,r) not in runs])
             for lang in LANGUAGES for letter in LETTERS if any((lang,letter,r) not in runs for r in range(1,11))]
    return dict(scope='Isolated frozen draft corpus measurements only' if draft_hash else 'Isolated reference descriptor measurements only',
        corpusManifestHash=draft_hash,controllerEvidence='hardened-v1',policyApproved=False,
        tenPassDatasetComplete=not missing,combinationCount=len(output),recordCount=len(runs),
        limitations=['Not a final reviewed test suite','Slow-solution diagnostics are separate and not counted here',
                     'No normal-concurrency or cold-start attribution','No DB/queue/worker restart acceptance',
                     'Source/tier/schedule/scoring/publication approvals remain external'],
        artifacts=artifacts,measurements=output,missing=missing)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports',nargs='+',type=Path)
    parser.add_argument('--suite',choices=('freshman','freshman-draft'),default='freshman')
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    frozen=json.loads(args.manifest.read_text(encoding='utf-8')) if args.manifest else None
    value=summarize(args.reports,suite=args.suite,manifest=frozen)
    if args.output:
        with args.output.open('x',encoding='utf-8') as stream: json.dump(value,stream,ensure_ascii=False,indent=2)
    else: print(json.dumps(value,ensure_ascii=False,indent=2))
