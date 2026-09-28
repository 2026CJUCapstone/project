import asyncio
import contextlib
import difflib
import json
import re
import shutil
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import docker
from docker.errors import APIError, DockerException
from docker.types import LogConfig, Ulimit
from requests.exceptions import ReadTimeout

from app.core.config import settings
from app.services.execution_phase import ExecutionPhaseDecoder
from app.services.compiler_graphs import (
    build_bpp_asm,
    build_bpp_asm_from_json,
    build_bpp_ast_graph,
    build_bpp_pipeline_from_json,
    build_bpp_ir,
    build_bpp_ssa_graph,
)

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
BPP_DIAGNOSTIC_RE = re.compile(
    r"^\[(?P<severity>ERROR|WARN|WARNING|INFO)\](?P<tags>(?:\[[^\]]+\])*)\s*(?P<message>.*)$"
)
BPP_LINE_COL_RE = re.compile(r"\bline (?P<line>\d+), column (?P<column>\d+)\b")
BPP_ARROW_LOCATION_RE = re.compile(r"^-->\s*(?P<line>\d+):(?P<column>\d+)\b")
BPP_TAG_RE = re.compile(r"\[([^\]]+)\]")
BPP_GENERIC_MESSAGE_PREFIXES = (
    "failed to load module:",
    "compiler pipeline completed with diagnostics",
    "parse failed",
)


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
    async def compile(
        self,
        source_code: str,
        language: str,
        optimize: bool = False,
        target: str = "all",
    ) -> dict:
        pass


