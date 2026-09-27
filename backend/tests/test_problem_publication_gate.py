"""Generic problem drafts must cross the same exact authoring gate as contests."""
from copy import deepcopy
import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import database as m
from app.services import problem_authoring
from app.services.execution_results import publish_result
from app.services.judge_policy import content_hash, freeze_stored_submission
from app.services.rating import difficulty_value, solved_count_bonus
from app.core.config import settings
from tests.test_contests import env, headers, payload
from tests.test_judge_metrics import full_report


def _problem_body(fixture):
    return deepcopy(payload(fixture)['problems'][0]['newProblem'])


async def _create_draft(client, fixture):
    response = await client.post(
        '/api/v1/problems/',
        headers=headers(fixture.admin),
        json=_problem_body(fixture),
    )
    assert response.status_code == 200, response.text
    assert response.json()['publicationStatus'] == 'draft'
    return response.json()


async def _install_metadata_and_reviews(client, fixture, problem_id, source):
    digest = 'sha256:' + hashlib.sha256(source.encode('utf-8')).hexdigest()
    url = f'/api/v1/problems/{problem_id}/authoring'
    current = (await client.get(url, headers=headers(fixture.admin))).json()
    metadata = {
        'sources': [{
            'url': 'https://example.invalid/synthetic-problem',
            'title': 'Synthetic problem fixture',
            'reuseBasis': 'original',
            'reuseEvidence': 'Created only for this publication gate test.',
        }],
        'adaptationNotes': 'Synthetic publication gate fixture.',
        'requiredLanguages': ['python'],
        'assets': [
            {'role': 'reference', 'name': 'reference.py', 'digest': digest, 'language': 'python'},
            {'role': 'validator', 'name': 'validator.py', 'digest': 'sha256:' + 'b' * 64},
            {'role': 'generator', 'name': 'generator.py', 'digest': 'sha256:' + 'c' * 64},
            {'role': 'wrong_solution', 'name': 'wrong.py', 'digest': 'sha256:' + 'd' * 64},
        ],
    }
    saved = await client.put(url, headers=headers(fixture.admin), json={
        'expectedFingerprint': current['fingerprint'],
        'metadata': metadata,
    })
    assert saved.status_code == 200, saved.text
    current = saved.json()
    for category in problem_authoring.CATEGORIES:
        reviewed = await client.post(url + '/reviews', headers=headers(fixture.admin), json={
            'requestId': f'generic-{category}-{current["fingerprint"][-8:]}',
            'expectedFingerprint': current['fingerprint'],
            'category': category,
            'decision': 'approved',
            'note': f'Synthetic {category} approval.',
        })
        assert reviewed.status_code == 200, reviewed.text
    return current, digest


