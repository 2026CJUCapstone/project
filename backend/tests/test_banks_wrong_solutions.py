"""Offline kill matrix for bounded, intentional wrong J solutions.

This checks named functional misunderstandings against the local J oracle.  It
does not claim judge coverage, benchmark a time limit, or run untrusted code.
"""

from __future__ import annotations

from collections import deque
from itertools import product
from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.freshman_contest import banks, banks_wrong


BFS_MAX_DEPTH = 100
BFS_MAX_STATES = 100_000


def _bounded_minimum_search(start: list[int]) -> int:
    """Small-input operation oracle, with explicit state/depth bounds."""

    queue = deque([(tuple(start), 0)])
    seen = {tuple(start)}
    while queue:
        state, depth = queue.popleft()
        if min(state) >= 0:
            return depth
        assert depth < BFS_MAX_DEPTH
        assert len(seen) < BFS_MAX_STATES
        for index, balance in enumerate(state):
            if balance >= 0:
                continue
            updated = list(state)
            updated[index] = -balance
            updated[(index - 1) % len(state)] += balance
            updated[(index + 1) % len(state)] += balance
            next_state = tuple(updated)
            if next_state not in seen:
                seen.add(next_state)
                queue.append((next_state, depth + 1))
    raise AssertionError("a positive-total small state should reach a terminal state")


def _bounded_corpus() -> tuple[str, ...]:
    """Finite valid corpus: small exhaustive states plus seeded generator cases."""

    cases = [case.text for case in banks_wrong.COUNTEREXAMPLES.values()]
    for count in range(1, 4):
        for balances in product(range(-2, 3), repeat=count):
            if sum(balances) > 0:
                cases.append(f"{count}\n" + " ".join(map(str, balances)) + "\n")
    for seed in (71, 1847):
        cases.extend(banks.generate(seed))
    return tuple(dict.fromkeys(cases))


MUTANT_IDS = tuple(mutant.identifier for mutant in banks_wrong.iter_mutants())


def test_catalogue_has_unique_documented_mutants_and_kill_cases() -> None:
    assert len(MUTANT_IDS) == len(set(MUTANT_IDS))
    assert set(MUTANT_IDS) == set(banks_wrong.COUNTEREXAMPLES)
    for mutant in banks_wrong.MUTANTS:
        case = banks_wrong.COUNTEREXAMPLES[mutant.identifier]
        assert case.identifier == mutant.identifier
        assert mutant.category
        assert mutant.description
        assert case.phenomenon
        assert callable(mutant.solve)


@pytest.mark.parametrize("identifier", MUTANT_IDS)
def test_handcrafted_valid_counterexample_kills_each_named_mutant(identifier: str) -> None:
    case = banks_wrong.COUNTEREXAMPLES[identifier]
    assert banks.validate(case.text) is None
    expected = banks.solve(case.text)
    assert expected == case.oracle_output
    actual = banks_wrong.solve_mutant(identifier, case.text)
    assert actual != expected, (
        f"J/{identifier} survived its valid kill case {case.text!r}: "
        f"expected {expected!r}, received {actual!r}"
    )


def test_small_counterexamples_agree_with_bounded_operation_search() -> None:
    for identifier, case in banks_wrong.COUNTEREXAMPLES.items():
        balances = banks.parse(case.text)
        if identifier == "signed_32_bit_accumulator":
            continue
        assert len(balances) <= 4
        assert int(case.oracle_output) == _bounded_minimum_search(balances), identifier


def test_overflow_counterexample_requires_more_than_signed_32_bits() -> None:
    case = banks_wrong.COUNTEREXAMPLES["signed_32_bit_accumulator"]
    balances = banks.parse(case.text)
    assert len(balances) == 101
    assert int(case.oracle_output) > 2**31 - 1
    assert banks.solve(case.text) == case.oracle_output
    assert banks_wrong.solve_mutant("signed_32_bit_accumulator", case.text) == "-1547855646"


def test_bounded_deterministic_corpus_is_valid_and_kills_every_mutant() -> None:
    cases = _bounded_corpus()
    assert cases
    assert max(len(text.split()) - 1 for text in cases) == 9_999
    expected = {}
    for text in cases:
        assert banks.validate(text) is None
        expected[text] = banks.solve(text)

    for identifier in MUTANT_IDS:
        killer = next(
            (text for text in cases if banks_wrong.solve_mutant(identifier, text) != expected[text]),
            None,
        )
        assert killer is not None, f"bounded corpus did not kill J/{identifier}"


def test_mutant_dispatch_rejects_unknown_identifier_after_input_validation() -> None:
    with pytest.raises(ValueError, match="unknown J mutant"):
        banks_wrong.solve_mutant("unknown", "1\n1\n")
    with pytest.raises(ValueError):
        banks_wrong.solve_mutant(MUTANT_IDS[0], "2\n-1 1\n")
