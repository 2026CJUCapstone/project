from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime

class Visibility(str, Enum):
    PUBLIC = "PUBLIC"
    UNLISTED = "UNLISTED"
    PRIVATE = "PRIVATE"

class CodeRequest(BaseModel):
    language: str
    source_code: str
    stdin: Optional[str] = None

class CodeResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float

class CompileRequest(BaseModel):
    source_code: str
    options: List[str] =[]

class CompileResponse(BaseModel):
    job_id: str
    status: str
    message: str

class SnippetCreateRequest(BaseModel):
    job_id: str = Field(..., description="컴파일 완료된 Job ID")
    visibility: Visibility = Field(default=Visibility.UNLISTED)
    expire_at: Optional[datetime] = Field(default=None, description="만료 일시 (UTC)", json_schema_extra={"example": None})
    custom_slug: Optional[str] = Field(default=None, description="사용자 지정 짧은 주소 (선택)")

class SnippetResponse(BaseModel):
    slug: str
    job_id: str
    visibility: Visibility
    expire_at: Optional[datetime]
    created_at: datetime

class LabPipelineRequest(BaseModel):
    source_code: str
    passes: List[str] = Field(..., description="사용자가 직접 구성한 최적화 패스 순서 목록")

class LabPipelineResponse(BaseModel):
    job_id: str
    status: str
    message: str

class LabShareRequest(BaseModel):
    job_id: str
    custom_slug: Optional[str] = None

class VersionAddRequest(BaseModel):
    job_id: str = Field(..., description="새로 추가할 컴파일 완료된 Job ID")
    commit_message: str = Field(default="새로운 버전 업데이트", description="변경 사항 메모")

class DiffResponse(BaseModel):
    base_job_id: str
    compare_job_id: str
    source_diff: str
