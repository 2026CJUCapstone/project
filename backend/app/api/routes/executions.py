"""Durable receipt and private result API; no sandbox executes in an API request."""
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.api.routes.auth import get_optional_current_user
from app.core.database import get_db
from app.models import database as m, schemas
from app.services.contest_access import iso, now_utc, require_public_problem
from app.services.durable_queue import IdempotencyConflict, QueueFull, ExecutionExpired, EXECUTION_EXPIRED_MESSAGE
from app.services.execution_admission import admit_execution, validate_execution_input
from app.services.execution_identity import execution_owner, execution_quota
from app.services.execution_runtime import execution_queue

router = APIRouter()


class ExecutionRequest(schemas.CodeRequest):
    kind: Literal['compile','run'] = 'run'
    target: schemas.CompilerTarget = 'all'


def request_id(request):
    value = request.headers.get('x-request-id')
    if value is None:
        return str(uuid4())
    try:
        return str(UUID(value))
    except ValueError:
        raise HTTPException(400, 'X-Request-ID must be a UUID') from None


@router.post('', status_code=202)
def accept_execution(data: ExecutionRequest, request: Request, response: Response,
                     db: Session = Depends(get_db), user=Depends(get_optional_current_user)):
    received = now_utc()
    validate_execution_input(data.source_code, data.stdin or '')
    admit_execution(request, user_id=user.id if user else None)
    owner = execution_owner(request, user, response)
    problem = None
    if data.problem_id:
        require_public_problem(db, data.problem_id)
        problem = db.get(m.Problem, data.problem_id)
    payload = {'code':data.source_code, 'language':data.language, 'stdin':data.stdin or '',
               'optimize':data.optimize, 'target':data.target, 'problem_id':data.problem_id}
    try:
        job = execution_queue().enqueue_in_session(db, owner_key=owner, quota_key=execution_quota(request,user),
            request_id=request_id(request), kind=data.kind, payload=payload, at=received)
    except QueueFull:
        raise HTTPException(429, '실행 대기열이 가득 찼습니다.', headers={'Retry-After':'5'}) from None
    except ExecutionExpired:
        raise HTTPException(410, EXECUTION_EXPIRED_MESSAGE, headers={'Cache-Control':'no-store'}) from None
    except IdempotencyConflict:
        raise HTTPException(409, '같은 요청 ID로 다른 코드를 제출할 수 없습니다.') from None
    except ValueError:
        raise HTTPException(413, '실행 요청이 너무 큽니다.') from None
    # History pruning must not make a retry resurrect a completed job as a
    # permanently queued public observation. The private receipt is authority.
    if job.status == 'queued' and db.get(m.CompileQueueRecord, job.id) is None:
        db.add(m.CompileQueueRecord(id=job.id, kind=data.kind, status='queued', verdict='pending', language=data.language,
            user_id=user.id if user else None, username=user.username if user else None,
            problem_id=problem.id if problem else None, problem_title=problem.title if problem else None,
            target=data.target if data.kind == 'compile' else None,
            source_size_bytes=len(data.source_code.encode('utf-8')), queued_at=job.received_at))
    db.commit()
    return {'id':job.id, 'status':job.status, 'receivedAt':iso(job.received_at), 'requestId':job.request_id}


@router.get('/{job_id}')
def read_execution(job_id: str, request: Request, response: Response,
                   db: Session = Depends(get_db), user=Depends(get_optional_current_user)):
    response.headers['Cache-Control'] = 'no-store'
    owner = execution_owner(request,user)
    job = db.query(m.ExecutionJob).filter_by(id=job_id, owner_key=owner).first() if owner else None
    if job is None:
        raise HTTPException(404, '실행 기록을 찾을 수 없습니다.')
    if job.content_expired_at is not None:
        raise HTTPException(410, EXECUTION_EXPIRED_MESSAGE, headers={'Cache-Control':'no-store'})
    result = None
    if job.result is not None:
        raw = job.result
        value = raw.get('value')
        if value is not None:
            if job.kind == 'practice':
                value = schemas.SubmissionResponse(**value).model_dump(by_alias=True)
            elif job.kind == 'run':
                value = schemas.CodeResponse(**value).model_dump(by_alias=True)
            elif job.kind == 'compile':
                value = schemas.CompileResponse(**value).model_dump(by_alias=True)
        result = {'ok':value is not None, 'value':value, 'verdict':raw.get('verdict')}
        if value is None:
            result['error'] = raw.get('message', '실행 서비스를 사용할 수 없습니다.')
    return {'id':job.id, 'status':job.status, 'receivedAt':iso(job.received_at), 'result':result}
