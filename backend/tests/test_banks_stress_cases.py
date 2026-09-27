"""Contract tests for the lazy, closed-form Banks stress corpus."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Final


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DIRECTORY = Path(__file__).resolve().parent
for directory in (PROJECT_ROOT, TEST_DIRECTORY):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from test_banks_package import brute, quadratic
from tools.freshman_contest import banks
from tools.freshman_contest.banks_stress_cases import (
    BALANCE_MAGNITUDE,
    LONG_BLOCK_LENGTH,
    MAX_BANKS,
    iter_cases,
)
from tools.freshman_contest.stress_cases import StressCase


EXPECTED_IDENTIFIERS: Final = (
    "j-single-bank-positive-total",
    "j-two-bank-duplicate-circular-neighbor",
    "j-equal-prefixes-nonnegative",
    "j-negative-prefix-floor-remainder",
    "j-signed-minimum-balance-unit-total",
    "j-maximum-all-positive-balances",
    "j-maximum-nonnegative-unit-total",
    "j-maximum-unit-total-long-positive-negative-blocks-int64",
)
SMALL_BFS_IDENTIFIERS: Final = frozenset(EXPECTED_IDENTIFIERS[:4])
MAX_INPUT_BYTES: Final = 16 * 1024 * 1024
MAX_EXPECTED_OUTPUT_BYTES: Final = 512 * 1024


def _cases_by_identifier() -> dict[str, StressCase]:
    return {case.name: case for case in iter_cases()}


def test_banks_stress_cases_are_lazy_and_deterministic(monkeypatch) -> None:
    import tools.freshman_contest.banks_stress_cases as stress_cases

    with monkeypatch.context() as scoped_monkeypatch:
        scoped_monkeypatch.setattr(
            stress_cases,
            "_maximum_all_positive_case",
            lambda: (_ for _ in ()).throw(AssertionError("eager maximum case")),
        )
        assert next(stress_cases.iter_cases()).name == EXPECTED_IDENTIFIERS[0]

    first = tuple(iter_cases())
    second = tuple(iter_cases())
    assert first == second
    assert tuple(case.name for case in first) == EXPECTED_IDENTIFIERS
    assert len({case.name for case in first}) == len(first)


def test_banks_stress_cases_are_valid_and_reach_the_declared_bounds() -> None:
    cases = _cases_by_identifier()
    for case in cases.values():
        assert banks.validate(case.input_text) is None
        assert len(case.input_text.encode("utf-8")) <= MAX_INPUT_BYTES
        assert len(case.expected_output.encode("utf-8")) <= MAX_EXPECTED_OUTPUT_BYTES
    parsed = {identifier: banks.parse(case.input_text) for identifier, case in cases.items()}

    assert tuple(cases) == EXPECTED_IDENTIFIERS
    assert max(len(values) for values in parsed.values()) == MAX_BANKS
    assert parsed["j-maximum-all-positive-balances"] == [BALANCE_MAGNITUDE] * MAX_BANKS
    assert parsed["j-maximum-nonnegative-unit-total"] == [0] * (MAX_BANKS - 1) + [1]
    assert parsed["j-maximum-unit-total-long-positive-negative-blocks-int64"] == (
        [BALANCE_MAGNITUDE] * LONG_BLOCK_LENGTH
        + [-BALANCE_MAGNITUDE] * LONG_BLOCK_LENGTH
        + [1]
    )


def test_banks_stress_expected_outputs_follow_closed_forms() -> None:
    cases = _cases_by_identifier()

    assert cases["j-single-bank-positive-total"].expected_output == "0"
    assert cases["j-two-bank-duplicate-circular-neighbor"].expected_output == "2"
    assert cases["j-equal-prefixes-nonnegative"].expected_output == "0"
    assert cases["j-negative-prefix-floor-remainder"].expected_output == "5"
    assert cases["j-signed-minimum-balance-unit-total"].expected_output == str(
        2 * BALANCE_MAGNITUDE - 1
    )
    assert cases["j-maximum-all-positive-balances"].expected_output == "0"
    assert cases["j-maximum-nonnegative-unit-total"].expected_output == "0"

    # Prefixes are 0..m-1, m..1, 0 after division by BALANCE_MAGNITUDE.
    # The proof's pair-distance sum is m(m+1)(2m+1)/3 and its strict
    # original-order increasing-pair correction is m**2.
    m = LONG_BLOCK_LENGTH
    expected_long_answer = BALANCE_MAGNITUDE * (m * (m + 1) * (2 * m + 1) // 3) - m**2
    long_case = cases["j-maximum-unit-total-long-positive-negative-blocks-int64"]
    assert int(long_case.expected_output) == expected_long_answer
    assert 2**31 - 1 < expected_long_answer < 2**63


def test_tiny_banks_stress_cases_match_the_independent_bfs_oracle() -> None:
    """Exercise only tiny states with the operation-level BFS from existing tests."""

    for case in iter_cases():
        if case.name not in SMALL_BFS_IDENTIFIERS:
            continue
        balances = banks.parse(case.input_text)
        assert len(balances) <= 3
        assert max(map(abs, balances)) <= 5
        assert brute(balances) == int(case.expected_output)


def test_long_block_closed_form_matches_bounded_quadratic_and_bfs_checks() -> None:
    """Compare the block formula with finite checks; never BFS a large descriptor."""

    for block_length in range(1, 6):
        distance_sum = block_length * (block_length + 1) * (2 * block_length + 1) // 3
        for magnitude in range(1, 4):
            balances = [magnitude] * block_length + [-magnitude] * block_length + [1]
            expected = magnitude * distance_sum - block_length**2
            assert quadratic(balances) == expected
            # Keep the operation-level BFS strictly tiny; the rest of this
            # bounded family is checked by the independent quadratic sum.
            if len(balances) <= 5 and expected <= 20:
                assert brute(balances) == expected


def test_banks_reference_agrees_with_stress_descriptors_as_a_regression_check() -> None:
    """This is not an independent oracle; closed forms and the tiny BFS are above."""

    for case in iter_cases():
        assert banks.solve(case.input_text) == case.expected_output
