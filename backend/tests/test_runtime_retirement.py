"""Crash/retry boundaries of the actual journal plus inventory state machine."""
from copy import deepcopy
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from tests.test_runtime_binding import binding
from tests.test_runtime_inventory import inventory
from tests.test_edge_deploy import edge
from runtime_retirement import Retirement


def exited(identity,containers,networks):
    item=containers[identity]
    item['State'].update(Running=False,Status='exited',Pid=0,ExitCode=0,FinishedAt='2026-09-10T00:01:00Z')
    item['NetworkSettings']['Ports']={}
    for name,endpoint in item['NetworkSettings']['Networks'].items():
        endpoint.update(EndpointID='',IPAddress='',GlobalIPv6Address='')
        if name in networks:
            networks[name]['Containers'].pop(identity,None)


@pytest.fixture
def retirement(binding,inventory,monkeypatch,request):
    bound,db,reports,containers,reads=binding
    deploy,release,unused,unused_containers,networks,calls=inventory
    cold=getattr(request,'param',False)
    retained=None if cold else deploy.config.release('green','b'*40)
    if cold:
        deploy.store.write(deploy.store.path/'state'/'candidate.json',{'version':1,'release':asdict(release)})
        tx=edge.Transaction(deploy.store,lambda _:True,lambda _:True)
        with pytest.raises(edge.EdgeError,match='committed route restored'):
            tx.switch(release,preflight=lambda _:True,postflight=lambda _:False)
        monkeypatch.setattr(deploy.runtime,'preflight',lambda:{'State':{'Running':True}})
        monkeypatch.setattr(deploy.runtime,'observe',lambda:deploy.store.expected(None))
    else:
        deploy.store.commit(release)
        deploy.store.intent(retained,'switch')
        deploy.store.commit(retained)
        deploy.store.clear_intent()
    monkeypatch.setattr(deploy,'verify',lambda target,edge=False:target==retained and edge)
    events=[]
    sandbox=SimpleNamespace(empty=lambda:True)
    subject=None
    def fence(identity,runtime):
        saved=json.loads(subject.path.read_text())
        assert saved['phase']=='fencing' and not saved['requested']
        events.append(('fence',identity))
    def stop(identity,*,signal):
        saved=json.loads(subject.path.read_text())
        assert saved['phase']=='stopping' and identity in saved['requested']
        events.append(('stop',identity,signal))
        exited(identity,containers,networks)
        return True
    subject=Retirement(deploy,release,binding=bound,sandboxes=sandbox,stop=stop,fence=fence)
    return subject,db,containers,networks,events


def quiesce(db):
    for key in ('active_http','active_websockets','active_claims'): db[key]=0
    for process in db['processes']:
        for key in ('active_http','active_websockets','active_claims'):
            if key in process: process[key]=0
    for lane in db['lanes']: lane['active_claims']=0


def test_durable_fence_precedes_wait_and_no_active_work_is_stopped(retirement):
    subject,db,containers,networks,events=retirement
    before=deepcopy(db)
    assert subject.step()['phase']=='draining'
    assert subject.step()['phase']=='draining'
    assert [e[0] for e in events]==['fence']
    assert db==before
    assert list((subject.store.path/'state'/'drains').iterdir())


def test_quiescent_retirement_preserves_inventory_then_consumes_only_own_marker(retirement):
    subject,db,containers,networks,events=retirement
    quiesce(db)
    before=subject.inventory.path.read_bytes()
    for _ in range(10):
        result=subject.step()
        if result['phase']=='retired': break
    assert result['phase']=='retired'
    stop_events=[e for e in events if e[0]=='stop']
    roles=[containers[e[1]]['Config']['Labels']['com.docker.compose.service'] for e in stop_events]
    assert roles==['frontend','proxy-controller','api-proxy','backend','backend','worker','pgbouncer']
    assert all(e[2]==('SIGQUIT' if role in ('frontend','api-proxy') else 'SIGTERM')
               for e,role in zip(stop_events,roles))
    assert json.loads(subject.path.read_text())['phase']=='retired'
    assert subject.inventory.path.read_bytes()==before
    assert not list((subject.store.path/'state'/'drains').iterdir())
    assert subject.deployment.retire_pending()=={'phase':'retired','remaining':0}


