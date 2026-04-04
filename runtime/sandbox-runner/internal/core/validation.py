from __future__ import annotations

from dataclasses import dataclass

from internal.model import ExecutionRequest


@dataclass(slots=True)
class ValidationFailure:
    reason_code: str
    message: str


def validate_execution_request(request: ExecutionRequest) -> ValidationFailure | None:
    if not request.request_id:
        return ValidationFailure("request_id_missing", "request_id is required")
    if not request.sample_name:
        return ValidationFailure("sample_name_missing", "sample_name is required")
    if not request.executable_path:
        return ValidationFailure("executable_path_missing", "executable_path is required")
    if request.limits is None:
        return ValidationFailure("limits_missing", "limits are required")
    if request.limits.timeout_ms <= 0:
        return ValidationFailure("invalid_timeout", "timeout must be positive")
    if request.limits.cpu_quota_cores <= 0:
        return ValidationFailure("invalid_cpu_quota", "cpu quota must be positive")
    if request.limits.memory_limit_mb <= 0:
        return ValidationFailure("invalid_memory_limit", "memory limit must be positive")
    if request.limits.process_limit <= 0:
        return ValidationFailure("invalid_process_limit", "process limit must be positive")
    return None
