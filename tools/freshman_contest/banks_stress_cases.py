"""Deterministic, lazy boundary inputs for freshman-contest problem J (Banks).

The expected answers below are closed forms from
``docs/banks-reference-proof-2026-09-26.md``.  This module deliberately does
not call ``banks.minimum_moves``: it is a descriptor corpus, not another
implementation of the reference algorithm.
"""

from __future__ import annotations

from itertools import chain, repeat
from typing import Final, Iterator

from .stress_cases import StressCase


MAX_BANKS: Final = 9_999
BALANCE_MAGNITUDE: Final = 31_999
LONG_BLOCK_LENGTH: Final = (MAX_BANKS - 1) // 2

_TWO_BANK_POSITIVE: Final = 5
_TWO_BANK_NEGATIVE: Final = -3


def _ceil_div(dividend: int, divisor: int) -> int:
    return (dividend + divisor - 1) // divisor


def _long_block_answer() -> int:
    """Return the periodic-inversion closed form for the largest block case.

    Its prefixes, divided by ``BALANCE_MAGNITUDE``, are
    ``0..m-1, m..1, 0``.  Their unordered absolute-difference sum is
    ``m * (m + 1) * (2m + 1) / 3``; exactly ``m ** 2`` original-order
    pairs are strictly increasing and must be subtracted.
    """

    m = LONG_BLOCK_LENGTH
    distance_sum = m * (m + 1) * (2 * m + 1) // 3
    return BALANCE_MAGNITUDE * distance_sum - m**2


def _maximum_all_positive_case() -> StressCase:
    return StressCase(
        "j-maximum-all-positive-balances",
        f"{MAX_BANKS}\n" + " ".join(repeat(str(BALANCE_MAGNITUDE), MAX_BANKS)) + "\n",
        "0",
    )


def _maximum_nonnegative_unit_total_case() -> StressCase:
    values = chain(repeat("0", MAX_BANKS - 1), ("1",))
    return StressCase(
        "j-maximum-nonnegative-unit-total",
        f"{MAX_BANKS}\n" + " ".join(values) + "\n",
        "0",
    )


def _maximum_total_one_long_blocks_case() -> StressCase:
    values = chain(
        repeat(str(BALANCE_MAGNITUDE), LONG_BLOCK_LENGTH),
        repeat(str(-BALANCE_MAGNITUDE), LONG_BLOCK_LENGTH),
        ("1",),
    )
    return StressCase(
        "j-maximum-unit-total-long-positive-negative-blocks-int64",
        f"{MAX_BANKS}\n" + " ".join(values) + "\n",
        str(_long_block_answer()),
    )


def iter_cases() -> Iterator[StressCase]:
    """Yield J boundary descriptors only when each case is requested."""

    # A sole positive balance and an all-nonnegative sequence are already done.
    yield StressCase("j-single-bank-positive-total", "1\n1\n", "0")
    # Prefixes 0, 5 and total 2 give ceil(5 / 2) - 1 periodic inversions.
    yield StressCase(
        "j-two-bank-duplicate-circular-neighbor",
        f"2\n{_TWO_BANK_POSITIVE} {_TWO_BANK_NEGATIVE}\n",
        str(_ceil_div(_TWO_BANK_POSITIVE, _TWO_BANK_POSITIVE + _TWO_BANK_NEGATIVE) - 1),
    )
    yield StressCase("j-equal-prefixes-nonnegative", "3\n0 1 0\n", "0")
    # Prefixes 0, -5, -1 with total two have periodic pair contributions
    # 3, 1, and 2, then the sole strict increase (-5, -1) is removed.
    yield StressCase("j-negative-prefix-floor-remainder", "3\n-5 4 3\n", "5")
    # Prefixes 0, -p, 0 with total one have 2p distance and one strict
    # increasing-prefix correction.
    yield StressCase(
        "j-signed-minimum-balance-unit-total",
        f"3\n{-BALANCE_MAGNITUDE} {BALANCE_MAGNITUDE} 1\n",
        str(2 * BALANCE_MAGNITUDE - 1),
    )
    yield _maximum_all_positive_case()
    yield _maximum_nonnegative_unit_total_case()
    yield _maximum_total_one_long_blocks_case()


__all__ = ["BALANCE_MAGNITUDE", "LONG_BLOCK_LENGTH", "MAX_BANKS", "iter_cases"]
