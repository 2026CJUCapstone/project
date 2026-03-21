import asyncio
import tempfile
import os
import time

from app.core.config import settings
from app.models.schemas import CodeRequest, CodeResponse

SUPPORTED_LANGUAGES = {"python", "c", "cpp", "java", "javascript"}

EXTENSIONS = {
    "python": "py",
    "c": "c",
    "cpp": "cpp",
    "java": "java",
    "javascript": "js",
}


async def execute(request: CodeRequest) -> CodeResponse:
    """Docker 샌드박스 컨테이너에서 코드를 실행합니다."""
    if request.language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"지원하지 않는 언어입니다: {request.language}")

    ext = EXTENSIONS[request.language]

    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False, mode="w") as tmp:
        tmp.write(request.source_code)
        tmp_path = tmp.name

    try:
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", "128m",
            "--cpus", "0.5",
            "-v", f"{tmp_path}:/sandbox/code.{ext}:ro",
            settings.SANDBOX_IMAGE,
            request.language,
            f"/sandbox/code.{ext}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.EXECUTION_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            return CodeResponse(
                stdout="",
                stderr="실행 시간이 초과되었습니다.",
                exit_code=-1,
                execution_time=settings.EXECUTION_TIMEOUT,
            )
        elapsed = time.monotonic() - start
        return CodeResponse(
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            exit_code=proc.returncode or 0,
            execution_time=round(elapsed, 3),
        )
    finally:
        os.unlink(tmp_path)
