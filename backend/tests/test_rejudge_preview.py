"""Read-only impact previews and stale-review fences; synthetic execution only."""
from copy import deepcopy
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text, inspect
from app.main import app
from app.models import database as m
from app.models.contest_rejudge import RejudgeApply
from app.services import contest_rejudge as service, solve_evidence
from tests.test_rejudge_apply import env, seeded, ready, headers


@pytest.mark.asyncio
async def test_preview_is_paginated_read_only_and_matches_application(env, seeded, monkeypatch):
    batch, body = await ready(env,seeded,monkeypatch)
    statements=[]
    engine=env.db.get_bind()
    def capture(_conn,_cursor,statement,*_): statements.append(statement.strip().upper())
    event.listen(engine,'before_cursor_execute',capture)
    try:
        with env.factory() as db:
            first=service.preview_candidate(db,'c',batch,limit=1)
            second=service.preview_candidate(db,'c',batch,offset=1,limit=1)
        assert not any(s.startswith(('INSERT','UPDATE','DELETE','REPLACE')) for s in statements)
    finally:
        event.remove(engine,'before_cursor_execute',capture)
    assert first['total']==2 and first['blockedCount']==0
    assert first['previewHash']==second['previewHash']==body['expectedPreviewHash']
    assert first['rows'][0]['userId']=='alice' and first['rows'][0]['practicePointDelta']==-120
    assert second['rows'][0]['userId']=='bob' and second['rows'][0]['practicePointDelta']==120
    assert first['rows'][0]['beforeRank']==1 and first['rows'][0]['afterRank']==2
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        path=f'/api/v1/contests/c/rejudges/{batch}/preview?limit=1'
        assert (await client.get(path)).status_code==401
        assert (await client.get(path,headers=headers(env.alice))).status_code==403
        response=await client.get(path,headers=headers(env.admin))
        assert response.status_code==200 and response.headers['Cache-Control']=='no-store'
        assert all(secret not in response.text for secret in ('corrected-private-input','print(42)','resourceReport','judgePolicy'))
    with env.factory() as db:
        service.apply_candidate(db,'c',batch,RejudgeApply.model_validate(body),env.admin)
        audit=db.get(m.ContestRejudgeApplication,batch)
        assert audit.preview_hash==first['previewHash']
        assert {r['userId']:r['delta'] for r in audit.score_changes}=={'alice':-120,'bob':120}


@pytest.mark.asyncio
async def test_new_practice_solve_invalidates_preview_without_overwriting_it(env,seeded,monkeypatch):
    batch,body=await ready(env,seeded,monkeypatch)
    with env.factory() as db:
        solve_evidence.record(db,user_id='alice',problem_id='p',source_kind='practice',source_id='later-ac',
            points=120,solved_at=env.clock[0])
        db.commit()
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        service.apply_candidate(db,'c',batch,RejudgeApply.model_validate(body),env.admin)
    assert error.value.status_code==409
    with env.factory() as db:
        assert db.get(m.ContestSubmission,'s0').verdict=='accepted'
        assert db.get(m.User,'alice').total_score==120 and db.get(m.User,'bob').total_score==0
        latest=service.preview_candidate(db,'c',batch)
        assert latest['previewHash']!=body['expectedPreviewHash']
        assert latest['rows'][0]['practicePointDelta']==0
        body['expectedPreviewHash']=latest['previewHash']
        assert service.apply_candidate(db,'c',batch,RejudgeApply.model_validate(body),env.admin)['status']=='applied'


@pytest.mark.asyncio
async def test_missing_participant_cannot_hide_an_award_delta_from_review(env, seeded, monkeypatch):
    batch, body = await ready(env, seeded, monkeypatch)
    with env.factory() as db:
        db.query(m.ContestParticipant).filter_by(contest_id='c', user_id='alice').delete()
        db.commit()
    for operation in ('preview', 'apply'):
        with env.factory() as db, pytest.raises(service.HTTPException) as error:
            if operation == 'preview': service.preview_candidate(db, 'c', batch)
            else: service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(body), env.admin)
        assert error.value.status_code == 409
    with env.factory() as db:
        assert db.get(m.User, 'alice').total_score == 120
        assert db.get(m.User, 'bob').total_score == 0
        assert db.get(m.ContestSubmission, 's0').verdict == 'accepted'
        assert db.query(m.ContestRejudgeApplication).count() == 0


@pytest.mark.asyncio
async def test_legacy_ambiguity_is_visible_without_creating_fake_evidence(env,seeded,monkeypatch):
    batch,_=await ready(env,seeded,monkeypatch,tracked=False)
    with env.factory() as db:
        preview=service.preview_candidate(db,'c',batch)
        assert preview['blockedCount']==1
        assert preview['rows'][0]['practicePointDelta'] is None
        assert preview['rows'][0]['blocker']
        assert db.query(m.SolveEvidence).count()==0
        assert db.query(m.ContestRejudgeApplication).count()==0


