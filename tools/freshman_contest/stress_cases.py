"""Deterministic, lazy A--I maximum and adversarial input cases.

The module constructs a case only when its iterator advances.  It deliberately
does not write files or invoke any compiler or judge runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import chain, cycle, islice, repeat
from typing import Final, Iterator

from .a_i import SUPPORTED_LETTERS


@dataclass(frozen=True)
class StressCase:
    """One named immutable statement input with its exact expected output."""

    name: str
    input_text: str
    expected_output: str


MAX_C_VALUES: Final = 1_000_000
MAX_D_CASES: Final = 1_000
MAX_E_LENGTH: Final = 1_000_000
MAX_F_VALUES: Final = 100_000
MAX_G_VALUES: Final = 1_000
MAX_H_DIMENSION: Final = 100
MAX_I_DIMENSION: Final = 1_000


def _require_letter(letter: str) -> str:
    if letter not in SUPPORTED_LETTERS:
        raise ValueError(f"unsupported freshman-contest letter: {letter!r}")
    return letter


def _c_maximum_case() -> StressCase:
    values = chain(("-1000000", "1000000"), repeat("-7", MAX_C_VALUES - 2))
    return StressCase(
        "c-maximum-extrema-negative-repetitions",
        f"{MAX_C_VALUES}\n" + " ".join(values) + "\n",
        "-1000000 1000000",
    )


def _d_maximum_case() -> StressCase:
    phrase = "AbCdEfGhIjKlMnOpQrSt"
    expanded = "".join(character * 8 for character in phrase)
    row = f"8 {phrase}\n"
    return StressCase(
        "d-maximum-case-count-repeat-and-length",
        f"{MAX_D_CASES}\n" + row * MAX_D_CASES,
        ((expanded + "\n") * MAX_D_CASES)[:-1],
    )


def _e_tie_case() -> StressCase:
    return StressCase(
        "e-maximum-case-insensitive-tie",
        "aAbB" * (MAX_E_LENGTH // 4) + "\n",
        "?",
    )


def _e_winner_case() -> StressCase:
    return StressCase(
        "e-maximum-case-insensitive-winner",
        "z" * 500_001 + "A" * 499_999 + "\n",
        "Z",
    )


def _f_maximum_case() -> StressCase:
    registrations = " ".join(
        chain(
            ("-2147483648", "2147483647", "0", "0"),
            (str(value) for value in range(1, MAX_F_VALUES - 3)),
        )
    )
    query_pattern = ("-2147483648", "2147483647", "0", "50000", "-1")
    queries = " ".join(islice(cycle(query_pattern), MAX_F_VALUES))
    answer_pattern = ("1", "1", "1", "1", "0")
    expected = "\n".join(islice(cycle(answer_pattern), MAX_F_VALUES))
    return StressCase(
        "f-maximum-registrations-and-queries-extrema-duplicates-absence",
        f"{MAX_F_VALUES}\n{registrations}\n{MAX_F_VALUES}\n{queries}\n",
        expected,
    )


def _g_all_largest_case() -> StressCase:
    return StressCase(
        "g-maximum-count-all-largest-durations",
        f"{MAX_G_VALUES}\n" + " ".join(repeat("1000", MAX_G_VALUES)) + "\n",
        "500500000",
    )


def _g_reverse_case() -> StressCase:
    total = MAX_G_VALUES * (MAX_G_VALUES + 1) * (MAX_G_VALUES + 2) // 6
    return StressCase(
        "g-maximum-count-reverse-durations",
        f"{MAX_G_VALUES}\n" + " ".join(str(value) for value in range(MAX_G_VALUES, 0, -1)) + "\n",
        str(total),
    )


def _h_open_case() -> StressCase:
    row = "1" * MAX_H_DIMENSION
    return StressCase(
        "h-maximum-open-grid",
        f"{MAX_H_DIMENSION} {MAX_H_DIMENSION}\n" + (row + "\n") * MAX_H_DIMENSION,
        "199",
    )


def _h_snake_case() -> StressCase:
    rows: list[str] = []
    full = "1" * MAX_H_DIMENSION
    for row_index in range(MAX_H_DIMENSION):
        if row_index % 2 == 0 or row_index == MAX_H_DIMENSION - 1:
            rows.append(full)
        elif ((row_index - 1) // 2) % 2 == 0:
            rows.append("0" * (MAX_H_DIMENSION - 1) + "1")
        else:
            rows.append("1" + "0" * (MAX_H_DIMENSION - 1))
    return StressCase(
        "h-maximum-serpentine-detour",
        f"{MAX_H_DIMENSION} {MAX_H_DIMENSION}\n" + "\n".join(rows) + "\n",
        "4951",
    )


def _i_maximum_single_frontier_case() -> StressCase:
    first_row = "1" + " 0" * (MAX_I_DIMENSION - 1)
    empty_row = "0" + " 0" * (MAX_I_DIMENSION - 1)
    return StressCase(
        "i-maximum-single-source-frontier",
        f"{MAX_I_DIMENSION} {MAX_I_DIMENSION}\n{first_row}\n" + (empty_row + "\n") * (MAX_I_DIMENSION - 1),
        "1998",
    )


def iter_cases(letter: str) -> Iterator[StressCase]:
    """Yield deterministic A--I stress descriptors without eager corpus storage."""

    letter = _require_letter(letter)
    if letter == "A":
        yield StressCase("a-minimum-groups", "+1 +1\n", "2")
        yield StressCase("a-maximum-groups", "+9 +9\n", "18")
    elif letter == "B":
        yield StressCase("b-minimum-triple", "+1 +1 +1\n", "11000")
        yield StressCase("b-maximum-triple", "+6 +6 +6\n", "16000")
        yield StressCase("b-pair-and-largest-distinct", "+1 +1 +6\n", "1100")
    elif letter == "C":
        yield StressCase("c-single-minimum", "1\n-1000000\n", "-1000000 -1000000")
        yield _c_maximum_case()
    elif letter == "D":
        yield StressCase("d-minimum-repeat-and-length", "1\n1 Z\n", "Z")
        yield _d_maximum_case()
    elif letter == "E":
        yield StressCase("e-single-lowercase-letter", "z\n", "Z")
        yield _e_tie_case()
        yield _e_winner_case()
    elif letter == "F":
        yield StressCase(
            "f-small-extrema-duplicate-membership",
            "4\n-2147483648 0 0 2147483647\n5\n-2147483648 -1 0 2147483647 0\n",
            "1\n0\n1\n1\n1",
        )
        yield _f_maximum_case()
    elif letter == "G":
        yield StressCase("g-single-largest-duration", "1\n1000\n", "1000")
        yield _g_all_largest_case()
        yield _g_reverse_case()
    elif letter == "H":
        yield StressCase("h-small-open-grid", "2 2\n11\n11\n", "3")
        yield _h_open_case()
        yield _h_snake_case()
    else:
        yield StressCase("i-small-multi-source", "3 3\n1 0 1\n0 0 0\n1 0 1\n", "2")
        yield StressCase("i-small-unreachable", "3 2\n1 -1 0\n0 -1 0\n", "-1")
        yield _i_maximum_single_frontier_case()


__all__ = ["StressCase", "iter_cases"]
