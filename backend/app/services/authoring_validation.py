"""Private, no-score reference-solution checks for saved contest drafts."""
from copy import deepcopy
import hashlib

from fastapi import HTTPException

from app.core.config import settings
from app.models import database as m
from app.models.problem_authoring import AuthoringMetadata
from app.services.contest_access import iso, now_utc, utc_naive
from app.services.durable_queue import (
    EXECUTION_EXPIRED_MESSAGE,
    ExecutionExpired,
    IdempotencyConflict,
    QueueFull,
)
from app.services.judge_policy import UNREVIEWED, content_hash, freeze_stored_submission
from app.services.judge_test_manifest import validate_stored_cases
from app.services.problem_authoring import current_snapshot, fingerprint


KIND = 'authoring-validation-v1'
PROBLEM_SCOPE = '__problem__'


def _owner(user) -> str:
    return f'authoring:{user.id}'


def _request_id(contest_id: str, contest_problem_id: str, request_id: str) -> str:
    value = f'{contest_id}:{contest_problem_id}:{request_id}'.encode('utf-8')
    return 'authoring:' + hashlib.sha256(value).hexdigest()


def _rejudge_request_id(contest_id: str, batch_id: str, request_id: str) -> str:
    value = f'{contest_id}:rejudge:{batch_id}:{request_id}'.encode('utf-8')
    return 'authoring:' + hashlib.sha256(value).hexdigest()


def _problem_request_id(problem_id: str, request_id: str) -> str:
    value = f'problem:{problem_id}:{request_id}'.encode('utf-8')
    return 'authoring:' + hashlib.sha256(value).hexdigest()


def _projection(job) -> dict:
    if job.content_expired_at is not None:
        raise HTTPException(410, EXECUTION_EXPIRED_MESSAGE, headers={'Cache-Control': 'no-store'})
    payload = job.payload if isinstance(job.payload, dict) else {}
    contract = payload.get('judge_contract') if isinstance(payload.get('judge_contract'), dict) else {}
    raw = job.result if isinstance(job.result, dict) else None
    result = None
    if raw is not None:
        value = raw.get('value') if isinstance(raw.get('value'), dict) else {}
        result = {
            'verdict': raw.get('verdict', 'system_error'),
            'resourceUsage': value.get('resource_usage'),
        }
        if raw.get('verdict') == 'system_error':
            result['error'] = '검증 실행을 완료하지 못했습니다.'
    return {
        'id': job.id,
        'status': job.status,
        'receivedAt': iso(job.received_at),
        'finishedAt': iso(job.finished_at) if job.finished_at else None,
        'language': payload.get('language'),
        'sourceHash': payload.get('source_hash'),
        'authoringFingerprint': payload.get('authoring_fingerprint'),
        'referenceAssetDigest': payload.get('reference_asset_digest'),
        'problemSnapshotHash': payload.get('problem_snapshot_hash'),
        'policyHash': contract.get('policyHash'),
        'testSuiteHash': contract.get('testSuiteHash'),
        'result': result,
    }


