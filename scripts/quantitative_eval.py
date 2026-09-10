#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
import gzip
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT_DIR / "docs" / "report-assets" / "quantitative-evaluation.json"
BACKEND_PORT = int(os.getenv("QUANT_BACKEND_PORT", "18010"))
FRONTEND_PORT = int(os.getenv("QUANT_FRONTEND_PORT", "15180"))
BACKEND_BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_BASE_URL = f"http://127.0.0.1:{FRONTEND_PORT}"


BPP_CODE = """import emitln from std.io;

func main() -> u64 {
    emitln("42");
    return 0;
}
"""

INVALID_BPP_CODE = """func main( -> u64 {
    return 0;
}
"""

PYTHON_CODE = """print("queue ok")
"""


def monotonic_ms() -> float:
    return time.perf_counter() * 1000


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * pct)))
    return ordered[index]


def summarize_ms(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "meanMs": 0.0, "p50Ms": 0.0, "p95Ms": 0.0, "minMs": 0.0, "maxMs": 0.0}
    return {
        "count": len(values),
        "meanMs": round(mean(values), 2),
        "p50Ms": round(median(values), 2),
        "p95Ms": round(percentile(values, 0.95), 2),
        "minMs": round(min(values), 2),
        "maxMs": round(max(values), 2),
    }


def tail(text: str, limit: int = 2500) -> str:
    return text[-limit:] if len(text) > limit else text


def run_command(name: str, args: list[str], cwd: Path = ROOT_DIR, env: dict[str, str] | None = None, timeout: int = 600) -> dict:
    command_env = {**os.environ, **(env or {})}
    start = monotonic_ms()
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    duration_ms = monotonic_ms() - start
    return {
        "name": name,
        "command": " ".join(args),
        "exitCode": proc.returncode,
        "passed": proc.returncode == 0,
        "durationMs": round(duration_ms, 2),
        "stdoutTail": tail(proc.stdout),
        "stderrTail": tail(proc.stderr),
    }


def wait_for_json(url: str, timeout_seconds: float = 90.0) -> dict:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return get_json(url, timeout_seconds=5.0)["payload"]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}") from last_error


