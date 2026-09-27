"""Synthetic report aggregation tests, not runtime measurement evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from summarize_freshman_measurements import summarize

DIGEST='1'*64
LIMITS=dict(cpuMs=1,wallMs=1,memoryBytes=1024,outputBytes=2,pids=4,tmpBytes=0)


def report(language='cpp',repetition=1):
    usage=dict(phase='run',exitCode=0,failureReason=None,oomKills=0,treeReaped=True,
               cpuUsec=100,wallNs=200000,peakMemoryBytes=1024,outputBytes=2)
    rows=[dict(letter=letter,language=language,repetition=repetition,passed=True,verdict='accepted',
        sourceHash='sha256:'+DIGEST,cases=[dict(name='case-'+letter,inputHash='sha256:'+DIGEST,
        expectedHash='sha256:'+DIGEST,inputBytes=2,expectedBytes=2)],
        contract=dict(kind='measured-v1',policyId='synthetic-'+letter,revision=1,
            policyHash='sha256:'+DIGEST,testSuiteHash='sha256:'+DIGEST,language=language,
            profile=dict(imageDigest='sha256:'+DIGEST,
                compile=deepcopy(LIMITS),run=deepcopy(LIMITS)),
            jobDeadlineMs=5002,reservationBytes=1024),
        phases=[{**usage,'phase':'compile'},deepcopy(usage)]) for letter in 'ABCDEFGHIJ']
    summary=dict(language=language,repetition=repetition,problemCount=10,passed=10,phaseContainers=20,
                 remainingSubmittedContainers=0,remainingJobDirectories=0)
    timeout=520
    return dict(version=1,suite='freshman',language=language,repetition=repetition,
        timedOut=False,controllerExitCode=0,controllerTimeoutSeconds=timeout,
        controllerElapsedSeconds=12.5,controllerTimeoutBasis={
            'kind':'frozen-suite-inner-deadlines-plus-reviewed-overhead',
            'frozenInnerDeadlineSeconds':timeout-60,'reviewedNonJobOverheadSeconds':60},
        cleanup={'attempted':True,'discovered':['a'*12],'removed':['a'*12],
                 'remaining':[],'errors':[],'complete':True},
        capacityBefore={'availableMemoryBytes':1,'freeDiskBytes':1},
        capacityBeforeCleanup={'availableMemoryBytes':1,'freeDiskBytes':1},
        capacityAfterCleanup={'availableMemoryBytes':1,'freeDiskBytes':1},
        runtimeImage='sha256:'+DIGEST,sourceArchiveSha256=DIGEST,referenceArchiveSha256=DIGEST,
        host={'kernel':'synthetic'},scriptsSha256={'probe':DIGEST},
        stdout='\n'.join(json.dumps(row) for row in rows+[summary]))


def save(tmp_path,value,name='report.json'):
    path=tmp_path/name;path.write_text(json.dumps(value),encoding='utf-8');return path


def mutate_row(value,action):
    rows=[json.loads(line) for line in value['stdout'].splitlines()]
    action(rows)
    value['stdout']='\n'.join(json.dumps(row) for row in rows)
    return value


def test_single_pass_never_approves_or_counts_as_ten(tmp_path):
    result=summarize([save(tmp_path,report())])
    assert result['combinationCount']==10 and result['recordCount']==10
    assert result['policyApproved'] is False and result['tenPassDatasetComplete'] is False
    assert all(row['repetitions']==1 for row in result['measurements'])
    assert len(result['missing'])==60
    assert result['measurements'][0]['cases'][0]['maxCpuUsec']==100


def test_all_ten_repetitions_are_counted_but_not_approved(tmp_path):
    paths=[save(tmp_path,report(lang,r),f'{lang}-{r}.json')
           for lang in ('c','cpp','python','java','javascript','bpp') for r in range(1,11)]
    result=summarize(paths)
    assert result['combinationCount']==60 and result['recordCount']==600
    assert result['tenPassDatasetComplete'] is True and result['missing']==[]
    assert result['policyApproved'] is False
    assert all(row['repetitions']==10 for row in result['measurements'])


def test_duplicate_report_cannot_inflate_repetitions(tmp_path):
    path=save(tmp_path,report())
    with pytest.raises(ValueError,match='Duplicate'): summarize([path,path])


@pytest.mark.parametrize('field,value',[('timedOut',True),('controllerExitCode',124),('suite','mechanics')])
def test_partial_or_wrong_scope_rejected(tmp_path,field,value):
    value_report=report();value_report[field]=value
    with pytest.raises(ValueError): summarize([save(tmp_path,value_report)])


@pytest.mark.parametrize('field,value',[('runtimeImage','sha256:'+'2'*64),('sourceArchiveSha256','2'*64),
    ('referenceArchiveSha256','2'*64),('host',{'kernel':'other'}),('scriptsSha256',{'probe':'2'*64})])
def test_changed_runtime_sources_host_or_probe_not_merged(tmp_path,field,value):
    second=report(repetition=2);second[field]=value
    with pytest.raises(ValueError,match='Mixed'):
        summarize([save(tmp_path,report()),save(tmp_path,second,'second.json')])


@pytest.mark.parametrize('mutation',('case','source','contract','missing','cleanup','phase','metrics','wrong','containers'))
def test_changed_or_incomplete_rows_rejected(tmp_path,mutation):
    second=report(repetition=2)
    def change(rows):
        if mutation=='case': rows[0]['cases'][0]['inputHash']='sha256:'+'2'*64
        if mutation=='source': rows[0]['sourceHash']='sha256:'+'2'*64
        if mutation=='contract': rows[0]['contract']['different']=True
        if mutation=='missing': rows.pop(0)
        if mutation=='cleanup': rows[-1]['remainingJobDirectories']=1
        if mutation=='phase': rows[0]['phases'].pop()
        if mutation=='metrics': rows[0]['phases'][0]['cpuUsec']=-1
        if mutation=='wrong': rows[0]['passed']=False
        if mutation=='containers': rows[-1]['phaseContainers']=19
    mutate_row(second,change)
    with pytest.raises(ValueError): summarize([save(tmp_path,report()),save(tmp_path,second,'second.json')])


def test_empty_input_is_not_complete():
    with pytest.raises(ValueError): summarize([])


@pytest.mark.parametrize(('field','value'),[
    ('language','python'),('controllerTimeoutSeconds',240),('controllerElapsedSeconds',521),
    ('controllerTimeoutBasis',{}),('cleanup',{'complete':True}),
    ('capacityAfterCleanup',None),
])
def test_hardened_controller_and_cleanup_envelope_is_required(tmp_path,field,value):
    value_report=report();value_report[field]=value
    with pytest.raises(ValueError,match='controller/cleanup'):
        summarize([save(tmp_path,value_report)])


def test_cleanup_failure_cannot_count_toward_ten_pass_dataset(tmp_path):
    value_report=report();value_report['cleanup']['errors']=['TimeoutError']
    value_report['cleanup']['complete']=False
    with pytest.raises(ValueError,match='controller/cleanup'):
        summarize([save(tmp_path,value_report)])


@pytest.mark.parametrize(('phase_index','field','value'),[
    (0,'cpuUsec',1000),(0,'wallNs',1_000_000),(0,'peakMemoryBytes',1025),(0,'outputBytes',3),
    (1,'cpuUsec',1000),(1,'wallNs',1_000_000),(1,'peakMemoryBytes',1025),(1,'outputBytes',3),
])
def test_accepted_measurement_above_its_own_frozen_limit_is_rejected(
        tmp_path,phase_index,field,value):
    value_report=report()
    def change(rows): rows[0]['phases'][phase_index][field]=value
    mutate_row(value_report,change)
    with pytest.raises(ValueError,match='exceeds'):
        summarize([save(tmp_path,value_report)])


def test_zero_peak_memory_is_not_accepted_measurement_evidence(tmp_path):
    value_report=report()
    mutate_row(value_report,lambda rows: rows[0]['phases'][0].update(peakMemoryBytes=0))
    with pytest.raises(ValueError,match='Invalid measurements'):
        summarize([save(tmp_path,value_report)])


def test_measurement_inside_deadlines_and_at_memory_output_limits_is_accepted(tmp_path):
    value_report=report()
    def change(rows):
        for phase in rows[0]['phases']:
            phase.update(cpuUsec=999,wallNs=999_999,peakMemoryBytes=1024,outputBytes=2)
    mutate_row(value_report,change)
    result=summarize([save(tmp_path,value_report)])
    assert result['controllerEvidence']=='hardened-v1'


@pytest.mark.parametrize(('field','value'),[('jobDeadlineMs',5001),('reservationBytes',1023)])
def test_frozen_deadline_and_reservation_must_match_stage_limits(tmp_path,field,value):
    value_report=report()
    mutate_row(value_report,lambda rows: rows[0]['contract'].__setitem__(field,value))
    with pytest.raises(ValueError,match='deadline or reservation'):
        summarize([save(tmp_path,value_report)])
