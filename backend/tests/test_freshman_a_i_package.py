"""Offline contract tests for the draft freshman-contest A--I package."""

from __future__ import annotations

from itertools import permutations
from pathlib import Path
import re
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.freshman_contest import METADATA, SUPPORTED_LETTERS, generate, metadata, solve, validate


STATEMENTS = PROJECT_ROOT / "docs" / "freshman-contest-statements-a-i-2026-09-26.md"
EXAMPLE_COUNTS = dict(zip(SUPPORTED_LETTERS, (2, 3, 2, 2, 3, 2, 2, 2, 4)))


def _statement_examples(letter: str) -> list[tuple[str, str]]:
    document = STATEMENTS.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^## {letter}\. .+?(?=^## [A-J]\. |^---\s*$)",
        document,
    )
    assert match is not None, f"missing {letter} statement section"
    blocks = re.findall(r"~~~text\n(.*?)\n~~~", match.group(0), flags=re.S)
    assert len(blocks) == EXAMPLE_COUNTS[letter] * 2
    return [(blocks[index], blocks[index + 1].strip()) for index in range(0, len(blocks), 2)]


def test_every_statement_example_validates_and_solves() -> None:
    total = 0
    for letter in SUPPORTED_LETTERS:
        examples = _statement_examples(letter)
        assert len(examples) == EXAMPLE_COUNTS[letter]
        for text, expected in examples:
            assert validate(letter, text) is None
            assert solve(letter, text) == expected
            total += 1
    assert total == 22


@pytest.mark.parametrize(
    ("letter", "text"),
    [
        ("A", "1 1 2\n"),
        ("B", "1 2 3 4\n"),
        ("C", "1\n0 1\n"),
        ("D", "1\n1 Go extra\n"),
        ("E", "Campus Code\n"),
        ("F", "1\n0 1\n1\n0\n"),
        ("G", "1\n1 2\n"),
        ("H", "2 2\n11\n11\n0\n"),
        ("I", "2 2\n1 0\n0 1 0\n"),
    ],
)
def test_validator_rejects_trailing_tokens_or_lines(letter: str, text: str) -> None:
    with pytest.raises(ValueError):
        validate(letter, text)


@pytest.mark.parametrize(
    ("letter", "text"),
    [
        ("A", "0 9\n"),
        ("B", "1 2 7\n"),
        ("C", "1\n1000001\n"),
        ("D", "1\n9 A\n"),
        ("E", "A1\n"),
        ("F", "1\n2147483648\n1\n0\n"),
        ("G", "1\n1001\n"),
        ("H", "2 2\n11\n10\n"),
        ("I", "2 2\n1 0\n0 2\n"),
    ],
)
def test_validator_rejects_statement_range_or_guarantee_violations(letter: str, text: str) -> None:
    with pytest.raises(ValueError):
        validate(letter, text)


def test_validator_rejects_bad_dispatch_and_non_string_text() -> None:
    with pytest.raises(ValueError):
        validate("J", "1\n1\n")
    with pytest.raises(ValueError):
        validate("a", "1 1\n")
    with pytest.raises(ValueError):
        validate("A", 11)  # type: ignore[arg-type]


def test_generators_are_seeded_reproducible_compact_and_valid() -> None:
    for letter in SUPPORTED_LETTERS:
        first = generate(letter, seed=71)
        assert first == generate(letter, seed=71)
        assert 1 <= len(first) <= 200
        for text in first:
            assert validate(letter, text) is None
            assert isinstance(solve(letter, text), str)


def test_metadata_remains_explicitly_pending_and_defensive() -> None:
    for letter in SUPPORTED_LETTERS:
        record = metadata(letter)
        assert record["source"]["status"] == "PENDING"
        assert record["external_review"] == "PENDING"
        assert record["tier_verification"] == "PENDING"
        assert record["license_verification"] == "PENDING"
        assert record["wrong_strategies"]
        record["title"] = "mutated by caller"
        assert METADATA[letter]["title"] != "mutated by caller"


def _brute_queue_total(values: list[int]) -> int:
    return min(sum(sum(order[: index + 1]) for index in range(len(order))) for order in permutations(values))


@pytest.mark.parametrize("values", ([1], [4, 1, 3, 2], [6, 6, 2, 5, 1], [3, 1, 4, 1, 5, 9]))
def test_g_matches_independent_permutation_oracle(values: list[int]) -> None:
    text = f"{len(values)}\n{' '.join(map(str, values))}\n"
    assert solve("G", text) == str(_brute_queue_total(values))


def _brute_h_shortest(grid: list[str]) -> int:
    rows, columns = len(grid), len(grid[0])
    goal = (rows - 1, columns - 1)
    best: int | None = None

    def visit(row: int, column: int, seen: set[tuple[int, int]]) -> None:
        nonlocal best
        distance = len(seen)
        if best is not None and distance >= best:
            return
        if (row, column) == goal:
            best = distance
            return
        for next_row, next_column in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
            if (
                0 <= next_row < rows
                and 0 <= next_column < columns
                and grid[next_row][next_column] == "1"
                and (next_row, next_column) not in seen
            ):
                visit(next_row, next_column, seen | {(next_row, next_column)})

    visit(0, 0, {(0, 0)})
    assert best is not None
    return best


@pytest.mark.parametrize(
    "grid",
    [
        ["11", "11"],
        ["111", "101", "111"],
        ["1101", "0101", "1111"],
    ],
)
def test_h_matches_independent_simple_path_oracle(grid: list[str]) -> None:
    text = f"{len(grid)} {len(grid[0])}\n" + "\n".join(grid) + "\n"
    assert solve("H", text) == str(_brute_h_shortest(grid))


def _synchronous_days(columns: int, rows: int, values: list[int]) -> int:
    grid = [values[row * columns:(row + 1) * columns] for row in range(rows)]
    days = 0
    while any(0 in row for row in grid):
        changes: list[tuple[int, int]] = []
        for row in range(rows):
            for column in range(columns):
                if grid[row][column] != 0:
                    continue
                if any(
                    0 <= next_row < rows
                    and 0 <= next_column < columns
                    and grid[next_row][next_column] == 1
                    for next_row, next_column in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1))
                ):
                    changes.append((row, column))
        if not changes:
            return -1
        for row, column in changes:
            grid[row][column] = 1
        days += 1
    return days


@pytest.mark.parametrize(
    ("columns", "rows", "values"),
    [
        (2, 2, [1, -1, 1, 1]),
        (2, 2, [0, 0, 0, -1]),
        (3, 3, [1, 0, 0, 0, -1, 0, 0, 0, 1]),
        (4, 2, [1, 0, -1, 0, 0, 0, -1, 0]),
    ],
)
def test_i_matches_independent_synchronous_oracle(columns: int, rows: int, values: list[int]) -> None:
    text = f"{columns} {rows}\n" + "\n".join(
        " ".join(map(str, values[row * columns:(row + 1) * columns])) for row in range(rows)
    ) + "\n"
    assert solve("I", text) == str(_synchronous_days(columns, rows, values))
