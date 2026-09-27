"""Exact correction approval with real transactions, synthetic judging/evidence."""
from copy import deepcopy
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect, text
from app.main import app
from app.core.database import migrate_schema
from app.models import database as m
from app.models.contest_rejudge import RejudgeCreate, RejudgeApply, RejudgeReview
from app.services import contest_rejudge as service, contest_rejudge_review as review
from app.services import problem_authoring
from tests.test_rejudge_apply import env, seeded, ready, headers
from tests.test_contest_rejudge import create
from tests.test_contest_package_authoring import package_body


def body_for(db, batch_id, *, category='tests', decision='rejected', request_id='review-again'):
    current = review.read(db, 'c', batch_id)
    return dict(requestId=request_id, expectedRequestHash=current['requestHash'],
        expectedFingerprint=current['fingerprint'], category=category, decision=decision,
        note='Synthetic review evidence for transaction testing only')


def append(env, batch_id, **kwargs):
    with env.factory() as db:
        return review.append(db, 'c', batch_id, RejudgeReview.model_validate(body_for(db, batch_id, **kwargs)), env.admin)


@pytest.mark.asyncio
async def test_latest_rejection_invalidates_preview_and_cannot_change_scores(env, seeded, monkeypatch):
    batch, request = await ready(env, seeded, monkeypatch)
    with env.factory() as db:
        original = {r.id:service.submission_fingerprint(r) for r in db.query(m.ContestSubmission)}
    append(env, batch)
    with env.factory() as db:
        latest = service.preview_candidate(db, 'c', batch)
        assert latest['reviewBlocked'] is True and latest['previewHash'] != request['expectedPreviewHash']
    for digest in (request['expectedPreviewHash'], latest['previewHash']):
        with env.factory() as db, pytest.raises(service.HTTPException) as error:
            service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate({**request, 'expectedPreviewHash':digest}), env.admin)
        assert error.value.status_code == 409
    with env.factory() as db:
        assert db.query(m.ContestRejudgeApplication).count() == 0
        assert original == {r.id:service.submission_fingerprint(r) for r in db.query(m.ContestSubmission)}
        assert db.get(m.User, 'alice').total_score == 120
    append(env, batch, decision='approved', request_id='tests-reapproved')
    with env.factory() as db:
        latest = service.preview_candidate(db, 'c', batch)
        assert not latest['reviewBlocked']
        service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate({**request, 'expectedPreviewHash':latest['previewHash']}), env.admin)
        provenance = deepcopy(db.get(m.ContestRejudgeApplication, batch).review_provenance)
        ids = {e.id for e in db.query(m.ContestRejudgeReviewEvent).filter_by(batch_id=batch, decision='approved')}
        assert len(provenance['approvals']) == 4
        assert {e['id'] for e in provenance['approvals']} <= ids
        assert all(e['fingerprint'] == provenance['fingerprint'] for e in provenance['approvals'])
        assert provenance['basis']['beforeFingerprint'] != provenance['fingerprint']
        assert provenance['basis']['sourceReviews'] == []  # No invented historical approvals.
    with env.factory() as db, pytest.raises(service.HTTPException):
        review.append(db, 'c', batch, RejudgeReview.model_validate(body_for(db, batch, request_id='after-apply')), env.admin)
    with env.factory() as db:
        assert review.read(db, 'c', batch)['applicationProvenance'] == provenance


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['no_reviews', 'old_fingerprint', 'legacy_basis', 'mutated_snapshot'])
async def test_old_missing_or_mismatched_evidence_never_approves_correction(env, seeded, monkeypatch, mutation):
    batch, request = await ready(env, seeded, monkeypatch)
    with env.factory() as db:
        row = db.get(m.ContestRejudgeBatch, batch)
        if mutation == 'no_reviews': db.query(m.ContestRejudgeReviewEvent).delete()
        elif mutation == 'old_fingerprint':
            db.query(m.ContestRejudgeReviewEvent).update({'fingerprint':row.review_basis['beforeFingerprint']})
        elif mutation == 'legacy_basis': row.review_basis = None
        else: row.snapshot = {**row.snapshot, 'description':'Unexpected frozen data modification'}
        db.commit()
    with env.factory() as db:
        preview = service.preview_candidate(db, 'c', batch)
        assert preview['reviewBlocked']
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate({**request, 'expectedPreviewHash':preview['previewHash']}), env.admin)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_review_api_admin_only_stale_targets_idempotency_and_private_data(env, seeded, monkeypatch):
    monkeypatch.setattr(problem_authoring, 'now_utc', lambda:env.clock[0])
    batch, _ = await ready(env, seeded, monkeypatch)
    path = f'/api/v1/contests/c/rejudges/{batch}/reviews'
    with env.factory() as db: payload = body_for(db, batch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for auth, status in (({}, 401), (headers(env.alice), 403)):
            assert (await client.get(path, headers=auth)).status_code == status
            assert (await client.post(path, json=payload, headers=auth)).status_code == status
        auth = headers(env.admin)
        current = await client.get(path, headers=auth)
        assert current.status_code == 200 and current.headers['Cache-Control'] == 'no-store'
        assert current.json()['snapshot']['hidden'][0]['input'] == 'corrected-private-input'
        for key in ('expectedRequestHash', 'expectedFingerprint'):
            rejected = await client.post(path, json={**payload, key:'sha256:'+'f'*64}, headers=auth)
            assert rejected.status_code == 409
        assert (await client.post(path.replace('/c/', '/other/'), json=payload, headers=auth)).status_code == 404
        first = await client.post(path, json=payload, headers=auth)
        assert first.status_code == 200 and first.headers['Cache-Control'] == 'no-store'
        repeat = await client.post(path, json=payload, headers=auth)
        assert first.json() == repeat.json()
        assert (await client.post(path, json={**payload, 'decision':'approved'}, headers=auth)).status_code == 409
        assert (await client.post(path, json={**payload, 'category':'score'}, headers=auth)).status_code == 422
        public = await client.get('/api/v1/contests/c')
        assert 'Synthetic review evidence' not in public.text and 'corrected-private-input' not in public.text
    with env.factory() as db:
        assert db.query(m.ContestRejudgeReviewEvent).count() == 5
        # Original started source remains locked; candidate reviews did not weaken it.
        with pytest.raises(service.HTTPException): problem_authoring.require_problem(db, 'p', editable=True)
        with pytest.raises(service.HTTPException) as error:
            review.append(db, 'c', batch, RejudgeReview.model_validate(payload), env.alice)
        assert error.value.status_code == 403


@pytest.mark.parametrize('failure', ['missing_metadata', 'pending_source', 'no_assets', 'missing_language'])
def test_candidate_review_evidence_validation(env, seeded, failure):
    data = deepcopy(seeded)
    meta = package_body(env)['entries'][0]['metadata']
    meta['sources'][0].update(reuseBasis='original', reuseEvidence='Synthetic only')
    category = 'tests'
    if failure != 'missing_metadata': data['authoring'] = meta
    if failure == 'pending_source':
        category = 'sources'; meta['sources'][0]['reuseBasis'] = 'pending'
    elif failure == 'no_assets': meta['assets'] = []
    elif failure == 'missing_language':
        category = 'resources'; meta['requiredLanguages'].append('java')
    batch = create(env, data)['id']
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        review.append(db, 'c', batch, RejudgeReview.model_validate(body_for(db, batch,
            category=category, decision='approved')), env.admin)
    assert error.value.status_code == 409
    with env.factory() as db: assert db.query(m.ContestRejudgeReviewEvent).count() == 0


def test_metadata_cannot_be_silently_removed_and_candidate_is_frozen(env, seeded):
    with pytest.raises(ValueError): RejudgeCreate.model_validate({**seeded, 'authoring':None})
    meta = package_body(env)['entries'][0]['metadata']
    data = {**seeded, 'authoring':meta}
    batch = create(env, data)['id']
    with env.factory() as db:
        assert review.read(db, 'c', batch)['metadata']['adaptationNotes'] == meta['adaptationNotes']
        assert db.get(m.Problem, 'p').test_cases['sample'][0]['expectedOutput'] == '42'
        assert db.get(m.ProblemAuthoring, 'p') is None
    meta['adaptationNotes'] = 'Changed payload after submission'
    with env.factory() as db: assert review.read(db, 'c', batch)['metadata']['adaptationNotes'] != meta['adaptationNotes']


@pytest.mark.asyncio
async def test_additive_migration_keeps_historical_provenance_unknown(env, seeded, monkeypatch):
    batch, request = await ready(env, seeded, monkeypatch)
    with env.factory() as db:
        service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(request), env.admin)
        audit = db.get(m.ContestRejudgeApplication, batch)
        original = {c.name:deepcopy(getattr(audit, c.name)) for c in audit.__table__.columns if c.name != 'review_provenance'}
    engine = env.db.get_bind()
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE contest_rejudge_applications DROP COLUMN review_provenance'))
        conn.execute(text('ALTER TABLE contest_rejudge_batches DROP COLUMN review_basis'))
    migrate_schema(engine); migrate_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT review_provenance FROM contest_rejudge_applications')).scalar() is None
        assert conn.execute(text('SELECT review_basis FROM contest_rejudge_batches')).scalar() is None
    assert 'review_provenance' in {c['name'] for c in inspect(engine).get_columns('contest_rejudge_applications')}
    with env.factory() as db:
        audit = db.get(m.ContestRejudgeApplication, batch)
        assert {name:getattr(audit,name) for name in original} == original
        assert review.read(db, 'c', batch)['applicationProvenance'] is None
        assert service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(request), env.admin)['status'] == 'applied'
        assert audit.review_provenance is None