@pytest.mark.parametrize('ack',[True,False])
def test_command_ack_or_timeout_does_not_prove_exit(retirement,ack):
    subject,db,containers,networks,events=retirement
    quiesce(db)
    requested=[]
    subject.stop=lambda identity,**kwargs:requested.append(identity) or ack
    assert subject.step()['phase']=='stopping'
    assert subject.step()['phase']=='stopping'
    assert len(set(requested))==1
    assert list((subject.store.path/'state'/'drains').iterdir())


def test_crash_after_stop_effect_before_return_resumes_from_actual_state(retirement):
    subject,db,containers,networks,events=retirement
    quiesce(db)
    stop=subject.stop
    def interrupted(identity,**kwargs):
        stop(identity,**kwargs)
        raise RuntimeError('simulated client loss')
    subject.stop=interrupted
    with pytest.raises(RuntimeError,match='client loss'): subject.step()
    first=json.loads(subject.path.read_text())['requested'][0]
    subject.stop=stop
    assert subject.step()['phase']=='stopping'
    stopped=[e[1] for e in events if e[0]=='stop']
    assert stopped.count(first)==1 and len(stopped)==2


def test_crash_after_certificate_before_marker_cleanup_is_repeatable(retirement,monkeypatch):
    subject,db,containers,networks,events=retirement
    quiesce(db)
    cleanup=subject._finish_markers
    monkeypatch.setattr(subject,'_finish_markers',lambda _:(_ for _ in ()).throw(RuntimeError('crash')))
    with pytest.raises(RuntimeError,match='crash'):
        for _ in range(10): subject.step()
    assert json.loads(subject.path.read_text())['phase']=='retired'
    count=len(events)
    monkeypatch.setattr(subject,'_finish_markers',cleanup)
    assert subject.step()['phase']=='retired'
    assert len(events)==count


@pytest.mark.parametrize('case',['active-release','pending-routing','unhealthy-retained','sandbox',
    'unknown-marker','wrong-retained','unrequested-death'])
def test_refuses_uncertain_retirement_before_any_stop(retirement,monkeypatch,case):
    subject,db,containers,networks,events=retirement
    quiesce(db)
    if case=='active-release': subject.store.commit(subject.release)
    elif case=='pending-routing': subject.store.intent(subject.release,'switch')
    elif case=='unhealthy-retained': monkeypatch.setattr(subject.deployment,'verify',lambda *a,**kw:False)
    elif case=='sandbox': subject.sandboxes.empty=lambda:False
    elif case=='unknown-marker': subject.store.write(subject.store.path/'state'/'drains'/'unknown.json',{})
    elif case=='wrong-retained': subject.store.commit(subject.deployment.config.release('green','c'*40))
    else: exited(next(iter(containers)),containers,networks)
    with pytest.raises(edge.EdgeError): subject.step()
    assert not any(e[0]=='stop' for e in events)


@pytest.mark.parametrize('mutation',['restart','image','configuration','wrong-request','kill','new-start','boolean-pid'])
def test_partial_stop_does_not_hide_identity_drift(retirement,mutation):
    subject,db,containers,networks,events=retirement
    quiesce(db)
    subject.step()
    identity=events[-1][1]
    if mutation=='restart': containers[identity]['RestartCount']+=1
    elif mutation=='image': containers[identity]['Image']='sha256:'+'e'*64
    elif mutation=='configuration': containers[identity]['Config']['Env'].append('NEW_FIELD=1')
    elif mutation=='kill': containers[identity]['State']['ExitCode']=137
    elif mutation=='new-start': containers[identity]['State']['StartedAt']='2026-09-10T00:00:02Z'
    elif mutation=='boolean-pid': containers[identity]['State']['Pid']=False
    else:
        state=json.loads(subject.path.read_text())
        state['requested']=[]
        subject.store.write(subject.path,state)
    count=len(events)
    with pytest.raises(edge.EdgeError): subject.step()
    assert len(events)==count


