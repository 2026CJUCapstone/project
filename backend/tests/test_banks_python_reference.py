"""Cross-check the standalone Python J reference against the proved local oracle.

This is a function-correctness comparison only; it does not measure judge time or
memory limits.
"""

from __future__ import annotations

import random

import pytest

from tests.test_freshman_cpp_sources import _run, _statement_examples
from tests.test_freshman_python_sources import SOURCE_DIRECTORY, _find_python
from tools.freshman_contest.banks import generate, solve


RUN_TIMEOUT_SECONDS = 2
LARGE_ANSWER_MINIMUM = 2**31


def test_banks_python_matches_checked_python_reference() -> None:
    """Run only the configured local Python runtime; do not install or benchmark it."""

    python = _find_python()
    if python is None:
        pytest.skip("Current test Python executable is unavailable; no runtime installation requested.")

    cases = _statement_examples("J")
    for seed in (0, 73, 1926):
        cases.extend((text, solve(text)) for text in generate(seed))

    rng = random.Random(10350)
    for _ in range(50):
        count = rng.randrange(2, 35)
        balances = [rng.randrange(-100, 101) for _ in range(count - 1)]
        balances.append(1 - sum(balances))
        text = f"{count}\n" + " ".join(map(str, balances)) + "\n"
        cases.append((text, solve(text)))

    # Python's divmod supplies mathematical floor division for negative prefixes.
    # The final signed case also confirms decimal tokens with a leading plus sign.
    for text in ("3\n-7 3 7\n", "4\n-15 5 8 6\n", "3\n+2 -1 +2\n"):
        cases.append((text, solve(text)))

    assert len(cases) == 90
    assert max(len(text.split()) - 1 for text, _ in cases) == 9_999
    assert max(int(expected) for _, expected in cases) > LARGE_ANSWER_MINIMUM
    source = SOURCE_DIRECTORY / "J.py"
    for text, expected in cases:
        result = _run([python, str(source)], input_text=text, timeout=RUN_TIMEOUT_SECONDS)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").rstrip("\n")
        assert actual == expected, f"J produced {actual!r} for input {text!r}; expected {expected!r}"