@pytest.mark.asyncio
async def test_two_sessions_idempotent_review_and_latest_decision_sequence(env, seeded, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    batch, _ = await ready(env, seeded, monkeypatch)
    with env.factory() as db: payload = body_for(db, batch)
    barrier = Barrier(2)
    def attempt():
        barrier.wait(timeout=10)
        with env.factory() as db:
            return review.append(db, 'c', batch, RejudgeReview.model_validate(payload), env.admin)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert results[0] == results[1]
    with env.factory() as db:
        assert db.query(m.ContestRejudgeReviewEvent).filter_by(request_id=payload['requestId']).count() == 1
        assert review.state(db, db.get(m.ContestRejudgeBatch, batch))['categories']['tests'] == 'rejected'


@pytest.mark.asyncio
async def test_apply_rechecks_runtime_evidence_after_approval(env, seeded, monkeypatch):
    batch, request = await ready(env, seeded, monkeypatch)
    def invalid(*_, **__): raise ValueError('Synthetic runtime evidence unavailable')
    monkeypatch.setattr(problem_authoring, 'validate_stored_publication', invalid)
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(request), env.admin)
    assert error.value.status_code == 409
    with env.factory() as db:
        assert db.get(m.User,'alice').total_score == 120
        assert db.query(m.ContestRejudgeApplication).count() == 0


@pytest.mark.asyncio
async def test_concurrent_rejection_and_apply_have_one_serial_order(env, seeded, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    batch, request = await ready(env, seeded, monkeypatch)
    with env.factory() as db: rejection = body_for(db, batch)
    barrier = Barrier(2)
    def attempt(kind):
        barrier.wait(timeout=10)
        with env.factory() as db:
            try:
                if kind == 'apply': service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(request), env.admin)
                else: review.append(db, 'c', batch, RejudgeReview.model_validate(rejection), env.admin)
                return 200
            except service.HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, kind) for kind in ('apply', 'reject')]
        applied, rejected = [f.result(timeout=15) for f in futures]
    assert (applied, rejected) in ((200, 409), (409, 200))
    with env.factory() as db:
        audit = db.get(m.ContestRejudgeApplication, batch)
        decision = review.state(db, db.get(m.ContestRejudgeBatch, batch))['categories']['tests']
        if applied == 200:
            assert audit is not None and decision == 'approved'
            assert db.get(m.User,'alice').total_score == 0
        else:
            assert audit is None and decision == 'rejected'
            assert db.get(m.User,'alice').total_score == 120