@pytest.mark.asyncio
async def test_new_generic_problem_is_private_and_cannot_enter_contest_before_review(env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        draft = await _create_draft(client, env)
        problem_id = draft['id']

        public_list = await client.get('/api/v1/problems/')
        assert public_list.status_code == 200
        assert all(item['id'] != problem_id for item in public_list.json())
        assert (await client.get(f'/api/v1/problems/{problem_id}')).status_code == 404
        admin_read = await client.get(
            f'/api/v1/problems/{problem_id}', headers=headers(env.admin)
        )
        assert admin_read.status_code == 200
        assert admin_read.json()['publicationStatus'] == 'draft'
        assert admin_read.headers['cache-control'] == 'no-store'

        contest = payload(env)
        contest['published'] = False
        contest['problems'] = [{'problemId': problem_id, 'points': 500}]
        blocked = await client.post(
            '/api/v1/contests', headers=headers(env.admin), json=contest
        )
        assert blocked.status_code == 400
        with env.factory() as db:
            assert db.query(m.Contest).count() == 0


@pytest.mark.asyncio
async def test_generic_problem_requires_current_reviews_and_exact_reference_attestation(env):
    source = 'print(42)'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        draft = await _create_draft(client, env)
        problem_id = draft['id']
        auth = headers(env.admin)
        publish_url = f'/api/v1/problems/{problem_id}/publish'

        missing_metadata = await client.post(publish_url, headers=auth)
        assert missing_metadata.status_code == 409
        assert '출처' in missing_metadata.text

        authoring, digest = await _install_metadata_and_reviews(
            client, env, problem_id, source
        )
        # A proof produced for another scope must not be replayable as the
        # generic problem's publication evidence, even when all content hashes
        # happen to match.
        with env.factory() as db:
            problem = db.get(m.Problem, problem_id)
            snapshot = problem_authoring.current_snapshot(db, problem)
            contract = freeze_stored_submission(
                snapshot['judgePolicy'],
                'python',
                snapshot['sample'],
                snapshot['hidden'],
                settings=settings,
            )
            db.add(m.ProblemValidationAttestation(
                job_id='wrong-scope-generic-proof',
                problem_id=problem_id,
                contest_id='another-contest',
                contest_problem_id='another-contest-problem',
                problem_snapshot_hash=content_hash(snapshot),
                authoring_fingerprint=problem_authoring.fingerprint(snapshot),
                language='python',
                source_hash=digest,
                reference_asset_digest=digest,
                policy_hash=contract['policyHash'],
                test_suite_hash=contract['testSuiteHash'],
            ))
            db.commit()
        missing_run = await client.post(publish_url, headers=auth)
        assert missing_run.status_code == 409
        assert '전체 테스트 통과' in missing_run.text

        validation_url = f'/api/v1/problems/{problem_id}/authoring-validations'
        request = {
            'code': source,
            'language': 'python',
            'requestId': 'generic-reference-v1',
            'expectedFingerprint': authoring['fingerprint'],
            'referenceAssetDigest': digest,
        }
        assert (await client.post(validation_url, json=request)).status_code == 401
        assert (
            await client.post(validation_url, headers=headers(env.alice), json=request)
        ).status_code == 403
        queued = await client.post(validation_url, headers=auth, json=request)
        assert queued.status_code == 202, queued.text
        receipt = queued.json()
        assert receipt['sourceHash'] == digest
        assert source not in queued.text and 'secret-input' not in queued.text

        with env.factory() as db:
            job = db.get(m.ExecutionJob, receipt['id'])
            assert job.payload['contest_id'] == '__problem__'
            assert job.payload['contest_problem_id'] == problem_id
            publish_result(db, job.id, {
                'verdict': 'accepted',
                'value': {'_resource_report': full_report(job.payload)},
            })
            db.commit()
            proof = db.get(m.ProblemValidationAttestation, job.id)
            assert proof.problem_id == problem_id
            assert proof.contest_id == '__problem__'

        published = await client.post(publish_url, headers=auth)
        assert published.status_code == 200, published.text
        assert published.json()['publicationStatus'] == 'published'
        assert (await client.get(f'/api/v1/problems/{problem_id}')).status_code == 200
        assert any(
            item['id'] == problem_id
            for item in (await client.get('/api/v1/problems/')).json()
        )

        edited = _problem_body(env)
        edited['description'] = 'A new exact content version.'
        changed = await client.put(
            f'/api/v1/problems/{problem_id}', headers=auth, json=edited
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()['publicationStatus'] == 'draft'
        assert (await client.get(f'/api/v1/problems/{problem_id}')).status_code == 404
        assert all(
            item['id'] != problem_id
            for item in (await client.get('/api/v1/problems/')).json()
        )
        stale = await client.post(publish_url, headers=auth)
        assert stale.status_code == 409
        assert '검수' in stale.text or '통과' in stale.text


@pytest.mark.asyncio
async def test_editing_solved_public_problem_hides_draft_from_rating_and_profile(env):
    body = _problem_body(env)
    problem_id = 'solved-public-problem-edited-to-draft'
    with env.factory() as db:
        problem = m.Problem(
            id=problem_id,
            creator_id=env.admin.id,
            title='Previously public problem',
            difficulty='ruby1',
            tags=['published-tag'],
            description=body['description'],
            points=body['points'],
            test_cases={
                'sample': body['testCases'],
                'hidden': body['hiddenTestCases'],
            },
            judge_policy=body['judgePolicy'],
            publication_review_required=None,
            publication_approved_at=None,
        )
        db.add(problem)
        db.add(m.UserProblemScore(
            user_id=env.alice.id,
            challenge_id=problem_id,
            points_awarded=body['points'],
        ))
        db.query(m.User).filter_by(id=env.alice.id).update({
            m.User.total_score: m.User.total_score + body['points'],
        })
        db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        before = await client.get('/api/v1/auth/me', headers=headers(env.alice))
        assert before.status_code == 200
        assert before.json()['rating'] == difficulty_value('ruby1') + solved_count_bonus(1)
        assert before.json()['topDifficulties'] == ['ruby1']
        assert {item['tag'] for item in before.json()['tagProficiencies']} == {'published-tag'}

        body['title'] = 'Private revised title'
        body['difficulty'] = 'gold1'
        body['tags'] = ['private-revised-tag']
        changed = await client.put(
            f'/api/v1/problems/{problem_id}',
            headers=headers(env.admin),
            json=body,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()['publicationStatus'] == 'draft'

        after = await client.get('/api/v1/auth/me', headers=headers(env.alice))
        assert after.status_code == 200
        assert after.json()['rating'] == 0
        assert after.json()['solvedCount'] == 0
        assert after.json()['topDifficulties'] == []
        assert after.json()['tagProficiencies'] == []

        leaderboard = await client.get('/api/v1/problems/leaderboard?limit=100')
        assert leaderboard.status_code == 200
        alice = next(row for row in leaderboard.json() if row['username'] == env.alice.username)
        assert alice['rating'] == 0
        assert alice['solvedCount'] == 0


@pytest.mark.asyncio
async def test_pre_gate_legacy_problem_remains_public_without_inferred_review(env):
    body = _problem_body(env)
    with env.factory() as db:
        legacy = m.Problem(
            id='legacy-public-problem',
            creator_id=env.admin.id,
            title=body['title'],
            difficulty=body['difficulty'],
            tags=body['tags'],
            description=body['description'],
            points=body['points'],
            test_cases={
                'sample': body['testCases'],
                'hidden': body['hiddenTestCases'],
            },
            judge_policy=body['judgePolicy'],
            publication_review_required=None,
            publication_approved_at=None,
        )
        db.add(legacy)
        db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        visible = await client.get('/api/v1/problems/legacy-public-problem')
        assert visible.status_code == 200
        assert visible.json()['publicationStatus'] == 'legacy'
        with env.factory() as db:
            assert db.get(m.ProblemAuthoring, 'legacy-public-problem') is None
            assert db.query(m.ProblemReviewEvent).filter_by(
                problem_id='legacy-public-problem'
            ).count() == 0
