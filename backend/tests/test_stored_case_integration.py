"""Actual isolated API/SQLite/queue, synthetic execution only; not cgroup evidence."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace
import zlib

import pytest
from httpx import ASGITransport,AsyncClient

from app.main import app
from app.core.config import settings
from app.models import database as m
from app.models.schemas import ProblemCreate
from app.models.judge_test_manifest import test_data_buffer_bytes as buffer_bytes
from app.services.judge_policy import freeze_stored_submission,test_suite_hash as suite_hash
from app.services.judging import judge_code
from app.services.measured_judge import validate_receipt
from app.services.execution_resources import ResourceBudget
from tests.test_contests import env,headers,payload as contest_body,authorize_private_contest
from tests.test_contest_package_authoring import author_env,package_body
from tests.test_judge_policy import policy_fixture
from tests.test_judge_test_manifest import case,reference,save
from tests.test_measured_judge import report_fixture
from tools.freshman_contest.a_i import solve as freshman_solve, validate as freshman_validate
from tools.freshman_contest.stress_cases import iter_cases as freshman_stress_cases


def body(data=b'secret\n'):
    sample=[dict(input='',expectedOutput='42')];hidden=[case(data,b'42')]
    return dict(title='Stored case test',description='Synthetic evidence only',difficulty='bronze5',
        tags=['io'],points=100,testCases=sample,hiddenTestCases=hidden,
        judgePolicy=policy_fixture(sample,hidden))


@pytest.mark.parametrize('location',['testCases','hiddenTestCases'])
def test_mixed_inline_reference_never_silently_discards_fields(location):
    raw=body();raw[location]=[{**case(), 'input':'', 'expectedOutput':''}]
    with pytest.raises(ValueError): ProblemCreate.model_validate(raw)


def test_schema_hash_budget_and_receipt_change_together(env):
    raw=body();sample,hidden=raw['testCases'],raw['hiddenTestCases']
    parsed=ProblemCreate.model_validate(raw)
    assert parsed.hidden_test_cases[0].model_dump(by_alias=True)==hidden[0]
    receipt=freeze_stored_submission(parsed.judge_policy,'python',sample,hidden,settings=settings)
    extra=buffer_bytes(sample,hidden)
    assert receipt['testDataBufferBytes']==extra>0
    assert receipt['reservationBytes']==128*1024**2+extra
    payload=dict(code='print(42)',language='python',sample=sample,hidden=hidden,judge_contract=receipt)
    validate_receipt(payload)
    budget=ResourceBudget(1024**3,2000,128*1024**2,1000,32*1024**2,'test-cpu')
    assert budget.reservation(payload,'host')['memoryBytes']==receipt['reservationBytes']+32*1024**2
    for field in ('testDataBufferBytes','reservationBytes'):
        broken=deepcopy(payload);broken['judge_contract'][field]-=1
        with pytest.raises(ValueError): validate_receipt(broken)
        with pytest.raises(ValueError): budget.reservation(broken,'host')
    changed=deepcopy(hidden);changed[0]['inputRef']['digest']='sha256:'+'f'*64
    assert suite_hash(sample,changed)!=receipt['testSuiteHash']
    with pytest.raises(ValueError): freeze_stored_submission(None,'python',sample,hidden,settings=settings)


@pytest.mark.asyncio
async def test_missing_and_corrupt_data_reject_authoring_atomically(env):
    raw=body()
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.post('/api/v1/problems/',headers=headers(env.admin),json=raw)).status_code==409
        draft=contest_body(env);draft['published']=False;draft['problems'][0]['newProblem']=raw
        assert (await client.post('/api/v1/contests',headers=headers(env.admin),json=draft)).status_code==409
        with env.factory() as db:
            assert db.query(m.Contest).count()==db.query(m.Problem).count()==0
            save(db,env,b'secret\n');save(db,env,b'42')
            row=db.get(m.JudgeTestData,reference(b'secret\n')['digest'])
            row.compressed=zlib.compress(b'broken\n');db.commit()
        assert (await client.post('/api/v1/problems/',headers=headers(env.admin),json=raw)).status_code==409
        with env.factory() as db: assert db.query(m.Problem).count()==0


@pytest.mark.asyncio
@pytest.mark.parametrize('corrupt',[False,True],ids=['accepted','corrupt-system-error'])
async def test_large_upload_receipt_restart_one_case_loading_and_private_score_result(env,monkeypatch,corrupt):
    from app.services import compiler,execution_worker
    # Restore the real dispatcher; only the sandbox execution below is synthetic.
    monkeypatch.setattr(execution_worker,'judge_code',judge_code)
    data=b'1000000\n'+b'-1000000 '*999999+b'-1000000\n';raw=body(data)
    events=[]
    class Measured:
        async def __aenter__(self): return self
        async def __aexit__(self,*_): pass
        async def _execute(self,**_):
            events.append('compile');usage=report_fixture();usage.update(phase='compile',outputBytes=0)
            return dict(exit_code=0,failure_reason=None,stdout='',stderr='',execution_phase='compile',resource_usage=usage)
        async def run(self,**kwargs):
            text=kwargs['stdin'];events.append('hidden' if text else 'sample')
            if text: assert text.encode()==data
            usage=report_fixture();usage.update(outputBytes=2)
            return dict(exit_code=0,failure_reason=None,stdout='42',stderr='',execution_phase='run',resource_usage=usage)
    monkeypatch.setattr(compiler.compiler_instance,'measured_submission',lambda _:Measured())
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        for blob in (data,b'42'):
            url='/api/v1/admin/judge-test-data/'+hashlib.sha256(blob).hexdigest()+f'?byteCount={len(blob)}'
            uploaded=await client.put(url,content=blob,headers={**headers(env.admin),'Content-Type':'text/plain'})
            assert uploaded.status_code==200,uploaded.text
        created=await client.post('/api/v1/problems/',json=raw,headers=headers(env.admin))
        assert created.status_code==200,created.text
        assert created.headers['cache-control']=='no-store'
        problem_id=created.json()['id']
        assert created.json()['hiddenTestCases']==raw['hiddenTestCases']
        # Stored-case hydration is the subject here; the exact publication
        # workflow has its own end-to-end gate regression.
        with env.factory() as db:
            db.get(m.Problem,problem_id).publication_approved_at=env.clock[0]
            db.commit()
        public=(await client.get('/api/v1/problems/'+problem_id)).json()
        assert public['hiddenTestCases']==[] and 'inputRef' not in json.dumps(public)
        submit_url='/api/v1/problems/'+problem_id+'/submit'
        auth={**headers(env.alice),'X-Request-ID':'e892ce44-c3f4-44c5-b54a-73f01d4e9e11'}
        submitted=await client.post(submit_url,headers=auth,json=dict(language='python',code='print(42)'))
        assert submitted.status_code==202,submitted.text
        with env.factory() as db:
            job=db.query(m.ExecutionJob).filter_by(public_id=submitted.json()['executionId']).one()
            internal_job_id=job.id
            frozen=deepcopy(job.payload)
            assert len(json.dumps(frozen).encode())<5000 and frozen['hidden']==raw['hiddenTestCases']
            source=db.get(m.Problem,problem_id)
            source.test_cases={'sample':[],'hidden':[dict(input='changed',expected_output='wrong')]}
            if corrupt:
                row=db.get(m.JudgeTestData,reference(data)['digest'])
                row.compressed=zlib.compress(b'broken');db.commit()
            db.commit()
        retry=await client.post(submit_url,headers=auth,json=dict(language='python',code='print(42)'))
        assert retry.json()['executionId']==submitted.json()['executionId']
        # Fresh worker object consumes committed receipt after the API request/session.
        assert await env.worker().run_once()
        if corrupt:
            # Infrastructure failures retry with the same frozen receipt. Do
            # not change that policy merely to make the test immediately final.
            with env.factory() as db:
                row=db.query(m.Submission).filter_by(execution_job_id=internal_job_id).one()
                assert row.verdict=='pending' and row.awarded_points==0
            for _ in range(env.worker().queue.max_attempts-1):
                assert await env.worker().run_once()
        with env.factory() as db:
            row=db.query(m.Submission).join(m.ExecutionJob).filter(
                m.ExecutionJob.public_id == submitted.json()['executionId']).one()
            assert row.verdict==('system_error' if corrupt else 'accepted')
            assert row.awarded_points==(0 if corrupt else 100)
            assert db.get(m.User,env.alice.id).total_score==(0 if corrupt else 100)
            job=db.get(m.ExecutionJob,row.execution_job_id)
            assert job.payload==frozen and 'inputRef' not in json.dumps(job.result)
        assert events==(['compile','sample']*env.worker().queue.max_attempts if corrupt else ['compile','sample','hidden'])


def test_large_case_host_reservation_limits_concurrent_claims(env):
    from app.services.durable_queue import DurableQueue
    raw=body(b'x'*9_000_000);sample,hidden=raw['testCases'],raw['hiddenTestCases']
    receipt=freeze_stored_submission(raw['judgePolicy'],'python',sample,hidden,settings=settings)
    budget=ResourceBudget(300*1024**2,4000,64*1024**2,1000,16*1024**2,'test-cpu')
    queue=DurableQueue(env.factory,concurrency=4,resource_budget=budget)
    for index in range(2):
        queue.enqueue(owner_key='same',request_id=str(index),kind='judge',
            payload=dict(code='print(42)',sample=sample,hidden=hidden,judge_contract=receipt))
    first=queue.claim(at=env.clock[0],daemon_id='isolated-host')
    assert first is not None and queue.claim(at=env.clock[0],daemon_id='isolated-host') is None
    with env.factory() as db:
        stored=db.get(m.ExecutionJob,first.id).resource_reservation
        assert stored['memoryBytes']==receipt['reservationBytes']+16*1024**2
    assert queue.finish(first.id,first.token,dict(verdict='accepted'))
    assert queue.claim(at=env.clock[0],daemon_id='isolated-host') is not None


@pytest.mark.asyncio
async def test_contest_schedule_edit_preserves_refs_and_receipt_uses_snapshot(env):
    raw=body();data=contest_body(env);data['problems'][0]['newProblem']=raw
    data['published']=False
    with env.factory() as db:
        save(db,env,b'secret\n');save(db,env,b'42')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        created=await client.post('/api/v1/contests',json=data,headers=headers(env.admin))
        assert created.status_code==201,created.text
        contest=await authorize_private_contest(client,env,created.json());data['published']=True;entry=contest['problems'][0];root='/api/v1/contests/'+contest['id']
        managed=(await client.get(root+'/manage',headers=headers(env.admin))).json()
        assert managed['problems'][0]['newProblem']['hiddenTestCases']==raw['hiddenTestCases']
        with env.factory() as db:
            db.get(m.Problem,entry['problemId']).test_cases={'sample':[],'hidden':[dict(input='new',expected_output='bad')]}
            db.commit()
        data['title']='Changed schedule title';data['problems']=[dict(problemId=entry['problemId'],points=500)]
        changed=await client.put(root,json=data,headers=headers(env.admin))
        assert changed.status_code==200,changed.text
        entry=changed.json()['problems'][0]
        await client.post(root+'/join',headers=headers(env.alice))
        env.clock[0]+=timedelta(seconds=10)
        endpoint=root+'/problems/'+entry['id']
        detail=(await client.get(endpoint,headers=headers(env.alice))).json()
        assert 'inputRef' not in json.dumps(detail)
        receipt=await client.post(endpoint+'/submit',headers=headers(env.alice),
            json=dict(code='print(42)',language='python',requestId='stored-frozen'))
        assert receipt.status_code==202,receipt.text
        with env.factory() as db:
            row=db.query(m.ContestSubmission).filter_by(public_id=receipt.json()['id']).one()
            assert db.get(m.ExecutionJob,row.execution_job_id).payload['hidden']==raw['hiddenTestCases']


@pytest.mark.asyncio
async def test_private_package_import_accepts_preuploaded_large_data_and_exact_retry(env):
    from tests.test_contest_package_authoring import package_body
    data=b'x'*9_000_000;package=package_body(env);package['entries'][0]['problem']=body(data)
    with env.factory() as db:
        save(db,env,data);save(db,env,b'42')
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        for replayed in (False,True):
            response=await client.post('/api/v1/contests/packages/import',json=package,headers=headers(env.admin))
            assert response.status_code==200,response.text
            assert response.json()['replayed']==replayed and response.json()['currentPublished'] is False
        with env.factory() as db:
            assert db.query(m.Contest).count()==db.query(m.Problem).count()==1
            assert db.query(m.ExecutionJob).count()==0


@pytest.mark.asyncio
@pytest.mark.parametrize('letter,maximum_name,sample_name',[
    ('C','c-maximum-extrema-negative-repetitions','c-single-minimum'),
    ('E','e-maximum-case-insensitive-tie','e-single-lowercase-letter'),
    ('E','e-maximum-case-insensitive-winner','e-single-lowercase-letter'),
    ('I','i-maximum-single-source-frontier','i-small-multi-source'),
])
async def test_actual_maximum_upload_contest_receipt_and_case_hydration(
        env,monkeypatch,letter,maximum_name,sample_name):
    """Actual C/E/I bytes traverse the private HTTP path; sandbox output is synthetic."""
    from app.services import compiler,execution_worker
    maximum=next(item for item in freshman_stress_cases(letter) if item.name==maximum_name)
    sample=next(item for item in freshman_stress_cases(letter) if item.name==sample_name)
    for item in (sample,maximum):
        freshman_validate(letter,item.input_text)
        assert freshman_solve(letter,item.input_text)==item.expected_output
    large_input=maximum.input_text.encode('utf-8')
    large_answer=maximum.expected_output.encode('utf-8')
    assert 512*1024<len(large_input)<16*1024**2
    public=[dict(input=sample.input_text,expectedOutput=sample.expected_output)]
    hidden=[case(large_input,large_answer)]
    problem=dict(title=f'Synthetic {letter} maximum',description='Transport test only',difficulty='bronze5',
        tags=['array'],points=120,testCases=public,hiddenTestCases=hidden,
        judgePolicy=policy_fixture(public,hidden))
    draft=contest_body(env)
    draft['problems'][0]['newProblem']=problem
    draft['published']=False
    events=[]
    class Measured:
        async def __aenter__(self): return self
        async def __aexit__(self,*_): pass
        async def _execute(self,**_):
            events.append('compile')
            usage=report_fixture();usage.update(phase='compile',outputBytes=0)
            return dict(exit_code=0,failure_reason=None,stdout='',stderr='',execution_phase='compile',resource_usage=usage)
        async def run(self,**kwargs):
            stdin=kwargs['stdin']
            assert stdin in (sample.input_text,maximum.input_text)
            events.append('sample' if stdin==sample.input_text else 'hidden')
            answer=sample.expected_output if stdin==sample.input_text else maximum.expected_output
            usage=report_fixture();usage.update(outputBytes=len(answer.encode('utf-8')))
            return dict(exit_code=0,failure_reason=None,stdout=answer,stderr='',execution_phase='run',resource_usage=usage)
    monkeypatch.setattr(execution_worker,'judge_code',judge_code)
    monkeypatch.setattr(compiler.compiler_instance,'measured_submission',lambda _:Measured())
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        for blob in (large_input,large_answer):
            target='/api/v1/admin/judge-test-data/'+hashlib.sha256(blob).hexdigest()+f'?byteCount={len(blob)}'
            response=await client.put(target,content=blob,
                headers={**headers(env.admin),'Content-Type':'text/plain'})
            assert response.status_code==200,response.text
            assert response.json()['digest']==reference(blob)['digest']
        created=await client.post('/api/v1/contests',json=draft,headers=headers(env.admin))
        assert created.status_code==201,created.text
        contest=await authorize_private_contest(client,env,created.json());entry=contest['problems'][0]
        root=f"/api/v1/contests/{contest['id']}"
        assert (await client.post(root+'/join',headers=headers(env.alice))).status_code==200
        env.clock[0]+=timedelta(seconds=10)
        detail=await client.get(root+'/problems/'+entry['id'],headers=headers(env.alice))
        assert detail.status_code==200 and 'inputRef' not in detail.text
        submitted=await client.post(root+'/problems/'+entry['id']+'/submit',headers=headers(env.alice),
            json=dict(code='print("synthetic")',language='python',requestId='actual-'+maximum_name))
        assert submitted.status_code==202,submitted.text
        with env.factory() as db:
            row=db.query(m.ContestSubmission).filter_by(public_id=submitted.json()['id']).one()
            job=db.get(m.ExecutionJob,row.execution_job_id)
            frozen=deepcopy(job.payload)
            assert frozen['hidden']==hidden and len(json.dumps(frozen).encode('utf-8'))<10_000
            db.get(m.Problem,entry['problemId']).test_cases={'sample':[],'hidden':[dict(input='changed',expected_output='wrong')]}
            db.commit()
        assert await env.worker().run_once()
        with env.factory() as db:
            row=db.query(m.ContestSubmission).filter_by(public_id=submitted.json()['id']).one()
            assert row.verdict=='accepted'
            job=db.get(m.ExecutionJob,row.execution_job_id)
            assert job.payload==frozen and 'inputRef' not in json.dumps(job.result)
        board=await client.get(root+'/scoreboard')
        assert board.status_code==200 and board.json()['rows'][0]['totalPoints']==500
        assert 'inputRef' not in board.text
    assert events==['compile','sample','hidden']


def actual_c_maximum_package(env):
    maximum=next(item for item in freshman_stress_cases('C')
                 if item.name=='c-maximum-extrema-negative-repetitions')
    sample=next(item for item in freshman_stress_cases('C') if item.name=='c-single-minimum')
    for item in (sample,maximum):
        freshman_validate('C',item.input_text)
        assert freshman_solve('C',item.input_text)==item.expected_output
    large_input=maximum.input_text.encode('utf-8')
    large_answer=maximum.expected_output.encode('utf-8')
    assert len(large_input)==3_000_019
    assert 512*1024<len(large_input)<16*1024**2
    public=[dict(input=sample.input_text,expectedOutput=sample.expected_output)]
    hidden=[case(large_input,large_answer)]
    package=package_body(env)
    package['packageId']='synthetic-c-maximum-flow'
    package['entries'][0]['problem']=dict(
        title='Synthetic C maximum package',description='Isolated transport and review test only',
        difficulty='bronze5',tags=['array'],points=120,testCases=public,hiddenTestCases=hidden,
        judgePolicy=policy_fixture(public,hidden))
    return package,sample,maximum,hidden,large_input,large_answer


@pytest.mark.asyncio
@pytest.mark.parametrize('contest_engine',['postgres'],indirect=True)
async def test_actual_c_maximum_private_import_cannot_activate_without_reviews(author_env):
    """A real stored maximum remains inert in PostgreSQL without invented approval evidence."""
    env=author_env
    package,_,_,_,large_input,large_answer=actual_c_maximum_package(env)
    package['packageId']='synthetic-c-maximum-negative-flow'
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        admin=headers(env.admin)
        for blob in (large_input,large_answer):
            target='/api/v1/admin/judge-test-data/'+hashlib.sha256(blob).hexdigest()+f'?byteCount={len(blob)}'
            response=await client.put(target,content=blob,
                headers={**admin,'Content-Type':'text/plain'})
            assert response.status_code==200,response.text
        imported=await client.post('/api/v1/contests/packages/import',json=package,headers=admin)
        assert imported.status_code==200,imported.text
        receipt=imported.json();cid=receipt['contestId'];entry=receipt['problems'][0]
        root='/api/v1/contests/'+cid
        managed=(await client.get(root+'/manage',headers=admin)).json()
        publish=contest_body(env);publish['problems']=managed['problems']
        denied=await client.put(root,json=publish,headers=admin)
        assert denied.status_code==409 and '검수' in denied.text
        alice=headers(env.alice)
        assert (await client.get(root,headers=alice)).status_code==404
        assert (await client.post(root+'/join',headers=alice)).status_code==404
        submit=await client.post(root+'/problems/'+entry['contestProblemId']+'/submit',headers=alice,
            json=dict(code='print("blocked")',language='python',requestId='unreviewed-c-maximum'))
        assert submit.status_code==404
        with env.factory() as db:
            contest=db.get(m.Contest,cid)
            assert contest is not None and contest.published is False
            assert db.query(m.ProblemReviewEvent).count()==0
            assert db.query(m.ContestParticipant).count()==0
            assert db.query(m.ContestSubmission).count()==0
            assert db.query(m.ExecutionJob).count()==0
            assert db.query(m.UserProblemScore).count()==0


@pytest.mark.asyncio
@pytest.mark.parametrize('contest_engine',['sqlite','postgres'],indirect=True)
async def test_actual_c_maximum_private_import_review_publication_and_submission(author_env,monkeypatch):
    """Exercise both DB backends; fixture approval is not real rights approval."""
    from app.services import compiler,execution_worker
    env=author_env
    package,sample,maximum,hidden,large_input,large_answer=actual_c_maximum_package(env)
    reference_source='print("synthetic")'
    reference_digest='sha256:'+hashlib.sha256(reference_source.encode('utf-8')).hexdigest()
    package['entries'][0]['metadata']['assets'][0]['digest']=reference_digest
    events=[]
    class Measured:
        async def __aenter__(self): return self
        async def __aexit__(self,*_): pass
        async def _execute(self,**_):
            events.append('compile')
            usage=report_fixture();usage.update(phase='compile',outputBytes=0)
            return dict(exit_code=0,failure_reason=None,stdout='',stderr='',execution_phase='compile',resource_usage=usage)
        async def run(self,**kwargs):
            stdin=kwargs['stdin']
            assert stdin in (sample.input_text,maximum.input_text)
            events.append('sample' if stdin==sample.input_text else 'hidden')
            answer=sample.expected_output if stdin==sample.input_text else maximum.expected_output
            usage=report_fixture();usage.update(outputBytes=len(answer.encode('utf-8')))
            return dict(exit_code=0,failure_reason=None,stdout=answer,stderr='',execution_phase='run',resource_usage=usage)
    monkeypatch.setattr(execution_worker,'judge_code',judge_code)
    monkeypatch.setattr(compiler.compiler_instance,'measured_submission',lambda _:Measured())
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        admin=headers(env.admin)
        for blob in (large_input,large_answer):
            target='/api/v1/admin/judge-test-data/'+hashlib.sha256(blob).hexdigest()+f'?byteCount={len(blob)}'
            response=await client.put(target,content=blob,
                headers={**admin,'Content-Type':'text/plain'})
            assert response.status_code==200,response.text
        imported=await client.post('/api/v1/contests/packages/import',json=package,headers=admin)
        assert imported.status_code==200,imported.text
        receipt=imported.json();cid=receipt['contestId'];pid=receipt['problems'][0]['problemId']
        root='/api/v1/contests/'+cid
        assert receipt['currentPublished'] is False
        assert (await client.get(root,headers=headers(env.alice))).status_code==404
        assert (await client.get('/api/v1/problems/'+pid,headers=headers(env.alice))).status_code==404
        managed=(await client.get(root+'/manage',headers=admin)).json()
        publish=contest_body(env);publish['problems']=managed['problems']
        denied=await client.put(root,json=publish,headers=admin)
        assert denied.status_code==409 and '검수' in denied.text
        review_url='/api/v1/problems/'+pid+'/authoring'
        current=(await client.get(review_url,headers=admin)).json()
        metadata=deepcopy(current['metadata'])
        metadata['sources'][0].update(reuseBasis='permission',reuseEvidence='Disposable synthetic test fixture only')
        current=(await client.put(review_url,headers=admin,json=dict(
            expectedFingerprint=current['fingerprint'],metadata=metadata))).json()
        # Persist the changed authoring metadata into the saved draft snapshot;
        # reference validation never trusts mutable source metadata alone.
        draft=deepcopy(publish);draft['published']=False
        saved=await client.put(root,json=draft,headers=admin)
        assert saved.status_code==200,saved.text
        current=(await client.get(review_url,headers=admin)).json()
        for category in ('sources','statement','tests','resources'):
            approved=await client.post(review_url+'/reviews',headers=admin,json=dict(
                requestId='synthetic-c-'+category,expectedFingerprint=current['fingerprint'],
                category=category,decision='approved',note='Disposable synthetic fixture only'))
            assert approved.status_code==200,approved.text
        managed=(await client.get(root+'/manage',headers=admin)).json()
        contest_problem_id=managed['problems'][0]['contestProblemId']
        validated=await client.post(
            f'{root}/problems/{contest_problem_id}/authoring-validations',headers=admin,json=dict(
                code=reference_source,language='python',requestId='synthetic-c-reference',
                expectedFingerprint=current['fingerprint'],referenceAssetDigest=reference_digest))
        assert validated.status_code==202,validated.text
        assert await env.worker().run_once()
        with env.factory() as db:
            proof=db.get(m.ProblemValidationAttestation,validated.json()['id'])
            assert proof is not None and proof.source_hash==reference_digest
        publish=contest_body(env);publish['problems']=managed['problems']
        published=await client.put(root,json=publish,headers=admin)
        assert published.status_code==200,published.text
        retry=await client.post('/api/v1/contests/packages/import',json=package,headers=admin)
        assert retry.status_code==200 and retry.json()['replayed'] is True
        assert retry.json()['currentPublished'] is True
        assert (await client.post(root+'/join',headers=headers(env.alice))).status_code==200
        env.clock[0]+=timedelta(seconds=10)
        entry=published.json()['problems'][0]
        detail=await client.get(root+'/problems/'+entry['id'],headers=headers(env.alice))
        assert detail.status_code==200 and 'inputRef' not in detail.text
        submitted=await client.post(root+'/problems/'+entry['id']+'/submit',headers=headers(env.alice),
            json=dict(code='print("synthetic")',language='python',requestId='imported-c-maximum'))
        assert submitted.status_code==202,submitted.text
        with env.factory() as db:
            row=db.query(m.ContestSubmission).filter_by(public_id=submitted.json()['id']).one()
            frozen=deepcopy(db.get(m.ExecutionJob,row.execution_job_id).payload)
            assert frozen['hidden']==hidden and len(json.dumps(frozen).encode('utf-8'))<10_000
            assert db.query(m.Contest).count()==db.query(m.Problem).count()==db.query(m.ContestPackageImport).count()==1
        assert await env.worker().run_once()
        with env.factory() as db:
            row=db.query(m.ContestSubmission).filter_by(public_id=submitted.json()['id']).one()
            assert row.verdict=='accepted'
            job=db.get(m.ExecutionJob,row.execution_job_id)
            assert job.payload==frozen and 'inputRef' not in json.dumps(job.result)
        board=await client.get(root+'/scoreboard')
        assert board.status_code==200 and board.json()['rows'][0]['totalPoints']==500
        assert 'inputRef' not in board.text
    assert events==['compile','sample','hidden']*2


def test_data_buffers_cannot_overcommit_a_policy_that_fits_without_data(env,monkeypatch):
    monkeypatch.setattr(settings,'EXECUTION_MEMORY_BUDGET_MB',192)
    monkeypatch.setattr(settings,'EXECUTION_JOB_OVERHEAD_MB',32)
    raw=body(b'x'*9_000_000)
    with pytest.raises(ValueError,match='memory reservation'):
        freeze_stored_submission(raw['judgePolicy'],'python',raw['testCases'],raw['hiddenTestCases'],settings=settings)
    raw=body(b'')
    assert freeze_stored_submission(raw['judgePolicy'],'python',raw['testCases'],raw['hiddenTestCases'],settings=settings)
