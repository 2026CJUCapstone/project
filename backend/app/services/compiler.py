import asyncio
import contextlib
import re
import shutil
import tempfile
import time
import asyncio
import contextlib
import difflib
import hashlib
import json
import random
import re
import shutil
import string
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional

import docker
from docker.errors import APIError, DockerException
from docker.types import Ulimit

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

GCC_DIAGNOSTIC_RE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<column>\d+): "
    r"(?P<severity>warning|error|fatal error): (?P<message>.*)$"
)
JAVA_DIAGNOSTIC_RE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+): (?P<severity>warning|error): (?P<message>.*)$"
)
PYTHON_LINE_RE = re.compile(r'File ".*?", line (?P<line>\d+)')
JAVASCRIPT_LINE_RE = re.compile(r"^(?P<file>.*?):(?P<line>\d+)$")
JAVA_CLASS_RE = re.compile(r"\bpublic\s+class\s+(?P<name>[A-Za-z_]\w*)")
JAVA_FALLBACK_CLASS_RE = re.compile(r"\bclass\s+(?P<name>[A-Za-z_]\w*)")
JAVA_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
JAVA_LINE_COMMENT_RE = re.compile(r"//.*$")
BPP_DIAGNOSTIC_RE = re.compile(r"^\[(?P<severity>ERROR|WARN|WARNING|INFO)\]\s+(?P<message>.*)$")
BPP_LINE_COL_RE = re.compile(r"\bline (?P<line>\d+), column (?P<column>\d+)\b")


class SandboxExecutionError(RuntimeError):
    pass


@dataclass(slots=True)
class Diagnostic:
    line: int
    column: int
    message: str
    severity: Literal["error", "warning", "info"]
    code: str | None = None

    def to_dict(self) -> dict:
        return {
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "severity": self.severity,
            "code": self.code,
        }


# ----------------- 컴파일러 인터페이스 (Async) -----------------
class CompilerRunner(ABC):
    @abstractmethod
    async def compile(self, source_code: str, options: List[str], language: str) -> dict:
        pass


