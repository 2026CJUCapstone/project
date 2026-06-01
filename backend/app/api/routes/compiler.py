from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.routes.auth import get_optional_current_user
from app.core.database import get_db
from app.models import database as db_models
from app.models import schemas
from app.models.schemas import CodeRequest, CodeResponse, CompileRequest, CompileResponse
from app.services import compiler as compiler_service
from app.services.compile_queue import compile_queue

router = APIRouter()


@router.post("/compile", response_model=CompileResponse, tags=["compiler"])
async def compile_code(
    request: CompileRequest,
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    problem = _get_problem(db, request.problem_id)
    try:
        result = await compile_queue.run(
            kind="compile",
            language=request.language,
            source_code=request.code,
            target=request.options.target,
            user_id=current_user.id if current_user else None,
            username=current_user.username if current_user else None,
            problem_id=request.problem_id,
            problem_title=problem.title if problem else None,
            task=lambda: compiler_service.compiler_instance.compile(
                source_code=request.code,
                language=request.language,
                optimize=request.options.optimize,
                target=request.options.target,
            ),
        )
        return CompileResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except compiler_service.SandboxExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/run", response_model=CodeResponse, tags=["Direct Execution"])
async def run_code(
    request: CodeRequest,
    db: Session = Depends(get_db),
    current_user: db_models.User | None = Depends(get_optional_current_user),
):
    problem = _get_problem(db, request.problem_id)
    try:
        result = await compile_queue.run(
            kind="run",
            language=request.language,
            source_code=request.source_code,
            user_id=current_user.id if current_user else None,
            username=current_user.username if current_user else None,
            problem_id=request.problem_id,
            problem_title=problem.title if problem else None,
            task=lambda: compiler_service.compiler_instance.run(
                source_code=request.source_code,
                language=request.language,
                stdin=request.stdin or "",
                optimize=request.optimize,
            ),
        )
        return CodeResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except compiler_service.SandboxExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/queue", response_model=schemas.CompileQueueResponse)
async def get_compile_queue(
    limit: int = Query(100, ge=1, le=500),
    status: str | None = Query(None),
    kind: str | None = Query(None),
    username: str | None = Query(None),
    user_id: str | None = Query(None, alias="userId"),
    problem_id: str | None = Query(None, alias="problemId"),
):
    return await compile_queue.snapshot(
        limit=limit,
        status=status,
        kind=kind,
        username=username,
        user_id=user_id,
        problem_id=problem_id,
    )


def _get_problem(db: Session, problem_id: str | None) -> db_models.Problem | None:
    if not problem_id:
        return None
    return db.query(db_models.Problem).filter(db_models.Problem.id == problem_id).first()
