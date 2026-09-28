"""Local contracts and adversarial artifacts; not real Docker acceptance."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.judge_policy import RuntimeLimits, StageLimits
from app.services.judge_policy import test_suite_hash as suite_hash
from app.services.judge_runtime_registry import RuntimeRegistry, TOOLCHAINS, launcher_digest, compile_argv, run_argv
from app.services import judge_runtime_registry as runtime_registry
from app.services.measured_judge import MeasuredSubmission, artifact_archive_script, decode_report, finish_io, unpack_artifact, validate_receipt
from app.services.judging import judge_code


def payload_fixture():
    stage=dict(cpuMs=1000,wallMs=2000,memoryBytes=128*1024**2,outputBytes=1024,pids=16,tmpBytes=16*1024**2)
    sample=[{'input':'sample','expectedOutput':'42'}]
    hidden=[{'input':'secret','expectedOutput':'84'}]
    profile=dict(runtimeId='python-test',runtimeVersion='unit-fixture',imageDigest='sha256:'+'1'*64,
        workerClass='unit',toolchainProfile=TOOLCHAINS['python'],launcherDigest=launcher_digest(),compile=deepcopy(stage),run=deepcopy(stage))
    return dict(language='python',code='print(42)',sample=sample,hidden=hidden,
        judge_contract=dict(kind='measured-v1',policyId='test',revision=1,policyHash='sha256:'+'2'*64,
            language='python',testSuiteHash=suite_hash(sample,hidden),profile=profile,jobDeadlineMs=7000,
            reservationBytes=128*1024**2))


def registry_fixture(payload=None):
    profile=(payload or payload_fixture())['judge_contract']['profile']
    return dict(version=1,runtimes=[{k:profile[k] for k in ('runtimeId','runtimeVersion','imageDigest','workerClass','toolchainProfile')}
        | dict(language='python',launcherDigest=launcher_digest())])


def report_fixture():
    return dict(version=2,phase='run',exitCode=0,failureReason=None,cpuUsec=100,wallNs=1000000,
        peakMemoryBytes=100000,oomKills=0,pidLimitHits=0,outputBytes=2,treeReaped=True)


def archive_bytes(entries, *, format=tarfile.USTAR_FORMAT):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w',format=format) as archive:
        for name,kind,data in entries:
            info=tarfile.TarInfo(name);info.type=kind
            if kind==tarfile.REGTYPE:
                info.size=len(data);archive.addfile(info,io.BytesIO(data))
            else:
                if kind in (tarfile.SYMTYPE,tarfile.LNKTYPE): info.linkname='/etc/passwd'
                archive.addfile(info)
    return output.getvalue()


def test_exact_registered_launcher_and_runtime_required(tmp_path):
    payload=payload_fixture();profile=validate_receipt(payload)
    raw=registry_fixture(payload);registry=RuntimeRegistry(raw)
    assert registry.resolve('python',profile,'unit').image_digest==profile.image_digest
    for field,value in [('runtimeVersion','other'),('launcherDigest','sha256:'+'3'*64),('imageDigest','sha256:'+'3'*64)]:
        bad=deepcopy(raw);bad['runtimes'][0][field]=value
        with pytest.raises(ValueError): RuntimeRegistry(bad).resolve('python',profile,'unit')
    with pytest.raises(ValueError): registry.resolve('python',profile,'other')
    with pytest.raises(RuntimeError): RuntimeRegistry.load('')
    with pytest.raises(ValueError): RuntimeRegistry.load('relative.json')
    path=tmp_path/'registry.json';path.write_text(json.dumps(raw),encoding='utf-8')
    assert RuntimeRegistry.load(path).resolve('python',profile,'unit')==registry.resolve('python',profile,'unit')
    path.write_text('{"version":1,"version":1,"runtimes":[]}',encoding='utf-8')
    with pytest.raises(ValueError,match='Duplicate'): RuntimeRegistry.load(path)


@pytest.mark.parametrize('field,value', [('version',True),('runtimes',[]),('extra',1)])
def test_registry_rejects_ambiguous_shape(field,value):
    raw=registry_fixture();raw[field]=value
    with pytest.raises(ValueError): RuntimeRegistry(raw)


def test_unapproved_toolchain_and_duplicate_registration_rejected():
    raw=registry_fixture();raw['runtimes'][0]['toolchainProfile']='arbitrary-shell'
    with pytest.raises(ValueError): RuntimeRegistry(raw)
    raw=registry_fixture();raw['runtimes']*=2
    with pytest.raises(ValueError,match='Duplicate'): RuntimeRegistry(raw)


def test_trusted_toolchain_recipes_have_frozen_fingerprints():
    from app.services.judge_toolchain_catalog import ADAPTERS,EXPECTED_FINGERPRINTS,trusted_adapter
    assert set(ADAPTERS)==set(EXPECTED_FINGERPRINTS)
    for key,adapter in ADAPTERS.items():
        assert trusted_adapter(*key)==adapter
        assert adapter.fingerprint()==EXPECTED_FINGERPRINTS[key]
    with pytest.raises(ValueError,match='Unknown trusted'):
        trusted_adapter('python','unregistered-profile')


@pytest.mark.asyncio
async def test_historical_adapter_snapshot_keeps_source_commands_and_layout(tmp_path,monkeypatch):
    from app.services import judge_toolchain_catalog as catalog
    from app.services.measured_judge import phase_tmpfs
    old_profile='cpython-pyc-legacy-test'
    current=catalog.trusted_adapter('python',TOOLCHAINS['python'])
    old=replace(current,profile=old_profile,source_name='legacy.py',
        compile_command=('/usr/bin/python3','-I','-c',
            "import py_compile;py_compile.compile('/source/legacy.py',cfile='/work/artifact/main.pyc',doraise=True)"),
        run_command=('/usr/bin/python3','-B','-I','/artifact/main.pyc'),
        scratch_layout='bpp-split-v1')
    entries=dict(catalog.ADAPTERS) | {('python',old_profile):old}
    fingerprints=dict(catalog.EXPECTED_FINGERPRINTS) | {('python',old_profile):old.fingerprint()}
    monkeypatch.setattr(catalog,'ADAPTERS',entries)
    monkeypatch.setattr(catalog,'EXPECTED_FINGERPRINTS',fingerprints)
    monkeypatch.setattr(runtime_registry,'ADAPTERS',entries)
    payload=payload_fixture()
    payload['judge_contract']['profile']['toolchainProfile']=old_profile
    raw=registry_fixture(payload)
    raw['version']=2
    raw['runtimes'][0]['admitNew']=False
    registry=RuntimeRegistry(raw)
    profile=validate_receipt(payload)
    with pytest.raises(ValueError,match='approved'):
        registry.resolve('python',profile,'unit',for_admission=True)
    snapshot=registry.replay_snapshots('unit')[runtime_registry.runtime_key('python',profile,'unit')]
    assert snapshot.toolchain==old and snapshot.toolchain_fingerprint==old.fingerprint()
    # A selected receipt never consults a changed process-global default.
    monkeypatch.setattr(catalog,'ADAPTERS',{key:value for key,value in entries.items() if key!=('python',old_profile)})
    monkeypatch.setattr(runtime_registry,'ADAPTERS',catalog.ADAPTERS)
    monkeypatch.setattr(settings,'SANDBOX_WORKDIR_ROOT',str(tmp_path/'workdirs'))
    client=SimpleNamespace(images=SimpleNamespace(get=lambda digest:SimpleNamespace(id=digest)),close=lambda:None)
    class Runner:
        labels={}
        def _get_client(self): return client
        async def _cleanup(self,action):
            action()
            return True
    session=MeasuredSubmission(Runner(),payload,None,'unit',snapshot=snapshot)
    phase=AsyncMock(side_effect=[{'exit_code':0,'failure_reason':None},{'exit_code':0,'failure_reason':None}])
    session._phase=phase
    async with session:
        assert (session.source/'legacy.py').read_text(encoding='utf-8')==payload['code']
        assert not (session.source/'main.py').exists()
        await session._execute(mode='compile',source_code=payload['code'],language='python')
        await session.run(source_code=payload['code'],language='python',stdin='')
        assert phase.await_args_list[0].args[2]==list(old.compile_command)
        assert phase.await_args_list[1].args[2]==list(old.run_command)
        assert '/tmp' in phase_tmpfs('python','compile',profile.compile,layout=session.toolchain.scratch_layout)


def test_frozen_v1_receipt_replays_with_archived_launcher_and_v1_contract():
    old_launcher='sha256:908bb710244512ea3f655831a7aa84b4fb5d6ec370cd32e558f14944fbc0e505'
    payload=payload_fixture()
    profile=payload['judge_contract']['profile']
    profile['toolchainProfile']='cpython-pyc-v1'
    profile['launcherDigest']=old_launcher
    raw=registry_fixture(payload)
    raw['version']=2
    raw['runtimes'][0]['launcherDigest']=old_launcher
    raw['runtimes'][0]['admitNew']=False
    registry=RuntimeRegistry(raw)
    parsed=validate_receipt(payload)
    with pytest.raises(ValueError,match='approved'):
        registry.resolve('python',parsed,'unit',for_admission=True)
    snapshot=registry.replay_snapshots('unit')[runtime_registry.runtime_key('python',parsed,'unit')]
    assert snapshot.registration.launcher_digest==old_launcher
    assert snapshot.toolchain.container_contract=='measured-container-v1'
    assert snapshot.container.name=='measured-container-v1'
    record=dict(version=1,phase='run',exitCode=0,failureReason=None,cpuUsec=100,
                wallNs=1000,peakMemoryBytes=4096,oomKills=0,outputBytes=0,treeReaped=True)
    assert snapshot.container.decode_report(json.dumps(record),'run',parsed.run)==record
    # A historical container protocol is replay-only even if an operator
    # accidentally pairs it with the current launcher in a v1 registry.
    unsafe=payload_fixture()
    unsafe['judge_contract']['profile']['toolchainProfile']='cpython-pyc-v1'
    unsafe_profile=validate_receipt(unsafe)
    with pytest.raises(ValueError,match='approved'):
        RuntimeRegistry(registry_fixture(unsafe)).resolve(
            'python',unsafe_profile,'unit',for_admission=True)


def test_tampered_or_missing_toolchain_adapter_cannot_be_preclaimed(monkeypatch):
    from app.services import judge_toolchain_catalog as catalog
    payload=payload_fixture()
    registry=RuntimeRegistry(registry_fixture(payload))
    key=runtime_registry.runtime_key('python',validate_receipt(payload),'unit')
    altered=replace(catalog.trusted_adapter('python',TOOLCHAINS['python']),source_name='changed.py')
    entries=dict(catalog.ADAPTERS) | {('python',TOOLCHAINS['python']):altered}
    monkeypatch.setattr(catalog,'ADAPTERS',entries)
    monkeypatch.setattr(runtime_registry,'ADAPTERS',entries)
    assert key not in registry.replay_snapshots('unit')
    with pytest.raises(ValueError,match='recipe changed'):
        registry.resolve('python',validate_receipt(payload),'unit')


def test_missing_replay_only_adapter_does_not_hide_current_registration():
    payload=payload_fixture()
    current=registry_fixture(payload)['runtimes'][0] | {'admitNew':True}
    old=current | {'toolchainProfile':'cpython-removed-v0','admitNew':False}
    registry=RuntimeRegistry({'version':2,'runtimes':[old,current]})
    profile=validate_receipt(payload)
    snapshots=registry.replay_snapshots('unit')
    assert runtime_registry.runtime_key('python',profile,'unit') in snapshots
    old_profile=profile.model_copy(update={'toolchain_profile':'cpython-removed-v0'})
    assert runtime_registry.runtime_key('python',old_profile,'unit') not in snapshots
    with pytest.raises(ValueError,match='Unknown trusted'):
        registry.resolve('python',old_profile,'unit')
    with pytest.raises(ValueError):
        RuntimeRegistry({'version':2,'runtimes':[old | {'admitNew':True},current]})


def test_artifact_v1_source_is_verified_before_claim_and_snapshot_retains_functions(tmp_path,monkeypatch):
    from app.services import judge_artifact_contracts as contracts
    payload=payload_fixture()
    registry=RuntimeRegistry(registry_fixture(payload))
    profile=validate_receipt(payload)
    key=runtime_registry.runtime_key('python',profile,'unit')
    snapshot=registry.replay_snapshots('unit')[key]
    assert snapshot.artifact.source_digest==contracts.V1_SHA256
    corrupted=tmp_path/'judge_artifact_contract_v1.py'
    corrupted.write_bytes(b'print("untrusted")\n')
    monkeypatch.setattr(contracts,'V1_SOURCE',corrupted)
    assert key not in registry.replay_snapshots('unit')
    with pytest.raises(ValueError,match='hash mismatch'):
        registry.resolve('python',profile,'unit')
    # The already selected in-process snapshot does not switch to new bytes.
    session=MeasuredSubmission(SimpleNamespace(labels={}),payload,None,'unit',snapshot=snapshot)
    assert session.artifact_contract is snapshot.artifact
    assert session.artifact_contract.archive_script()==snapshot.artifact.archive_script()
    corrupted.unlink()
    with pytest.raises(ValueError,match='unavailable'):
        contracts.verified_contract('bounded-tar-v1')


def test_container_v2_source_is_verified_before_claim_and_snapshot_retains_functions(tmp_path,monkeypatch):
    from app.services import judge_container_contracts as contracts
    payload=payload_fixture()
    registry=RuntimeRegistry(registry_fixture(payload))
    profile=validate_receipt(payload)
    key=runtime_registry.runtime_key('python',profile,'unit')
    snapshot=registry.replay_snapshots('unit')[key]
    assert snapshot.container.source_digest==contracts.V2_SHA256
    corrupted=tmp_path/'judge_container_contract_v2.py'
    corrupted.write_bytes(b'print("untrusted")\n')
    monkeypatch.setattr(contracts,'V2_SOURCE',corrupted)
    assert key not in registry.replay_snapshots('unit')
    with pytest.raises(ValueError,match='hash mismatch'):
        registry.resolve('python',profile,'unit')
    session=MeasuredSubmission(SimpleNamespace(labels={}),payload,None,'unit',snapshot=snapshot)
    assert session.container_contract is snapshot.container
    assert session.container_contract.create_options is snapshot.container.create_options
    assert session.container_contract.decode_report is snapshot.container.decode_report
    corrupted.unlink()
    with pytest.raises(ValueError,match='unavailable'):
        contracts.verified_contract('measured-container-v2')
    with pytest.raises(ValueError,match='Unknown trusted'):
        contracts.verified_contract('measured-container-v3')


def test_report_v2_source_is_verified_before_claim_and_snapshot_retains_parser(tmp_path,monkeypatch):
    from app.services import judge_supervisor_records as reports
    payload=payload_fixture()
    registry=RuntimeRegistry(registry_fixture(payload))
    profile=validate_receipt(payload)
    key=runtime_registry.runtime_key('python',profile,'unit')
    snapshot=registry.replay_snapshots('unit')[key]
    assert snapshot.container.report_source_digest==reports.V2_SHA256
    corrupted=tmp_path/'judge_supervisor_record_v2.py'
    corrupted.write_bytes(b'print("untrusted")\n')
    monkeypatch.setattr(reports,'V2_SOURCE',corrupted)
    assert key not in registry.replay_snapshots('unit')
    with pytest.raises(ValueError,match='hash mismatch'):
        registry.resolve('python',profile,'unit')
    # Already selected jobs retain their verified parser.
    record=report_fixture()
    assert snapshot.container.decode_report(json.dumps(record),'run',profile.run)==record
    corrupted.unlink()
    with pytest.raises(ValueError,match='unavailable'):
        reports.verified_contract('supervisor-record-v2')


def test_collection_v1_source_is_verified_before_claim_and_snapshot_retains_collector(tmp_path,monkeypatch):
    from app.services import judge_collection_contracts as collections
    payload=payload_fixture()
    registry=RuntimeRegistry(registry_fixture(payload))
    profile=validate_receipt(payload)
    key=runtime_registry.runtime_key('python',profile,'unit')
    snapshot=registry.replay_snapshots('unit')[key]
    assert snapshot.container.collection_source_digest==collections.V1_SHA256
    corrupted=tmp_path/'judge_collection_contract_v1.py'
    corrupted.write_bytes(b'print("untrusted")\n')
    monkeypatch.setattr(collections,'V1_SOURCE',corrupted)
    assert key not in registry.replay_snapshots('unit')
    with pytest.raises(ValueError,match='hash mismatch'):
        registry.resolve('python',profile,'unit')
    session=MeasuredSubmission(SimpleNamespace(labels={}),payload,None,'unit',snapshot=snapshot)
    assert session.container_contract.collect is snapshot.container.collect
    corrupted.unlink()
    with pytest.raises(ValueError,match='unavailable'):
        collections.verified_contract('measured-collection-v1')


def test_collection_v1_requires_bounded_accounted_output_and_root_reader(tmp_path):
    from app.services.judge_collection_contracts import verified_contract
    collect=verified_contract('measured-collection-v1').collect
    limits=StageLimits.model_validate(payload_fixture()['judge_contract']['profile']['run'])
    record=report_fixture()
    class Container:
        def __init__(self,out): self.out=out;self.calls=[]
        def exec_run(self,argv,*,user):
            self.calls.append((argv,user))
            return SimpleNamespace(exit_code=0,output=self.out if argv[-2]=='stdout' else b'')
    container=Container(b'ok')
    result=collect(container,record,'run',limits,None,tmp_path,'python')
    assert result['stdout']=='ok' and result['stderr']==''
    assert result['resource_usage'] is record
    assert len(container.calls)==2
    assert [call[0][-2] for call in container.calls]==['stdout','stderr']
    assert all(call[1]=='0:0' for call in container.calls)
    with pytest.raises(RuntimeError,match='accounting'):
        collect(Container(b'o'),record,'run',limits,None,tmp_path,'python')
    with pytest.raises(RuntimeError,match='bounded'):
        collect(Container(b'x'*(limits.output_bytes+1)),record,'run',limits,None,tmp_path,'python')


@pytest.mark.parametrize('phase',['compile','run'])
@pytest.mark.parametrize('contract_name,spec_version',[
    ('measured-container-v1',1),('measured-container-v2',2)])
def test_container_contract_has_exact_isolation_and_phase_protocol(tmp_path,phase,contract_name,spec_version):
    from app.services.judge_container_contracts import verified_contract
    contract=verified_contract(contract_name)
    limits=StageLimits.model_validate(payload_fixture()['judge_contract']['profile'][phase])
    options=contract.create_options(phase_id='a'*32,phase=phase,limits=limits,
        argv=['/usr/bin/python3','-I','/artifact/main.pyc'],language='python',
        layout='work-v1',inputs=tmp_path/'input',source=tmp_path/'source',
        artifact=tmp_path/'artifact',empty=tmp_path/'empty',
        image_digest='sha256:'+'1'*64,launcher_script='launcher-script',
        labels={'webcompiler.job':'job'})
    assert set(options)=={'image','entrypoint','command','detach','name','labels',
        'user','network_disabled','read_only','tmpfs','volumes','init','cgroupns',
        'ipc_mode','healthcheck','mem_limit','memswap_limit','nano_cpus',
        'pids_limit','ulimits','cap_drop','cap_add','security_opt','log_config',
        'environment'}
    assert options['image']=='sha256:'+'1'*64
    assert options['entrypoint']==['/usr/bin/python3','-I','-c']
    assert options['command']==['launcher-script'] and options['detach'] is True
    assert options['name']=='compiler-measured-'+'a'*32
    assert options['labels']=={'webcompiler.job':'job','webcompiler.phase':'a'*32}
    assert options['user']=='0:0' and options['network_disabled'] is True
    assert options['read_only'] is True and options['init'] is False
    assert options['cgroupns']=='private' and options['ipc_mode']=='none'
    assert options['healthcheck']=={'test':['NONE']}
    assert options['mem_limit']==options['memswap_limit']==limits.memory_bytes
    assert options['nano_cpus']==1000000000 and options['pids_limit']==limits.pids
    assert options['ulimits']==[{'Name':'nofile','Soft':64,'Hard':64}]
    assert options['cap_drop']==['ALL']
    assert options['cap_add']==['KILL','SETUID','SETGID']
    assert options['security_opt']==['no-new-privileges']
    assert options['log_config']=={'Type':'none','Config':{}}
    assert options['tmpfs']=={
        '/control':f'rw,noexec,nosuid,nodev,size={limits.output_bytes+65536},mode=0700',
        '/work':f'rw,exec,nosuid,nodev,size={limits.tmp_bytes},mode=1777'}
    assert options['volumes']=={
        str(tmp_path/'input'):{'bind':'/input','mode':'ro'},
        str(tmp_path/('source' if phase=='compile' else 'artifact')):{
            'bind':'/source' if phase=='compile' else '/artifact','mode':'ro'}}
    assert json.loads(options['environment']['JUDGE_PHASE_SPEC'])=={
        'version':spec_version,'phase':phase,'argv':['/usr/bin/python3','-I','/artifact/main.pyc'],
        'stdin':'/input/stdin','limits':limits.model_dump(by_alias=True)}


@pytest.mark.parametrize('language',list(TOOLCHAINS))
def test_fixed_compile_and_run_commands_have_no_user_interpolation(language):
    assert compile_argv(language)[0].startswith('/')
    assert run_argv(language)[0].startswith('/')
    assert '/source/' in ' '.join(compile_argv(language))
    assert any(arg=='/artifact' or arg.startswith('/artifact/') for arg in run_argv(language))


@pytest.mark.parametrize('field,value', [('policyId','../../escape'),('revision',True),('jobDeadlineMs',True),
    ('jobDeadlineMs',5000),('jobDeadlineMs',130000),('reservationBytes',1),('language','java'),
    ('policyHash','latest'),('testSuiteHash','sha256:'+'0'*64),('extra',1)])
def test_receipt_is_exact_and_never_recomputes_mutated_tests(field,value):
    payload=payload_fixture();payload['judge_contract'][field]=value
    with pytest.raises(ValueError): validate_receipt(payload)


def test_compile_requires_pid_and_artifact_space():
    payload=payload_fixture();payload['judge_contract']['profile'].pop('launcherDigest')
    with pytest.raises(ValueError,match='freeze'): validate_receipt(payload)
    payload=payload_fixture();payload['judge_contract']['profile']['compile']['tmpBytes']=0
    with pytest.raises(ValueError,match='artifact'): validate_receipt(payload)
    payload=payload_fixture();payload['judge_contract']['profile']['run']['pids']=1
    with pytest.raises(ValueError,match='PID'): validate_receipt(payload)


def test_frozen_receipt_remains_valid_after_live_service_ceiling_decreases(monkeypatch):
    payload=payload_fixture()  # Frozen 7-second deadline, accepted before setting drift.
    monkeypatch.setattr(settings,'EXECUTION_JOB_TIMEOUT_SECONDS',6)
    assert validate_receipt(payload).run.wall_ms==2000
    assert payload['judge_contract']['jobDeadlineMs']==7000


@pytest.mark.parametrize('size', [8192, 12288, 16*1024**2])
def test_bpp_compile_scratch_is_split_not_duplicated(size):
    from app.services.measured_judge import phase_tmpfs
    limits = StageLimits.model_validate({**payload_fixture()['judge_contract']['profile']['compile'], 'tmpBytes':size})
    mounts = phase_tmpfs('bpp', 'compile', limits)
    def budget(path): return int(next(part[5:] for part in mounts[path].split(',') if part.startswith('size=')))
    assert set(mounts) == {'/work','/tmp','/control'}
    assert budget('/work') + budget('/tmp') == size
    assert budget('/work') % 4096 == budget('/tmp') % 4096 == 0
    assert '/tmp' not in phase_tmpfs('bpp', 'run', limits)
    assert '/tmp' not in phase_tmpfs('python', 'compile', limits)


@pytest.mark.parametrize('size', [0, 1, 4096, 8193])
def test_bpp_bad_scratch_is_rejected_before_admission_or_execution(size):
    from app.services.measured_judge import phase_tmpfs
    limits = StageLimits.model_validate({**payload_fixture()['judge_contract']['profile']['compile'], 'tmpBytes':size})
    with pytest.raises(ValueError, match='scratch'): phase_tmpfs('bpp','compile',limits)
    profile = payload_fixture()['judge_contract']['profile']
    profile['toolchainProfile'] = TOOLCHAINS['bpp']; profile['compile']['tmpBytes'] = size
    registration = {k:profile[k] for k in ('runtimeId','runtimeVersion','imageDigest','workerClass','toolchainProfile','launcherDigest')}
    registry = RuntimeRegistry(dict(version=1,runtimes=[dict(language='bpp',**registration)]))
    with pytest.raises(ValueError, match='scratch'): registry.resolve('bpp',RuntimeLimits.model_validate(profile),'unit')


def test_bpp_old_toolchain_cannot_silently_receive_a_new_mount_contract():
    raw = registry_fixture(); raw['runtimes'][0].update(language='bpp',toolchainProfile='bpp-native-o1-v1')
    with pytest.raises(ValueError): RuntimeRegistry(raw)


def test_old_receipt_cannot_run_after_reenrolling_a_new_launcher():
    payload=payload_fixture();profile=RuntimeLimits.model_validate(payload['judge_contract']['profile'])
    profile.launcher_digest='sha256:'+'0'*64
    with pytest.raises(ValueError,match='launcher'):
        RuntimeRegistry(registry_fixture()).resolve('python',profile,'unit')


def test_archived_launcher_is_exact_replay_only_and_cached(tmp_path, monkeypatch):
    old=b"print('archived supervisor')\n"
    new=b"print('new supervisor')\n"
    old_digest='sha256:'+hashlib.sha256(old).hexdigest()
    active=tmp_path/'active.py';active.write_bytes(new)
    archive=tmp_path/'archive';archive.mkdir()
    old_file=archive/('sha256-'+old_digest[7:]+'.py');old_file.write_bytes(old)
    monkeypatch.setattr(runtime_registry,'LAUNCHER_PATH',active)
    monkeypatch.setattr(runtime_registry,'LAUNCHER_ARCHIVE_DIR',archive)
    payload=payload_fixture();payload['judge_contract']['profile']['launcherDigest']=old_digest
    profile=RuntimeLimits.model_validate(payload['judge_contract']['profile'])
    registration=registry_fixture(payload)['runtimes'][0]
    registration['launcherDigest']=old_digest
    replay_only=RuntimeRegistry({'version':2,'runtimes':[registration | {'admitNew':False}]})
    assert replay_only.resolve('python',profile,'unit').launcher_digest==old_digest
    with pytest.raises(ValueError,match='approved'):
        replay_only.resolve('python',profile,'unit',for_admission=True)
    session=MeasuredSubmission(None,payload,replay_only,'unit')
    assert session.launcher_script==old.decode()
    old_file.write_bytes(b"print('tampered supervisor')\n")
    assert session.launcher_script==old.decode()
    with pytest.raises(ValueError,match='hash mismatch'):
        MeasuredSubmission(None,payload,replay_only,'unit')
    old_file.unlink()
    with pytest.raises(ValueError,match='unavailable'):
        replay_only.resolve('python',profile,'unit')
    if sys.platform != 'win32':
        old_file.symlink_to(active)
        with pytest.raises(ValueError,match='unavailable'):
            replay_only.resolve('python',profile,'unit')


def test_archived_launcher_cannot_be_misconfigured_for_new_admission(tmp_path, monkeypatch):
    old=b"print('archived supervisor')\n"
    current=b"print('current supervisor')\n"
    old_digest='sha256:'+hashlib.sha256(old).hexdigest()
    active=tmp_path/'active.py';active.write_bytes(current)
    archive=tmp_path/'archive';archive.mkdir()
    (archive/('sha256-'+old_digest[7:]+'.py')).write_bytes(old)
    monkeypatch.setattr(runtime_registry,'LAUNCHER_PATH',active)
    monkeypatch.setattr(runtime_registry,'LAUNCHER_ARCHIVE_DIR',archive)
    payload=payload_fixture()
    payload['judge_contract']['profile']['launcherDigest']=old_digest
    profile=RuntimeLimits.model_validate(payload['judge_contract']['profile'])
    registration=registry_fixture(payload)['runtimes'][0] | {
        'launcherDigest':old_digest,'admitNew':True}
    registry=RuntimeRegistry({'version':2,'runtimes':[registration]})

    # Exact historical receipts remain replayable, but an operator typo cannot
    # admit new work with the current toolchain/container protocol and an old
    # supervisor protocol.
    assert registry.resolve('python',profile,'unit').launcher_digest==old_digest
    with pytest.raises(ValueError,match='approved'):
        registry.resolve('python',profile,'unit',for_admission=True)


def test_runtime_registry_distinguishes_historical_launcher_identity(tmp_path, monkeypatch):
    first=b"print('first')\n";second=b"print('second')\n"
    active=tmp_path/'active.py';active.write_bytes(second)
    archive=tmp_path/'archive';archive.mkdir()
    first_digest='sha256:'+hashlib.sha256(first).hexdigest()
    second_digest='sha256:'+hashlib.sha256(second).hexdigest()
    (archive/('sha256-'+first_digest[7:]+'.py')).write_bytes(first)
    monkeypatch.setattr(runtime_registry,'LAUNCHER_PATH',active)
    monkeypatch.setattr(runtime_registry,'LAUNCHER_ARCHIVE_DIR',archive)
    payload=payload_fixture()
    record=registry_fixture(payload)['runtimes'][0]
    old=record | {'launcherDigest':first_digest,'admitNew':False}
    current=record | {'launcherDigest':second_digest,'admitNew':True}
    registry=RuntimeRegistry({'version':2,'runtimes':[old,current]})
    for digest,admit in ((first_digest,False),(second_digest,True)):
        profile_data=deepcopy(payload['judge_contract']['profile'])
        profile_data['launcherDigest']=digest
        profile=RuntimeLimits.model_validate(profile_data)
        assert registry.resolve('python',profile,'unit').launcher_digest==digest
        if admit:
            assert registry.resolve('python',profile,'unit',for_admission=True).admit_new
        else:
            with pytest.raises(ValueError): registry.resolve('python',profile,'unit',for_admission=True)
    with pytest.raises(ValueError,match='Duplicate'):
        RuntimeRegistry({'version':2,'runtimes':[old,old]})
    with pytest.raises(ValueError,match='Invalid runtime registration'):
        RuntimeRegistry({'version':1,'runtimes':[old]})
    with pytest.raises(ValueError,match='Untrusted'):
        RuntimeRegistry({'version':2,'runtimes':[old | {'admitNew':1}]})


def test_tar_extracts_only_validated_regular_artifacts(tmp_path):
    data=archive_bytes([('Main.class',tarfile.REGTYPE,b'class'),('pkg/',tarfile.DIRTYPE,b''),('pkg/Child.class',tarfile.REGTYPE,b'child')])
    unpack_artifact(data,tmp_path,'java')
    assert (tmp_path/'pkg/Child.class').read_bytes()==b'child'
    for path in tmp_path.rglob('*'):
        if path.is_file(): path.chmod(0o600)


def test_unicode_java_artifacts_and_long_pax_leaf_names_preserve_bytes(tmp_path):
    names=['Main.class','Main$도우미.class','분류/계산기.class',
           '분류/'+'자료'*24+'.class','Main$𐐀.class']
    entries=[(name,tarfile.REGTYPE,('bytecode:'+name).encode()) for name in names]
    unpack_artifact(archive_bytes(entries,format=tarfile.PAX_FORMAT),tmp_path,'java')
    try:
        for name,_,expected in entries: assert (tmp_path/name).read_bytes()==expected
    finally:
        for path in tmp_path.rglob('*.class'): path.chmod(0o600)


def test_actual_java_unicode_inner_class_survives_collector_roundtrip(tmp_path):
    # Trusted, authored fixture only; not a sandbox or Linux resource benchmark.
    java,javac=shutil.which('java'),shutil.which('javac')
    if not java or not javac: pytest.skip('Existing Java tools are required; no installation')
    source=tmp_path/'Main.java';compiled=tmp_path/'compiled';restored=tmp_path/'restored'
    compiled.mkdir();restored.mkdir()
    source.write_text('public class Main { static class 도우미 { static int value(){return 42;} } '
        'public static void main(String[] args){System.out.println(도우미.value());} }',encoding='utf-8')
    subprocess.run([javac,'-encoding','UTF-8','--release','17','-d',str(compiled),str(source)],
                   check=True,capture_output=True,timeout=20)
    archived=subprocess.run([sys.executable,'-I','-c',artifact_archive_script(str(compiled))],
                            check=True,capture_output=True,timeout=5).stdout
    unpack_artifact(archived,restored,'java')
    try:
        assert (restored/'Main$도우미.class').read_bytes()==(compiled/'Main$도우미.class').read_bytes()
        result=subprocess.run([java,'-cp',str(restored),'Main'],check=True,capture_output=True,timeout=5)
        assert result.stdout.strip()==b'42'
    finally:
        for path in restored.rglob('*.class'): path.chmod(0o600)


@pytest.mark.parametrize('names',[
    ['Main.class','main.class'],['Main.class','Pkg/One.class','pkg/Two.class'],
    ['Main.class','Café.class','Cafe\u0301.class'],
    ['Main.class','분류/../탈출.class'],['Main.class','Main$\u202e.class'],
    ['Main.class','Main$\x00.class'],['Main.class','a'*241+'.class'],
    ['Main.class','자료'*40+'.class'],['Main.class','분류\\탈출.class'],
])
def test_unicode_pax_cannot_bypass_portable_path_checks(tmp_path,names):
    entries=[(name,tarfile.REGTYPE,b'fixture') for name in names]
    with pytest.raises(ValueError):
        unpack_artifact(archive_bytes(entries,format=tarfile.PAX_FORMAT),tmp_path,'java')
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('headers,global_headers',[
    ({'path':'../Main.class'},{}),({'mtime':'1.1'},{}),({'linkpath':'outside'},{}),
    ({'SCHILY.xattr.user.bad':'bad'},{}),({}, {'comment':'global'}),
])
def test_pax_extensions_other_than_validated_path_rejected(tmp_path,headers,global_headers):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w',format=tarfile.PAX_FORMAT,pax_headers=global_headers) as archive:
        info=tarfile.TarInfo('Main.class');info.size=1;info.pax_headers=headers
        archive.addfile(info,io.BytesIO(b'x'))
    with pytest.raises(ValueError): unpack_artifact(output.getvalue(),tmp_path,'java')
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('name,kind', [('../escape.class',tarfile.REGTYPE),('/escape.class',tarfile.REGTYPE),
    ('pkg//Bad.class',tarfile.REGTYPE),('pkg/./Bad.class',tarfile.REGTYPE),('NUL.class',tarfile.REGTYPE),
    ('C:Bad.class',tarfile.REGTYPE),('pkg\\Bad.class',tarfile.REGTYPE),('pkg./Bad.class',tarfile.REGTYPE),
    ('Bad.class',tarfile.SYMTYPE),('Bad.class',tarfile.LNKTYPE),('Bad.class',tarfile.CHRTYPE),('Bad.class',tarfile.FIFOTYPE),
    ('unexpected.py',tarfile.REGTYPE)])
def test_malicious_artifact_is_rejected_before_any_write(tmp_path,name,kind):
    data=archive_bytes([('Main.class',tarfile.REGTYPE,b'ok'),(name,kind,b'bad')])
    with pytest.raises(ValueError): unpack_artifact(data,tmp_path,'java')
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('entries',[
    [('Main.class',tarfile.REGTYPE,b'a'),('Main.class',tarfile.REGTYPE,b'b')],
    [('Main.class',tarfile.REGTYPE,b'a'),('Main.class/',tarfile.DIRTYPE,b'')],
    [('Main.class',tarfile.REGTYPE,b'a'),('Main.class/Child.class',tarfile.REGTYPE,b'b')],
    [('Main.class',tarfile.REGTYPE,b'a'),('Main.class/sub/',tarfile.DIRTYPE,b'')],
    [('Other.class',tarfile.REGTYPE,b'a')],
])
def test_duplicate_collision_and_missing_entry_artifact(tmp_path,entries):
    with pytest.raises(ValueError): unpack_artifact(archive_bytes(entries),tmp_path,'java')
    assert list(tmp_path.iterdir())==[]


def test_artifact_size_and_existing_host_content_are_not_overwritten(tmp_path,monkeypatch):
    from app.services import judge_artifact_contract_v1
    monkeypatch.setattr(judge_artifact_contract_v1,'ARTIFACT_BYTES',2)
    with pytest.raises(ValueError,match='cap'): unpack_artifact(archive_bytes([('program',tarfile.REGTYPE,b'abc')]),tmp_path,'c')
    (tmp_path/'program').write_bytes(b'user')
    with pytest.raises(ValueError,match='empty'): unpack_artifact(archive_bytes([('program',tarfile.REGTYPE,b'a')]),tmp_path,'c')
    assert (tmp_path/'program').read_bytes()==b'user'


@pytest.mark.parametrize('field,value',[('version',True),('treeReaped',False),('exitCode',True),('oomKills',1),
    ('cpuUsec',1000000),('wallNs',2000000000),('peakMemoryBytes',0),('outputBytes',1025),('extra',1)])
def test_report_requires_trusted_complete_resource_evidence(field,value):
    record=report_fixture();record[field]=value
    limits=StageLimits.model_validate(payload_fixture()['judge_contract']['profile']['run'])
    with pytest.raises(ValueError): decode_report(json.dumps(record),'run',limits)


def test_report_accepts_proven_oom_even_with_zero_parent_exit():
    record=report_fixture();record.update(oomKills=1,failureReason='memory_limit_exceeded')
    limits=StageLimits.model_validate(payload_fixture()['judge_contract']['profile']['run'])
    assert decode_report(json.dumps(record),'run',limits)==record


def test_report_rejects_mle_without_kernel_oom_evidence():
    record=report_fixture();record.update(oomKills=0,failureReason='memory_limit_exceeded')
    limits=StageLimits.model_validate(payload_fixture()['judge_contract']['profile']['run'])
    with pytest.raises(ValueError,match='without an OOM kill'):
        decode_report(json.dumps(record),'run',limits)


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_inflight_collection():
    entered=threading.Event();release=threading.Event();events=[]
    def collect():
        entered.set();assert release.wait(3);events.append('write');return 42
    task=asyncio.create_task(finish_io(collect))
    assert await asyncio.to_thread(entered.wait,2)
    task.cancel();await asyncio.sleep(.01);task.cancel();await asyncio.sleep(.01)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError): await task
    events.append('cleanup')
    assert events==['write','cleanup']


@pytest.mark.asyncio
async def test_cancelled_stream_acquisition_closes_late_stream():
    entered=threading.Event();release=threading.Event();closed=[]
    def acquire(): entered.set();assert release.wait(3);return 'stream'
    task=asyncio.create_task(finish_io(acquire,on_cancel=closed.append))
    assert await asyncio.to_thread(entered.wait,2)
    task.cancel();release.set()
    with pytest.raises(asyncio.CancelledError): await task
    assert closed==['stream']


@pytest.mark.asyncio
async def test_submission_compiles_once_and_each_case_uses_frozen_artifact():
    payload=payload_fixture();session=MeasuredSubmission(None,payload,RuntimeRegistry(registry_fixture()),'unit')
    session._phase=AsyncMock(return_value=dict(exit_code=0,failure_reason=None))
    with pytest.raises(ValueError): await session.run(source_code=payload['code'],language='python',stdin='x')
    await session._execute(mode='compile',source_code=payload['code'],language='python')
    await session.run(source_code=payload['code'],language='python',stdin='sample')
    await session.run(source_code=payload['code'],language='python',stdin='secret')
    with pytest.raises(ValueError): await session._execute(mode='compile',source_code=payload['code'],language='python')
    with pytest.raises(ValueError): await session.run(source_code='changed',language='python',stdin='secret')
    assert [call.args[0] for call in session._phase.call_args_list]==['compile','run','run']
    assert [call.args[3] for call in session._phase.call_args_list]==['','sample','secret']


@pytest.mark.asyncio
async def test_measured_session_uses_common_grading_without_hidden_output_disclosure():
    payload=payload_fixture();events=[]
    class Session:
        async def __aenter__(self): events.append('enter');return self
        async def __aexit__(self,*args): events.append('exit')
        async def _execute(self,**kwargs):
            events.append('compile')
            return dict(exit_code=0,stdout='',stderr='',resource_usage={**report_fixture(),'phase':'compile','outputBytes':0})
        async def run(self,**kwargs):
            events.append(kwargs['stdin'])
            return dict(exit_code=0,stdout='42' if kwargs['stdin']=='sample' else 'HIDDEN_WRONG',stderr='',resource_usage=report_fixture())
    result=await judge_code(SimpleNamespace(measured_submission=lambda _:Session()),payload)
    assert result['verdict']=='wrong_answer'
    assert events==['enter','compile','sample','secret','exit']
    assert 'secret' not in json.dumps(result) and 'HIDDEN_WRONG' not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('language',['python','bpp'])
@pytest.mark.parametrize('removal',['normal','already-gone','failure','ownership-lost','input-ownership-lost'])
@pytest.mark.parametrize('launcher_mode',['current','archived'])
async def test_real_adapter_uses_three_separate_bounded_containers_and_cleans_files(tmp_path,monkeypatch,removal,language,launcher_mode):
    from app.services.compiler import DockerCompilerRunner
    payload=payload_fixture();created=[];events=[]
    payload['language']=payload['judge_contract']['language']=language
    payload['judge_contract']['profile']['toolchainProfile']=TOOLCHAINS[language]
    registry=registry_fixture(payload);registry['runtimes'][0]['language']=language
    launcher_script=runtime_registry.launcher_source(payload['judge_contract']['profile']['launcherDigest'])
    if launcher_mode=='archived':
        archive=tmp_path/'archive';archive.mkdir()
        digest=payload['judge_contract']['profile']['launcherDigest']
        (archive/('sha256-'+digest[7:]+'.py')).write_bytes(launcher_script.encode('utf-8'))
        active=tmp_path/'new-launcher.py';active.write_text("print('replacement')\n",encoding='utf-8')
        monkeypatch.setattr(runtime_registry,'LAUNCHER_PATH',active)
        monkeypatch.setattr(runtime_registry,'LAUNCHER_ARCHIVE_DIR',archive)
        registry['version']=2;registry['runtimes'][0]['admitNew']=False
    source_name='main.bpp' if language=='bpp' else 'main.py'
    artifact_name='program' if language=='bpp' else 'main.pyc'
    registry_file=tmp_path/'registry.json';registry_file.write_text(json.dumps(registry),encoding='utf-8')
    monkeypatch.setattr(settings,'JUDGE_RUNTIME_REGISTRY',str(registry_file))
    monkeypatch.setattr(settings,'JUDGE_WORKER_CLASS','unit')
    work=tmp_path/'work';monkeypatch.setattr(settings,'SANDBOX_WORKDIR_ROOT',str(work))
    class Stream:
        def __init__(self,record): self.record=record
        def __iter__(self): yield (json.dumps(self.record).encode()+b'\n',None)
        def close(self): events.append('stream closed')
    class Container:
        def __init__(self,options,index):
            self.index=index;self.options=options
            self.out=[b'',b'42\n',b'84\n'][index]
            self.phase='compile' if index==0 else 'run'
        def attach(self,**options):
            assert options==dict(stream=True,logs=False,demux=True)
            record=report_fixture();record.update(phase=self.phase,outputBytes=len(self.out))
            return Stream(record)
        def start(self): events.append(('start',self.index))
        def remove(self,force):
            from docker.errors import APIError,NotFound
            assert force;events.append(('remove',self.index))
            if self.index==1 and removal=='failure': raise APIError('synthetic removal failure')
            if self.index==1 and removal=='already-gone': raise NotFound('synthetic already gone')
        def exec_run(self,args,user):
            assert user=='0:0'
            if args[-2]=='stdout': return SimpleNamespace(exit_code=0,output=self.out)
            if args[-2]=='stderr': return SimpleNamespace(exit_code=0,output=b'')
            assert self.phase=='compile'
            return SimpleNamespace(exit_code=0,output=archive_bytes([(artifact_name,tarfile.REGTYPE,b'fixture bytecode')]))
    def create(**options):
        index=len(created)
        assert options['command']==[launcher_script]
        assert options['image']==payload['judge_contract']['profile']['imageDigest']
        assert options['network_disabled'] and options['read_only']
        assert options['ipc_mode']=='none' and options['cgroupns']=='private' and options['init'] is False
        assert options['healthcheck']=={'test':['NONE']}
        assert options['mem_limit']==options['memswap_limit']==128*1024**2
        assert options['nano_cpus']==1000000000 and options['pids_limit']==16
        assert options['cap_drop']==['ALL'] and set(options['cap_add'])=={'KILL','SETUID','SETGID'}
        if language=='bpp' and index==0:
            scratch=[]
            for mount in ('/tmp','/work'):
                scratch.append(int(next(flag[5:] for flag in options['tmpfs'][mount].split(',') if flag.startswith('size='))))
            assert all(size%4096==0 for size in scratch)
            assert sum(scratch)==payload['judge_contract']['profile']['compile']['tmpBytes']
        else:
            assert '/tmp' not in options['tmpfs']
        mounts={value['bind']:Path(path) for path,value in options['volumes'].items()}
        # At creation only this phase's input directory may remain, including
        # between compile and run. No suite-sized spool on the worker disk.
        phase_root=mounts['/input'].parent
        assert list(phase_root.glob('input-*'))==[mounts['/input']]
        assert len(list(phase_root.glob('empty-*')))==1
        assert all(value['mode']=='ro' for value in options['volumes'].values())
        assert (mounts['/input']/'stdin').read_text(encoding='utf-8')==['','sample','secret'][index]
        if index==0:
            assert set(mounts)=={'/input','/source'}
            assert (mounts['/source']/source_name).read_text(encoding='utf-8')==payload['code']
        else:
            assert set(mounts)=={'/input','/artifact'}
            assert (mounts['/artifact']/artifact_name).read_bytes()==b'fixture bytecode'
        result=Container(options,index);created.append(result);return result
    connections=[]
    client=SimpleNamespace(images=SimpleNamespace(get=lambda digest:SimpleNamespace(id=digest)),containers=SimpleNamespace(create=create),close=lambda:events.append('client closed'))
    main_thread=threading.get_ident()
    def connect():
        assert threading.get_ident()!=main_thread
        connections.append(1)
        return client
    runner=DockerCompilerRunner(client_factory=connect)
    if removal in ('ownership-lost','input-ownership-lost'):
        original_cleanup=runner._cleanup
        second_phase_cleanups=0
        async def cleanup(action):
            nonlocal second_phase_cleanups
            if len(created)==2:
                second_phase_cleanups+=1
                if removal=='ownership-lost' or second_phase_cleanups>1: return False
            return await original_cleanup(action)
        monkeypatch.setattr(runner,'_cleanup',cleanup)
    if removal in ('failure','ownership-lost','input-ownership-lost'):
        from docker.errors import APIError
        with pytest.raises((APIError,RuntimeError)):
            await judge_code(runner,payload)
        assert len(created)==2  # Never begin hidden case after ambiguous cleanup.
        assert len(list(work.glob('*/input-*')))==1
        assert events.count('stream closed')==2 and events[-1]=='client closed'
        # These are fake containers. Make test-owned readonly fixtures removable
        # for pytest; production retains this directory for fenced recovery.
        for path in work.rglob('*'):
            path.chmod(0o700 if path.is_dir() else 0o600)
        return
    result=await judge_code(runner,payload)
    assert result['verdict']=='accepted'
    assert len(created)==3 and len({c.options['name'] for c in created})==3
    assert [e for e in events if isinstance(e,tuple)]==[('start',0),('remove',0),('start',1),('remove',1),('start',2),('remove',2)]
    assert events.count('stream closed')==3
    assert connections==[1] and events[-1]=='client closed'
    assert list(work.iterdir())==[]


@pytest.mark.asyncio
async def test_host_chmod_and_removal_never_run_after_lease_guard_denies(tmp_path):
    payload=payload_fixture()
    runner=SimpleNamespace(_cleanup=AsyncMock(return_value=False))
    session=MeasuredSubmission(runner,payload,RuntimeRegistry(registry_fixture()),'unit')
    session.directory=tmp_path/'owned';session.directory.mkdir()
    artifact=session.directory/'readonly';artifact.write_bytes(b'compiled');artifact.chmod(0o444)
    before=artifact.stat().st_mode
    try:
        with pytest.raises(RuntimeError,match='cleanup'): await session._remove_host_directory(session.directory)
        assert artifact.read_bytes()==b'compiled' and artifact.stat().st_mode==before
        with pytest.raises(ValueError,match='outside'): await session._remove_host_directory(tmp_path)
    finally: artifact.chmod(0o600)
