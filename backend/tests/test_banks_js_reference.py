"""Cross-check the authored Node.js J reference against the checked Python oracle."""

from __future__ import annotations

import random

import pytest

from tests.test_freshman_cpp_sources import _run, _statement_examples
from tests.test_freshman_js_sources import SOURCE_DIRECTORY, _find_node
from tools.freshman_contest.banks import generate, solve


RUN_TIMEOUT_SECONDS = 2
LARGE_ANSWER_MINIMUM = 2**31


def test_banks_node_matches_checked_python_reference() -> None:
    """Use an existing local Node runtime only; do not install or benchmark it."""

    node = _find_node()
    if node is None:
        pytest.skip("No local Node.js executable is available at the configured path or on PATH.")

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

    # BigInt accepts signed decimal input; floor division must not truncate a
    # negative prefix toward zero.
    for text in ("3\n-7 3 7\n", "4\n-15 5 8 6\n", "3\n+2 -1 +2\n"):
        cases.append((text, solve(text)))

    assert len(cases) == 90
    assert any(int(text.split()[0]) == 9999 for text, _ in cases)
    assert max(int(expected) for _, expected in cases) > LARGE_ANSWER_MINIMUM

    source = SOURCE_DIRECTORY / "J.js"
    for text, expected in cases:
        result = _run([node, str(source)], input_text=text, timeout=RUN_TIMEOUT_SECONDS)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").rstrip("\n")
        assert actual == expected, f"J produced {actual!r} for input {text!r}; expected {expected!r}"