def test_duplicate_target_marker_is_rejected_before_effect(retirement):
    subject,db,containers,networks,events=retirement
    quiesce(db)
    path=next((subject.store.path/'state'/'drains').iterdir())
    value=subject.store.read_json(path)
    value['retire']*=2
    subject.store.write(path,value)
    with pytest.raises(edge.EdgeError,match='Duplicate runtime'): subject.step()
    assert events==[]


@pytest.mark.parametrize('retirement',[True],indirect=True)
def test_failed_first_candidate_retires_only_after_closed_route_and_quiescence(retirement):
    subject,db,containers,networks,events=retirement
    assert subject.store.committed() is None
    with pytest.raises(edge.EdgeError,match='drain/retirement'):
        subject.deployment.candidate('blue',subject.release.sha)
    assert subject.step()['phase']=='draining'
    assert not any(e[0]=='stop' for e in events)
    quiesce(db)
    for _ in range(10):
        result=subject.step()
        if result['phase']=='retired': break
    assert result['phase']=='retired'
    assert json.loads(subject.path.read_text())['retained'] is None
    assert subject.store.committed() is None
    assert subject.deployment.reserved() is None
    assert subject.deployment.retire_pending()=={'phase':'retired','remaining':0}
    replacement=subject.deployment.candidate('blue',subject.release.sha)
    assert replacement.runtime_id!=subject.release.runtime_id


@pytest.mark.parametrize('retirement',[True],indirect=True)
@pytest.mark.parametrize('case',['no-edge','stopped-edge','wrong-ack','config-drift','open-port','pending'])
def test_cold_retirement_requires_owned_closed_configuration_before_fencing(retirement,monkeypatch,case):
    subject,db,containers,networks,events=retirement
    quiesce(db)
    if case=='no-edge': monkeypatch.setattr(subject.deployment.runtime,'preflight',lambda:None)
    elif case=='stopped-edge': monkeypatch.setattr(subject.deployment.runtime,'preflight',lambda:{'State':{'Running':False}})
    elif case=='wrong-ack': monkeypatch.setattr(subject.deployment.runtime,'observe',lambda:subject.store.expected(subject.release))
    elif case=='config-drift': subject.store.install(subject.release)
    elif case=='open-port': monkeypatch.setattr(subject.deployment,'verify',lambda *a,**kw:False)
    else: subject.store.intent(subject.release,'switch')
    with pytest.raises(edge.EdgeError): subject.step()
    assert events==[] and not subject.path.exists()
    assert subject.deployment.reserved()==subject.release
    assert list((subject.store.path/'state'/'drains').iterdir())


@pytest.mark.parametrize('retirement',[True],indirect=True)
def test_cold_certificate_cleanup_retry_never_reuses_retired_reservation(retirement,monkeypatch):
    subject,db,containers,networks,events=retirement
    quiesce(db)
    original=subject._finish_markers
    monkeypatch.setattr(subject,'_finish_markers',lambda _:(_ for _ in ()).throw(RuntimeError('cleanup crash')))
    with pytest.raises(RuntimeError,match='cleanup crash'):
        for _ in range(10): subject.step()
    assert subject.deployment.reserved()==subject.release
    count=len(events)
    monkeypatch.setattr(subject,'_finish_markers',original)
    assert subject.step()['phase']=='retired' and len(events)==count
    assert subject.deployment.candidate('blue',subject.release.sha).runtime_id!=subject.release.runtime_id
