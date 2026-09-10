"""Atomically preserve practice receipts and their immutable grading inputs."""
from fastapi import HTTPException
from uuid import uuid4

from app.models import database as m
from app.services.contest_access import now_utc, iso, require_public_problem
from app.services.durable_queue import IdempotencyConflict, QueueFull, EXECUTION_EXPIRED_MESSAGE
from app.services.execution_admission import admit_execution, validate_execution_input
from app.services.execution_identity import execution_owner, execution_quota
from app.services.execution_runtime import execution_queue


def accept_practice(problem_id, data, request, response, db, user):
    # Capture before admission/DB waits; the code is committed before any worker
    # can claim it. A request cancellation cannot erase an acknowledged receipt.
    received = now_utc()
    validate_execution_input(data.code)
    admit_execution(request, user_id=user.id if user else None)
    owner = execution_owner(request, user, response)
    from app.api.routes.executions import request_id
    from app.api.routes.problems import _normalize_problem_test_cases
    key = request_id(request)
    queue = execution_queue()
    queue._lock(db)
    previous = db.query(m.ExecutionJob).filter_by(owner_key=owner, request_id=key).first()
    if previous:
        if previous.content_expired_at is not None:
            raise HTTPException(410, EXECUTION_EXPIRED_MESSAGE, headers={'Cache-Control':'no-store'})
        payload = previous.payload
        if previous.kind != 'practice' or payload.get('problem_id') != problem_id or payload.get('code') != data.code or payload.get('language') != data.language:
            raise HTTPException(409, '같은 요청 ID로 다른 코드를 제출할 수 없습니다.')
        record = db.query(m.Submission).filter_by(execution_job_id=previous.id).first()
        db.commit()
        if record is None:
            # Ordinary history retention must not turn a retry of a completed
            # receipt into a new score-earning submission (or a server error).
            status = ((previous.result or {}).get('value') or {}).get('status', previous.status)
            return {'id':payload['submission_id'], 'executionId':previous.id,
                    'status':status, 'receivedAt':iso(previous.received_at)}
        return receipt(record, previous)
    require_public_problem(db, problem_id)
    # Freeze tests/points while excluding concurrent archive/update until receipt
    # commit. On SQLite the preceding queue write already holds the writer lock.
    problem = db.query(m.Problem).filter_by(id=problem_id).with_for_update().one()
    if problem.deleted_at is not None:
        raise HTTPException(404, '문제를 찾을 수 없습니다.')
    sample, hidden = _normalize_problem_test_cases(problem.test_cases)
    if not sample and not hidden:
        raise HTTPException(409, '채점 테스트가 없어 제출할 수 없습니다. 관리자에게 문의하세요.')
    submission_id = str(uuid4())
    payload = {'submission_id':submission_id, 'problem_id':problem.id, 'code':data.code, 'language':data.language,
               'sample':sample, 'hidden':hidden, 'practice_points':problem.points}
    try:
        job = queue.enqueue_in_session(db, owner_key=owner, quota_key=execution_quota(request,user),
            request_id=key, kind='practice', payload=payload, at=received)
    except QueueFull:
        raise HTTPException(429, '실행 대기열이 가득 찼습니다.', headers={'Retry-After':'5'}) from None
    except IdempotencyConflict:
        raise HTTPException(409, '같은 요청 ID로 다른 코드를 제출할 수 없습니다.') from None
    except ValueError:
        raise HTTPException(413, '채점 요청이 너무 큽니다. 관리자에게 문의하세요.') from None
    record = m.Submission(id=submission_id, execution_job_id=job.id, user_id=user.id if user else None, problem_id=problem.id,
        code=data.code, language=data.language, created_at=received, status='queued', verdict='pending',
        sample_total_cases=len(sample), sample_passed_cases=0, grading_completed=False, grading_passed=False, awarded_points=0)
    db.add(record)
    db.add(m.CompileQueueRecord(id=job.id, kind='grading', status='queued', verdict='pending', language=data.language,
        user_id=user.id if user else None, username=user.username if user else None,
        problem_id=problem.id, problem_title=problem.title,
        source_size_bytes=len(data.code.encode('utf-8')), queued_at=received))
    db.commit()
    return receipt(record, job)


def receipt(submission, job):
    return {'id':submission.id, 'executionId':job.id, 'status':submission.status, 'receivedAt':iso(submission.created_at)}
