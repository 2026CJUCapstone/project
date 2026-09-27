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
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Authorization, Cookie'
    if (mine or source == 'contest' or contest_id) and current_user is None:
        raise HTTPException(401, '내 기록과 콘테스트 기록은 로그인 후 조회할 수 있습니다.',
                            headers={'Cache-Control': 'no-store'})
    return await compile_queue.snapshot(
        limit=limit,
        offset=offset,
        status=status,
        verdict=verdict,
        kind=kind,
        username=username,
        user_id=user_id,
        problem_id=problem_id,
        source=source, contest_id=contest_id, problem_search=problem_search,
        language=language, mine=mine, viewer_id=current_user.id if current_user else None,
    )


def _get_problem(db: Session, problem_id: str | None) -> db_models.Problem | None:
    if not problem_id:
        return None
    require_public_problem(db, problem_id)
    return db.query(db_models.Problem).filter(db_models.Problem.id == problem_id).first()
