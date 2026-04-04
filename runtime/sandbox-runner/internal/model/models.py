from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FinalStatus(str, Enum):
    SUCCESS = "Success"
    RUNTIME_ERROR = "RuntimeError"
    TIMEOUT = "Timeout"
    OOM = "OOM"
    SECURITY_VIOLATION = "SecurityViolation"
    INTERNAL_ERROR = "InternalError"


class TraceMode(str, Enum):
    NONE = "none"
    BASIC = "basic"
    VERBOSE = "verbose"


@dataclass(slots=True)
class ExecutionLimits:
    timeout_ms: int
    cpu_quota_cores: int
    cpu_time_ms: int
    memory_limit_mb: int
    process_limit: int
    max_threads: int
    stdout_buffer_bytes: int
    stderr_buffer_bytes: int
    max_open_files: int
    network_mode: str
    filesystem_mode: str
    syscall_profile: str


@dataclass(slots=True)
class ExecutionRequest:
    request_id: str
    sample_name: str
    executable_path: str
    args: list[str] = field(default_factory=list)
    stdin_data: str = ""
    working_directory: str = ""
    limits: ExecutionLimits | None = None
    trace_mode: TraceMode = TraceMode.NONE
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExecutionMetrics:
    duration_ms: int = 0
    cpu_time_ms: int = 0
    peak_memory_kb: int = 0
    stdout_bytes: int = 0
    stderr_bytes: int = 0


@dataclass(slots=True)
class ExecutionViolation:
    category: str
    reason: str
    message: str
    resource: str


@dataclass(slots=True)
class OutputMeta:
    bytes: int = 0
    truncated: bool = False
    encoding: str = "utf-8"


@dataclass(slots=True)
class ExecutionResult:
    request_id: str
    sample_name: str
    final_status: FinalStatus
    exit_code: int
    runtime_error_reason: str = ""
    signal: str = ""
    started_at: str = ""
    finished_at: str = ""
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    violation: ExecutionViolation | None = None
    profile_summary: dict[str, Any] | None = None
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    stdout_meta: OutputMeta = field(default_factory=OutputMeta)
    stderr_meta: OutputMeta = field(default_factory=OutputMeta)
    internal_reason_code: str = ""
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _normalize(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {_to_camel_case(key): _normalize(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_normalize(value) for value in obj]
    return obj


def _to_camel_case(value: str) -> str:
    aliases = {
        "memory_limit_mb": "memoryLimitMB",
        "peak_memory_kb": "peakMemoryKb",
    }
    if value in aliases:
        return aliases[value]
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def to_dict(value: Any) -> dict[str, Any]:
    return _normalize(asdict(value))