def get_json(url: str, timeout_seconds: float = 20.0) -> dict:
    start = monotonic_ms()
    with urlopen(url, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    duration_ms = monotonic_ms() - start
    return {"durationMs": round(duration_ms, 2), "payload": json.loads(raw)}


def get_text(url: str, timeout_seconds: float = 20.0) -> dict:
    start = monotonic_ms()
    with urlopen(url, timeout=timeout_seconds) as response:
        payload = response.read().decode("utf-8")
    duration_ms = monotonic_ms() - start
    return {"durationMs": round(duration_ms, 2), "payload": payload}


def post_json(url: str, payload: dict, timeout_seconds: float = 60.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    start = monotonic_ms()
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    duration_ms = monotonic_ms() - start
    return {"durationMs": round(duration_ms, 2), "payload": json.loads(raw)}


def parse_backend_pytest(result: dict) -> dict:
    text = f"{result['stdoutTail']}\n{result['stderrTail']}"
    passed = int(re.search(r"(\d+) passed", text).group(1)) if re.search(r"(\d+) passed", text) else 0
    warnings = int(re.search(r"(\d+) warnings?", text).group(1)) if re.search(r"(\d+) warnings?", text) else 0
    return {"passedTests": passed, "failedTests": 0 if result["passed"] else None, "warnings": warnings}


def parse_vitest(result: dict) -> dict:
    text = f"{result['stdoutTail']}\n{result['stderrTail']}"
    tests = int(re.search(r"Tests\s+(\d+) passed", text).group(1)) if re.search(r"Tests\s+(\d+) passed", text) else 0
    files = int(re.search(r"Test Files\s+(\d+) passed", text).group(1)) if re.search(r"Test Files\s+(\d+) passed", text) else 0
    return {"passedTests": tests, "passedFiles": files}


def parse_playwright(result: dict) -> dict:
    text = f"{result['stdoutTail']}\n{result['stderrTail']}"
    match = re.search(r"(\d+) passed", text)
    return {"passedTests": int(match.group(1)) if match else 0}


def parse_build_assets(result: dict) -> dict:
    text = f"{result['stdoutTail']}\n{result['stderrTail']}"
    assets: dict[str, float] = {}
    for label, pattern in {
        "jsKb": r"dist/assets/index-[^\s]+\.js\s+([\d.]+) kB",
        "jsGzipKb": r"dist/assets/index-[^\s]+\.js\s+[\d.]+ kB │ gzip:\s+([\d.]+) kB",
        "cssKb": r"dist/assets/index-[^\s]+\.css\s+([\d.]+) kB",
        "cssGzipKb": r"dist/assets/index-[^\s]+\.css\s+[\d.]+ kB │ gzip:\s+([\d.]+) kB",
    }.items():
        match = re.search(pattern, text)
        if match:
            assets[label] = float(match.group(1))
    return assets


def collect_build_asset_files() -> dict:
    assets_dir = ROOT_DIR / "frontend" / "dist" / "assets"
    if not assets_dir.exists():
        return {}

    result: dict[str, float] = {}
    js_files = sorted(assets_dir.glob("index-*.js"))
    css_files = sorted(assets_dir.glob("index-*.css"))
    if js_files:
        js_payload = js_files[0].read_bytes()
        result["jsKb"] = round(len(js_payload) / 1024, 2)
        result["jsGzipKb"] = round(len(gzip.compress(js_payload)) / 1024, 2)
    if css_files:
        css_payload = css_files[0].read_bytes()
        result["cssKb"] = round(len(css_payload) / 1024, 2)
        result["cssGzipKb"] = round(len(gzip.compress(css_payload)) / 1024, 2)
    return result


def measure_repeated_get(name: str, url: str, count: int) -> dict:
    durations: list[float] = []
    failures = 0
    for _ in range(count):
        try:
            result = get_json(url)
            durations.append(result["durationMs"])
        except Exception:  # noqa: BLE001
            failures += 1
    return {"name": name, "attempts": count, "successes": len(durations), "failures": failures, **summarize_ms(durations)}


def measure_compile(count: int) -> dict:
    durations: list[float] = []
    backend_execution_times: list[float] = []
    successes = 0
    for _ in range(count):
        result = post_json(
            f"{FRONTEND_BASE_URL}/api/v1/compiler/compile",
            {"code": BPP_CODE, "language": "bpp", "options": {"optimize": False, "target": "all"}},
            timeout_seconds=90,
        )
        durations.append(result["durationMs"])
        payload = result["payload"]
        backend_execution_times.append(float(payload.get("execution_time", 0)))
        if payload.get("success") is True:
            successes += 1
    return {
        "attempts": count,
        "successes": successes,
        "clientLatency": summarize_ms(durations),
        "backendExecutionTime": summarize_ms(backend_execution_times),
    }


def measure_invalid_compile(count: int) -> dict:
    durations: list[float] = []
    successes = 0
    diagnostic_counts: list[int] = []
    for _ in range(count):
        result = post_json(
            f"{FRONTEND_BASE_URL}/api/v1/compiler/compile",
            {"code": INVALID_BPP_CODE, "language": "bpp", "options": {"optimize": False, "target": "all"}},
            timeout_seconds=90,
        )
        durations.append(result["durationMs"])
        payload = result["payload"]
        errors = payload.get("errors") or []
        diagnostic_counts.append(len(errors))
        if payload.get("success") is False and errors:
            successes += 1
    return {
        "attempts": count,
        "diagnosticSuccesses": successes,
        "clientLatency": summarize_ms(durations),
        "diagnosticCountMean": round(mean(diagnostic_counts), 2) if diagnostic_counts else 0,
    }


def measure_run(count: int) -> dict:
    durations: list[float] = []
    backend_execution_times: list[float] = []
    successes = 0
    for _ in range(count):
        result = post_json(
            f"{FRONTEND_BASE_URL}/api/v1/compiler/run",
            {"code": BPP_CODE, "language": "bpp"},
            timeout_seconds=90,
        )
        durations.append(result["durationMs"])
        payload = result["payload"]
        backend_execution_times.append(float(payload.get("execution_time", 0)))
        if payload.get("exit_code") == 0 and str(payload.get("stdout", "")).strip() == "42":
            successes += 1
    return {
        "attempts": count,
        "successes": successes,
        "clientLatency": summarize_ms(durations),
        "backendExecutionTime": summarize_ms(backend_execution_times),
    }


def measure_concurrent_queue(count: int, workers: int) -> dict:
    def one_request() -> dict:
        return post_json(
            f"{FRONTEND_BASE_URL}/api/v1/compiler/run",
            {"code": PYTHON_CODE, "language": "python"},
            timeout_seconds=90,
        )

    start = monotonic_ms()
    durations: list[float] = []
    successes = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(one_request) for _ in range(count)]
        for future in as_completed(futures):
            result = future.result()
            durations.append(result["durationMs"])
            payload = result["payload"]
            if payload.get("exit_code") == 0 and "queue ok" in str(payload.get("stdout", "")):
                successes += 1
    wall_ms = monotonic_ms() - start

    snapshot = get_json(f"{FRONTEND_BASE_URL}/api/v1/compiler/queue?limit=200")["payload"]
    queue_jobs = snapshot.get("jobs", [])
    recent_python_jobs = [
        job for job in queue_jobs
        if job.get("language") == "python" and job.get("kind") == "run" and job.get("status") == "completed"
    ][:count]
    wait_values = [float(job.get("waitMs") or 0) for job in recent_python_jobs]
    run_values = [float(job.get("runMs") or 0) for job in recent_python_jobs]

    return {
        "attempts": count,
        "workers": workers,
        "successes": successes,
        "wallMs": round(wall_ms, 2),
        "throughputJobsPerSecond": round(count / (wall_ms / 1000), 2) if wall_ms else 0,
        "clientLatency": summarize_ms(durations),
        "queueWait": summarize_ms(wait_values),
        "queueRun": summarize_ms(run_values),
    }


def run_stack_measurements() -> dict:
    env = {
        "PROJECT_ROOT": str(ROOT_DIR),
        "COMPOSE_PROJECT_NAME": "webcompiler-quant",
        "WEBCOMPILER_BACKEND_PORT_MAPPING": f"127.0.0.1:{BACKEND_PORT}:8000",
        "WEBCOMPILER_FRONTEND_PORT_MAPPING": f"127.0.0.1:{FRONTEND_PORT}:8080",
        "WEBCOMPILER_CORS_ORIGINS": f"http://127.0.0.1:{FRONTEND_PORT}",
        "WEBCOMPILER_SHARED_POSTGRES_NETWORK": "webcompiler-quant-shared",
    }
    stack: dict = {}
    try:
        stack["dockerUp"] = run_command("docker_up_webcompiler", ["bash", "scripts/docker_up_webcompiler.sh"], env=env, timeout=1800)
        if not stack["dockerUp"]["passed"]:
            return stack

        backend_health = wait_for_json(f"{BACKEND_BASE_URL}/health")
        frontend_health = wait_for_json(f"{FRONTEND_BASE_URL}/health")
        stack["healthPayloads"] = {"backend": backend_health, "frontend": frontend_health}

        stack["playwright"] = run_command(
            "playwright_e2e",
            ["npm", "run", "e2e:playwright"],
            cwd=ROOT_DIR / "frontend",
            env={"PLAYWRIGHT_BASE_URL": FRONTEND_BASE_URL},
            timeout=360,
        )
        stack["playwrightSummary"] = parse_playwright(stack["playwright"])

        index_result = get_text(f"{FRONTEND_BASE_URL}/")
        stack["frontendIndex"] = {
            "latencyMs": index_result["durationMs"],
            "containsRoot": '<div id="root"></div>' in index_result["payload"],
        }
        stack["api"] = {
            "backendHealth": measure_repeated_get("backend_health", f"{BACKEND_BASE_URL}/health", 20),
            "frontendHealth": measure_repeated_get("frontend_health", f"{FRONTEND_BASE_URL}/health", 20),
            "leaderboard": measure_repeated_get("leaderboard", f"{FRONTEND_BASE_URL}/api/v1/problems/leaderboard?limit=50", 20),
            "compileBpp": measure_compile(5),
            "invalidCompileDiagnostics": measure_invalid_compile(3),
            "runBpp": measure_run(5),
            "concurrentPythonRunQueue": measure_concurrent_queue(8, 8),
        }
        stack["queueSnapshot"] = get_json(f"{FRONTEND_BASE_URL}/api/v1/compiler/queue?limit=20")["payload"]
    finally:
        stack["dockerDown"] = run_command("docker_down_webcompiler", ["bash", "scripts/docker_down_webcompiler.sh"], env=env, timeout=300)
    return stack


def system_info() -> dict:
    mem_total_kb = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                    break
    except OSError:
        pass
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpuCount": os.cpu_count(),
        "memTotalMb": round(mem_total_kb / 1024) if mem_total_kb else None,
    }


