from __future__ import annotations

from enum import Enum
from typing import Any

from internal.model import ExecutionRequest, ExecutionResult, FinalStatus, RuntimeOutcome
from internal.policy import PolicyTemplate, default_policy_template, policy_template_from_admin_payload


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


OFFICIAL_DEFAULT_LIMITS = {
    "timeoutMs": 3000,
    "cpuQuota": 1,
    "cpuTimeMs": 3000,
    "memoryLimitMB": 256,
    "processLimit": 64,
    "maxThreads": 8,
    "stdoutBufferBytes": 65536,
    "stderrBufferBytes": 65536,
    "maxOpenFiles": 32,
    "networkMode": "no-network",
    "filesystemMode": "isolated",
    "syscallProfile": "minimal-runtime",
}


def validate_run_request(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data.get("code"), str) or not data["code"].strip():
        errors.append("code is required")
    stdin = data.get("stdin", "")
    if not isinstance(stdin, str):
        errors.append("stdin must be a string")
    timeout_ms = data.get("timeoutMs", OFFICIAL_DEFAULT_LIMITS["timeoutMs"])
    if not isinstance(timeout_ms, int) or timeout_ms <= 0:
        errors.append("timeoutMs must be a positive integer")
    return errors


def validate_compile_request(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data.get("code"), str) or not data["code"].strip():
        errors.append("code is required")
    language = data.get("language", "bpp")
    if language != "bpp":
        errors.append("language must be bpp")
    options = data.get("options", {})
    if options.get("target", "native") not in {"native", "wasm"}:
        errors.append("options.target must be native or wasm")
    if options.get("optLevel", "O0") not in {"O0", "O1", "O2"}:
        errors.append("options.optLevel must be O0, O1, or O2")
    if not isinstance(options.get("preset", "safe-default"), str):
        errors.append("options.preset must be a string")
    return errors


def validate_analyze_request(data: dict[str, Any]) -> list[str]:
    errors = validate_compile_request({"code": data.get("code", ""), "language": "bpp", "options": data.get("options", {})})
    stdin = data.get("stdin", "")
    if not isinstance(stdin, str):
        errors.append("stdin must be a string")
    return errors


def normalize_run_request(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "requestType": "run",
        "code": data["code"],
        "stdin": data.get("stdin", ""),
        "timeoutMs": data.get("timeoutMs", OFFICIAL_DEFAULT_LIMITS["timeoutMs"]),
    }


def normalize_compile_request(data: dict[str, Any]) -> dict[str, Any]:
    options = data.get("options", {})
    return {
        "requestType": "compile",
        "code": data["code"],
        "language": data.get("language", "bpp"),
        "options": {
            "target": options.get("target", "native"),
            "optLevel": options.get("optLevel", "O0"),
            "preset": options.get("preset", "safe-default"),
            "optimize": options.get("optimize", False),
        },
    }


def normalize_analyze_request(data: dict[str, Any]) -> dict[str, Any]:
    options = data.get("options", {})
    return {
        "requestType": "analyze",
        "code": data["code"],
        "stdin": data.get("stdin", ""),
        "options": {
            "emitAst": options.get("emitAst", False),
            "emitCfg": options.get("emitCfg", False),
            "emitSsa": options.get("emitSsa", False),
            "emitAsm": options.get("emitAsm", False),
            "profile": options.get("profile", False),
            "target": options.get("target", "native"),
            "optLevel": options.get("optLevel", "O0"),
            "preset": options.get("preset", "safe-default"),
        },
    }


def adapt_admin_policy_to_template(policy: dict[str, Any]) -> PolicyTemplate:
    if not policy:
        return default_policy_template()
    return policy_template_from_admin_payload(policy)


def adapt_admin_policy_to_execution_limits(policy: dict[str, Any]):
    return adapt_admin_policy_to_template(policy).to_execution_limits()


def build_internal_execution_request(
    request_id: str,
    sample_name: str,
    executable_path: str,
    *,
    stdin_data: str = "",
    working_directory: str = "",
    args: list[str] | None = None,
    policy: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionRequest:
    template = adapt_admin_policy_to_template(policy or {})
    return ExecutionRequest(
        request_id=request_id,
        sample_name=sample_name,
        executable_path=executable_path,
        args=args or [],
        stdin_data=stdin_data,
        working_directory=working_directory,
        limits=template.to_execution_limits(),
        metadata={
            "policyName": template.name,
            "policyVersion": template.version,
            "policySource": template.source,
            **(template.metadata or {}),
            **(metadata or {}),
        },
    )


def map_final_status_to_runtime_outcome(final_status: FinalStatus) -> str:
    mapping = {
        FinalStatus.SUCCESS: RuntimeOutcome.SUCCESS.value,
        FinalStatus.RUNTIME_ERROR: RuntimeOutcome.RUNTIME_ERROR.value,
        FinalStatus.TIMEOUT: RuntimeOutcome.TIMEOUT.value,
        FinalStatus.OOM: RuntimeOutcome.OOM.value,
        FinalStatus.SECURITY_VIOLATION: RuntimeOutcome.SECURITY_VIOLATION.value,
        FinalStatus.INTERNAL_ERROR: RuntimeOutcome.INTERNAL_ERROR.value,
    }
    return mapping[final_status]


def map_result_to_public_job_response(
    job_status: JobStatus,
    result: ExecutionResult | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {"status": job_status.value}
    if result is None:
        return response

    response.update(
        {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exitCode": result.exit_code,
            "durationMs": result.metrics.duration_ms,
            "runtimeOutcome": map_final_status_to_runtime_outcome(result.final_status),
            "signal": result.signal,
            "violationReason": result.violation.reason if result.violation else "",
        }
    )
    return response


def build_queued_response(job_id: str) -> dict[str, Any]:
    return {"jobId": job_id, "status": JobStatus.QUEUED.value}


def build_compile_queued_response(job_id: str, compiler_contract_version: str = "2.0.0") -> dict[str, Any]:
    response = build_queued_response(job_id)
    response["compilerContractVersion"] = compiler_contract_version
    return response
