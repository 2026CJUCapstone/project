"""Cross-check the offline Java 17 J reference against the proved Python oracle.

This is a function-correctness comparison only; it does not measure judge time or
memory limits.
"""

from __future__ import annotations

from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import threading
from typing import Final

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.freshman_contest.banks import generate, solve


STATEMENTS = PROJECT_ROOT / "docs" / "freshman-contest-statements-a-i-2026-09-26.md"
SOURCE = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "java" / "J" / "Main.java"
MAX_OUTPUT_BYTES: Final = 16 * 1024
COMPILE_TIMEOUT_SECONDS: Final = 20
RUN_TIMEOUT_SECONDS: Final = 2


def _find_java_tools() -> tuple[str, str] | None:
    java = shutil.which("java")
    javac = shutil.which("javac")
    if java is None or javac is None:
        return None
    return java, javac


def _statement_examples() -> list[tuple[str, str]]:
    document = STATEMENTS.read_text(encoding="utf-8")
    section = re.search(r"(?ms)^## J\. .+?(?=^---\s*$)", document)
    assert section is not None, "missing J statement section"
    blocks = re.findall(r"~~~text\n(.*?)\n~~~", section.group(0), flags=re.S)
    assert len(blocks) % 2 == 0
    return [(blocks[index], blocks[index + 1].strip()) for index in range(0, len(blocks), 2)]


def _drain_stream(
    stream: object,
    captured: bytearray,
    limit_exceeded: threading.Event,
    process: subprocess.Popen[bytes],
) -> None:
    """Drain a process stream while retaining at most the diagnostic output cap."""

    readable = stream
    while chunk := readable.read(4096):  # type: ignore[union-attr]
        available = MAX_OUTPUT_BYTES - len(captured)
        if available > 0:
            captured.extend(chunk[:available])
        if len(chunk) > available:
            limit_exceeded.set()
            try:
                process.kill()
            except ProcessLookupError:
                pass


def _run(command: list[str], *, input_text: str | None, timeout: int) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL if input_text is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    standard_output = bytearray()
    standard_error = bytearray()
    output_limit_exceeded = threading.Event()
    output_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stdout, standard_output, output_limit_exceeded, process),
    )
    error_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stderr, standard_error, output_limit_exceeded, process),
    )
    output_thread.start()
    error_thread.start()
    if input_text is not None:
        assert process.stdin is not None
        try:
            process.stdin.write(input_text.encode("utf-8"))
        except BrokenPipeError:
            pass
        finally:
            process.stdin.close()
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        pytest.fail(f"process exceeded its {timeout}-second time cap: {command!r}")
    finally:
        output_thread.join()
        error_thread.join()
    assert not output_limit_exceeded.is_set(), "reference process exceeded the output cap"
    return subprocess.CompletedProcess(command, return_code, bytes(standard_output), bytes(standard_error))


def test_banks_java17_matches_checked_python_reference(tmp_path: Path) -> None:
    """Use only Java tools already on PATH; no runtime or compiler installation occurs."""

    tools = _find_java_tools()
    if tools is None:
        pytest.skip("No local java and javac executables are available on PATH.")
    java, javac = tools
    classes = tmp_path / "classes"
    classes.mkdir()
    compilation = _run(
        [javac, "--release", "17", "-encoding", "UTF-8", "-d", str(classes), str(SOURCE)],
        input_text=None,
        timeout=COMPILE_TIMEOUT_SECONDS,
    )
    assert compilation.returncode == 0, compilation.stderr.decode("utf-8", errors="replace")

    cases = _statement_examples()
    for seed in (0, 73, 1926):
        cases.extend((text, solve(text)) for text in generate(seed))
    rng = random.Random(10350)
    for _ in range(50):
        count = rng.randrange(2, 35)
        values = [rng.randrange(-100, 101) for _ in range(count - 1)]
        values.append(1 - sum(values))
        text = f"{count}\n" + " ".join(map(str, values)) + "\n"
        cases.append((text, solve(text)))
    # Java must retain the oracle's floor, rather than truncating, division for negative prefixes.
    for text in ("3\n-7 3 7\n", "4\n-15 5 8 6\n"):
        cases.append((text, solve(text)))

    assert len(cases) == 89
    assert max(len(text.split()) - 1 for text, _ in cases) == 9_999
    assert max(int(expected) for _, expected in cases) > 2**31
    for text, expected in cases:
        result = _run([java, "-cp", str(classes), "Main"], input_text=text, timeout=RUN_TIMEOUT_SECONDS)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").strip()
        assert actual == expected
