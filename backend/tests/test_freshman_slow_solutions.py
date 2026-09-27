"""Correctness-only checks for separately labelled slow F/I/J submissions.

These tests do not establish a time limit or run a sandboxed resource probe.
"""

from pathlib import Path
import random
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.freshman_contest.a_i import solve as solve_a_i, validate as validate_a_i
from tools.freshman_contest.banks import solve as solve_j
from tools.freshman_contest.coverage_cases import iter_coverage_cases
from tools.freshman_contest.slow_solutions.python.F import solve as slow_f
from tools.freshman_contest.slow_solutions.python.I import solve as slow_i
from tools.freshman_contest.slow_solutions.python.J import solve as slow_j


def test_f_linear_scan_is_correct_for_small_duplicate_and_absent_queries() -> None:
    rng = random.Random(617)
    for _ in range(70):
        registrations = [rng.randint(-6, 6) for _ in range(rng.randint(1, 14))]
        queries = [rng.randint(-8, 8) for _ in range(rng.randint(1, 16))]
        data = (f"{len(registrations)}\n" + " ".join(map(str, registrations))
                + f"\n{len(queries)}\n" + " ".join(map(str, queries)) + "\n")
        assert slow_f(data) == solve_a_i("F", data)


def test_i_front_delete_is_correct_on_small_random_grids() -> None:
    rng = random.Random(618)
    for _ in range(60):
        columns = rng.randint(2, 6)
        rows = rng.randint(2, 6)
        cells = [rng.choice((-1, 0, 0, 1)) for _ in range(columns * rows)]
        if all(value == -1 for value in cells):
            cells[0] = 0
        data = (f"{columns} {rows}\n" + "\n".join(
            " ".join(map(str, cells[row * columns:(row + 1) * columns]))
            for row in range(rows)
        ) + "\n")
        assert slow_i(data) == solve_a_i("I", data)


def test_j_pair_formula_is_correct_on_small_random_balances() -> None:
    rng = random.Random(619)
    for _ in range(80):
        balances = [rng.randint(-10, 10) for _ in range(rng.randint(1, 17))]
        if sum(balances) <= 0:
            balances[-1] += 1 - sum(balances)
        data = f"{len(balances)}\n" + " ".join(map(str, balances)) + "\n"
        assert slow_j(data) == solve_j(data)


def test_many_sources_i_discriminator_is_within_statement_and_has_independent_answer() -> None:
    case = next(case for case in iter_coverage_cases("I")
                if case.name == "i-maximum-many-sources-front-delete-discriminator")
    assert case.input_text.startswith("1000 1000\n")
    assert case.input_text.count("\n") == 1_001
    assert case.input_text.endswith("1 " * 999 + "0\n")
    assert case.expected_output == "1"
    validate_a_i("I", case.input_text)
    assert solve_a_i("I", case.input_text) == "1"


@pytest.mark.parametrize("letter,data,expected", [
    ("F", "3\n4 4 -1\n3\n-1 8 4\n", "1\n0\n1"),
    ("I", "2 2\n1 1\n1 0\n", "1"),
    ("J", "3\n-1 2 1\n", None),
])
def test_slow_sources_run_as_plain_stdin_submissions(letter: str, data: str, expected: str | None) -> None:
    source = ROOT / "tools" / "freshman_contest" / "slow_solutions" / "python" / f"{letter}.py"
    completed = subprocess.run([sys.executable, str(source)], input=data, text=True,
                               capture_output=True, timeout=5, check=True)
    assert completed.stdout == (expected if expected is not None else solve_j(data))
    assert completed.stderr == ""
