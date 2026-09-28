"""Audited legacy-award decisions; synthetic correction execution only."""
import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.models import database as m
from app.models.contest_rejudge import LegacySolveResolutionWrite, RejudgeApply
from app.services import contest_rejudge as service, legacy_solve_resolution
from tests.test_rejudge_apply import env, seeded, ready, headers


async def context(env, seeded, monkeypatch):
    batch, apply_body = await ready(env, seeded, monkeypatch, tracked=False)
    path = f'/api/v1/contests/c/rejudges/{batch}/legacy-resolutions'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get(path, headers=headers(env.admin))
    assert response.status_code == 200
    candidate = response.json()['candidates'][0]
    return batch, apply_body, path, candidate


@pytest.mark.asyncio
async def test_explicit_retain_is_idempotent_audited_and_keeps_legacy_award(env, seeded, monkeypatch):
    batch, apply_body, path, candidate = await context(env, seeded, monkeypatch)
    request = dict(requestId='retain-old-award', expectedRequestHash=apply_body['expectedRequestHash'],
        userId='alice', expectedLegacyFingerprint=candidate['legacyFingerprint'],
        decision='retain_unattributed', note='기존 점수의 출처는 확인할 수 없어 이번 정정에서도 명시적으로 유지합니다.')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get(path)).status_code == 401
        assert (await client.post(path, headers=headers(env.alice), json=request)).status_code == 403
        first = await client.post(path, headers=headers(env.admin), json=request)
        assert first.status_code == 200 and first.headers['Cache-Control'] == 'no-store'
        assert all(secret not in first.text for secret in ('print(42)', 'private-rejudge-input', 'corrected-private-input'))
        assert (await client.post(path, headers=headers(env.admin), json=request)).json() == first.json()
        changed = {**request, 'decision':'link_verified_receipt', 'sourceKind':'contest', 'sourceId':'s0'}
        assert (await client.post(path, headers=headers(env.admin), json=changed)).status_code == 409
    with env.factory() as db:
        preview = service.preview_candidate(db, 'c', batch)
        assert preview['blockedCount'] == 0
        assert next(row for row in preview['rows'] if row['userId'] == 'alice')['practicePointDelta'] == 0
        apply_body['expectedPreviewHash'] = preview['previewHash']
        service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(apply_body), env.admin)
    with env.factory() as db:
        assert db.get(m.User, 'alice').total_score == 120
        assert db.query(m.UserProblemScore).filter_by(user_id='alice', challenge_id='p').one().points_awarded == 120
        audit = db.get(m.ContestRejudgeApplication, batch)
        assert [item['decision'] for item in audit.legacy_resolution_provenance] == ['retain_unattributed']
        assert 'code' not in str(audit.legacy_resolution_provenance).lower()


@pytest.mark.asyncio
async def test_verified_contest_receipt_link_allows_exactly_one_safe_revoke(env, seeded, monkeypatch):
    batch, apply_body, path, candidate = await context(env, seeded, monkeypatch)
    request = dict(requestId='link-old-award', expectedRequestHash=apply_body['expectedRequestHash'],
        userId='alice', expectedLegacyFingerprint=candidate['legacyFingerprint'],
        decision='link_verified_receipt', sourceKind='contest', sourceId='s0',
        note='기존 점수는 이 대회 정답 영수증에서 지급된 것으로 원본 기록과 대조했습니다.')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post(path, headers=headers(env.admin), json=request)
        assert response.status_code == 200, response.text
    with env.factory() as db:
        preview = service.preview_candidate(db, 'c', batch)
        assert preview['blockedCount'] == 0
        assert next(row for row in preview['rows'] if row['userId'] == 'alice')['practicePointDelta'] == -120
        apply_body['expectedPreviewHash'] = preview['previewHash']
        service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(apply_body), env.admin)
    with env.factory() as db:
        assert db.get(m.User, 'alice').total_score == 0
        assert db.query(m.UserProblemScore).filter_by(user_id='alice', challenge_id='p').count() == 0
        assert db.query(m.LegacySolveResolution).count() == 1
        assert db.query(m.ContestRejudgeApplication).count() == 1
        assert db.get(m.ContestRejudgeApplication, batch).score_changes[0]['delta'] == -120


@pytest.mark.asyncio
async def test_verified_independent_practice_receipt_preserves_the_award(env, seeded, monkeypatch):
    batch, apply_body, path, candidate = await context(env, seeded, monkeypatch)
    with env.factory() as db:
        db.add(m.Submission(id='old-independent-practice', user_id='alice', problem_id='p',
            language='python', code='print(42)', status='Accepted', verdict='accepted',
            grading_completed=True, grading_passed=True, awarded_points=120, created_at=env.clock[0]))
        db.commit()
    request = dict(requestId='link-independent-practice', expectedRequestHash=apply_body['expectedRequestHash'],
        userId='alice', expectedLegacyFingerprint=candidate['legacyFingerprint'],
        decision='link_verified_receipt', sourceKind='practice', sourceId='old-independent-practice',
        note='보존된 일반 문제 정답 영수증이 같은 사용자·문제·배점임을 확인했습니다.')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post(path, headers=headers(env.admin), json=request)
        assert response.status_code == 200, response.text
    with env.factory() as db:
        preview = service.preview_candidate(db, 'c', batch)
        assert preview['blockedCount'] == 0
        assert next(row for row in preview['rows'] if row['userId'] == 'alice')['practicePointDelta'] == 0
        apply_body['expectedPreviewHash'] = preview['previewHash']
        service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(apply_body), env.admin)
    with env.factory() as db:
        assert db.get(m.User, 'alice').total_score == 120
        assert db.query(m.UserProblemScore).filter_by(user_id='alice', challenge_id='p').count() == 1


