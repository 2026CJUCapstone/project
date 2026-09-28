"""Supplementary deterministic boundary cases for freshman-contest A--I.

The maximum/adversarial corpus in :mod:`stress_cases` intentionally remains
small.  This module fills its behavioral gaps without performing I/O: every
descriptor is built only as ``iter_coverage_cases`` advances, expected results
come from local formulas or small independent graph traversals, and each case
is within the statement limits.
"""

from __future__ import annotations

from collections import deque
from itertools import product, repeat
from string import ascii_lowercase, ascii_uppercase
from typing import Final, Iterator, Sequence

from .a_i import SUPPORTED_LETTERS
from .stress_cases import StressCase


MAX_F_VALUES: Final = 100_000
_B_TRIPLES_ALREADY_IN_STRESS_CASES: Final = frozenset({(1, 1, 1), (6, 6, 6), (1, 1, 6)})


def _require_letter(letter: str) -> str:
    if not isinstance(letter, str) or letter not in SUPPORTED_LETTERS:
        raise ValueError(f"letter must be one of {', '.join(SUPPORTED_LETTERS)}")
    return letter


def _b_score(cards: tuple[int, int, int]) -> int:
    """Evaluate the three documented B scoring branches without a solver."""

    first, second, third = cards
    if first == second == third:
        return 10_000 + first * 1_000
    if first == second or first == third:
        return 1_000 + first * 100
    if second == third:
        return 1_000 + second * 100
    return max(cards) * 100


def _c_extrema_case(name: str, values: tuple[int, ...]) -> StressCase:
    return StressCase(
        name,
        f"{len(values)}\n" + " ".join(str(value) for value in values) + "\n",
        f"{min(values)} {max(values)}",
    )


def _d_expand(repeats: int, phrase: str) -> str:
    return "".join(character * repeats for character in phrase)


def _e_tie_word() -> str:
    """Make every ASCII letter appear twice, once in each case."""

    return ascii_lowercase + ascii_uppercase


def _f_asymmetric_case() -> StressCase:
    query_values = tuple(0 if index % 2 == 0 else 1 for index in range(MAX_F_VALUES))
    expected = "\n".join("1" if value == 0 else "0" for value in query_values)
    return StressCase(
        "f-asymmetric-one-registration-many-queries",
        "1\n0\n"
        f"{MAX_F_VALUES}\n"
        + " ".join(str(value) for value in query_values)
        + "\n",
        expected,
    )


def _f_linear_lookup_discriminator_case() -> StressCase:
    """Bounded 100,000-by-100,000 lookup workload with mostly absent queries."""

    registrations = tuple(2 * value for value in range(MAX_F_VALUES))
    queries = tuple(2 * value + 1 for value in range(MAX_F_VALUES - 1)) + (registrations[-1],)
    return StressCase(
        "f-linear-scan-discriminator-mostly-absent-queries",
        f"{MAX_F_VALUES}\n"
        + " ".join(str(value) for value in registrations)
        + f"\n{MAX_F_VALUES}\n"
        + " ".join(str(value) for value in queries)
        + "\n",
        "\n".join((*repeat("0", MAX_F_VALUES - 1), "1")),
    )


def _g_total_completion_time(durations: Sequence[int]) -> int:
    elapsed = 0
    total = 0
    for duration in sorted(durations):
        elapsed += duration
        total += elapsed
    return total


def _h_shortest_path_length(grid: tuple[str, ...]) -> int:
    """Small standalone BFS oracle for a validated H grid."""

    rows = len(grid)
    columns = len(grid[0])
    queue = deque([(0, 0, 1)])
    seen = {(0, 0)}
    while queue:
        row, column, distance = queue.popleft()
        if (row, column) == (rows - 1, columns - 1):
            return distance
        for next_row, next_column in (
            (row - 1, column),
            (row + 1, column),
            (row, column - 1),
            (row, column + 1),
        ):
            if (
                0 <= next_row < rows
                and 0 <= next_column < columns
                and grid[next_row][next_column] == "1"
                and (next_row, next_column) not in seen
            ):
                seen.add((next_row, next_column))
                queue.append((next_row, next_column, distance + 1))
    raise AssertionError("coverage H grid must have a route")


def _h_case(name: str, grid: tuple[str, ...]) -> StressCase:
    return StressCase(
        name,
        f"{len(grid)} {len(grid[0])}\n" + "\n".join(grid) + "\n",
        str(_h_shortest_path_length(grid)),
    )


