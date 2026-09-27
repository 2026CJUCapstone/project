"""Bounded, intentional wrong-answer mutants for freshman contest problem J.

The functions in this module are offline test fixtures.  They describe common
mistakes in implementations of the periodic-inversion solution in ``banks``;
they are neither contestant submissions nor runtime-limit probes.  Each mutant
has O(n log n) or better work on a valid input, so even the 9,999-bank generator
case remains finite and practical to exercise in a local test.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Callable, Final, Iterator

from . import banks


MutantSolver = Callable[[str], str]


@dataclass(frozen=True)
class Mutant:
    """One named, deliberately incorrect J implementation strategy."""

    identifier: str
    category: str
    description: str
    solve: MutantSolver


@dataclass(frozen=True)
class KillCase:
    """A valid, deterministic input that distinguishes one named mutant."""

    identifier: str
    phenomenon: str
    text: str
    oracle_output: str


def _prefixes(balances: list[int]) -> tuple[list[int], int]:
    prefixes: list[int] = []
    current = 0
    for balance in balances:
        prefixes.append(current)
        current += balance
    return prefixes, current


def _periodic_pair_sum(
    prefixes: list[int],
    total: int,
    quotient_remainder: Callable[[int, int], tuple[int, int]] = divmod,
) -> int:
    """Compute the unordered periodic-pair contribution used by the reference."""

    remainders = sorted({quotient_remainder(value, total)[1] for value in prefixes})
    counts = banks.Fenwick(len(remainders))
    quotient_sum = 0
    answer = 0
    for index, value in enumerate(sorted(prefixes)):
        quotient, remainder = quotient_remainder(value, total)
        rank = bisect_left(remainders, remainder)
        answer += index * quotient - quotient_sum + counts.before(rank)
        quotient_sum += quotient
        counts.add(rank)
    return answer


def _increasing_prefix_pairs(prefixes: list[int], *, include_equal: bool = False) -> int:
    """Count earlier prefixes smaller than this one, optionally including equals."""

    values = sorted(set(prefixes))
    counts = banks.Fenwick(len(values))
    answer = 0
    for value in prefixes:
        rank = bisect_left(values, value)
        answer += counts.before(rank + int(include_equal))
        counts.add(rank)
    return answer


def _truncating_divmod(value: int, modulus: int) -> tuple[int, int]:
    """The C/Java-style error: division of a negative prefix truncates to zero."""

    quotient = abs(value) // modulus
    if value < 0:
        quotient = -quotient
    return quotient, value - quotient * modulus


def j_single_neighbor_for_two_banks(text: str) -> str:
    """Treat the two circular neighbours as one bank when N is two."""

    balances = banks.parse(text)
    if len(balances) != 2:
        return banks.solve(text)
    # With a positive total, at most one of two balances is negative.  A direct
    # simulator that stores neighbours in a set would stop after this one step,
    # because it subtracts the negative amount only once instead of twice.
    return "1" if min(balances) < 0 else "0"


def j_truncating_negative_division(text: str) -> str:
    """Use truncation-to-zero rather than floor division for negative prefixes."""

    prefixes, total = _prefixes(banks.parse(text))
    answer = _periodic_pair_sum(prefixes, total, _truncating_divmod)
    answer -= _increasing_prefix_pairs(prefixes)
    return str(answer)


def j_missing_increasing_prefix_correction(text: str) -> str:
    """Keep the unordered periodic-pair sum but omit its order correction."""

    prefixes, total = _prefixes(banks.parse(text))
    return str(_periodic_pair_sum(prefixes, total))


def j_equal_prefixes_as_increasing(text: str) -> str:
    """Subtract equal-prefix pairs too, as if the correction were non-strict."""

    prefixes, total = _prefixes(banks.parse(text))
    answer = _periodic_pair_sum(prefixes, total)
    answer -= _increasing_prefix_pairs(prefixes, include_equal=True)
    return str(answer)


def j_one_period_inversions_only(text: str) -> str:
    """Count ordinary inversions in one prefix period and ignore periodic copies."""

    prefixes, _ = _prefixes(banks.parse(text))
    values = sorted(set(prefixes))
    counts = banks.Fenwick(len(values))
    answer = 0
    for index, value in enumerate(prefixes):
        rank = bisect_left(values, value)
        # Prior values greater than value are ordinary inversions.
        answer += index - counts.before(rank + 1)
        counts.add(rank)
    return str(answer)


def _signed_i32(value: int) -> int:
    value &= (1 << 32) - 1
    return value - (1 << 32) if value >= 1 << 31 else value


def j_signed_32_bit_accumulator(text: str) -> str:
    """Store the final answer in a signed 32-bit accumulator instead of int64."""

    return str(_signed_i32(int(banks.solve(text))))


MUTANTS: Final[tuple[Mutant, ...]] = (
    Mutant(
        "single_neighbor_for_two_banks",
        "circular_duplicate_neighbor",
        "For N=2, de-duplicates the left and right neighbour before subtracting.",
        j_single_neighbor_for_two_banks,
    ),
    Mutant(
        "truncating_negative_division",
        "negative_floor_division",
        "Uses truncation toward zero for a negative prefix quotient and remainder.",
        j_truncating_negative_division,
    ),
    Mutant(
        "missing_increasing_prefix_correction",
        "missing_inversion_correction",
        "Omits the strict original-order increasing-prefix correction.",
        j_missing_increasing_prefix_correction,
    ),
    Mutant(
        "equal_prefixes_as_increasing",
        "strictness_error",
        "Subtracts equal prefixes in a correction that must be strictly increasing.",
        j_equal_prefixes_as_increasing,
    ),
    Mutant(
        "one_period_inversions_only",
        "periodicity_omitted",
        "Counts inversions in one prefix period and omits all periodic copies.",
        j_one_period_inversions_only,
    ),
    Mutant(
        "signed_32_bit_accumulator",
        "integer_overflow",
        "Narrows the answer to a signed 32-bit integer.",
        j_signed_32_bit_accumulator,
    ),
)


COUNTEREXAMPLES: Final[dict[str, KillCase]] = {
    "single_neighbor_for_two_banks": KillCase(
        "single_neighbor_for_two_banks",
        "N=2 has the same neighbour on both sides, so it is charged twice.",
        "2\n5 -3\n",
        "2",
    ),
    "truncating_negative_division": KillCase(
        "truncating_negative_division",
        "A negative prefix needs Euclidean floor division, not truncation to zero.",
        "3\n-6 8 5\n",
        "2",
    ),
    "missing_increasing_prefix_correction": KillCase(
        "missing_increasing_prefix_correction",
        "Already nonnegative balances still have increasing prefix pairs to subtract.",
        "2\n1 1\n",
        "0",
    ),
    "equal_prefixes_as_increasing": KillCase(
        "equal_prefixes_as_increasing",
        "Equal prefix values must not enter the strict increasing-pair correction.",
        "3\n0 1 0\n",
        "0",
    ),
    "one_period_inversions_only": KillCase(
        "one_period_inversions_only",
        "The finite answer includes inversions with later periodic copies.",
        "4\n2 -1 -1 1\n",
        "5",
    ),
    "signed_32_bit_accumulator": KillCase(
        "signed_32_bit_accumulator",
        "The valid result exceeds signed 32-bit range and requires a 64-bit accumulator.",
        "101\n" + " ".join(["31999"] * 50 + ["-31999"] * 50 + ["1"]) + "\n",
        "2747111650",
    ),
}


def iter_mutants() -> Iterator[Mutant]:
    """Yield each bounded intentional J wrong-answer strategy."""

    yield from MUTANTS


def solve_mutant(identifier: str, text: str) -> str:
    """Validate a statement input and run one named offline wrong-answer mutant."""

    banks.validate(text)
    for mutant in MUTANTS:
        if mutant.identifier == identifier:
            return mutant.solve(text)
    raise ValueError(f"unknown J mutant: {identifier}")


__all__ = ["COUNTEREXAMPLES", "MUTANTS", "KillCase", "Mutant", "iter_mutants", "solve_mutant"]
