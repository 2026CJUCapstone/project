from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.api.routes.auth import get_optional_current_user
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas
from app.models.schemas import CodeRequest, CompileRequest
from app.api.routes import executions
from app.services.compile_queue import compile_queue
from app.services.contest_access import require_public_problem
from app.services.public_identity import public_display_name, public_problem_id, public_receipt_id

router = APIRouter()


@router.post("/compile", status_code=202, tags=["compiler"])
def compile_code(
    request: CompileRequest,
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    return executions.accept_execution(
        executions.ExecutionRequest(
            kind="compile",
            source_code=request.code,
            language=request.language,
            optimize=request.options.optimize,
            target=request.options.target,
            problem_id=request.problem_id,
        ),
        http_request,
        response,
        db,
        current_user,
    )


@router.post("/run", status_code=202, tags=["Direct Execution"])
def run_code(
    request: CodeRequest,
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    return executions.accept_execution(
        executions.ExecutionRequest(
            kind="run",
            source_code=request.source_code,
            language=request.language,
            stdin=request.stdin or "",
            optimize=request.optimize,
            problem_id=request.problem_id,
        ),
        http_request,
        response,
        db,
        current_user,
    )


@router.get("/queue", response_model=schemas.CompileQueueResponse)
async def get_compile_queue(
    response: Response,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    verdict: str | None = Query(None),
    kind: str | None = Query(None),
    username: str | None = Query(None),
    user_id: str | None = Query(None, alias="userId"),
    problem_id: str | None = Query(None, alias="problemId"),
    source: Literal['all', 'ide', 'practice', 'contest'] = Query('all'),
    contest_id: str | None = Query(None, alias='contestId', max_length=128),
    problem_search: str | None = Query(None, alias='problemSearch', max_length=200),
    language: schemas.CompilerLanguage | None = Query(None),
    mine: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Authorization, Cookie'
    if (mine or source == 'contest' or contest_id) and current_user is None:
        raise HTTPException(401, '내 기록과 콘테스트 기록은 로그인 후 조회할 수 있습니다.',
                            headers={'Cache-Control': 'no-store'})
    is_admin = current_user is not None and current_user.role == 'admin'
    # Public callers receive only operational totals. A signed-in user may
    # inspect their own receipts, while cross-user identifiers and filters are
    # reserved for administrators.
    own_only = current_user is not None and not is_admin
    result = await compile_queue.snapshot(
        limit=limit,
        offset=offset,
        status=status,
        verdict=verdict,
        kind=kind,
        username=username if is_admin else None,
        user_id=user_id if is_admin else None,
        problem_id=problem_id if current_user is not None else None,
        source=source, contest_id=contest_id, problem_search=problem_search,
        language=language, mine=(mine or own_only), viewer_id=current_user.id if current_user else None,
    )
    if is_admin:
        result['detail_scope'] = 'admin'
        return result
    if own_only:
        result['detail_scope'] = 'mine'
        result['user_groups'] = []
        raw_job_ids = [job['id'] for job in result['jobs'] if not job['id'].startswith('contest:')]
        jobs = db.query(db_models.ExecutionJob).filter(db_models.ExecutionJob.id.in_(raw_job_ids)).all() if raw_job_ids else []
        public_jobs = {job.id: job.public_id for job in jobs}
        internal_problem_ids = {
            item.get('problem_id') for item in [*result['jobs'], *result['problem_options'], *result['problem_groups']]
            if item.get('problem_id')
        }
        problems = db.query(db_models.Problem).filter(db_models.Problem.id.in_(internal_problem_ids)).all() if internal_problem_ids else []
        public_problems = {problem.id: public_problem_id(problem) for problem in problems}
        contest_problem_ids = {
            item.get('contest_problem_id') for item in [*result['jobs'], *result['problem_groups']]
            if item.get('contest_problem_id')
        }
        contest_problems = db.query(db_models.ContestProblem).filter(
            db_models.ContestProblem.id.in_(contest_problem_ids)
        ).all() if contest_problem_ids else []
        public_contest_problems = {
            problem.id: chr(65 + problem.position) for problem in contest_problems
        }

        def redact(item):
            item['user_id'] = None
            if 'username' in item:
                item['username'] = public_display_name(current_user)
            raw_id = item.get('id')
            if raw_id:
                item['id'] = (
                    public_receipt_id(raw_id.removeprefix('contest:'))
                    if raw_id.startswith('contest:') else public_jobs.get(raw_id, public_receipt_id(raw_id))
                )
            if item.get('problem_id') in public_problems:
                item['problem_id'] = public_problems[item['problem_id']]
            if item.get('contest_problem_id') in public_contest_problems:
                item['contest_problem_id'] = public_contest_problems[item['contest_problem_id']]

        for job in result['jobs']:
            redact(job)
        for option in result['problem_options']:
            if option.get('id') in public_problems:
                option['id'] = public_problems[option['id']]
        for group in result['problem_groups']:
            redact(group)
            group['key'] = (
                f"contest:{group['contest_id']}:{group['contest_problem_id']}"
                if group.get('contest_id') else group.get('problem_id') or '__main__'
            )
        return result
    return {
        'jobs': [], 'total': result['total'], 'filtered_total': result['filtered_total'],
        'queued': result['queued'], 'running': result['running'],
        'problem_groups': [], 'user_groups': [], 'contest_options': [],
        'problem_options': [], 'option_limit': 0, 'options_truncated': False,
        'detail_scope': 'aggregate',
    }


def _get_problem(db: Session, problem_id: str | None) -> db_models.Problem | None:
    if not problem_id:
        return None
    return require_public_problem(db, problem_id)
