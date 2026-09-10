from fastapi import APIRouter, Depends, Query, Request, Response
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
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    verdict: str | None = Query(None),
    kind: str | None = Query(None),
    username: str | None = Query(None),
    user_id: str | None = Query(None, alias="userId"),
    problem_id: str | None = Query(None, alias="problemId"),
):
    return await compile_queue.snapshot(
        limit=limit,
        offset=offset,
        status=status,
        verdict=verdict,
        kind=kind,
        username=username,
        user_id=user_id,
        problem_id=problem_id,
    )


def _get_problem(db: Session, problem_id: str | None) -> db_models.Problem | None:
    if not problem_id:
        return None
    require_public_problem(db, problem_id)
    return db.query(db_models.Problem).filter(db_models.Problem.id == problem_id).first()
