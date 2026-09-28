"""Contract checks for the supplementary freshman-contest boundary corpus."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import FrozenInstanceError
from itertools import product
from pathlib import Path
import sys
from typing import Final

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.freshman_contest.a_i import SUPPORTED_LETTERS, validate
from tools.freshman_contest.coverage_cases import StressCase, iter_coverage_cases
from tools.freshman_contest.stress_cases import iter_cases as iter_stress_cases


EXPECTED_CASE_COUNTS: Final = {
    "A": 1,
    "B": 213,
    "C": 3,
    "D": 1,
    "E": 1,
    "F": 2,
    "G": 2,
    "H": 2,
    "I": 4,
}
MAX_CASE_BYTES: Final = 16 * 1024 * 1024
MAX_EXPECTED_OUTPUT_BYTES: Final = 512 * 1024


def _independent_h_shortest(grid: list[str]) -> str:
    row_count = len(grid)
    column_count = len(grid[0])
    distances = [[0] * column_count for _ in range(row_count)]
    queue = deque([(0, 0)])
    distances[0][0] = 1
    while queue:
        row, column = queue.popleft()
        if (row, column) == (row_count - 1, column_count - 1):
            return str(distances[row][column])
        for next_row, next_column in (
            (row - 1, column),
            (row + 1, column),
            (row, column - 1),
            (row, column + 1),
        ):
            if (
                0 <= next_row < row_count
                and 0 <= next_column < column_count
                and grid[next_row][next_column] == "1"
                and distances[next_row][next_column] == 0
            ):
                distances[next_row][next_column] = distances[row][column] + 1
                queue.append((next_row, next_column))
    raise AssertionError("H coverage input unexpectedly has no route")


def _independent_i_days(rows: list[list[int]]) -> str:
    row_count = len(rows)
    column_count = len(rows[0])
    queue = deque(
        (row, column)
        for row in range(row_count)
        for column in range(column_count)
        if rows[row][column] == 1
    )
    pending = sum(cell == 0 for row in rows for cell in row)
    if pending == 0:
        return "0"
    if not queue:
        return "-1"
    days = 0
    while queue and pending:
        for _ in range(len(queue)):
            row, column = queue.popleft()
            for next_row, next_column in (
                (row - 1, column),
                (row + 1, column),
                (row, column - 1),
                (row, column + 1),
            ):
                if 0 <= next_row < row_count and 0 <= next_column < column_count:
                    if rows[next_row][next_column] == 0:
                        rows[next_row][next_column] = 1
                        pending -= 1
                        queue.append((next_row, next_column))
        days += 1
    return str(days if pending == 0 else -1)


def _independent_expected(letter: str, input_text: str) -> str:
    """Compute only this bounded corpus with no call to the reference solver."""

    lines = input_text.splitlines()
    if letter == "A":
        first, second = (int(value) for value in lines[0].split())
        return str(first + second)
    if letter == "B":
        first, second, third = (int(value) for value in lines[0].split())
        if first == second == third:
            return str(10_000 + first * 1_000)
        if first == second or first == third:
            return str(1_000 + first * 100)
        if second == third:
            return str(1_000 + second * 100)
        return str(max(first, second, third) * 100)
    if letter == "C":
        values = [int(value) for value in lines[1].split()]
        return f"{min(values)} {max(values)}"
    if letter == "D":
        repeat_count, phrase = lines[1].split()
        return "".join(character * int(repeat_count) for character in phrase)
    if letter == "E":
        counts = Counter(lines[0].upper())
        maximum = max(counts.values())
        winners = [letter for letter, count in counts.items() if count == maximum]
        return winners[0] if len(winners) == 1 else "?"
    if letter == "F":
        registrations = {int(value) for value in lines[1].split()}
        return "\n".join("1" if int(value) in registrations else "0" for value in lines[3].split())
    if letter == "G":
        elapsed = 0
        total = 0
        for duration in sorted(int(value) for value in lines[1].split()):
            elapsed += duration
            total += elapsed
        return str(total)
    if letter == "H":
        return _independent_h_shortest(lines[1:])
    return _independent_i_days([[int(value) for value in line.split()] for line in lines[1:]])


def test_coverage_cases_are_lazy_deterministic_and_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.freshman_contest.coverage_cases as coverage_cases

    with monkeypatch.context() as scoped_monkeypatch:
        scoped_monkeypatch.setattr(
            coverage_cases,
            "_f_linear_lookup_discriminator_case",
            lambda: (_ for _ in ()).throw(AssertionError("eager F discriminator")),
        )
        first = next(coverage_cases.iter_coverage_cases("F"))
        assert first.name == "f-asymmetric-one-registration-many-queries"

    first = tuple(iter_coverage_cases("A"))
    assert first == tuple(iter_coverage_cases("A"))
    with pytest.raises(FrozenInstanceError):
        first[0].name = "replacement"  # type: ignore[misc]
    with pytest.raises(ValueError):
        next(iter_coverage_cases("J"))


def test_coverage_cases_have_expected_names_counts_bounds_and_valid_inputs() -> None:
    for letter in SUPPORTED_LETTERS:
        cases = tuple(iter_coverage_cases(letter))
        assert len(cases) == EXPECTED_CASE_COUNTS[letter]
        assert len({case.name for case in cases}) == len(cases)
        for case in cases:
            assert case.name.startswith(letter.lower() + "-")
            validate(letter, case.input_text)
            assert len(case.input_text.encode("utf-8")) <= MAX_CASE_BYTES
            assert len(case.expected_output.encode("utf-8")) <= MAX_EXPECTED_OUTPUT_BYTES
            assert len(case.input_text.encode("utf-8")) + len(case.expected_output.encode("utf-8")) <= MAX_CASE_BYTES

        combined_count = len(cases) + len(tuple(iter_stress_cases(letter)))
        # B is intentionally the bounded exhaustive 6**3 exception.
        assert combined_count <= 10 or letter == "B"

    assert sum(EXPECTED_CASE_COUNTS.values()) == 229


def test_b_coverage_completes_the_bounded_exhaustive_ordered_triple_space() -> None:
    legacy = {
        tuple(int(value) for value in case.input_text.split())
        for case in iter_stress_cases("B")
    }
    supplementary = {
        tuple(int(value) for value in case.input_text.split())
        for case in iter_coverage_cases("B")
    }
    all_legal_triples = set(product(range(1, 7), repeat=3))

    assert legacy.isdisjoint(supplementary)
    assert legacy | supplementary == all_legal_triples
    assert len(supplementary) == 213


def test_coverage_cases_match_closed_forms_or_independent_bounded_oracles() -> None:
    for letter in SUPPORTED_LETTERS:
        for case in iter_coverage_cases(letter):
            assert _independent_expected(letter, case.input_text) == case.expected_output


def test_required_boundary_categories_are_present() -> None:
    names = {
        letter: {case.name for case in iter_coverage_cases(letter)}
        for letter in SUPPORTED_LETTERS
    }
    assert names["A"] == {"a-distinct-boundary-operands"}
    assert names["C"] == {"c-all-negative-values", "c-all-positive-values", "c-all-equal-values"}
    assert names["D"] == {"d-digit-characters-repeat-individually"}
    assert names["E"] == {"e-26-way-case-insensitive-tie"}
    assert names["F"] == {
        "f-asymmetric-one-registration-many-queries",
        "f-linear-scan-discriminator-mostly-absent-queries",
    }
    assert names["G"] == {"g-single-minimum-duration", "g-maximum-count-all-minimum-durations"}
    assert names["H"] == {"h-rectangular-open-corridor", "h-rectangular-branched-cycle-shortest-path"}
    assert names["I"] == {
        "i-initially-complete",
        "i-no-initial-source",
        "i-rectangular-single-source-propagation",
        "i-maximum-many-sources-front-delete-discriminator",
    }
