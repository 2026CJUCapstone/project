"""Compile and cross-check the authored C++17 A--I reference solutions locally."""

from __future__ import annotations

from pathlib import Path
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

from tools.freshman_contest.a_i import SUPPORTED_LETTERS, generate, solve


STATEMENTS = PROJECT_ROOT / "docs" / "freshman-contest-statements-a-i-2026-09-26.md"
SOURCE_DIRECTORY = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "cpp"
EXPECTED_SOURCE_NAMES = {f"{letter}.cpp" for letter in SUPPORTED_LETTERS}
MAX_OUTPUT_BYTES: Final = 16 * 1024
COMPILE_TIMEOUT_SECONDS: Final = 20
RUN_TIMEOUT_SECONDS: Final = 2
STATEMENT_SAMPLE_COUNT: Final = 22


def _find_cpp_compiler() -> str | None:
    for candidate in ("g++", "clang++"):
        compiler = shutil.which(candidate)
        if compiler:
            return compiler
    return None


def _statement_examples(letter: str) -> list[tuple[str, str]]:
    document = STATEMENTS.read_text(encoding="utf-8")
    section = re.search(rf"(?ms)^## {letter}\. .+?(?=^## [A-J]\. |^---\s*$)", document)
    assert section is not None, f"missing {letter} statement section"
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


def test_authored_cpp17_references_match_examples_and_seeded_oracle_cases(tmp_path: Path) -> None:
    """Use only a compiler explicitly available on PATH; never install one for tests."""

    source_names = {path.name for path in SOURCE_DIRECTORY.glob("*.cpp")}
    assert source_names == EXPECTED_SOURCE_NAMES | {'J.cpp'}

    compiler = _find_cpp_compiler()
    if compiler is None:
        pytest.skip("No local g++ or clang++ compiler is available on PATH.")

    executables: dict[str, Path] = {}
    for letter in SUPPORTED_LETTERS:
        source = SOURCE_DIRECTORY / f"{letter}.cpp"
        executable = tmp_path / f"freshman_{letter}"
        compilation = _run(
            [compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-pedantic", str(source), "-o", str(executable)],
            input_text=None,
            timeout=COMPILE_TIMEOUT_SECONDS,
        )
        assert compilation.returncode == 0, compilation.stderr.decode("utf-8", errors="replace")
        executables[letter] = executable

    cases: list[tuple[str, str, str]] = []
    sample_count = 0
    generated_count = 0
    for letter in SUPPORTED_LETTERS:
        examples = _statement_examples(letter)
        sample_count += len(examples)
        cases.extend((letter, text, expected) for text, expected in examples)
        for seed in (71, 1847):
            generated = generate(letter, seed=seed)
            generated_count += len(generated)
            cases.extend((letter, text, solve(letter, text)) for text in generated)

    assert sample_count == STATEMENT_SAMPLE_COUNT
    assert generated_count > 0
    for letter, text, expected in cases:
        result = _run([str(executables[letter])], input_text=text, timeout=RUN_TIMEOUT_SECONDS)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").rstrip("\n")
        assert actual == expected, f"{letter} produced {actual!r} for input {text!r}; expected {expected!r}"
