import asyncio
import tempfile
import os
import time
import hashlib
import string
import random
import json
import difflib
from datetime import datetime, timezone
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

from app.core.config import settings

# ----------------- 임시 메모리 데이터베이스 -----------------
job_store: Dict[str, dict] = {}
hash_store: Dict[str, str] = {}
snippet_store: Dict[str, dict] = {}
access_log_store: List[dict] = []

ALLOWED_PASSES = {"Lexer", "Parser", "ASTBuilder", "Mem2Reg", "LoopUnroll", "DCE", "ConstProp"}
SUPPORTED_LANGUAGES = {"bpp", "python", "c", "cpp", "java", "javascript"}
EXTENSIONS = {
    "bpp": "bpp",
    "python": "py",
    "c": "c",
    "cpp": "cpp",
    "java": "java",
    "javascript": "js",
}

# ----------------- 컴파일러 인터페이스 (Async) -----------------
class CompilerRunner(ABC):
    @abstractmethod
    async def compile(self, source_code: str, options: List[str], language: str) -> dict:
        pass

# ----------------- Docker 샌드박스 구현체 -----------------
class DockerCompilerRunner(CompilerRunner):
    async def compile(self, source_code: str, options: List[str], language: str) -> dict:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"지원하지 않는 언어입니다: {language}")

        ext = EXTENSIONS.get(language, "txt")

        # 임시 파일 생성
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False, mode="w") as tmp:
            tmp.write(source_code)
            tmp_path = tmp.name

        try:
            start_time = time.monotonic()
            
            # Docker 실행 명령어 구성
            proc = await asyncio.create_subprocess_exec(
                "docker", "run", "--rm",
                "--network", "none",
                "--memory", "128m",
                "--cpus", "0.5",
                "-v", f"{tmp_path}:/sandbox/code.{ext}:ro",
                settings.SANDBOX_IMAGE,
                language,
                f"/sandbox/code.{ext}",
                *options, # 추가 컴파일러 옵션 전달
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                # 실행 시간 제한 (Timeout) 처리
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=settings.EXECUTION_TIMEOUT
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except:
                    pass
                return {
                    "is_success": False,
                    "stdout": "",
                    "stderr": "실행 시간이 초과되었습니다. (Timeout)",
                    "exit_code": -1,
                    "execution_time": settings.EXECUTION_TIMEOUT,
                }

            elapsed = time.monotonic() - start_time
            
            return {
                "is_success": proc.returncode == 0,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode or 0,
                "execution_time": round(elapsed, 3),
                "ast": {"info": "See stdout for raw data"},
                "cfg": {"info": "See stdout for raw data"}
            }
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

# ----------------- 기존 가짜(Mock) 구현체 -----------------
class MockBppCompiler(CompilerRunner):
    async def compile(self, source_code: str, options: List[str], language: str = "bpp") -> dict:
        await asyncio.sleep(1) # 비동기 대기
        output = "Hello World" if "Hello World" in source_code else "실행 완료"
        return {
            "is_success": True,
            "ast": {"type": "Program", "body": "Mock AST Data"},
            "cfg": {"nodes": ["A", "B"], "edges":["A->B"]},
            "stdout": output,
            "execution_time": 1.0
        }

# compiler_instance = DockerCompilerRunner() 실제 컴파일러 연결시 변경
compiler_instance = MockBppCompiler()

async def mock_execute_pipeline(source_code: str, passes: List[str]) -> dict:
    await asyncio.sleep(2)
    pass_results = [{"pass_name": p, "log": f"{p} 적용 완료"} for p in passes]
    return {
        "is_success": True,
        "pipeline_used": passes,
        "pass_results": pass_results,
        "final_asm": "MOV EAX, 1"
    }

# ----------------- 백그라운드 워커 함수들 (Async) -----------------
async def process_compile_job(job_id: str, source_code: str, options: List[str], language: str = "bpp"):
    if job_store[job_id]["status"] == "CANCELED": return
    job_store[job_id]["status"] = "RUNNING"
    try:
        # 비동기 방식으로 컴파일러 호출
        result = await compiler_instance.compile(source_code, options, language)
        
        if job_store[job_id].get("status") == "CANCELED": return
        
        job_store[job_id]["status"] = "COMPLETED"
        job_store[job_id]["result"] = result
    except Exception as e:
        if job_store[job_id].get("status") != "CANCELED":
            job_store[job_id]["status"] = "FAILED"
            job_store[job_id]["error"] = str(e)

async def process_lab_job(job_id: str, source_code: str, passes: List[str]):
    if job_store[job_id]["status"] == "CANCELED": return
    job_store[job_id]["status"] = "RUNNING"
    try:
        result = await mock_execute_pipeline(source_code, passes)
        if job_store[job_id].get("status") == "CANCELED": return
        job_store[job_id]["status"] = "COMPLETED"
        job_store[job_id]["result"] = result
    except Exception as e:
        if job_store[job_id].get("status") != "CANCELED":
            job_store[job_id]["status"] = "FAILED"
            job_store[job_id]["error"] = str(e)

# ----------------- 유틸리티 함수 -----------------
def generate_random_slug(length: int = 6) -> str:
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))

def get_unique_slug(desired_slug: Optional[str] = None) -> str:
    base_slug = desired_slug if desired_slug else generate_random_slug()
    if base_slug not in snippet_store: return base_slug
    suffix_counter = 1
    while f"{base_slug}-{suffix_counter}" in snippet_store:
        suffix_counter += 1
    return f"{base_slug}-{suffix_counter}"

def generate_text_diff(text1: str, text2: str) -> str:
    diff = difflib.unified_diff(
        text1.splitlines(keepends=True),
        text2.splitlines(keepends=True),
        fromfile='Base Version',
        tofile='New Version'
    )
    return "".join(diff)

def generate_html_report(job_id: str, result: dict) -> str:
    pretty_json = json.dumps(result, indent=4, ensure_ascii=False)
    html_template = f"""
    <html>
    <body>
        <h1>B++ Report - {job_id}</h1>
        <pre>{pretty_json}</pre>
    </body>
    </html>
    """
    return html_template
