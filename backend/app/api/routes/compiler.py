import hashlib
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request

from app.models.schemas import (
    CodeRequest, CodeResponse, CompileRequest, CompileResponse,
    SnippetCreateRequest, SnippetResponse, VersionAddRequest, DiffResponse,
    Visibility, LabPipelineRequest, LabPipelineResponse, LabShareRequest,
)
from app.services.compiler import (
    job_store, hash_store, snippet_store, access_log_store, ALLOWED_PASSES,
    process_compile_job, process_lab_job, get_unique_slug, generate_text_diff
    
)

router = APIRouter()

@router.post("/run", response_model=CodeResponse, tags=["Direct Execution"])
async def run_code(request: CodeRequest):
    """사용자 코드를 샌드박스에서 실행하고 결과를 반환합니다."""
    try:
        result = await compiler_instance.compile(
            request.source_code, 
            request.options,
            request.language
        )
        return CodeResponse(
            stdout=result["stdout"],
            stderr=result["stderr"],
            exit_code=result["exit_code"],
            execution_time=result["execution_time"]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"코드 실행 중 오류가 발생했습니다.: {str(e)}")

# ----------------- 일반 컴파일 기능 -----------------
@router.post("/compile", response_model=CompileResponse, tags=["Compiler"])
async def submit_compile_job(request: CompileRequest, background_tasks: BackgroundTasks):
    raw_str = request.source_code + "".join(request.options)
    hash_value = hashlib.sha256(raw_str.encode('utf-8')).hexdigest()
    
    if hash_value in hash_store and job_store[hash_store[hash_value]]["status"] != "FAILED":
        return CompileResponse(
            job_id=hash_store[hash_value], 
            status=job_store[hash_store[hash_value]]["status"], 
            message="중복 병합됨 (기존 작업을 재사용합니다)"
        )

    job_id = str(uuid.uuid4())
    hash_store[hash_value] = job_id
    job_store[job_id] = {"status": "PENDING", "result": None, "error": None}
    
    background_tasks.add_task(
        process_compile_job, 
        job_id, 
        request.source_code, 
        request.options, 
        "bpp"
    )
    
    return CompileResponse(
        job_id=job_id, 
        status="PENDING", 
        message="작업이 등록되었습니다. (Docker 샌드박스 실행)"
    )

@router.get("/compile/{job_id}", tags=["Compiler"])
async def get_job_status(job_id: str):
    if job_id not in job_store: raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **job_store[job_id]}

@router.post("/jobs/{job_id}/cancel", tags=["Job Management"])
async def cancel_job(job_id: str):
    if job_id not in job_store:
        raise HTTPException(404, "Job not found")
    
    current_status = job_store[job_id]["status"]

    if current_status == "COMPLETED":
        raise HTTPException(status_code=400, detail="이미 컴파일이 완료되어 취소할 수 없습니다.")
    elif current_status == "FAILED":
        raise HTTPException(status_code=400, detail="컴파일 중 에러가 발생해 취소할 수 없습니다.")
    elif current_status == "CANCELED":
        raise HTTPException(status_code=400, detail="이미 취소 처리된 작업입니다.")

    job_store[job_id]["status"] = "CANCELED"
    return {"job_id": job_id, "status": "CANCELED", "message": "작업 취소됨"}

# ----------------- 스니펫(공유) 기능 -----------------
@router.post("/snippets", response_model=SnippetResponse, tags=["Snippet"])
async def create_snippet(request: SnippetCreateRequest):
    if request.job_id not in job_store or job_store[request.job_id]["status"] != "COMPLETED":
        raise HTTPException(400, "유효하지 않은 Job ID")
    slug = get_unique_slug(request.custom_slug)
    snippet_data = {
        "slug": slug, "job_id": request.job_id, "visibility": request.visibility,
        "expire_at": request.expire_at, "created_at": datetime.now(timezone.utc)
    }
    snippet_store[slug] = snippet_data
    return snippet_data