def main() -> int:
    results: dict = {
        "system": system_info(),
        "commands": {},
    }

    command_plan = [
        ("backend_pytest", [str(ROOT_DIR / ".venv" / "bin" / "python"), "-m", "pytest", "backend/tests", "-q"], ROOT_DIR, 600),
        ("frontend_typecheck", ["npm", "run", "typecheck"], ROOT_DIR / "frontend", 300),
        ("frontend_vitest", ["npm", "run", "test:run"], ROOT_DIR / "frontend", 300),
        ("frontend_build", ["npm", "run", "build"], ROOT_DIR / "frontend", 360),
        ("compose_config", ["bash", "-lc", 'PROJECT_ROOT="$PWD" docker compose -f docker-compose.yml config >/tmp/webcompiler-compose.yml'], ROOT_DIR, 120),
        ("deploy_compose_config", ["bash", "-lc", 'PROJECT_ROOT="$PWD" docker compose -f docker-compose.yml -f docker-compose.deploy.yml config >/tmp/webcompiler-compose-deploy.yml'], ROOT_DIR, 120),
        ("deploy_script_syntax", ["bash", "-n", "scripts/deploy_server.sh"], ROOT_DIR, 60),
        ("report_check", ["python3", "/home/vulpo/.codex/skills/paper-writing/scripts/paper_check.py", "docs/보고서.md"], ROOT_DIR, 120),
    ]

    for name, args, cwd, timeout_seconds in command_plan:
        result = run_command(name, args, cwd=cwd, timeout=timeout_seconds)
        results["commands"][name] = result

    results["summaries"] = {
        "backend_pytest": parse_backend_pytest(results["commands"]["backend_pytest"]),
        "frontend_vitest": parse_vitest(results["commands"]["frontend_vitest"]),
        "frontend_build_assets": {
            **parse_build_assets(results["commands"]["frontend_build"]),
            **collect_build_asset_files(),
        },
    }

    results["stack"] = run_stack_measurements()

    command_passed = all(command["passed"] for command in results["commands"].values())
    stack = results["stack"]
    stack_passed = (
        stack.get("dockerUp", {}).get("passed") is True
        and stack.get("playwright", {}).get("passed") is True
        and stack.get("dockerDown", {}).get("passed") is True
    )
    results["overall"] = {
        "passed": command_passed and stack_passed,
        "commandSuites": len(results["commands"]),
        "passedCommandSuites": sum(1 for command in results["commands"].values() if command["passed"]),
    }

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "artifact": str(ARTIFACT_PATH.relative_to(ROOT_DIR)),
        "overall": results["overall"],
        "backendPytest": results["summaries"]["backend_pytest"],
        "frontendVitest": results["summaries"]["frontend_vitest"],
        "buildAssets": results["summaries"]["frontend_build_assets"],
        "stackPassed": stack_passed,
        "api": stack.get("api", {}),
        "playwright": stack.get("playwrightSummary", {}),
    }, ensure_ascii=False, indent=2))
    return 0 if results["overall"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
