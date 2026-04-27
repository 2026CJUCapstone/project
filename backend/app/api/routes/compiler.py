from fastapi import APIRouter, HTTPException

from app.models.schemas import CodeRequest, CodeResponse, CompileRequest, CompileResponse
from app.services import compiler as compiler_service

router = APIRouter()


@router.post("/compile", response_model=CompileResponse, tags=["compiler"])
async def compile_code(request: CompileRequest):
    try:
        result = await compiler_service.compiler_instance.compile(
            source_code=request.code,
            language=request.language,
            optimize=request.options.optimize,
            target=request.options.target,
        )
        return CompileResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except compiler_service.SandboxExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/run", response_model=CodeResponse, tags=["Direct Execution"])
async def run_code(request: CodeRequest):
    try:
        result = await compiler_service.compiler_instance.run(
            source_code=request.source_code,
            language=request.language,
            stdin=request.stdin or "",
            optimize=request.optimize,
        )
        return CodeResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except compiler_service.SandboxExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
