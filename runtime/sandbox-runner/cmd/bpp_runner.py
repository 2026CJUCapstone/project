#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from internal.model import ExecutionMetrics, ExecutionResult, FinalStatus, OutputMeta, to_dict


DEFAULT_TIMEOUT_MS = int(os.environ.get("BPP_TIMEOUT_MS", "3000"))
DEFAULT_STDOUT_BUFFER_BYTES = int(os.environ.get("BPP_STDOUT_BUFFER_BYTES", "65536"))
DEFAULT_STDERR_BUFFER_BYTES = int(os.environ.get("BPP_STDERR_BUFFER_BYTES", "65536"))


def iso_now(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def keep_tail(text: str, max_bytes: int) -> tuple[str, int, bool]:
    raw = text.encode("utf-8", errors="replace")
    total = len(raw)
    if total <= max_bytes:
        return text, total, False
    trimmed = raw[-max_bytes:]
    return trimmed.decode("utf-8", errors="replace"), total, True


def resolve_bpp_executable() -> str:
    candidates = [
        os.environ.get("BPP_EXECUTABLE", ""),
        shutil.which("bpp") or "",
        "/usr/local/bin/bpp",
        "/opt/bpp/bin/bpp",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError(
        "B++ compiler not found. Set BPP_EXECUTABLE or install the 'bpp' launcher in PATH."
    )


def build_bpp_command(
    bpp_executable: str,
    source_path: str,
    mode: str,
    opt_level: str,
    extra_args: list[str],
) -> list[str]:
    command = [bpp_executable]
    command.append("-O1" if opt_level == "O1" else "-O0")
    if mode == "dump-ir":
        command.append("-dump-ir")
    elif mode == "dump-ssa":
        command.append("-dump-ssa")
    elif mode == "asm":
        command.append("-asm")
    command.extend(extra_args)
    command.append(source_path)
    return command


def runtime_error_reason(returncode: int) -> tuple[str, str]:
    if returncode == 0:
        return "", ""
    if returncode < 0:
        sig = -returncode
        if sig == signal.SIGSEGV:
            return "signal_segv", "SIGSEGV"
        if sig == signal.SIGABRT:
            return "signal_abrt", "SIGABRT"
        if sig == signal.SIGTERM:
            return "signal_term", "SIGTERM"
        if sig == signal.SIGKILL:
            return "signal_kill", "SIGKILL"
        return "unknown_signal", ""
    return "nonzero_exit", ""


def load_request(path: Path) -> dict:
    return json.loads(path.read_text())


def run_bpp_request(request: dict) -> ExecutionResult:
    request_id = request.get("requestId", "bpp-run-001")
    source_path = str(Path(request["sourcePath"]).resolve())
    source_name = Path(source_path).name
    mode = request.get("mode", "run")
    opt_level = request.get("optLevel", "O0")
    working_directory = request.get("workingDirectory") or str(Path(source_path).parent)
    stdin_data = request.get("stdinData", "")
    trace_id = request.get("metadata", {}).get("traceId", "")
    timeout_ms = int(request.get("timeoutMs", DEFAULT_TIMEOUT_MS))
    extra_args = request.get("extraArgs", [])
    started = time.time()

    try:
        bpp_executable = resolve_bpp_executable()
    except FileNotFoundError as exc:
        finished = time.time()
        return ExecutionResult(
            request_id=request_id,
            sample_name=source_name,
            final_status=FinalStatus.INTERNAL_ERROR,
            exit_code=1,
            started_at=iso_now(started),
            finished_at=iso_now(finished),
            internal_reason_code="bpp_executable_not_found",
            notes=str(exc),
            metadata={
                "requestId": request_id,
                "traceId": trace_id,
                "targetLanguage": "bpp",
                "mode": mode,
                "optLevel": opt_level,
            },
        )

    command = build_bpp_command(
        bpp_executable=bpp_executable,
        source_path=source_path,
        mode=mode,
        opt_level=opt_level,
        extra_args=extra_args,
    )

    try:
        completed = subprocess.run(
            command,
            input=stdin_data,
            text=True,
            capture_output=True,
            cwd=working_directory,
            timeout=max(1, timeout_ms // 1000),
        )
        finished = time.time()
    except subprocess.TimeoutExpired as exc:
        finished = time.time()
        stdout_text, stdout_total_bytes, stdout_truncated = keep_tail(
            exc.stdout or "", DEFAULT_STDOUT_BUFFER_BYTES
        )
        stderr_text, stderr_total_bytes, stderr_truncated = keep_tail(
            exc.stderr or "", DEFAULT_STDERR_BUFFER_BYTES
        )
        return ExecutionResult(
            request_id=request_id,
            sample_name=source_name,
            final_status=FinalStatus.TIMEOUT,
            exit_code=124,
            started_at=iso_now(started),
            finished_at=iso_now(finished),
            metrics=ExecutionMetrics(
                duration_ms=int((finished - started) * 1000),
                stdout_bytes=len(stdout_text.encode("utf-8")),
                stderr_bytes=len(stderr_text.encode("utf-8")),
            ),
            stdout=stdout_text,
            stderr=stderr_text,
            stdout_meta=OutputMeta(bytes=len(stdout_text.encode("utf-8")), truncated=stdout_truncated, encoding="utf-8"),
            stderr_meta=OutputMeta(bytes=len(stderr_text.encode("utf-8")), truncated=stderr_truncated, encoding="utf-8"),
            internal_reason_code="wall_time_limit_exceeded",
            notes="bpp runner timeout",
            metadata={
                "requestId": request_id,
                "traceId": trace_id,
                "targetLanguage": "bpp",
                "mode": mode,
                "optLevel": opt_level,
                "workingDirectory": working_directory,
                "stdoutTotalBytes": stdout_total_bytes,
                "stderrTotalBytes": stderr_total_bytes,
            },
        )

    final_status = FinalStatus.SUCCESS if completed.returncode == 0 else FinalStatus.RUNTIME_ERROR
    err_reason, signal_name = runtime_error_reason(completed.returncode)
    stdout_text, stdout_total_bytes, stdout_truncated = keep_tail(completed.stdout, DEFAULT_STDOUT_BUFFER_BYTES)
    stderr_text, stderr_total_bytes, stderr_truncated = keep_tail(completed.stderr, DEFAULT_STDERR_BUFFER_BYTES)
    return ExecutionResult(
        request_id=request_id,
        sample_name=source_name,
        final_status=final_status,
        exit_code=completed.returncode,
        runtime_error_reason=err_reason,
        signal=signal_name,
        started_at=iso_now(started),
        finished_at=iso_now(finished),
        metrics=ExecutionMetrics(
            duration_ms=int((finished - started) * 1000),
            stdout_bytes=len(stdout_text.encode("utf-8")),
            stderr_bytes=len(stderr_text.encode("utf-8")),
        ),
        stdout=stdout_text,
        stderr=stderr_text,
        stdout_meta=OutputMeta(bytes=len(stdout_text.encode("utf-8")), truncated=stdout_truncated, encoding="utf-8"),
        stderr_meta=OutputMeta(bytes=len(stderr_text.encode("utf-8")), truncated=stderr_truncated, encoding="utf-8"),
        notes="bpp runner completed",
        metadata={
            "requestId": request_id,
            "traceId": trace_id,
            "targetLanguage": "bpp",
            "bppExecutable": bpp_executable,
            "mode": mode,
            "optLevel": opt_level,
            "workingDirectory": working_directory,
            "stdoutTotalBytes": stdout_total_bytes,
            "stderrTotalBytes": stderr_total_bytes,
        },
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run B++ compiler in project runtime")
    parser.add_argument("--request", help="Path to a B++ runtime request JSON file")
    parser.add_argument("--source", help="Path to a .bpp source file")
    parser.add_argument("--mode", default="run", choices=["run", "dump-ir", "dump-ssa", "asm"])
    parser.add_argument("--opt-level", default="O0", choices=["O0", "O1"])
    parser.add_argument("--stdin-file", help="Optional stdin file")
    parser.add_argument("--working-directory", default="")
    parser.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS)
    parser.add_argument("--trace-id", default="")
    parser.add_argument("--request-id", default="bpp-run-001")
    parser.add_argument("--extra-arg", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.request:
        request = load_request(Path(args.request))
    else:
        if not args.source:
            print("Either --request or --source must be provided.", file=sys.stderr)
            return 2
        stdin_data = ""
        if args.stdin_file:
            stdin_data = Path(args.stdin_file).read_text()
        request = {
            "requestId": args.request_id,
            "sourcePath": str(Path(args.source).resolve()),
            "mode": args.mode,
            "optLevel": args.opt_level,
            "stdinData": stdin_data,
            "workingDirectory": args.working_directory,
            "timeoutMs": args.timeout_ms,
            "extraArgs": args.extra_arg,
            "metadata": {"traceId": args.trace_id},
        }

    result = run_bpp_request(request)
    print(json.dumps(to_dict(result), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