@router.get("/snippets/{slug}", tags=["Snippet"])
async def get_snippet(slug: str, request: Request):
    if slug not in snippet_store: raise HTTPException(404, "스니펫 없음")
    snippet = snippet_store[slug]
    if snippet.get("expire_at") and datetime.now(timezone.utc) > snippet["expire_at"]:
        raise HTTPException(410, "만료된 스니펫")
    
    client_ip = request.client.host if request.client else "Unknown IP"
    access_log_store.append({"slug": slug, "ip": client_ip, "time": datetime.now(timezone.utc)})
    return {"snippet_info": snippet, "compiler_result": job_store[snippet["job_id"]]["result"]}

# ----------------- 실험실 기능 -----------------
@router.post("/lab/execute", response_model=LabPipelineResponse, tags=["Lab Mode"])
async def execute_lab_pipeline(request: LabPipelineRequest, background_tasks: BackgroundTasks):
    for p in request.passes:
        if p not in ALLOWED_PASSES: raise HTTPException(400, f"알 수 없는 패스: {p}")
    job_id = "lab-" + str(uuid.uuid4())
    job_store[job_id] = {"status": "PENDING", "result": None, "error": None}
    background_tasks.add_task(process_lab_job, job_id, request.source_code, request.passes)
    return LabPipelineResponse(job_id=job_id, status="PENDING", message="실험실 큐 등록됨")

@router.post("/lab/share", tags=["Lab Mode"])
async def share_lab_pipeline(request: LabShareRequest):
    if request.job_id not in job_store or job_store[request.job_id]["status"] != "COMPLETED":
        raise HTTPException(400, "유효하지 않은 Job ID")
    slug = get_unique_slug(request.custom_slug)
    snippet_store[slug] = {
        "slug": slug, "job_id": request.job_id, "type": "LAB_SHARE",
        "created_at": datetime.now(timezone.utc), "visibility": "PUBLIC", "expire_at": None
    }
    return {"slug": slug, "message": "실험실 공유 링크 생성됨"}

# ----------------- 히스토리 및 Diff 기능 -----------------
@router.post("/snippets/{slug}/versions", tags=["Version History"])
async def add_snippet_version(slug: str, request: VersionAddRequest):
    """기존 스니펫에 새로운 버전(Job)을 추가합니다."""
    if slug not in snippet_store:
        raise HTTPException(status_code=404, detail="스니펫을 찾을 수 없습니다.")
    if request.job_id not in job_store or job_store[request.job_id]["status"] != "COMPLETED":
        raise HTTPException(status_code=400, detail="유효하지 않거나 완료되지 않은 Job ID입니다.")
        
    snippet = snippet_store[slug]
    
    if "versions" not in snippet:
        snippet["versions"] = [{
            "version": 1,
            "job_id": snippet["job_id"],
            "commit_message": "최초 생성",
            "created_at": snippet["created_at"]
        }]
        
    next_version = len(snippet["versions"]) + 1
    
    new_version_data = {
        "version": next_version,
        "job_id": request.job_id,
        "commit_message": request.commit_message,
        "created_at": datetime.now(timezone.utc)
    }
    snippet["versions"].append(new_version_data)
    
    snippet["job_id"] = request.job_id
    
    return {"message": f"버전 {next_version}이(가) 성공적으로 추가되었습니다.", "versions": snippet["versions"]}

@router.get("/diff", response_model=DiffResponse, tags=["Version History"])
async def get_job_diff(base_job_id: str, compare_job_id: str):
    """두 개의 Job 사이에 어떤 코드가 변경되었는지(Diff) 확인합니다."""
    if base_job_id not in job_store or compare_job_id not in job_store:
        raise HTTPException(status_code=404, detail="비교할 Job을 찾을 수 없습니다.")
    
    base_output = job_store[base_job_id]["result"].get("stdout", "")
    compare_output = job_store[compare_job_id]["result"].get("stdout", "")
    
    diff_result = generate_text_diff(base_output, compare_output)
    
    if not diff_result:
        diff_result = "변경 사항이 없습니다."
        
    return DiffResponse(
        base_job_id=base_job_id,
        compare_job_id=compare_job_id,
        source_diff=diff_result
    )
