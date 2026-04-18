#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from internal.adapter import (
    build_internal_execution_request,
    build_queued_response,
    normalize_run_request,
    validate_run_request,
)
from internal.core import run_request
from internal.model import to_dict


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: api_demo.py <public-run-request.json> <sample-name>", file=sys.stderr)
        return 2

    request_path = Path(sys.argv[1]).resolve()
    sample_name = sys.argv[2]
    public_request = json.loads(request_path.read_text())

    errors = validate_run_request(public_request)
    if errors:
        print(json.dumps({"errors": errors}, ensure_ascii=True, indent=2))
        return 1

    normalized = normalize_run_request(public_request)
    internal_request = build_internal_execution_request(
        request_id="demo-run-001",
        sample_name=sample_name,
        executable_path=str(ROOT_DIR / "build" / "samples" / sample_name),
        stdin_data=normalized["stdin"],
        working_directory=str(ROOT_DIR / "build" / "samples"),
        policy={"timeoutMs": normalized["timeoutMs"]},
        metadata={"executionMode": "api-demo", "engine": "local", "traceId": "demo-trace-001"},
    )
    queued = build_queued_response("demo-job-001")
    result = run_request(ROOT_DIR, internal_request)

    print(
        json.dumps(
            {
                "publicRequest": public_request,
                "normalizedRequest": normalized,
                "queuedResponse": queued,
                "internalExecutionRequest": to_dict(internal_request),
                "runtimeResult": to_dict(result),
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
