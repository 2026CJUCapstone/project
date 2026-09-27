"""Run the authored standalone Python A--I references against checked local cases.

This is a function-correctness comparison only; it is not a Linux judge-runtime
benchmark.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.test_freshman_cpp_sources import _run, _statement_examples
from tools.freshman_contest.a_i import SUPPORTED_LETTERS, generate, solve


SOURCE_DIRECTORY = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "python"
EXPECTED_SOURCE_NAMES = {f"{letter}.py" for letter in (*SUPPORTED_LETTERS, "J")}
RUN_TIMEOUT_SECONDS = 2
STATEMENT_SAMPLE_COUNT = 22
SIGNED_TOKEN_CASES = {
    "A": "+1 +9\n",
    "B": "+5 +2 +5\n",
    "C": "3\n+4 -6 +2\n",
    "D": "1\n+2 A1\n",
    "F": "2\n+0 -2147483648\n3\n+0 +1 -2147483648\n",
    "G": "3\n+2 +1 +3\n",
    "H": "+2 +2\n11\n11\n",
    "I": "+2 +2\n+1 +0\n-1 +0\n",
}


def _find_python() -> str | None:
    """Run sources with pytest's current Python interpreter; never install one."""

    executable = Path(sys.executable)
    return str(executable) if executable.is_file() else None


def test_authored_python_references_match_examples_and_seeded_oracle_cases() -> None:
    """Every submitted source is standalone and receives complete stdin text."""

    assert {path.name for path in SOURCE_DIRECTORY.glob("*.py")} == EXPECTED_SOURCE_NAMES
    python = _find_python()
    if python is None:
        pytest.skip("Current test Python executable is unavailable; no runtime installation requested.")

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
    assert generated_count == 126
    cases.extend((letter, text, solve(letter, text)) for letter, text in SIGNED_TOKEN_CASES.items())
    for letter, text, expected in cases:
        result = _run(
            [python, str(SOURCE_DIRECTORY / f"{letter}.py")],
            input_text=text,
            timeout=RUN_TIMEOUT_SECONDS,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").rstrip("\n")
        assert actual == expected, f"{letter} produced {actual!r} for input {text!r}; expected {expected!r}"
