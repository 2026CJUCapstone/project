from pydantic import BaseModel
from typing import Optional


class CodeRequest(BaseModel):
    language: str
    source_code: str
    stdin: Optional[str] = None


class CodeResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float