def _create(db, *, contest_id, contest_problem_id, snapshot, problem_id, data, user, queue,
            request_id, rejudge_batch_id=None):
    """Admit one exact server-owned snapshot without participant or score side effects."""
    received = now_utc()
    source_hash = 'sha256:' + hashlib.sha256(data.code.encode('utf-8')).hexdigest()
    previous = db.query(m.ExecutionJob).filter_by(
        owner_key=_owner(user), request_id=request_id
    ).first()
    if previous is not None:
        if previous.content_expired_at is not None:
            return _projection(previous)  # Raises the durable 410 response.
        prior = previous.payload if isinstance(previous.payload, dict) else {}
        expected = {
            'contest_id': contest_id,
            'contest_problem_id': contest_problem_id,
            'language': data.language,
            'source_hash': source_hash,
            'authoring_fingerprint': data.expected_fingerprint,
            'reference_asset_digest': data.reference_asset_digest,
            'rejudge_batch_id': rejudge_batch_id,
        }
        if previous.kind != KIND or any(prior.get(key) != value for key, value in expected.items()):
            raise HTTPException(409, '동일 요청 ID에 다른 검증 코드를 사용할 수 없습니다.')
        return _projection(previous)
    if not data.code.strip() or len(data.code.encode('utf-8')) > settings.SUBMISSION_CODE_MAX_BYTES:
        raise HTTPException(400, '코드가 비어 있거나 제출 크기 제한을 초과했습니다.')

    snapshot = deepcopy(snapshot)
    current_fingerprint = fingerprint(snapshot)
    if current_fingerprint != data.expected_fingerprint:
        raise HTTPException(409, '문제가 변경되었습니다. 최신 내용을 다시 확인하세요.')
    try:
        metadata = AuthoringMetadata.model_validate(snapshot.get('authoring'))
    except ValueError:
        raise HTTPException(409, '출처와 기준 풀이 파일 지문을 먼저 저장하세요.') from None
    matching_reference = any(
        asset.role == 'reference'
        and asset.language == data.language
        and asset.digest == data.reference_asset_digest
        for asset in metadata.assets
    )
    if not matching_reference:
        raise HTTPException(409, '선택한 언어의 기준 풀이 파일 지문을 확인하세요.')
    if source_hash != data.reference_asset_digest:
        raise HTTPException(409, '기준 풀이 코드가 등록된 파일 지문과 다릅니다.')
    policy = snapshot.get('judgePolicy')
    if policy in (None, UNREVIEWED):
        raise HTTPException(409, '측정·검수된 언어별 채점 제한을 먼저 저장하세요.')
    try:
        validate_stored_cases(db, snapshot.get('sample', []), snapshot.get('hidden', []), integrity=True)
        contract = freeze_stored_submission(
            policy,
            data.language,
            snapshot.get('sample', []),
            snapshot.get('hidden', []),
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    if contract.get('kind') != 'measured-v1':
        raise HTTPException(409, '검증된 측정 정책만 출제 검증에 사용할 수 있습니다.')

    snapshot_hash = content_hash(snapshot)
    payload = {
        'authoring_validation_version': 1,
        'contest_id': contest_id,
        'contest_problem_id': contest_problem_id,
        'problem_id': problem_id,
        'problem_snapshot_hash': snapshot_hash,
        'authoring_fingerprint': current_fingerprint,
        'reference_asset_digest': data.reference_asset_digest,
        'source_hash': source_hash,
        'code': data.code,
        'language': data.language,
        'sample': snapshot.get('sample', []),
        'hidden': snapshot.get('hidden', []),
        'judge_contract': contract,
    }
    if rejudge_batch_id is not None:
        payload['rejudge_batch_id'] = rejudge_batch_id
    try:
        job = queue.enqueue_in_session(
            db,
            owner_key=_owner(user),
            quota_key=f'account:{user.id}',
            request_id=request_id,
            kind=KIND,
            payload=payload,
            at=received,
        )
    except QueueFull:
        raise HTTPException(429, '실행 대기열이 가득 찼습니다.', headers={'Retry-After': '5'}) from None
    except ExecutionExpired:
        raise HTTPException(410, EXECUTION_EXPIRED_MESSAGE, headers={'Cache-Control': 'no-store'}) from None
    except IdempotencyConflict:
        raise HTTPException(409, '동일 요청 ID에 다른 검증 코드를 사용할 수 없습니다.') from None
    except ValueError:
        raise HTTPException(413, '검증 요청이 너무 큽니다.') from None
    db.commit()
    return _projection(job)


def create(db, *, contest_id, contest_problem_id, data, user, queue):
    """Admit one exact saved draft without participant or score side effects."""
    queue._lock(db)  # Same serialization order as contest edits and publication.
    contest = db.query(m.Contest).filter_by(id=contest_id).first()
    if contest is None:
        raise HTTPException(404, '대회를 찾을 수 없습니다.')
    if contest.published and utc_naive(contest.starts_at) <= now_utc():
        raise HTTPException(409, '시작한 대회의 출제 검증은 실행할 수 없습니다.')
    problem = db.query(m.ContestProblem).filter_by(
        id=contest_problem_id, contest_id=contest_id
    ).first()
    if problem is None:
        raise HTTPException(404, '문제를 찾을 수 없습니다.')
    return _create(db, contest_id=contest_id, contest_problem_id=contest_problem_id,
        snapshot=problem.snapshot, problem_id=problem.problem_id, data=data, user=user, queue=queue,
        request_id=_request_id(contest_id, contest_problem_id, data.request_id))


def create_problem(db, *, problem_id, data, user, queue):
    """Validate one exact administrator-only practice problem draft."""
    queue._lock(db)
    problem = db.query(m.Problem).filter_by(id=problem_id).first()
    if problem is None or problem.deleted_at is not None:
        raise HTTPException(404, '문제를 찾을 수 없습니다.')
    if problem.publication_review_required is not True:
        raise HTTPException(409, '기존 공개 문제는 별도의 출제 검증이 필요하지 않습니다.')
    snapshot = current_snapshot(db, problem)
    return _create(
        db,
        contest_id=PROBLEM_SCOPE,
        contest_problem_id=problem_id,
        snapshot=snapshot,
        problem_id=problem_id,
        data=data,
        user=user,
        queue=queue,
        request_id=_problem_request_id(problem_id, data.request_id),
    )


def create_rejudge(db, *, contest_id, batch_id, data, user, queue):
    """Admit the immutable correction snapshot, never the currently live problem."""
    queue._lock(db)  # Fence apply/discard before reading candidate status/snapshot.
    batch = db.query(m.ContestRejudgeBatch).filter_by(id=batch_id, contest_id=contest_id).first()
    if batch is None:
        raise HTTPException(404, '재채점 기록을 찾을 수 없습니다.')
    if batch.status not in ('pending', 'running', 'ready'):
        raise HTTPException(409, '검증할 수 없는 재채점 후보입니다.')
    problem = db.query(m.ContestProblem).filter_by(
        id=batch.contest_problem_id, contest_id=contest_id
    ).first()
    if problem is None:
        raise HTTPException(404, '대회 문제를 찾을 수 없습니다.')
    return _create(db, contest_id=contest_id, contest_problem_id=problem.id,
        snapshot=batch.snapshot, problem_id=problem.problem_id, data=data, user=user, queue=queue,
        request_id=_rejudge_request_id(contest_id, batch_id, data.request_id),
        rejudge_batch_id=batch_id)


def read(db, *, contest_id, contest_problem_id, job_id, user):
    job = db.query(m.ExecutionJob).filter_by(
        id=job_id, owner_key=_owner(user), kind=KIND
    ).first()
    if job is None:
        raise HTTPException(404, '출제 검증 기록을 찾을 수 없습니다.')
    if job.content_expired_at is not None:
        return _projection(job)  # Raises the durable 410 receipt response.
    payload = job.payload if job is not None and isinstance(job.payload, dict) else {}
    if (
        payload.get('contest_id') != contest_id
        or payload.get('contest_problem_id') != contest_problem_id
    ):
        raise HTTPException(404, '출제 검증 기록을 찾을 수 없습니다.')
    return _projection(job)


def read_problem(db, *, problem_id, job_id, user):
    job = db.query(m.ExecutionJob).filter_by(
        id=job_id, owner_key=_owner(user), kind=KIND
    ).first()
    if job is None:
        raise HTTPException(404, '출제 검증 기록을 찾을 수 없습니다.')
    if job.content_expired_at is not None:
        return _projection(job)
    payload = job.payload if isinstance(job.payload, dict) else {}
    if (
        payload.get('contest_id') != PROBLEM_SCOPE
        or payload.get('contest_problem_id') != problem_id
        or payload.get('problem_id') != problem_id
    ):
        raise HTTPException(404, '출제 검증 기록을 찾을 수 없습니다.')
    return _projection(job)


def read_rejudge(db, *, contest_id, batch_id, job_id, user):
    job = db.query(m.ExecutionJob).filter_by(
        id=job_id, owner_key=_owner(user), kind=KIND
    ).first()
    if job is None:
        raise HTTPException(404, '출제 검증 기록을 찾을 수 없습니다.')
    if job.content_expired_at is not None:
        return _projection(job)
    payload = job.payload if isinstance(job.payload, dict) else {}
    if payload.get('contest_id') != contest_id or payload.get('rejudge_batch_id') != batch_id:
        raise HTTPException(404, '출제 검증 기록을 찾을 수 없습니다.')
    return _projection(job)