@pytest.mark.asyncio
@pytest.mark.parametrize('changed_field', ['report', 'finished_at'])
async def test_candidate_results_cannot_change_after_preview(env,seeded,monkeypatch,changed_field):
    batch,body=await ready(env,seeded,monkeypatch)
    with env.factory() as db:
        item=db.query(m.ContestRejudgeItem).filter_by(batch_id=batch,submission_id='s0').one()
        if changed_field == 'report':
            report=deepcopy(item.resource_report)
            report['compile']['cpuUsec']+=1
            item.resource_report=report
        else:
            from datetime import timedelta
            item.finished_at += timedelta(seconds=1)
        db.commit()
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        service.apply_candidate(db,'c',batch,RejudgeApply.model_validate(body),env.admin)
    assert error.value.status_code==409


@pytest.mark.asyncio
@pytest.mark.parametrize('evidence_id', ['00000000', 'zzzzzzzz'])
async def test_equal_timestamp_awards_use_stable_source_identity_not_row_uuid(env, seeded, monkeypatch, evidence_id):
    batch, body = await ready(env, seeded, monkeypatch)
    with env.factory() as db:
        # Retained independent solve, but materialized award absent: selecting
        # between differing point values cannot depend on a newly allocated UUID.
        db.add(m.SolveEvidence(id=evidence_id, user_id='bob', problem_id='p', source_kind='practice',
            source_id='independent', points=200, solved_at=db.get(m.ContestSubmission, 's1').received_at))
        db.commit()
    with env.factory() as db:
        preview = service.preview_candidate(db, 'c', batch)
        predicted = next(row for row in preview['rows'] if row['userId'] == 'bob')['practicePointDelta']
        assert predicted == 120
        body['expectedPreviewHash'] = preview['previewHash']
        service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(body), env.admin)
        audit = db.get(m.ContestRejudgeApplication, batch)
        assert next(row for row in audit.score_changes if row['userId'] == 'bob')['delta'] == predicted
        assert db.query(m.UserProblemScore).filter_by(user_id='bob', challenge_id='p').one().points_awarded == predicted


@pytest.mark.asyncio
async def test_v18_additive_column_migration_preserves_null_unknown_preview(env, seeded, monkeypatch):
    from app.core.database import migrate_schema
    batch, body = await ready(env, seeded, monkeypatch)
    with env.factory() as db:
        service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(body), env.admin)
        audit = db.get(m.ContestRejudgeApplication, batch)
        original = {c.name: deepcopy(getattr(audit, c.name)) for c in audit.__table__.columns if c.name != 'preview_hash'}
    engine=env.db.get_bind()
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE contest_rejudge_applications DROP COLUMN preview_hash'))
    assert 'preview_hash' not in {c['name'] for c in inspect(engine).get_columns('contest_rejudge_applications')}
    migrate_schema(engine); migrate_schema(engine)
    assert 'preview_hash' in {c['name'] for c in inspect(engine).get_columns('contest_rejudge_applications')}
    with env.factory() as db:
        audit = db.get(m.ContestRejudgeApplication, batch)
        assert audit.preview_hash is None
        assert {name: getattr(audit, name) for name in original} == original
        # Historical applications had no preview digest. A compatibility retry
        # only reports their existing result; it must not invent evidence or mutate.
        assert service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(body), env.admin)['status'] == 'applied'
        assert db.get(m.ContestRejudgeApplication, batch).preview_hash is None
        assert db.query(m.ContestRejudgeApplication).count() == 1


@pytest.mark.asyncio
async def test_apply_requires_review_hash_and_conflicting_retry_cannot_replace_it(env, seeded, monkeypatch):
    batch, body = await ready(env, seeded, monkeypatch)
    path = f'/api/v1/contests/c/rejudges/{batch}/apply'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        missing = {key: value for key, value in body.items() if key != 'expectedPreviewHash'}
        assert (await client.post(path, json=missing, headers=headers(env.admin))).status_code == 422
        with env.factory() as db:
            assert db.get(m.ContestRejudgeBatch, batch).status == 'ready'
            assert db.query(m.ContestRejudgeApplication).count() == 0
        assert (await client.post(path, json=body, headers=headers(env.admin))).status_code == 200
        changed = {**body, 'expectedPreviewHash': 'sha256:' + '0' * 64}
        assert (await client.post(path, json=changed, headers=headers(env.admin))).status_code == 409
        assert (await client.post(path, json=body, headers=headers(env.admin))).status_code == 200
    with env.factory() as db:
        assert db.query(m.ContestRejudgeApplication).count() == 1
        assert db.get(m.ContestRejudgeApplication, batch).preview_hash == body['expectedPreviewHash']
