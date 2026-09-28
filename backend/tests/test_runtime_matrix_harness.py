"""Offline tests for the isolated verifier; these never contact Docker."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from app.models.judge_policy import StageLimits
from app.services.judge_runtime_registry import LAUNCHER_PATH, compile_argv, run_argv
from app.services.measured_judge import phase_tmpfs

spec=importlib.util.spec_from_file_location('runtime_matrix_probe',Path(__file__).resolve().parents[2]/'scripts/verify_runtime_matrix.py')
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def limits():
    return dict(cpuMs=1000,wallMs=2000,memoryBytes=128*1024**2,outputBytes=1024,pids=64,tmpBytes=16*1024**2)


def outcome(kind):
    phase=dict(exitCode=0,failureReason=None,cpuUsec=100,wallNs=1000,peakMemoryBytes=1000,
               oomKills=0,outputBytes=2,treeReaped=True)
    verdict={'cpu':'time_limit_exceeded','wall':'time_limit_exceeded','oom':'memory_limit_exceeded',
             'output':'output_limit_exceeded','pids':'process_limit_exceeded',
             'exit137':'runtime_error'}.get(kind,kind)
    report=dict(compile=deepcopy(phase),cases=[])
    if kind=='compile_error': report['compile']['exitCode']=1
    else:
        changes={'cpu':dict(failureReason=verdict,cpuUsec=1000000),
                 'wall':dict(failureReason=verdict,wallNs=2000000000),
                 'oom':dict(failureReason=verdict,oomKills=1),
                 'output':dict(failureReason=verdict,outputBytes=1024),
                 'pids':dict(failureReason=verdict,pidLimitHits=1),
                 'exit137':dict(exitCode=137)}.get(kind,{})
        report['cases']=[dict(verdict=verdict,usage={**phase,**changes}) for _ in range(2 if kind=='accepted' else 1)]
    return dict(verdict=verdict,_resource_report=report)


KINDS=('accepted','wrong_answer','compile_error','cpu','wall','oom','output','pids','exit137')


@pytest.mark.parametrize('kind',KINDS)
def test_exact_success_witness(kind):
    result=outcome(kind);names=['compile']+[str(i) for i in range(len(result['_resource_report']['cases']))]
    assert probe.verify_case_evidence(kind,result['verdict'],result,limits(),names)
    with pytest.raises(ValueError): probe.verify_case_evidence(kind,result['verdict'],result,limits(),names+['extra'])
    result['_resource_report']['compile']['treeReaped']=False
    with pytest.raises(ValueError): probe.verify_case_evidence(kind,result['verdict'],result,limits(),names)


@pytest.mark.parametrize('kind,field,value',[
    ('cpu','cpuUsec',999999),('cpu','wallNs',2000000000),('wall','wallNs',1999999999),
    ('wall','cpuUsec',1000000),('oom','oomKills',0),('output','outputBytes',1023),
    ('pids','pidLimitHits',0),
    ('exit137','exitCode',-9),('exit137','oomKills',1),('accepted','exitCode',1),
    ('wrong_answer','failureReason','time_limit_exceeded')])
def test_broad_verdict_cannot_substitute_for_witness(kind,field,value):
    result=outcome(kind);result['_resource_report']['cases'][-1]['usage'][field]=value
    names=['compile']+[str(i) for i in range(len(result['_resource_report']['cases']))]
    with pytest.raises(ValueError): probe.verify_case_evidence(kind,result['verdict'],result,limits(),names)


def test_wrong_answer_prefix_and_compile_resource_failure_rejected():
    result=outcome('wrong_answer');result['_resource_report']['cases']=[]
    with pytest.raises(ValueError): probe.verify_case_evidence('wrong_answer','wrong_answer',result,limits(),['compile'])
    result=outcome('compile_error');result['_resource_report']['compile']['failureReason']='time_limit_exceeded'
    with pytest.raises(ValueError): probe.verify_case_evidence('compile_error','compile_error',result,limits(),['compile'])


def child_options(root,language='python',phase='compile'):
    stage=StageLimits.model_validate(limits())
    phase_id='a'*32
    phase_spec=dict(version=2,phase=phase,stdin='/input/stdin',limits=limits(),
                    argv=(compile_argv if phase=='compile' else run_argv)(language))
    return dict(image='test-image',name='compiler-measured-'+phase_id,
        labels={'webcompiler.isolated-runtime-matrix':'test-owner','webcompiler.phase':phase_id},
        network_disabled=True,read_only=True,init=False,cgroupns='private',ipc_mode='none',
        entrypoint=['/usr/bin/python3','-I','-c'],command=[LAUNCHER_PATH.read_text(encoding='utf-8')],detach=True,
        healthcheck={'test':['NONE']},user='0:0',mem_limit=stage.memory_bytes,memswap_limit=stage.memory_bytes,
        nano_cpus=1000000000,pids_limit=64,cap_drop=['ALL'],cap_add=['KILL','SETUID','SETGID'],
        security_opt=['no-new-privileges'],log_config={'Type':'none','Config':{}},
        ulimits=[{'Name':'nofile','Soft':64,'Hard':64}],tmpfs=phase_tmpfs(language,phase,stage),
        volumes={str(root/'job/input'):{'bind':'/input','mode':'ro'},
                 str(root/'job/source'):{'bind':'/source' if phase=='compile' else '/artifact','mode':'ro'}},
        environment={'JUDGE_PHASE_SPEC':json.dumps(phase_spec)})


@pytest.mark.parametrize('language',tuple(probe.SOURCES))
@pytest.mark.parametrize('phase',('compile','run'))
def test_all_language_phase_contracts(tmp_path,language,phase):
    probe.verify_child_options(child_options(tmp_path,language,phase),tmp_path,'test-image','test-owner')


@pytest.mark.parametrize('key,value',[
    ('network_disabled',False),('read_only',False),('init',True),('cgroupns','host'),('ipc_mode','host'),
    ('memswap_limit',-1),('nano_cpus',2000000000),('pids_limit',100),('cap_drop',[]),('cap_add',['SYS_ADMIN']),
    ('security_opt',[]),('log_config',{'Type':'json-file','Config':{}}),('ulimits',[]),('healthcheck',{}),
    ('entrypoint',['/bin/sh']),('command',['bad command']),('user','65534:65534')])
def test_isolation_regression_rejected_before_create(tmp_path,key,value):
    options=child_options(tmp_path);options[key]=value
    with pytest.raises(RuntimeError): probe.verify_child_options(options,tmp_path,'test-image','test-owner')


@pytest.mark.parametrize('key,value',[
    ('privileged',True),('pid_mode','host'),('userns_mode','host'),
    ('devices',['/dev/kmsg:/dev/kmsg:rwm']),('mounts',[object()]),
])
def test_unreviewed_docker_option_rejected_before_create(tmp_path,key,value):
    options=child_options(tmp_path);options[key]=value
    with pytest.raises(RuntimeError,match='Unreviewed'):
        probe.verify_child_options(options,tmp_path,'test-image','test-owner')


@pytest.mark.parametrize('mutation',('name','phase_label','extra_label','extra_environment'))
def test_phase_identity_or_extra_environment_rejected(tmp_path,mutation):
    options=child_options(tmp_path)
    if mutation=='name': options['name']='compiler-measured-'+'b'*32
    if mutation=='phase_label': options['labels']['webcompiler.phase']='b'*32
    if mutation=='extra_label': options['labels']['unexpected']='value'
    if mutation=='extra_environment': options['environment']['UNREVIEWED']='value'
    with pytest.raises(RuntimeError):
        probe.verify_child_options(options,tmp_path,'test-image','test-owner')


@pytest.mark.parametrize('mutation',('outside','writable','extra','tmp','argv'))
def test_mount_or_command_escape_rejected(tmp_path,mutation):
    options=child_options(tmp_path)
    if mutation=='outside': options['volumes'][str(tmp_path.parent/'outside')]={'bind':'/input','mode':'ro'}
    if mutation=='writable': options['volumes'][str(tmp_path/'job/input')]['mode']='rw'
    if mutation=='extra': options['volumes'][str(tmp_path/'job/extra')]={'bind':'/unexpected','mode':'ro'}
    if mutation=='tmp': options['tmpfs']['/tmp']='rw,size=1234'
    if mutation=='argv':
        value=json.loads(options['environment']['JUDGE_PHASE_SPEC']);value['argv']=['/bin/sh','-c','oops']
        options['environment']['JUDGE_PHASE_SPEC']=json.dumps(value)
    with pytest.raises(RuntimeError): probe.verify_child_options(options,tmp_path,'test-image','test-owner')


def test_full_matrix_requires_every_unique_case():
    results=[dict(language=lang,case=kind,passed=True) for lang in probe.SOURCES for kind in KINDS[:3]]
    results += [dict(language='python',case=kind,passed=True) for kind in KINDS[3:]]
    probe.verify_complete_matrix(results,'all')
    for invalid in ([],results[:-1],results+[results[0]],results[:-1]+[results[0]]):
        with pytest.raises(RuntimeError): probe.verify_complete_matrix(invalid,'all')
    results[-1]['passed']=False
    with pytest.raises(RuntimeError): probe.verify_complete_matrix(results,'all')


def test_cleanup_failure_preserves_primary_error_and_only_fails_clean_execution():
    primary=ValueError('original execution failure')
    probe.preserve_primary_cleanup_error(primary,['list:TimeoutError'],'matrix')
    assert 'matrix cleanup incomplete: list:TimeoutError' in primary.__notes__
    with pytest.raises(RuntimeError,match='matrix cleanup incomplete'):
        probe.preserve_primary_cleanup_error(None,['remove:TimeoutError'],'matrix')


def test_private_workspace_rejects_unsafe_mode_and_preexisting_jobs(tmp_path):
    workspace=tmp_path/'work';workspace.mkdir()
    safe=SimpleNamespace(st_mode=stat.S_IFDIR|0o700)
    assert probe.require_private_workspace(workspace,metadata=safe)==workspace.resolve()
    for mode in (0o770,0o707,0o755):
        with pytest.raises(RuntimeError,match='Private empty'):
            probe.require_private_workspace(
                workspace,metadata=SimpleNamespace(st_mode=stat.S_IFDIR|mode))
    (workspace/'jobs').mkdir()
    with pytest.raises(RuntimeError,match='Private empty'):
        probe.require_private_workspace(workspace,metadata=safe)
