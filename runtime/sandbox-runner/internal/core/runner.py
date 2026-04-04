from __future__ import annotations

import json
from pathlib import Path

from internal.model import ExecutionMetrics, ExecutionRequest, ExecutionResult, ExecutionViolation, FinalStatus, OutputMeta, to_dict
from internal.policy import EngineType, LocalExecutionEngine, NamespaceExecutionEngine

from .state_machine import RunnerState, can_transition
from .validation import validate_execution_request


def transition(current: RunnerState, nxt: RunnerState) -> RunnerState:
    if not can_transition(current, nxt):
        raise RuntimeError(f"invalid state transition: {current.value} -> {nxt.value}")
    return nxt


def select_engine(engine_name: str):
    if engine_name == EngineType.NAMESPACE.value:
        return NamespaceExecutionEngine()
    return LocalExecutionEngine()


def run_request(root_dir: Path, request: ExecutionRequest) -> ExecutionResult:
    state = RunnerState.CREATED
    state = transition(state, RunnerState.VALIDATING)

    validation_failure = validate_execution_request(request)
    if validation_failure is not None:
        state = transition(state, RunnerState.FAILED)
        return ExecutionResult(
            request_id=request.request_id,
            sample_name=request.sample_name,
            final_status=FinalStatus.INTERNAL_ERROR,
            exit_code=1,
            internal_reason_code=validation_failure.reason_code,
            notes=validation_failure.message,
            metadata={"runnerState": state.value},
        )

    state = transition(state, RunnerState.PREPARING)
    report_dir = root_dir / "reports" / request.sample_name
    raw_report_json = report_dir / "raw-result.json"
    result_json = report_dir / "result.json"
    engine_name = request.metadata.get("engine", EngineType.LOCAL.value)
    engine = select_engine(engine_name)

    state = transition(state, RunnerState.RUNNING)
    try:
        completed = engine.run_sample(
            root_dir,
            request.sample_name,
            stdin_data=request.stdin_data,
            working_directory=request.working_directory,
            args=request.args,
        )
    except Exception as exc:
        state = transition(state, RunnerState.FAILED)
        return ExecutionResult(
            request_id=request.request_id,
            sample_name=request.sample_name,
            final_status=FinalStatus.INTERNAL_ERROR,
            exit_code=1,
            internal_reason_code="execution_engine_failed",
            notes=str(exc),
            metadata={"runnerState": state.value, "engine": engine_name},
        )

    if completed.returncode != 0:
        state = transition(state, RunnerState.FAILED)
        return ExecutionResult(
            request_id=request.request_id,
            sample_name=request.sample_name,
            final_status=FinalStatus.INTERNAL_ERROR,
            exit_code=completed.returncode,
            internal_reason_code="poc_runner_execution_failed",
            notes=completed.stderr.strip(),
            metadata={"runnerState": state.value, "engine": engine_name},
        )

    state = transition(state, RunnerState.COLLECTING)
    data = json.loads(raw_report_json.read_text())
    result = _build_result_from_report(report_dir, request, data, engine_name)
    result_json.write_text(json.dumps(to_dict(result), ensure_ascii=True, indent=2) + "\n")
    transition(state, RunnerState.FINISHED)
    return result


def _build_result_from_report(
    report_dir: Path,
    request: ExecutionRequest,
    data: dict,
    engine_name: str,
) -> ExecutionResult:
    stdout = (report_dir / "stdout.txt").read_text()
    stderr = (report_dir / "stderr.txt").read_text()
    violation = None
    if data["violation"] is not None:
        violation = ExecutionViolation(
            category=data["violation"]["category"],
            reason=data["violation"]["reason"],
            message=data["violation"]["message"],
            resource=data["violation"]["resource"],
        )

    metadata = {
        **data["metadata"],
        "engine": engine_name,
        "runnerState": RunnerState.FINISHED.value,
        "requestId": request.request_id,
    }
    trace_id = request.metadata.get("traceId")
    if trace_id:
        metadata["traceId"] = trace_id

    return ExecutionResult(
        request_id=request.request_id,
        sample_name=data["sampleName"],
        final_status=FinalStatus(data["finalStatus"]),
        exit_code=data["exitCode"],
        runtime_error_reason=data.get("runtimeErrorReason", ""),
        signal=data["signal"],
        started_at=data["startedAt"],
        finished_at=data["finishedAt"],
        metrics=ExecutionMetrics(
            duration_ms=data["metrics"]["durationMs"],
            cpu_time_ms=data["metrics"]["cpuTimeMs"],
            peak_memory_kb=data["metrics"]["peakMemoryKb"],
            stdout_bytes=data["metrics"]["stdoutBytes"],
            stderr_bytes=data["metrics"]["stderrBytes"],
        ),
        violation=violation,
        stdout=stdout,
        stderr=stderr,
        stdout_meta=OutputMeta(
            bytes=data["stdoutMeta"]["bytes"],
            truncated=data["stdoutMeta"]["truncated"],
            encoding=data["stdoutMeta"]["encoding"],
        ),
        stderr_meta=OutputMeta(
            bytes=data["stderrMeta"]["bytes"],
            truncated=data["stderrMeta"]["truncated"],
            encoding=data["stderrMeta"]["encoding"],
        ),
        internal_reason_code=data["internalReasonCode"],
        notes=f"runner_state={RunnerState.FINISHED.value}",
        metadata=metadata,
    )
