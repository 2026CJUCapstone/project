from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from internal.model import ExecutionLimits


@dataclass(slots=True)
class PolicyTemplate:
    name: str = "default"
    version: str = "official-v1"
    source: str = "official-default"
    cpu_quota: int = 1
    memory_limit_mb: int = 256
    timeout_ms: int = 3000
    process_limit: int = 64
    network_mode: str = "no-network"
    max_threads: int = 8
    stdout_buffer_bytes: int = 65536
    stderr_buffer_bytes: int = 65536
    max_open_files: int = 32
    filesystem_mode: str = "isolated"
    syscall_profile: str = "minimal-runtime"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_execution_limits(self) -> ExecutionLimits:
        return ExecutionLimits(
            timeout_ms=self.timeout_ms,
            cpu_quota_cores=self.cpu_quota,
            cpu_time_ms=self.timeout_ms,
            memory_limit_mb=self.memory_limit_mb,
            process_limit=self.process_limit,
            max_threads=self.max_threads,
            stdout_buffer_bytes=self.stdout_buffer_bytes,
            stderr_buffer_bytes=self.stderr_buffer_bytes,
            max_open_files=self.max_open_files,
            network_mode=self.network_mode,
            filesystem_mode=self.filesystem_mode,
            syscall_profile=self.syscall_profile,
        )


def policy_template_from_admin_payload(policy: dict[str, Any]) -> PolicyTemplate:
    return PolicyTemplate(
        name=policy.get("name", "default"),
        version=policy.get("version", "official-v1"),
        source=policy.get("source", "admin-policy-api"),
        cpu_quota=policy.get("cpuQuota", 1),
        memory_limit_mb=policy.get("memoryLimitMB", 256),
        timeout_ms=policy.get("timeoutMs", 3000),
        process_limit=policy.get("processLimit", 64),
        network_mode=policy.get("networkMode", "no-network"),
        metadata=policy.get("metadata", {}),
    )


def default_policy_template() -> PolicyTemplate:
    return PolicyTemplate()
