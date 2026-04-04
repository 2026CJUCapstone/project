#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from internal.core import run_request
from internal.model import ExecutionRequest, to_dict


def load_request(path: Path) -> ExecutionRequest:
    data = json.loads(path.read_text())
    limits_data = data["limits"]
    from internal.model import ExecutionLimits, TraceMode

    return ExecutionRequest(
        request_id=data["requestId"],
        sample_name=data["sampleName"],
        executable_path=data["executablePath"],
        args=data.get("args", []),
        stdin_data=data.get("stdinData", ""),
        working_directory=data.get("workingDirectory", ""),
        limits=ExecutionLimits(
            timeout_ms=limits_data["timeoutMs"],
            cpu_quota_cores=limits_data["cpuQuotaCores"],
            cpu_time_ms=limits_data["cpuTimeMs"],
            memory_limit_mb=limits_data["memoryLimitMB"],
            process_limit=limits_data["processLimit"],
            max_threads=limits_data["maxThreads"],
            stdout_buffer_bytes=limits_data["stdoutBufferBytes"],
            stderr_buffer_bytes=limits_data["stderrBufferBytes"],
            max_open_files=limits_data["maxOpenFiles"],
            network_mode=limits_data["networkMode"],
            filesystem_mode=limits_data["filesystemMode"],
            syscall_profile=limits_data["syscallProfile"],
        ),
        trace_mode=TraceMode(data.get("traceMode", "none")),
        metadata=data.get("metadata", {}),
    )
def main() -> int:
    if len(sys.argv) != 2:
        print("usage: poc_runner.py <request.json>", file=sys.stderr)
        return 2

    request_path = Path(sys.argv[1]).resolve()
    request = load_request(request_path)
    result = run_request(ROOT_DIR, request)
    print(json.dumps(to_dict(result), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
