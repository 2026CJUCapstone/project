"""Synthetic metrics, privacy and fenced persistence; not real cgroup evidence."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime,timedelta
import json
from types import SimpleNamespace

import pytest
from httpx import ASGITransport,AsyncClient

from app.main import app
from app.models import database as m
from app.services.judge_metrics import JudgeMetrics, public_usage, validate_report
from app.services.judging import judge_code
from app.services.execution_results import publish_result
from app.services.durable_queue import DurableQueue
from tests.test_measured_judge import payload_fixture,report_fixture
from tests.test_durable_queue import replicas
from tests.test_contests import env,headers


def phase_result(phase='run',**usage):
    report={**report_fixture(),'phase':phase,**usage}
    return dict(exit_code=report['exitCode'],failure_reason=report['failureReason'],stdout='42',stderr='',
                execution_phase=phase,resource_usage=report)


def full_report(payload):
    collector=JudgeMetrics(payload)
    collector.add(phase_result('compile',cpuUsec=1200),phase='compile')
    collector.add(phase_result(cpuUsec=3000,wallNs=4000000,peakMemoryBytes=1024),phase='sample',index=1,verdict='accepted')
    collector.add(phase_result(cpuUsec=5000,wallNs=6000000,peakMemoryBytes=2048),phase='grading',index=1,verdict='accepted')
    return collector.finish()


def test_public_projection_totals_maxima_and_no_hidden_details():
    report=full_report(payload_fixture());summary=public_usage(report)
    assert summary['compile']['cpuMs']==1.2
    assert summary['run']==dict(cpuMs=8,wallMs=10,maxCpuMs=5,maxWallMs=6,peakMemoryBytes=2048)
    assert public_usage(None) is None
    for forbidden in ('cases','testSuiteHash','policyHash','oomKills','pidLimitHits','outputBytes','grading','secret'):
        assert forbidden not in json.dumps(summary)


def test_pid_limit_evidence_is_preserved_privately_but_redacted_publicly():
    payload=payload_fixture();collector=JudgeMetrics(payload)
    collector.add(phase_result('compile'),phase='compile')
    limited=phase_result(failureReason='process_limit_exceeded',pidLimitHits=1)
    collector.add(limited,phase='sample',index=1,verdict='process_limit_exceeded')
    report=collector.finish()
    assert report['cases'][0]['usage']['pidLimitHits']==1
    assert report['cases'][0]['verdict']=='process_limit_exceeded'
    assert 'pidLimitHits' not in json.dumps(public_usage(report))


@pytest.mark.parametrize('change',['missing','bool','negative','identity','order','phase','unreaped','extra'])
def test_report_rejects_malformed_or_rebound_measurement(change):
    payload=payload_fixture();report=full_report(payload)
    if change=='missing': report['compile']=None
    elif change=='bool': report['compile']['cpuUsec']=True
    elif change=='negative': report['compile']['wallNs']=-1
    elif change=='identity': report['identity']['revision']=2
    elif change=='order': report['cases'].reverse()
    elif change=='phase': report['cases'][0]['usage']['phase']='compile'
    elif change=='unreaped': report['compile']['treeReaped']=False
    else: report['cases'][0]['usage']['stdout']='secret-input'
    with pytest.raises(ValueError): validate_report(report,payload)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['compile','first_case','none'])
async def test_measured_early_returns_keep_only_completed_measurements(failure):
    payload=payload_fixture();count=0
    class Phase:
        async def _execute(self,**kwargs):
            return phase_result('compile',exitCode=1 if failure=='compile' else 0)
        async def run(self,**kwargs):
            nonlocal count
            count+=1
            value=phase_result()
            value['stdout']='wrong' if failure=='first_case' else ('42' if count==1 else '84')
            return value
    @asynccontextmanager
    async def measured(_): yield Phase()
    result=await judge_code(SimpleNamespace(measured_submission=measured),payload,contest=True)
    assert len(result['_resource_report']['cases'])=={'compile':0,'first_case':1,'none':2}[failure]
    assert result['verdict']=={'compile':'compile_error','first_case':'wrong_answer','none':'accepted'}[failure]
    if failure=='compile': assert public_usage(result['_resource_report'])['run'] is None


@pytest.mark.asyncio
async def test_missing_metrics_and_unresolved_legacy_fail_closed():
    payload=payload_fixture()
    class Phase:
        async def _execute(self,**kwargs): return dict(exit_code=0,stdout='',stderr='')
        async def run(self,**kwargs): return dict(exit_code=0,stdout='wrong',stderr='')
    @asynccontextmanager
    async def measured(_): yield Phase()
    with pytest.raises(ValueError): await judge_code(SimpleNamespace(measured_submission=measured),payload)
    payload.pop('judge_contract')
    with pytest.raises(RuntimeError, match='exact measured'):
        await judge_code(Phase(),payload)


def seed(factory,kind='practice'):
    payload=payload_fixture();payload.update(practice_points=5,problem_id='p')
    queue=DurableQueue(factory,on_terminal=publish_result,lease_seconds=10)
    job_id=queue.enqueue(owner_key='owner',request_id='metrics',kind=kind,payload=payload)
    with factory() as db:
        db.add(m.User(id='owner',username='owner',hashed_password='unused'))
        db.flush()
        db.add(m.Problem(id='p',creator_id='owner',title='Fixture',description='Fixture',difficulty='iron5',tags=[],test_cases={}))
        db.flush()
        if kind=='practice':
            row=m.Submission(id='s',execution_job_id=job_id,problem_id='p',code='private source',language='python',status='queued',verdict='pending')
        else:
            db.add(m.Contest(id='c',creator_id='owner',title='Fixture',description='',published=False,
                             starts_at=datetime(2030,1,1),ends_at=datetime(2030,1,2)))
            db.flush()
            db.add(m.ContestProblem(id='cp',contest_id='c',problem_id='p',position=0,points=1,snapshot={},is_new=True))
            db.flush()
            row=m.ContestSubmission(id='s',execution_job_id=job_id,contest_id='c',contest_problem_id='cp',user_id='owner',
                request_id='r',code='private source',language='python',status='queued',verdict='pending',received_at=datetime(2030,1,1))
        db.add(row);db.commit()
    return queue,job_id,payload,m.Submission if kind=='practice' else m.ContestSubmission


@pytest.mark.parametrize('kind',['practice','contest'])
def test_finish_metrics_survive_restart_and_are_fenced_atomic_and_redacted(replicas,kind):
    queue,job_id,payload,model=seed(replicas[0],kind)
    at=datetime(2030,1,1);claim=queue.claim(at=at)
    report=full_report(payload)
    raw=dict(verdict='accepted',value=dict(verdict='accepted',_resource_report=report))
    assert queue.finish(job_id,'stale-token',deepcopy(raw),at=at) is False
    with replicas[1]() as db: assert db.get(model,'s').resource_report is None
    assert queue.finish(job_id,claim.token,deepcopy(raw),at=at+timedelta(seconds=1))
    assert queue.finish(job_id,claim.token,deepcopy(raw),at=at+timedelta(seconds=2)) is False
    with replicas[1]() as db:
        assert db.get(model,'s').resource_report==report
        saved=db.get(m.ExecutionJob,job_id).result
        assert '_resource_report' not in saved['value']
        assert 'cases' not in saved['value']['resource_usage']
        assert saved['value']['resource_usage']['run']['peakMemoryBytes']==2048


def test_invalid_metric_finish_rolls_back_verdict_and_resource_report(replicas):
    queue,job_id,payload,model=seed(replicas[0])
    at=datetime(2030,1,1);claim=queue.claim(at=at)
    report=full_report(payload);report['identity']['policyHash']='sha256:'+'0'*64
    with pytest.raises(ValueError):
        queue.finish(job_id,claim.token,dict(verdict='accepted',value=dict(_resource_report=report)),at=at)
    with replicas[1]() as db:
        assert db.get(model,'s').resource_report is None
        assert db.get(m.ExecutionJob,job_id).status=='running'
        assert db.get(model,'s').verdict=='pending'


@pytest.mark.asyncio
async def test_admin_resource_report_is_not_exposed_to_owner_or_public_list(env):
    report=full_report(payload_fixture())
    with env.factory() as db:
        db.add(m.Problem(id='visible',creator_id='admin',title='Fixture',description='',difficulty='iron5',tags=[],test_cases={}))
        db.flush()
        db.add(m.Submission(id='metrics-submission',problem_id='visible',user_id='alice',code='private',language='python',
            status='Accepted',verdict='accepted',resource_report=report))
        db.commit()
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        url='/api/v1/problems/submissions/metrics-submission/resources'
        assert (await client.get(url)).status_code==401
        assert (await client.get(url,headers=headers(env.alice))).status_code==403
        response=await client.get(url,headers=headers(env.admin))
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        assert response.json()['report']==report
        public=(await client.get('/api/v1/problems/submissions')).json()['submissions'][0]
        assert public['resourceUsage']['run']['cpuMs']==8
        assert 'testSuiteHash' not in json.dumps(public) and 'resourceReport' not in public
