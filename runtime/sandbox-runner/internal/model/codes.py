from __future__ import annotations

from enum import Enum


class RuntimeOutcome(str, Enum):
    SUCCESS = "success"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"
    OOM = "oom"
    SECURITY_VIOLATION = "security_violation"
    INTERNAL_ERROR = "internal_error"


class RuntimeErrorReason(str, Enum):
    NONZERO_EXIT = "nonzero_exit"
    SIGNAL_SEGV = "signal_segv"
    SIGNAL_ABRT = "signal_abrt"
    SIGNAL_TERM = "signal_term"
    SIGNAL_KILL = "signal_kill"
    UNKNOWN_SIGNAL = "unknown_signal"


class ViolationReason(str, Enum):
    WALL_TIME_LIMIT_EXCEEDED = "wall_time_limit_exceeded"
    CPU_TIME_LIMIT_EXCEEDED = "cpu_time_limit_exceeded"
    MEMORY_LIMIT_EXCEEDED = "memory_limit_exceeded"
    PROCESS_LIMIT_EXCEEDED = "process_limit_exceeded"
    THREAD_LIMIT_EXCEEDED = "thread_limit_exceeded"
    FORBIDDEN_FILE_ACCESS = "forbidden_file_access"
    FORBIDDEN_NETWORK_ACCESS = "forbidden_network_access"
    FORBIDDEN_SYSCALL = "forbidden_syscall"
    READ_ONLY_ROOTFS_VIOLATION = "read_only_rootfs_violation"
    REQUEST_VALIDATION_FAILED = "request_validation_failed"
    EXECUTION_ENGINE_FAILED = "execution_engine_failed"
    POLICY_LOAD_FAILED = "policy_load_failed"
    RESULT_COLLECTION_FAILED = "result_collection_failed"
    UNEXPECTED_RUNNER_EXCEPTION = "unexpected_runner_exception"


class SignalCode(str, Enum):
    SIGKILL = "SIGKILL"
    SIGSEGV = "SIGSEGV"
    SIGABRT = "SIGABRT"
    SIGTERM = "SIGTERM"
    UNKNOWN_SIGNAL = "UNKNOWN_SIGNAL"
