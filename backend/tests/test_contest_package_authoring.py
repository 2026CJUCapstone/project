"""Synthetic authoring fixtures; never evidence of source reuse permission."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from app.main import app
from app.core.config import settings
from app.models import database as m
from app.models.problem_authoring import MAX_PACKAGE_BYTES, PrivateContestPackage, canonical_package_bytes
from app.services import problem_authoring as review
from app.services.contest_packages import import_package
from app.services.judge_policy import content_hash, freeze_stored_submission
from tests.test_contests import env, headers, payload


@pytest.fixture
def author_env(env,monkeypatch):
    monkeypatch.setattr(review,'now_utc',lambda:env.clock[0])
    return env


def package_body(env):
    contest=payload(env)
    metadata=dict(sources=[dict(url='https://example.com/synthetic-source',title='Synthetic fixture only')],
        adaptationNotes='Unit-test invented metadata, no permission or measurement claim',requiredLanguages=['python'],
        assets=[dict(role=role,name=f'{role}.py',digest='sha256:'+'1'*64,**({'language':'python'} if role=='reference' else {}))
                for role in ('reference','validator','generator','wrong_solution')])
    return dict(schemaVersion=1,packageId='fixture-package',revision=1,title=contest['title'],description=contest['description'],
        startsAt=contest['startsAt'],endsAt=contest['endsAt'],entries=[dict(key='A',points=500,
            problem=contest['problems'][0]['newProblem'],metadata=metadata)])


async def imported(client,env):
    response=await client.post('/api/v1/contests/packages/import',json=package_body(env),headers=headers(env.admin))
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.asyncio
async def test_private_import_rejects_oversized_raw_body_before_database_write(env):
    body=package_body(env)
    raw=json.dumps(body,separators=(',', ':')).encode('utf-8')
    expanded=raw+b' '*(MAX_PACKAGE_BYTES-len(raw)+1)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/v1/contests/packages/import',content=expanded,
            headers={**headers(env.admin),'Content-Type':'application/json'})
        assert response.status_code==413
        async def chunks():
            yield raw
            yield b' '*(MAX_PACKAGE_BYTES-len(raw)+1)
        streamed=await client.post('/api/v1/contests/packages/import',content=chunks(),
            headers={**headers(env.admin),'Content-Type':'application/json'})
        assert streamed.status_code==413
        async def unread():
            raise AssertionError('Unauthenticated body must not be consumed')
            yield b''
        unauthorized=await client.post('/api/v1/contests/packages/import',content=unread())
        assert unauthorized.status_code==401
    with env.factory() as db:
        assert count(db,m.Contest)==count(db,m.Problem)==count(db,m.ContestPackageImport)==0


@pytest.mark.asyncio
@pytest.mark.parametrize('content_type',[None,'text/plain','application/json; charset=utf-16','application/json; broken'])
async def test_private_import_rejects_invalid_content_type_before_body_read(env,content_type):
    async def unread():
        raise AssertionError('Invalid Content-Type body must not be consumed')
        yield b''

    auth=headers(env.admin)
    if content_type is not None:
        auth['Content-Type']=content_type
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/v1/contests/packages/import',content=unread(),headers=auth)
    assert response.status_code==415,response.text
    with env.factory() as db:
        assert count(db,m.Contest)==count(db,m.Problem)==count(db,m.ContestPackageImport)==0


@pytest.mark.asyncio
async def test_private_import_rejects_oversized_content_length_before_body_read(env):
    async def unread():
        raise AssertionError('Oversized Content-Length body must not be consumed')
        yield b''

    auth={**headers(env.admin),'Content-Type':'application/json',
          'Content-Length':str(MAX_PACKAGE_BYTES+1)}
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/api/v1/contests/packages/import',content=unread(),headers=auth)
    assert response.status_code==413,response.text
    with env.factory() as db:
        assert count(db,m.Contest)==count(db,m.Problem)==count(db,m.ContestPackageImport)==0


def test_private_import_counts_the_exact_canonical_wire_bytes(env):
    body=package_body(env)
    baseline=PrivateContestPackage.model_validate(body)
    padding=MAX_PACKAGE_BYTES-len(canonical_package_bytes(baseline))
    body['entries'][0]['problem']['testCases'][0]['input']+='x'*padding
    valid=PrivateContestPackage.model_validate(body)
    assert len(canonical_package_bytes(valid))==MAX_PACKAGE_BYTES
    # Regression for the old calculation: Pydantic's default serializer uses
    # internal snake_case names, although the importer always transports the
    # canonical camelCase aliases.
    assert len(valid.model_dump_json().encode('utf-8'))>MAX_PACKAGE_BYTES
    body['entries'][0]['problem']['testCases'][0]['input']+='x'
    with pytest.raises(ValueError,match='aggregate byte budget'):
        PrivateContestPackage.model_validate(body)


@pytest.mark.asyncio
async def test_private_import_accepts_exact_canonical_wire_and_rejects_one_byte_tamper(env):
    body=package_body(env)
    baseline=PrivateContestPackage.model_validate(body)
    body['entries'][0]['problem']['testCases'][0]['input']+='x'*(
        MAX_PACKAGE_BYTES-len(canonical_package_bytes(baseline)))
    package=PrivateContestPackage.model_validate(body)
    wire=canonical_package_bytes(package)
    assert len(wire)==MAX_PACKAGE_BYTES

    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        accepted=await client.post('/api/v1/contests/packages/import',content=wire,
            headers={**headers(env.admin),'Content-Type':'application/json'})
        assert accepted.status_code==200,accepted.text
        # Whitespace does not change JSON meaning, but it changes the bounded
        # request bytes.  Reject it before parsing/importing a second receipt.
        rejected=await client.post('/api/v1/contests/packages/import',content=wire+b' ',
            headers={**headers(env.admin),'Content-Type':'application/json'})
        assert rejected.status_code==413
    with env.factory() as db:
        assert count(db,m.Contest)==count(db,m.Problem)==count(db,m.ContestPackageImport)==1


def count(db,model): return db.query(model).count()


@pytest.mark.asyncio
async def test_private_atomic_import_is_admin_only_and_retries_do_not_overwrite_edits(author_env):
    env=author_env
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        body=package_body(env)
        assert (await client.post('/api/v1/contests/packages/import',json=body)).status_code==401
        assert (await client.post('/api/v1/contests/packages/import',json=body,headers=headers(env.alice))).status_code==403
        result=await imported(client,env);cid=result['contestId'];pid=result['problems'][0]['problemId']
        assert result['replayed'] is False and result['currentPublished'] is False
        for who in (None,env.alice,env.bob):
            auth=headers(who) if who else {}
            assert (await client.get('/api/v1/contests/'+cid,headers=auth)).status_code==404
            assert (await client.get('/api/v1/problems/'+pid,headers=auth)).status_code==404
            assert (await client.get('/api/v1/problems/'+pid+'/authoring',headers=auth)).status_code in (401,403)
        with env.factory() as db:
            c=db.get(m.Contest,cid);c.title='User-edited title';db.commit()
        retry=await client.post('/api/v1/contests/packages/import',json=body,headers=headers(env.admin))
        assert retry.json()['contestId']==cid and retry.json()['replayed'] is True
        with env.factory() as db:
            assert count(db,m.Contest)==count(db,m.Problem)==count(db,m.ContestPackageImport)==1
            assert db.get(m.Contest,cid).title=='User-edited title'
            assert count(db,m.Submission)==count(db,m.ContestSubmission)==count(db,m.ExecutionJob)==count(db,m.UserProblemScore)==0
            assert db.get(m.Problem,pid).judge_policy is not None
        changed={**body,'title':'different'}
        assert (await client.post('/api/v1/contests/packages/import',json=changed,headers=headers(env.admin))).status_code==409
        assert (await client.post('/api/v1/contests/packages/import',json={**body,'published':True},headers=headers(env.admin))).status_code==422
        receipt=await client.get('/api/v1/contests/packages/'+body['packageId'],headers=headers(env.admin))
        assert receipt.headers['cache-control']=='no-store' and 'secret-input' not in receipt.text


@pytest.mark.asyncio
async def test_reviews_bind_exact_content_revoke_and_freeze_on_contest_start(author_env):
    env=author_env
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        record=await imported(client,env);cid=record['contestId'];pid=record['problems'][0]['problemId']
        url='/api/v1/problems/'+pid+'/authoring';auth=headers(env.admin)
        current=(await client.get(url,headers=auth)).json()
        assert set(current['categories'].values())=={'pending'}
        event_body=dict(requestId='blocked-source',expectedFingerprint=current['fingerprint'],category='sources',decision='approved',note='Synthetic check')
        assert (await client.post(url+'/reviews',json=event_body,headers=auth)).status_code==409
        metadata=deepcopy(current['metadata']);metadata['sources'][0].update(reuseBasis='permission',reuseEvidence='Synthetic permission fixture only')
        current=(await client.put(url,json=dict(expectedFingerprint=current['fingerprint'],metadata=metadata),headers=auth)).json()
        first_stamp=current['fingerprint']
        for category in review.CATEGORIES:
            data=dict(requestId='review-'+category,expectedFingerprint=first_stamp,category=category,decision='approved',note='Synthetic '+category)
            response=await client.post(url+'/reviews',json=data,headers=auth)
            assert response.status_code==200,response.text
            assert (await client.post(url+'/reviews',json=data,headers=auth)).status_code==200
        current=(await client.get(url,headers=auth)).json()
        assert len(current['events'])==4 and set(current['categories'].values())=={'approved'}
        collision={**data,'note':'changed request'}
        assert (await client.post(url+'/reviews',json=collision,headers=auth)).status_code==409
        # Rejection invalidates an earlier approval without erasing either event.
        revoke=dict(requestId='revoke',expectedFingerprint=first_stamp,category='statement',decision='rejected',note='Synthetic revision needed')
        assert (await client.post(url+'/reviews',json=revoke,headers=auth)).status_code==200
        managed=(await client.get('/api/v1/contests/'+cid+'/manage',headers=auth)).json()
        body=payload(env);body['problems']=managed['problems']
        assert (await client.put('/api/v1/contests/'+cid,json=body,headers=auth)).status_code==409
        redo={**revoke,'requestId':'redo','decision':'approved'}
        assert (await client.post(url+'/reviews',json=redo,headers=auth)).status_code==200
        # Changing a statement invalidates ALL previous per-content approvals.
        body['published']=False;body['problems'][0]['newProblem']['description']='Changed content'
        assert (await client.put('/api/v1/contests/'+cid,json=body,headers=auth)).status_code==200
        updated=(await client.get(url,headers=auth)).json()
        assert updated['fingerprint']!=first_stamp and set(updated['categories'].values())=={'pending'}
        assert len(updated['events'])==6
        assert (await client.post(url+'/reviews',json={**redo,'requestId':'stale'},headers=auth)).status_code==409
        for category in review.CATEGORIES:
            response=await client.post(url+'/reviews',json=dict(requestId='new-'+category,expectedFingerprint=updated['fingerprint'],category=category,decision='approved',note='New synthetic review'),headers=auth)
            assert response.status_code==200,response.text
        # This test exercises review lifecycle rather than the private runner;
        # install the same non-secret proof that an accepted durable validation
        # would create. End-to-end publication gating is covered separately.
        with env.factory() as db:
            saved=db.query(m.ContestProblem).filter_by(contest_id=cid,problem_id=pid).one()
            snap=saved.snapshot
            contract=freeze_stored_submission(snap['judgePolicy'],'python',snap['sample'],snap['hidden'],settings=settings)
            digest=next(asset['digest'] for asset in snap['authoring']['assets']
                        if asset['role']=='reference' and asset.get('language')=='python')
            db.add(m.ProblemValidationAttestation(
                job_id='synthetic-review-lifecycle-proof',problem_id=pid,contest_id=cid,
                contest_problem_id=saved.id,problem_snapshot_hash=content_hash(snap),
                authoring_fingerprint=review.fingerprint(snap),language='python',
                source_hash=digest,reference_asset_digest=digest,
                policy_hash=contract['policyHash'],test_suite_hash=contract['testSuiteHash']))
            db.commit()
        body['published']=True
        response=await client.put('/api/v1/contests/'+cid,json=body,headers=auth)
        assert response.status_code==200,response.text
        public=await client.get('/api/v1/contests/'+cid)
        assert 'reuseEvidence' not in public.text and 'Synthetic permission' not in public.text
        env.clock[0]+=timedelta(seconds=10)
        assert (await client.post(url+'/reviews',json=dict(requestId='after-start',expectedFingerprint=updated['fingerprint'],category='statement',decision='rejected',note='Cannot change'),headers=auth)).status_code==409


@pytest.mark.asyncio
async def test_pending_package_cannot_be_published_even_with_measured_policy(author_env):
    env=author_env
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        record=await imported(client,env)
        managed=(await client.get('/api/v1/contests/'+record['contestId']+'/manage',headers=headers(env.admin))).json()
        body=payload(env);body['problems']=managed['problems']
        response=await client.put('/api/v1/contests/'+record['contestId'],json=body,headers=headers(env.admin))
        assert response.status_code==409 and '검수' in response.text
        with env.factory() as db:
            assert db.get(m.Contest,record['contestId']).published is False
            assert count(db,m.ProblemReviewEvent)==0


@pytest.mark.asyncio
async def test_package_retry_resolves_new_row_ids_and_does_not_restore_removed_problems(author_env):
    env=author_env;auth=headers(env.admin)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        record=await imported(client,env);cid=record['contestId']
        managed=(await client.get('/api/v1/contests/'+cid+'/manage',headers=auth)).json()
        body=payload(env);body.update(published=False,problems=managed['problems'])
        assert (await client.put('/api/v1/contests/'+cid,json=body,headers=auth)).status_code==200
        retry=await imported(client,env)
        assert retry['originalProblems']==record['originalProblems']
        assert retry['problems'][0]['contestProblemId']!=record['problems'][0]['contestProblemId']
        assert retry['problems'][0]['removed'] is False
        # Removal is an administrative edit, never a reason to recreate content.
        body['problems']=[]
        assert (await client.put('/api/v1/contests/'+cid,json=body,headers=auth)).status_code==200
        retry=await imported(client,env)
        assert retry['problems'][0]['removed'] is True
        assert retry['problems'][0]['contestProblemId'] is None
        with env.factory() as db:
            assert count(db,m.Problem)==count(db,m.ContestProblem)==0
            assert count(db,m.ContestPackageImport)==1


def test_import_failure_rolls_back_problem_contest_metadata_and_receipt(author_env):
    env=author_env
    def fail(*_): raise RuntimeError('synthetic metadata storage failure')
    event.listen(m.ProblemAuthoring,'before_insert',fail)
    try:
        with env.factory() as db:
            with pytest.raises(RuntimeError,match='synthetic'):
                import_package(db,PrivateContestPackage.model_validate(package_body(env)),db.get(m.User,'admin'))
            for model in (m.Problem,m.Contest,m.ContestProblem,m.ProblemAuthoring,m.ContestPackageImport):
                assert count(db,model)==0
    finally: event.remove(m.ProblemAuthoring,'before_insert',fail)


def test_simultaneous_import_has_one_atomic_mapping(author_env):
    env=author_env;barrier=Barrier(2);data=PrivateContestPackage.model_validate(package_body(env))
    def execute(_):
        with env.factory() as db:
            actor=db.get(m.User,'admin');barrier.wait()
            return import_package(db,data,actor)
    with ThreadPoolExecutor(max_workers=2) as pool: records=list(pool.map(execute,range(2)))
    assert records[0]['contestId']==records[1]['contestId']
    assert sorted(r['replayed'] for r in records)==[False,True]
    with env.factory() as db:
        assert count(db,m.Contest)==count(db,m.Problem)==count(db,m.ContestPackageImport)==1


@pytest.mark.parametrize('mutation',['duplicate','no_timezone','too_many','too_large','unknown','blank_note'])
def test_package_validation_rejects_ambiguous_or_unbounded_input(author_env,mutation):
    from pydantic import ValidationError
    body=package_body(author_env)
    if mutation=='duplicate': body['entries']*=2
    elif mutation=='no_timezone': body['startsAt']='2030-01-01T00:00:00'
    elif mutation=='too_many': body['entries'][0]['problem']['testCases']*=201
    elif mutation=='too_large': body['entries'][0]['problem']['testCases'][0]['input']='x'*1_000_001
    elif mutation=='unknown': body['entries'][0]['problem']['serverId']='guess'
    else: body['entries'][0]['metadata']['adaptationNotes']=''
    with pytest.raises(ValidationError): PrivateContestPackage.model_validate(body)