class DockerCompilerRunner:
    async def compile(self, source_code: str, language: str, optimize: bool = False) -> dict:
        result = await self._execute(
            mode="compile",
            source_code=source_code,
            language=language,
            optimize=optimize,
        )
        diagnostics = self._parse_diagnostics(result["stderr"], language, result["exit_code"] == 0)
        errors = [item.to_dict() for item in diagnostics if item.severity == "error"]
        warnings = [item.to_dict() for item in diagnostics if item.severity == "warning"]
        return {
            "success": result["exit_code"] == 0,
            "errors": errors,
            "warnings": warnings,
            "execution_time": result["execution_time"],
            "metadata": {
                "node_count": len(source_code.splitlines()),
                "optimization_level": 2 if optimize else 0,
            },
        }

    async def run(self, source_code: str, language: str, stdin: str = "", optimize: bool = False) -> dict:
        return await self._execute(
            mode="run",
            source_code=source_code,
            language=language,
            stdin=stdin,
            optimize=optimize,
        )

    async def _execute(
        self,
        *,
        mode: Literal["compile", "run"],
        source_code: str,
        language: str,
        stdin: str = "",
        optimize: bool = False,
    ) -> dict:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"지원하지 않는 언어입니다: {language}")

        sandbox_root = Path(settings.SANDBOX_WORKDIR_ROOT)
        sandbox_root.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix="job-", dir=sandbox_root))
        temp_dir.chmod(0o755)
        source_path = temp_dir / self._resolve_filename(language, source_code)
        source_path.write_text(source_code, encoding="utf-8")
        source_path.chmod(0o644)
        stdin_path: Path | None = None

        if mode == "run" and stdin:
            stdin_path = temp_dir / "stdin.txt"
            stdin_path.write_text(stdin, encoding="utf-8")
            stdin_path.chmod(0o644)

        client = self._get_client()
        container_name = f"compiler-sandbox-{uuid.uuid4().hex[:12]}"
        command = [mode, language, f"/workspace/{source_path.name}"]
        if stdin_path is not None:
            command.append(f"/workspace/{stdin_path.name}")

        container = None
        start_time = time.monotonic()

        try:
            container = await asyncio.to_thread(
                client.containers.create,
                image=settings.SANDBOX_IMAGE,
                command=command,
                detach=True,
                name=container_name,
                network_disabled=True,
                read_only=True,
                tmpfs={"/tmp": f"rw,exec,nosuid,size={settings.SANDBOX_MEMORY_MB}m"},
                mem_limit=f"{settings.SANDBOX_MEMORY_MB}m",
                nano_cpus=max(1, int(settings.SANDBOX_CPU_LIMIT * 1_000_000_000)),
                pids_limit=settings.SANDBOX_PIDS_LIMIT,
                ulimits=[Ulimit(name="nofile", soft=settings.SANDBOX_NOFILE_LIMIT, hard=settings.SANDBOX_NOFILE_LIMIT)],
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                volumes={str(temp_dir): {"bind": "/workspace", "mode": "ro"}},
                environment={
                    "COMPILER_OPTIMIZE": "1" if optimize else "0",
                    "HOME": "/tmp",
                },
            )
            await asyncio.to_thread(container.start)
            await self._wait_for_exit(container)

            wait_result = await asyncio.to_thread(container.wait)
            stdout = await asyncio.to_thread(container.logs, stdout=True, stderr=False)
            stderr = await asyncio.to_thread(container.logs, stdout=False, stderr=True)
            exit_code = int(wait_result.get("StatusCode", 1))
        except TimeoutError:
            if container is not None:
                await self._kill_container(container)
            elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
            return {
                "stdout": "",
                "stderr": "실행 시간이 초과되었습니다. (Timeout)",
                "exit_code": 124,
                "execution_time": elapsed_ms,
            }
        except (DockerException, APIError) as exc:
            raise SandboxExecutionError(f"Docker 샌드박스 실행 중 오류가 발생했습니다: {exc}") from exc
        except Exception as exc:
            raise SandboxExecutionError(f"샌드박스 실행 중 오류가 발생했습니다: {exc}") from exc
        finally:
            if container is not None:
                await self._remove_container(container)
            shutil.rmtree(temp_dir, ignore_errors=True)

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": exit_code,
            "execution_time": elapsed_ms,
        }

    def _get_client(self) -> docker.DockerClient:
        try:
            client = docker.from_env()
            client.ping()
            return client
        except DockerException as exc:
            raise SandboxExecutionError(f"Docker 실행 환경을 찾을 수 없습니다: {exc}") from exc

    async def _wait_for_exit(self, container: docker.models.containers.Container) -> None:
        deadline = time.monotonic() + settings.EXECUTION_TIMEOUT

        while True:
            await asyncio.to_thread(container.reload)
            if container.status in {"exited", "dead"}:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Sandbox execution timed out")
            await asyncio.sleep(0.1)

    async def _kill_container(self, container: docker.models.containers.Container) -> None:
        with contextlib.suppress(DockerException, APIError):
            await asyncio.to_thread(container.kill)

    async def _remove_container(self, container: docker.models.containers.Container) -> None:
        with contextlib.suppress(DockerException, APIError):
            await asyncio.to_thread(container.remove, force=True)

    def _resolve_filename(self, language: str, source_code: str) -> str:
        if language == "java":
            sanitized_source = JAVA_BLOCK_COMMENT_RE.sub("", source_code)
            sanitized_source = JAVA_LINE_COMMENT_RE.sub("", sanitized_source)
            match = JAVA_CLASS_RE.search(sanitized_source) or JAVA_FALLBACK_CLASS_RE.search(sanitized_source)
            class_name = match.group("name") if match else "Main"
            return f"{class_name}.java"
        return f"main.{EXTENSIONS[language]}"

    def _parse_diagnostics(self, stderr: str, language: str, success: bool) -> list[Diagnostic]:
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        diagnostics: list[Diagnostic] = []

        for line in lines:
            diagnostic = self._parse_gcc_style(line)
            if diagnostic is None and language == "java":
                diagnostic = self._parse_java_style(line)
            if diagnostic is None and language == "bpp":
                diagnostic = self._parse_bpp_style(line)
            if diagnostic is not None:
                diagnostics.append(diagnostic)

        if diagnostics:
            return diagnostics

        fallback = self._parse_language_specific_fallback(lines, language, success)
        if fallback is not None:
            return [fallback]
        return []

    def _parse_gcc_style(self, line: str) -> Diagnostic | None:
        match = GCC_DIAGNOSTIC_RE.match(line)
        if not match:
            return None
        severity = "warning" if match.group("severity") == "warning" else "error"
        return Diagnostic(
            line=int(match.group("line")),
            column=int(match.group("column")),
            message=match.group("message").strip(),
            severity=severity,
        )

    def _parse_java_style(self, line: str) -> Diagnostic | None:
        match = JAVA_DIAGNOSTIC_RE.match(line)
        if not match:
            return None
        severity = "warning" if match.group("severity") == "warning" else "error"
        return Diagnostic(
            line=int(match.group("line")),
            column=1,
            message=match.group("message").strip(),
            severity=severity,
        )

    def _parse_bpp_style(self, line: str) -> Diagnostic | None:
        match = BPP_DIAGNOSTIC_RE.match(line)
        if not match:
            return None

        raw_severity = match.group("severity")
        if raw_severity in {"WARN", "WARNING"}:
            severity: Literal["error", "warning", "info"] = "warning"
        elif raw_severity == "INFO":
            severity = "info"
        else:
            severity = "error"

        message = match.group("message").strip()
        line_no = 1
        column_no = 1
        location = BPP_LINE_COL_RE.search(message)
        if location:
            line_no = int(location.group("line"))
            column_no = int(location.group("column"))

        return Diagnostic(
            line=line_no,
            column=column_no,
            message=message,
            severity=severity,
        )

    def _parse_language_specific_fallback(
        self,
        lines: list[str],
        language: str,
        success: bool,
    ) -> Diagnostic | None:
        if not lines:
            return None

        severity: Literal["error", "warning", "info"] = "warning" if success else "error"
        line_no = 1

        if language == "python":
            for line in lines:
                match = PYTHON_LINE_RE.search(line)
                if match:
                    line_no = int(match.group("line"))
            return Diagnostic(line=line_no, column=1, message=lines[-1], severity=severity)

        if language == "javascript":
            for line in lines:
                match = JAVASCRIPT_LINE_RE.match(line)
                if match:
                    line_no = int(match.group("line"))
                    break
            return Diagnostic(line=line_no, column=1, message=lines[-1], severity=severity)

        return Diagnostic(line=line_no, column=1, message=lines[-1], severity=severity)


