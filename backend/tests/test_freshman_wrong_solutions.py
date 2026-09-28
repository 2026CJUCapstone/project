"""Offline kill-matrix checks for deliberately wrong freshman A--I solvers.

The matrix proves only that its named finite mutants disagree with the trusted
reference on listed valid inputs.  It does not establish complete judge coverage,
resource limits, or general data quality.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
from pathlib import Path
import sys
from typing import Iterator

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.freshman_contest.a_i import SUPPORTED_LETTERS, generate, solve, validate
from tools.freshman_contest.wrong_solutions import MUTANTS, Mutant, iter_mutants, solve_mutant


@dataclass(frozen=True)
class KillCase:
    category: str
    text: str


def _snake_maze(columns: int) -> str:
    """Build a valid H maze whose only route must travel left after going right."""

    rows = 5
    grid = (
        "1" * columns,
        "0" * (columns - 1) + "1",
        "1" * columns,
        "1" + "0" * (columns - 1),
        "1" * columns,
    )
    return f"{rows} {columns}\n" + "\n".join(grid) + "\n"


HANDCRAFTED_KILLS: dict[tuple[str, str], KillCase] = {
    ("A", "subtract_groups"): KillCase("arithmetic", "4 9\n"),
    ("A", "multiply_groups"): KillCase("arithmetic", "2 3\n"),
    ("B", "pair_before_triple"): KillCase("branch_order", "4 4 4\n"),
    ("B", "middle_card_when_distinct"): KillCase("wrong_statistic", "1 4 6\n"),
    ("C", "zero_initialized_extrema"): KillCase("initialization", "3\n2 4 8\n"),
    ("C", "assume_input_extrema_order"): KillCase("ordering_assumption", "3\n3 -2 9\n"),
    ("D", "repeat_whole_phrase"): KillCase("repeat_scope", "1\n2 Ab\n"),
    ("D", "ignore_repeat_count"): KillCase("ignored_input", "1\n3 A\n"),
    ("E", "case_sensitive_counts"): KillCase("normalization", "aA\n"),
    ("E", "return_first_tied_letter"): KillCase("tie_handling", "AaBb\n"),
    ("F", "remove_after_query"): KillCase("state_mutation", "1\n7\n2\n7 7\n"),
    ("F", "ignore_nonpositive_numbers"): KillCase("domain_assumption", "3\n-2 0 5\n3\n-2 0 5\n"),
    ("G", "keep_input_order"): KillCase("missing_optimization", "3\n3 1 2\n"),
    ("G", "sum_processing_times_only"): KillCase("objective_misread", "3\n3 1 2\n"),
    ("H", "count_moves_not_cells"): KillCase("off_by_one", "2 2\n11\n11\n"),
    ("H", "only_moves_right_or_down"): KillCase("incomplete_search", _snake_maze(7)),
    ("I", "single_initial_source"): KillCase("missing_sources", "3 2\n1 0 1\n0 0 0\n"),
    ("I", "allow_same_day_chain"): KillCase("synchronization", "2 2\n1 0\n0 0\n"),
}


def _i_case(cells: tuple[int, ...]) -> str:
    return "2 2\n" + "\n".join(" ".join(map(str, cells[row * 2:(row + 1) * 2])) for row in range(2)) + "\n"


def _deterministic_cases(letter: str) -> Iterator[str]:
    """Small, finite generated corpus, plus the package's seeded boundary cases."""

    yield from generate(letter, seed=71)
    yield from generate(letter, seed=1847)

    if letter == "A":
        yield from (f"{first} {second}\n" for first, second in product(range(1, 10), repeat=2))
    elif letter == "B":
        yield from (f"{first} {second} {third}\n" for first, second, third in product(range(1, 7), repeat=3))
    elif letter == "C":
        for values in permutations((-4, 1, 7)):
            yield f"3\n{' '.join(map(str, values))}\n"
    elif letter == "D":
        for repeats in range(1, 4):
            for phrase in ("A", "Ab", "a1B"):
                yield f"1\n{repeats} {phrase}\n"
    elif letter == "E":
        yield from ("aA\n", "AaBb\n", "ZzZy\n")
    elif letter == "F":
        yield from (
            "2\n5 5\n2\n5 5\n",
            "3\n-1 0 1\n3\n-1 0 1\n",
        )
    elif letter == "G":
        for values in permutations((1, 2, 3)):
            yield f"3\n{' '.join(map(str, values))}\n"
    elif letter == "H":
        yield from (_snake_maze(columns) for columns in range(2, 7))
    else:  # I
        for cells in product((-1, 0, 1), repeat=4):
            if any(value != -1 for value in cells):
                yield _i_case(cells)


MUTANT_KEYS = tuple((mutant.letter, mutant.identifier) for mutant in iter_mutants())


def _mutant(letter: str, identifier: str) -> Mutant:
    return next(mutant for mutant in MUTANTS[letter] if mutant.identifier == identifier)


def test_catalogue_has_two_named_functional_mutants_per_problem() -> None:
    assert tuple(MUTANTS) == SUPPORTED_LETTERS
    assert len(MUTANT_KEYS) == len(set(MUTANT_KEYS))
    for letter in SUPPORTED_LETTERS:
        assert len(MUTANTS[letter]) >= 2
        assert all(mutant.letter == letter and callable(mutant.solve) for mutant in MUTANTS[letter])


@pytest.mark.parametrize(
    ("letter", "identifier"),
    MUTANT_KEYS,
    ids=[f"{letter}-{identifier}" for letter, identifier in MUTANT_KEYS],
)
def test_handcrafted_kill_matrix_catches_each_named_mutant(letter: str, identifier: str) -> None:
    mutant = _mutant(letter, identifier)
    case = HANDCRAFTED_KILLS[(letter, identifier)]
    assert case.category == mutant.category
    assert validate(letter, case.text) is None
    expected = solve(letter, case.text)
    actual = solve_mutant(letter, identifier, case.text)
    assert actual != expected, (
        f"{letter}/{identifier} ({case.category}) survived its handcrafted valid kill case "
        f"{case.text!r}: expected {expected!r}, received {actual!r}"
    )


def test_handcrafted_kill_matrix_covers_only_known_catalogue_entries() -> None:
    assert set(HANDCRAFTED_KILLS) == set(MUTANT_KEYS)


@pytest.mark.parametrize("letter", SUPPORTED_LETTERS)
def test_deterministic_generated_corpus_kills_every_mutant_for_its_problem(letter: str) -> None:
    cases = tuple(_deterministic_cases(letter))
    assert cases
    for text in cases:
        assert validate(letter, text) is None

    for mutant in MUTANTS[letter]:
        killer = next(
            (
                text
                for text in cases
                if solve_mutant(letter, mutant.identifier, text) != solve(letter, text)
            ),
            None,
        )
        assert killer is not None, f"generated corpus did not kill {letter}/{mutant.identifier} ({mutant.category})"


def test_mutant_dispatch_rejects_unknown_letter_or_identifier() -> None:
    with pytest.raises(ValueError):
        solve_mutant("J", "anything", "1\n")
    with pytest.raises(ValueError):
        solve_mutant("A", "unknown", "1 1\n")
