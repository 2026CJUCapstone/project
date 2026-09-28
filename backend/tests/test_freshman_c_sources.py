"""Compile and cross-check the authored C17 A--I reference solutions locally.

This is an offline function-correctness check, not a time or memory benchmark.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.test_freshman_cpp_sources import _run, _statement_examples
from tools.freshman_contest.a_i import SUPPORTED_LETTERS, generate, solve


SOURCE_DIRECTORY = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "c"
EXPECTED_SOURCE_NAMES = {f"{letter}.c" for letter in (*SUPPORTED_LETTERS, "J")}
COMPILE_TIMEOUT_SECONDS = 20
RUN_TIMEOUT_SECONDS = 2
STATEMENT_SAMPLE_COUNT = 22


def _find_c_compiler() -> str | None:
    for candidate in ("gcc", "C:/mingw64/bin/gcc.exe"):
        compiler = shutil.which(candidate)
        if compiler:
            return compiler
    return None


def test_authored_c17_references_match_examples_and_seeded_oracle_cases(tmp_path: Path) -> None:
    """Use only a C compiler already installed on PATH; never install one for tests."""

    source_names = {path.name for path in SOURCE_DIRECTORY.glob("*.c")}
    assert source_names == EXPECTED_SOURCE_NAMES

    compiler = _find_c_compiler()
    if compiler is None:
        pytest.skip("No local gcc compiler is available on PATH.")

    executables: dict[str, Path] = {}
    for letter in SUPPORTED_LETTERS:
        source = SOURCE_DIRECTORY / f"{letter}.c"
        executable = tmp_path / f"freshman_{letter}"
        compilation = _run(
            [compiler, "-std=c17", "-O2", "-Wall", "-Wextra", "-pedantic", str(source), "-o", str(executable)],
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
