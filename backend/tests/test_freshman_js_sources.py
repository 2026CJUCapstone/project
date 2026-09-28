"""Run the authored Node.js A--I references against local checked cases only."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from tests.test_freshman_cpp_sources import _run, _statement_examples
from tools.freshman_contest.a_i import SUPPORTED_LETTERS, generate, solve


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIRECTORY = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "javascript"
EXPECTED_SOURCE_NAMES = {f"{letter}.js" for letter in SUPPORTED_LETTERS} | {"J.js"}
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


def _find_node() -> str | None:
    """Prefer the configured Windows runtime, then use a Node executable on PATH."""

    configured = Path(r"C:\nvm4w\nodejs\node.exe")
    candidates = (str(configured), shutil.which("node"), shutil.which("nodejs"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def test_authored_node_references_match_examples_and_seeded_oracle_cases() -> None:
    """Do not install Node: run only the explicitly available local runtime."""

    assert {path.name for path in SOURCE_DIRECTORY.glob("*.js")} == EXPECTED_SOURCE_NAMES
    node = _find_node()
    if node is None:
        pytest.skip("No local Node.js executable is available at the configured path or on PATH.")

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
    cases.extend(
        (letter, text, solve(letter, text)) for letter, text in SIGNED_TOKEN_CASES.items()
    )
    for case_index, (letter, text, expected) in enumerate(cases, 1):
        try:
            result = _run(
                [node, str(SOURCE_DIRECTORY / f"{letter}.js")],
                input_text=text,
                timeout=RUN_TIMEOUT_SECONDS,
            )
        except pytest.fail.Exception as exc:
            pytest.fail(f"case {case_index}, problem {letter}, input bytes {len(text.encode('utf-8'))}, "
                f"prefix {text[:256]!r}: {exc}", pytrace=False)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").rstrip("\n")
        assert actual == expected, f"{letter} produced {actual!r} for input {text!r}; expected {expected!r}"
