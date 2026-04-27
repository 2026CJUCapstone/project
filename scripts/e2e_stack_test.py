#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_PORT = 18010
FRONTEND_PORT = 15180
BACKEND_BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_BASE_URL = f"http://127.0.0.1:{FRONTEND_PORT}"
ENV = {
    **os.environ,
    "PROJECT_ROOT": str(ROOT_DIR),
    "WEBCOMPILER_BACKEND_PORT_MAPPING": f"127.0.0.1:{BACKEND_PORT}:8000",
    "WEBCOMPILER_FRONTEND_PORT_MAPPING": f"127.0.0.1:{FRONTEND_PORT}:80",
}


def run_command(*args: str) -> None:
    subprocess.run(args, cwd=ROOT_DIR, env=ENV, check=True)


def wait_for_json(url: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)

    raise RuntimeError(f"Timed out waiting for {url}: {last_error}") from last_error


def post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    with urlopen(url, timeout=10) as response:
        return response.read().decode("utf-8")


def main() -> int:
    bpp_code = """import emitln from std.io;

func main() -> u64 {
    emitln("42");
    return 0;
}
"""

    invalid_bpp_code = """func main( -> u64 {
    return 0;
}
"""

    try:
        run_command("bash", "scripts/docker_up.sh")

        backend_health = wait_for_json(f"{BACKEND_BASE_URL}/health")
        frontend_health = wait_for_json(f"{FRONTEND_BASE_URL}/health")

        if backend_health.get("status") != "ok" or frontend_health.get("status") != "ok":
            raise RuntimeError("Health check failed")

        index_html = fetch_text(f"{FRONTEND_BASE_URL}/")
        if '<div id="root"></div>' not in index_html:
            raise RuntimeError("Frontend index page did not load correctly")

        compile_result = post_json(
            f"{FRONTEND_BASE_URL}/api/v1/compiler/compile",
            {
                "code": bpp_code,
                "language": "bpp",
                "options": {"optimize": False, "target": "all"},
            },
        )
        if compile_result.get("success") is not True:
            raise RuntimeError(f"Compile endpoint failed: {compile_result}")

        invalid_compile_result = post_json(
            f"{FRONTEND_BASE_URL}/api/v1/compiler/compile",
            {
                "code": invalid_bpp_code,
                "language": "bpp",
                "options": {"optimize": False, "target": "all"},
            },
        )
        if invalid_compile_result.get("success") is not False or not invalid_compile_result.get("errors"):
            raise RuntimeError(f"Compile diagnostics endpoint failed: {invalid_compile_result}")

        run_result = post_json(
            f"{FRONTEND_BASE_URL}/api/v1/compiler/run",
            {
                "language": "bpp",
                "code": bpp_code,
            },
        )
        if run_result.get("exit_code") != 0:
            raise RuntimeError(f"Run endpoint failed: {run_result}")
        if run_result.get("stdout", "").strip() != "42":
            raise RuntimeError(f"Unexpected run output: {run_result}")

        leaderboard_user = f"ci_leader_{int(time.time())}"
        leaderboard_challenge = f"ci_problem_{int(time.time())}"
        first_score = post_json(
            f"{FRONTEND_BASE_URL}/api/v1/problems/leaderboard/score",
            {
                "username": leaderboard_user,
                "points": 20,
                "challengeId": leaderboard_challenge,
            },
        )
        if first_score.get("awardedPoints") != 20 or first_score.get("alreadySolved") is not False:
            raise RuntimeError(f"Initial leaderboard score failed: {first_score}")

        duplicate_score = post_json(
            f"{FRONTEND_BASE_URL}/api/v1/problems/leaderboard/score",
            {
                "username": leaderboard_user,
                "points": 20,
                "challengeId": leaderboard_challenge,
            },
        )
        if duplicate_score.get("awardedPoints") != 0 or duplicate_score.get("alreadySolved") is not True:
            raise RuntimeError(f"Duplicate leaderboard score was not blocked: {duplicate_score}")
        if duplicate_score.get("totalScore") != 20:
            raise RuntimeError(f"Duplicate leaderboard score changed total: {duplicate_score}")

        leaderboard = wait_for_json(f"{FRONTEND_BASE_URL}/api/v1/problems/leaderboard?limit=10")
        leaderboard_row = next((row for row in leaderboard if row.get("username") == leaderboard_user), None)
        if not leaderboard_row or leaderboard_row.get("totalScore") != 20:
            raise RuntimeError(f"Leaderboard row missing or invalid: {leaderboard}")

        print(json.dumps({
            "backend_health": backend_health,
            "frontend_health": frontend_health,
            "compile_success": compile_result.get("success"),
            "invalid_compile_errors": len(invalid_compile_result.get("errors", [])),
            "run_stdout": run_result.get("stdout", "").strip(),
            "leaderboard_awarded_points": first_score.get("awardedPoints"),
            "leaderboard_duplicate_awarded_points": duplicate_score.get("awardedPoints"),
        }, ensure_ascii=True, indent=2))
        return 0
    finally:
        try:
            run_command("bash", "scripts/docker_down.sh")
        except (subprocess.CalledProcessError, URLError):
            pass


if __name__ == "__main__":
    sys.exit(main())