@pytest.mark.asyncio
async def test_mismatched_or_mutated_receipt_never_unlocks_application(env, seeded, monkeypatch):
    batch, apply_body, path, candidate = await context(env, seeded, monkeypatch)
    request = dict(requestId='bad-link', expectedRequestHash=apply_body['expectedRequestHash'],
        userId='alice', expectedLegacyFingerprint=candidate['legacyFingerprint'],
        decision='link_verified_receipt', sourceKind='contest', sourceId='s1',
        note='다른 참가자의 영수증은 과거 점수의 출처로 연결되어서는 안 됩니다.')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        rejected = await client.post(path, headers=headers(env.admin), json=request)
        assert rejected.status_code == 409
        valid = {**request, 'requestId':'good-link', 'sourceId':'s0'}
        assert (await client.post(path, headers=headers(env.admin), json=valid)).status_code == 200
    with env.factory() as db:
        db.get(m.ContestSubmission, 's0').code = 'mutated after explicit resolution'
        db.commit()
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        service.preview_candidate(db, 'c', batch)
    assert error.value.status_code == 409
    with env.factory() as db:
        assert db.get(m.User, 'alice').total_score == 120
        assert db.get(m.ContestSubmission, 's0').verdict == 'accepted'
        assert db.query(m.ContestRejudgeApplication).count() == 0


@pytest.mark.asyncio
async def test_concurrent_duplicate_resolution_and_stale_apply_are_serialized(env, seeded, monkeypatch):
    batch, apply_body, _path, candidate = await context(env, seeded, monkeypatch)
    request = LegacySolveResolutionWrite.model_validate(dict(
        requestId='concurrent-retain', expectedRequestHash=apply_body['expectedRequestHash'],
        userId='alice', expectedLegacyFingerprint=candidate['legacyFingerprint'],
        decision='retain_unattributed',
        note='동시 요청에서도 동일한 과거 점수 유지 결정 하나만 기록합니다.'))
    barrier = Barrier(3)

    def resolve():
        barrier.wait(timeout=10)
        with env.factory() as db:
            return legacy_solve_resolution.append(db, 'c', batch, request, env.admin)

    def apply_stale():
        barrier.wait(timeout=10)
        with env.factory() as db:
            try:
                service.apply_candidate(db, 'c', batch, RejudgeApply.model_validate(apply_body), env.admin)
                return 200
            except service.HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(resolve), pool.submit(resolve), pool.submit(apply_stale)]
        results = [future.result(timeout=20) for future in futures]
    assert results[2] == 409
    with env.factory() as db:
        assert db.query(m.LegacySolveResolution).count() == 1
        assert db.query(m.ContestRejudgeApplication).count() == 0
        assert db.get(m.User, 'alice').total_score == 120
        preview = service.preview_candidate(db, 'c', batch)
        apply_body['expectedPreviewHash'] = preview['previewHash']
        assert service.apply_candidate(db, 'c', batch,
            RejudgeApply.model_validate(apply_body), env.admin)['status'] == 'applied'
    with env.factory() as db:
        assert db.query(m.LegacySolveResolution).count() == 1
        assert db.query(m.ContestRejudgeApplication).count() == 1
        assert db.get(m.User, 'alice').total_score == 120
# End of test module.
@pytest.mark.asyncio
async def test_stale_legacy_fingerprint_blocks_after_resolution(env, seeded, monkeypatch):
    batch, apply_body, path, candidate = await context(env, seeded, monkeypatch)
    request = dict(requestId='stale-legacy', expectedRequestHash=apply_body['expectedRequestHash'],
        userId='alice', expectedLegacyFingerprint=candidate['legacyFingerprint'],
        decision='retain_unattributed', note='과거 점수 원장의 현재 지문을 검토하고 유지 결정을 기록합니다.')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post(path, headers=headers(env.admin), json=request)).status_code == 200
    with env.factory() as db:
        db.query(m.SolveEvidence).filter_by(user_id='alice', problem_id='p', source_kind='legacy').one().points += 1
        db.commit()
    with env.factory() as db, pytest.raises(service.HTTPException) as error:
        service.preview_candidate(db, 'c', batch)
    assert error.value.status_code == 409
    with env.factory() as db:
        assert db.query(m.ContestRejudgeApplication).count() == 0
        assert db.get(m.User, 'alice').total_score == 120

# End of test module.