# ----------------- 가짜 구현체 (개발/테스트용) -----------------
class MockBppCompiler:
    async def compile(self, source_code: str, options: List[str], language: str = "bpp") -> dict:
        await asyncio.sleep(0)
        output = "Hello World" if "Hello World" in source_code else "실행 완료"
        return {
            "is_success": True,
            "ast": {"type": "Program", "body": "Mock AST Data"},
            "cfg": {"nodes": ["A", "B"], "edges": ["A->B"]},
            "stdout": output,
            "execution_time": 1.0,
        }


compiler_instance = DockerCompilerRunner()


async def mock_execute_pipeline(source_code: str, passes: List[str]) -> dict:
    await asyncio.sleep(2)
    pass_results = [{"pass_name": p, "log": f"{p} 적용 완료"} for p in passes]
    return {
        "is_success": True,
        "pipeline_used": passes,
        "pass_results": pass_results,
        "final_asm": "MOV EAX, 1",
    }


# ----------------- 백그라운드 워커 함수들 (Async) -----------------
async def process_compile_job(job_id: str, source_code: str, options: List[str], language: str = "bpp"):
    if job_store[job_id]["status"] == "CANCELED":
        return
    job_store[job_id]["status"] = "RUNNING"
    try:
        result = await compiler_instance.compile(source_code, language)
        if job_store[job_id].get("status") == "CANCELED":
            return
        job_store[job_id]["status"] = "COMPLETED"
        job_store[job_id]["result"] = result
    except Exception as e:
        if job_store[job_id].get("status") != "CANCELED":
            job_store[job_id]["status"] = "FAILED"
            job_store[job_id]["error"] = str(e)


async def process_lab_job(job_id: str, source_code: str, passes: List[str]):
    if job_store[job_id]["status"] == "CANCELED":
        return
    job_store[job_id]["status"] = "RUNNING"
    try:
        result = await mock_execute_pipeline(source_code, passes)
        if job_store[job_id].get("status") == "CANCELED":
            return
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
    if base_slug not in snippet_store:
        return base_slug
    suffix_counter = 1
    while f"{base_slug}-{suffix_counter}" in snippet_store:
        suffix_counter += 1
    return f"{base_slug}-{suffix_counter}"


def generate_text_diff(text1: str, text2: str) -> str:
    diff = difflib.unified_diff(
        text1.splitlines(keepends=True),
        text2.splitlines(keepends=True),
        fromfile='Base Version',
        tofile='New Version',
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
