from fastapi import APIRouter, HTTPException

from app.models.schemas import CodeRequest, CodeResponse
from app.services import compiler as compiler_service

router = APIRouter()


@router.post("/run", response_model=CodeResponse)
async def run_code(request: CodeRequest):
    """사용자 코드를 샌드박스에서 실행하고 결과를 반환합니다."""
    try:
        result = await compiler_service.execute(request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="코드 실행 중 오류가 발생했습니다.")