def _i_propagation_days(rows: tuple[tuple[int, ...], ...]) -> int:
    """Small independent multi-source, day-layer BFS oracle for I."""

    row_count = len(rows)
    column_count = len(rows[0])
    cells = [list(row) for row in rows]
    queue = deque(
        (row, column)
        for row in range(row_count)
        for column in range(column_count)
        if cells[row][column] == 1
    )
    pending = sum(cell == 0 for row in cells for cell in row)
    if pending == 0:
        return 0
    if not queue:
        return -1

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
                    if cells[next_row][next_column] == 0:
                        cells[next_row][next_column] = 1
                        pending -= 1
                        queue.append((next_row, next_column))
        days += 1
    return days if pending == 0 else -1


def _i_case(name: str, rows: tuple[tuple[int, ...], ...]) -> StressCase:
    return StressCase(
        name,
        f"{len(rows[0])} {len(rows)}\n"
        + "\n".join(" ".join(str(cell) for cell in row) for row in rows)
        + "\n",
        str(_i_propagation_days(rows)),
    )


def _i_front_delete_discriminator_case() -> StressCase:
    """One million cells; nearly all are initial sources but the last is empty.

    A FIFO deque reaches the last cell in one day.  A correct list.pop(0)
    implementation must first remove almost the entire initial frontier and
    repeatedly shifts a very large list.  This is separate from the existing
    single-source case, whose queue never gets wide enough to expose that cost.
    """

    full_row = "1 " * 999 + "1"
    last_row = "1 " * 999 + "0"
    return StressCase(
        "i-maximum-many-sources-front-delete-discriminator",
        "1000 1000\n" + (full_row + "\n") * 999 + last_row + "\n",
        "1",
    )


def iter_coverage_cases(letter: str) -> Iterator[StressCase]:
    """Yield named supplementary A--I boundary cases one descriptor at a time.

    B is the sole deliberately larger family: after excluding the three B
    descriptors already in ``stress_cases``, it yields every remaining legal
    ordered triple.  Combined, the two modules exhaust all 6**3 B inputs.
    """

    letter = _require_letter(letter)
    if letter == "A":
        yield StressCase("a-distinct-boundary-operands", "+1 +9\n", "10")
    elif letter == "B":
        for cards in product(range(1, 7), repeat=3):
            if cards in _B_TRIPLES_ALREADY_IN_STRESS_CASES:
                continue
            yield StressCase(
                f"b-exhaustive-triple-{cards[0]}-{cards[1]}-{cards[2]}",
                f"{cards[0]} {cards[1]} {cards[2]}\n",
                str(_b_score(cards)),
            )
    elif letter == "C":
        yield _c_extrema_case("c-all-negative-values", (-999_999, -17, -1, -42))
        yield _c_extrema_case("c-all-positive-values", (1, 42, 999_999, 7))
        yield _c_extrema_case("c-all-equal-values", (-314, -314, -314, -314))
    elif letter == "D":
        phrase = "0123456789"
        yield StressCase(
            "d-digit-characters-repeat-individually",
            f"1\n2 {phrase}\n",
            _d_expand(2, phrase),
        )
    elif letter == "E":
        yield StressCase("e-26-way-case-insensitive-tie", _e_tie_word() + "\n", "?")
    elif letter == "F":
        yield _f_asymmetric_case()
        yield _f_linear_lookup_discriminator_case()
    elif letter == "G":
        yield StressCase("g-single-minimum-duration", "1\n1\n", "1")
        all_minimum = (1,) * 1_000
        yield StressCase(
            "g-maximum-count-all-minimum-durations",
            "1000\n" + " ".join(str(value) for value in all_minimum) + "\n",
            str(_g_total_completion_time(all_minimum)),
        )
    elif letter == "H":
        yield _h_case("h-rectangular-open-corridor", ("1111111", "0000001"))
        yield _h_case(
            "h-rectangular-branched-cycle-shortest-path",
            ("1111111", "1010001", "1010111", "1010101", "1111111"),
        )
    else:
        yield _i_case("i-initially-complete", ((1, 1, 1), (1, 1, 1)))
        yield _i_case("i-no-initial-source", ((0, -1, 0, 0), (0, 0, -1, 0)))
        yield _i_case(
            "i-rectangular-single-source-propagation",
            ((1, 0, 0, 0, 0), (0, 0, 0, 0, 0)),
        )
        yield _i_front_delete_discriminator_case()


__all__ = ["StressCase", "iter_coverage_cases"]