class DockerCompilerRunner:
    def __init__(self, *, start_guard=None, labels=None, operation_guard=None, cleanup_guard=None, client_factory=None):
        self.start_guard = start_guard
        self.labels = labels or {}
        self.operation_guard = operation_guard
        self.cleanup_guard = cleanup_guard
        self.client_factory = client_factory

    def measured_submission(self, payload):
        from app.services.measured_judge import MeasuredSubmission
        from app.services.judge_runtime_registry import RuntimeRegistry
        snapshot=getattr(self,'measured_snapshot',None)
        worker_class=getattr(self,'measured_worker_class',settings.JUDGE_WORKER_CLASS)
        if snapshot is not None:
            return MeasuredSubmission(self,payload,None,worker_class,snapshot=snapshot)
        return MeasuredSubmission(self,payload,
            RuntimeRegistry.load(settings.JUDGE_RUNTIME_REGISTRY),worker_class)

    async def compile(
        self,
        source_code: str,
        language: str,
        optimize: bool = False,
        target: str = "all",
    ) -> dict:
        started_at = time.monotonic()
        requested_targets = self._resolve_requested_targets(target) if language == "bpp" else set()

        result = await self._execute(
            mode="compile-json" if requested_targets else "compile",
            source_code=source_code,
            language=language,
            optimize=optimize,
        )

        diagnostics = self._parse_diagnostics(result["stderr"], language, result["exit_code"] == 0)
        errors = [item.to_dict() for item in diagnostics if item.severity == "error"]
        warnings = [item.to_dict() for item in diagnostics if item.severity == "warning"]
        response = {
            "success": result["exit_code"] == 0 and not result.get("failure_reason"),
            "failure_reason": result.get("failure_reason"),
            "errors": errors,
            "warnings": warnings,
            "execution_time": result["execution_time"],
            "metadata": {
                "node_count": len(source_code.splitlines()),
                "optimization_level": 1 if optimize else 0,
            },
        }

        if not response["success"] or language != "bpp":
            return response

        source_filename = self._resolve_filename(language, source_code)
        resolved_targets: set[str] = set()

        if requested_targets:
            # The sandbox returns JSON only after assembling and linking the
            # same compilation's full native output. Older images fail closed
            # on this mode instead of silently bypassing native validation.
            json_result = result
            if json_result["exit_code"] == 0:
                pipeline = build_bpp_pipeline_from_json(
                    json_result["stdout"],
                    source_code,
                    source_filename,
                    requested_targets,
                )
                if pipeline:
                    for target_name in ("ast", "ssa", "ir", "asm"):
                        if (
                            target_name in requested_targets
                            and target_name in pipeline
                            and self._pipeline_target_has_data(target_name, pipeline[target_name])
                        ):
                            response[target_name] = pipeline[target_name]
                            resolved_targets.add(target_name)
                            if target_name == "ast":
                                response["metadata"]["node_count"] = len(pipeline[target_name].get("nodes", []))
                    if isinstance(pipeline.get("sourceRangeSemantics"), dict):
                        response["metadata"]["source_range_semantics"] = pipeline["sourceRangeSemantics"]

        missing_targets = requested_targets - resolved_targets

        # Compatibility fallback for older/incomplete unified payloads only.
        # Modern Bpp supplies views.ir in a stage="ir" SSA envelope, which
        # the parser consumes without starting another compiler/container.
        if "ir" in missing_targets:
            ir_json = await self._execute(
                mode="dump-ir-json", source_code=source_code,
                language=language, optimize=optimize,
            )
            if ir_json["exit_code"] == 0:
                ir_pipeline = build_bpp_pipeline_from_json(
                    ir_json["stdout"], source_code, source_filename, {"ir"},
                )
                if ir_pipeline and self._pipeline_target_has_data("ir", ir_pipeline.get("ir")):
                    response["ir"] = ir_pipeline["ir"]
                    missing_targets.remove("ir")
                    if isinstance(ir_pipeline.get("sourceRangeSemantics"), dict):
                        response["metadata"]["source_range_semantics"] = ir_pipeline["sourceRangeSemantics"]

        if "ast" in missing_targets:
            ast_graph = build_bpp_ast_graph(source_code)
            response["ast"] = ast_graph
            response["metadata"]["node_count"] = len(ast_graph["nodes"])
            resolved_targets.add("ast")

        # One accepted job owns one execution slot. Do not fan it out into
        # several simultaneous containers when graph JSON falls back to dumps.
        dump_results: dict[str, dict] = {}
        if "ssa" in missing_targets:
            dump_results["ssa"] = await self._execute(
                    mode="dump-ssa",
                    source_code=source_code,
                    language=language,
                    optimize=optimize,
            )
        if "ir" in missing_targets:
            dump_results["ir"] = await self._execute(
                    mode="dump-ir",
                    source_code=source_code,
                    language=language,
                    optimize=optimize,
            )
        if "asm" in missing_targets:
            dump_results["asm"] = await self._execute(
                    mode="asm",
                    source_code=source_code,
                    language=language,
                    optimize=optimize,
            )

        if dump_results:
            for target_name, dump_result in dump_results.items():
                if dump_result["exit_code"] != 0:
                    continue
                if target_name == "ssa":
                    response["ssa"] = build_bpp_ssa_graph(dump_result["stdout"], source_code)
                elif target_name == "ir":
                    response["ir"] = build_bpp_ir(dump_result["stdout"], source_code)
                elif target_name == "asm":
                    response["asm"] = build_bpp_asm_from_json(
                        dump_result["stdout"],
                        source_filename,
                    ) or build_bpp_asm(
                        dump_result["stdout"],
                        source_code,
                    )

        response["execution_time"] = round((time.monotonic() - started_at) * 1000, 2)
        return response

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
        mode: Literal["compile", "compile-json", "run", "dump-ir", "dump-ir-json", "dump-ssa", "asm", "json"],
        source_code: str,
        language: str,
        stdin: str = "",
        optimize: bool = False,
    ) -> dict:
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"지원하지 않는 언어입니다: {language}")

        sandbox_root = Path(settings.SANDBOX_WORKDIR_ROOT)
        sandbox_root.mkdir(parents=True, exist_ok=True)
        prefix = "job-"
        if self.labels.get('webcompiler.job') and self.labels.get('webcompiler.lease'):
            prefix = f"job-{self.labels['webcompiler.job']}-{self.labels['webcompiler.lease']}-"
        temp_dir = Path(tempfile.mkdtemp(prefix=prefix, dir=sandbox_root))
        container = None
        output_stream = None
        output_task = None
        phase_token = uuid.uuid4().hex
        phase = ExecutionPhaseDecoder(phase_token)
        failure_reason = None

        try:
            temp_dir.chmod(0o755)
            source_path = temp_dir / self._resolve_filename(language, source_code)
            source_path.write_text(source_code, encoding="utf-8", newline="")
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

            start_time = time.monotonic()
        except BaseException:
            await self._remove_workdir(temp_dir)
            raise

        try:
            container = await self._allocate_container(
                client.containers.create,
                image=settings.SANDBOX_IMAGE,
                command=command,
                detach=True,
                name=container_name,
                labels=self.labels,
                network_disabled=True,
                read_only=True,
                tmpfs={"/tmp": f"rw,exec,nosuid,size={settings.SANDBOX_MEMORY_MB}m"},
                mem_limit=f"{settings.SANDBOX_MEMORY_MB}m",
                memswap_limit=f"{settings.SANDBOX_MEMORY_MB}m",
                nano_cpus=max(1, int(settings.SANDBOX_CPU_LIMIT * 1_000_000_000)),
                pids_limit=settings.SANDBOX_PIDS_LIMIT,
                ulimits=[Ulimit(name="nofile", soft=settings.SANDBOX_NOFILE_LIMIT, hard=settings.SANDBOX_NOFILE_LIMIT)],
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                log_config=LogConfig(type="none"),
                volumes={str(temp_dir): {"bind": "/workspace", "mode": "ro"}},
                environment={
                    "COMPILER_OPTIMIZE": "1" if optimize else "0",
                    "COMPILER_PHASE_TOKEN": phase_token,
                    "HOME": "/tmp",
                },
            )
            # Attach before start, so fast programs cannot lose their first bytes.
            # Stream directly; Docker must not retain an unbounded log on disk.
            output_stream = await asyncio.to_thread(container.attach, stream=True, logs=False, demux=True)
            output_task = asyncio.create_task(asyncio.to_thread(self._collect_output, output_stream, container, phase))
            await self._start_container(container)
            wait_result = await self._wait_for_exit(container)
            stdout, stderr, output_exceeded = await asyncio.wait_for(asyncio.shield(output_task), timeout=settings.EXECUTION_TIMEOUT)
            exit_code = int(wait_result.get("StatusCode", 1))
            if container.attrs.get('State', {}).get('OOMKilled') is True:
                failure_reason = 'memory_limit_exceeded'
            if output_exceeded:
                exit_code = 1
                stderr += b"\nOutput limit exceeded."
                # Preserve proven OOM if both collectors observed a failure.
                failure_reason = failure_reason or 'output_limit_exceeded'
        except TimeoutError:
            if container is not None:
                await self._kill_container(container)
            elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
            return {
                "stdout": "",
                "stderr": "실행 시간이 초과되었습니다. (Timeout)",
                "exit_code": 124,
                "execution_time": elapsed_ms,
                "execution_phase": phase.phase,
                "failure_reason": "time_limit_exceeded",
            }
        except (DockerException, APIError) as exc:
            raise SandboxExecutionError(f"Docker 샌드박스 실행 중 오류가 발생했습니다: {exc}") from exc
        except Exception as exc:
            raise SandboxExecutionError(f"샌드박스 실행 중 오류가 발생했습니다: {exc}") from exc
        finally:
            # One durable cleanup intent can cover both resources. Keep the
            # container-first order, and never delete the mounted source after
            # an uncertain daemon response. The worker still confirms complete
            # claim absence before releasing capacity/publishing the receipt.
            try:
                await self._remove_execution_resources(container, temp_dir)
            finally:
                if output_stream is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(output_stream.close)
                if output_task is not None:
                    if not output_task.done():
                        output_task.cancel()
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        await output_task

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": exit_code,
            "execution_time": elapsed_ms,
            "execution_phase": phase.phase,
            "failure_reason": failure_reason,
        }

    async def _allocate_container(self, create, **kwargs):
        def allocate():
            if self.operation_guard is None:
                return create(**kwargs)
            def action(operation):
                options={**kwargs,'name':operation['name'],
                    'labels':{**(kwargs.get('labels') or self.labels),
                        'webcompiler.operation':operation['id']}}
                return create(**options)
            return self.operation_guard('create',action)
        task = asyncio.create_task(asyncio.to_thread(allocate))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancelling to_thread does not cancel the Docker request. Wait for
            # allocation to finish so the newly created container is not lost.
            with contextlib.suppress(Exception):
                container = await task
                await self._remove_container(container)
            raise

    async def _start_container(self, container):
        def start():
            if self.operation_guard is not None:
                return self.operation_guard('start',lambda operation:container.start(),container_id=container.id)
            if self.start_guard is None:
                container.start()
            elif not self.start_guard(container.start):
                raise SandboxExecutionError("Execution lease is no longer valid")
        task = asyncio.create_task(asyncio.to_thread(start))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Join the start request before finally removes the container.
            with contextlib.suppress(Exception):
                await task
            raise

    def _collect_output(self, stream, container, phase=None):
        """One combined stdout/stderr budget; no all-output logs() call."""
        remaining = max(1, settings.SANDBOX_OUTPUT_MAX_BYTES)
        stdout, stderr = bytearray(), bytearray()
        def decoded_chunks():
            for out, err in stream:
                yield out, phase.feed(err or b'') if phase is not None else err
            if phase is not None:
                yield None, phase.finish()
        for out, err in decoded_chunks():
            for chunk, target in ((out, stdout), (err, stderr)):
                if not chunk:
                    continue
                kept = min(remaining, len(chunk))
                target.extend(chunk[:kept])
                remaining -= kept
                if kept < len(chunk):
                    with contextlib.suppress(DockerException, APIError):
                        container.kill()
                    return bytes(stdout), bytes(stderr), True
        return bytes(stdout), bytes(stderr), False

    def _resolve_requested_targets(self, target: str) -> set[str]:
        if target == "all":
            return {"ast", "ssa", "ir", "asm"}
        return {target}

    def _pipeline_target_has_data(self, target: str, value: object) -> bool:
        if not isinstance(value, dict):
            return False
        # A successfully parsed, empty view is still complete (for example
        # when source filtering removes all generated instructions).
        field = {"ast": "nodes", "ssa": "blocks", "ir": "instructions", "asm": "lines"}.get(target)
        return field is not None and isinstance(value.get(field), list)

    def _get_client(self) -> docker.DockerClient:
        if self.client_factory is not None:
            return self.client_factory()
        try:
            client = docker.from_env()
            client.ping()
            return client
        except DockerException as exc:
            raise SandboxExecutionError(f"Docker 실행 환경을 찾을 수 없습니다: {exc}") from exc

    async def _wait_for_exit(self, container: docker.models.containers.Container) -> dict:
        # Docker's wait endpoint wakes at exit. Polling inspect adds an extra
        # interval (and repeated daemon calls) to every short compilation.
        # Bound both the coroutine and the underlying HTTP request: cancelling
        # to_thread alone does not cancel its socket. The caller always kills /
        # removes the sandbox on timeout or cancellation before releasing its
        # lease. Inspect once afterwards to retain the authoritative OOM flag.
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(container.wait, timeout=settings.EXECUTION_TIMEOUT),
                timeout=settings.EXECUTION_TIMEOUT,
            )
        except ReadTimeout as exc:
            raise TimeoutError("Sandbox execution timed out") from exc
        await asyncio.to_thread(container.reload)
        return result

    async def _kill_container(self, container: docker.models.containers.Container) -> None:
        with contextlib.suppress(DockerException, APIError):
            await asyncio.to_thread(container.kill)

    async def _remove_container(self, container: docker.models.containers.Container) -> None:
        with contextlib.suppress(DockerException, APIError):
            await self._cleanup(lambda:container.remove(force=True))

    async def _cleanup(self, action):
        if self.cleanup_guard is None:
            await asyncio.to_thread(action)
            return True
        return await asyncio.to_thread(self.cleanup_guard,action)

    async def _remove_workdir(self, directory):
        return await self._cleanup(lambda: self._delete_workdir(directory))

    async def _remove_execution_resources(self, container, directory):
        def remove():
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass
            self._delete_workdir(directory)
        return await self._cleanup(remove)

    @staticmethod
    def _delete_workdir(directory):
        try:
            shutil.rmtree(directory)
        except FileNotFoundError:
            return
        # A cleanup guard may execute on a delayed/remote filesystem. Do not
        # publish a terminal receipt unless absence is observable.
        if directory.exists():
            raise RuntimeError('Sandbox work directory cleanup was not confirmed')

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

        if language == "bpp":
            diagnostics = self._parse_bpp_diagnostics(lines)
            if diagnostics:
                return diagnostics

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

        tags = BPP_TAG_RE.findall(match.group("tags") or "")
        code = next((tag for tag in reversed(tags) if re.fullmatch(r"[A-Z]\d+", tag)), None)

        return Diagnostic(
            line=line_no,
            column=column_no,
            message=message,
            severity=severity,
            code=code,
        )

    def _parse_bpp_diagnostics(self, lines: list[str]) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []

        for line in lines:
            location = BPP_ARROW_LOCATION_RE.match(line)
            if location and diagnostics:
                diagnostics[-1].line = int(location.group("line"))
                diagnostics[-1].column = int(location.group("column"))
                continue

            diagnostic = self._parse_bpp_style(line)
            if diagnostic is not None and diagnostic.message:
                diagnostics.append(diagnostic)

        if not diagnostics:
            return []

        specific = [
            diagnostic
            for diagnostic in diagnostics
            if not self._is_bpp_generic_message(diagnostic.message)
        ]
        return self._dedupe_diagnostics(specific or diagnostics)

    def _is_bpp_generic_message(self, message: str) -> bool:
        normalized = message.strip().lower()
        return any(normalized.startswith(prefix) for prefix in BPP_GENERIC_MESSAGE_PREFIXES)

    def _dedupe_diagnostics(self, diagnostics: list[Diagnostic]) -> list[Diagnostic]:
        seen: set[tuple[str, int, int, str, str | None]] = set()
        unique: list[Diagnostic] = []
        for diagnostic in diagnostics:
            key = (
                diagnostic.severity,
                diagnostic.line,
                diagnostic.column,
                diagnostic.message,
                diagnostic.code,
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(diagnostic)
        return unique

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


compiler_instance = DockerCompilerRunner()


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
