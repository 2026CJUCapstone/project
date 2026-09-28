"""Independent full-input oracle for the frozen freshman J long-block case.

The descriptor intentionally keeps its hidden expected output out of the
manifest, so this test binds the independently reconstructed input and answer
to the manifest's content hashes.  It must remain separate from both
``tools.freshman_contest.banks`` and ``banks_stress_cases``: importing either
would make the check depend on the production solver or the descriptor's
closed-form expected-output generator.
"""

from __future__ import annotations

from bisect import bisect_left, insort_left
import hashlib
import json
from itertools import chain, repeat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "tools" / "freshman_contest" / "corpus-manifest-draft-v2.json"
CASE_NAME = "j-maximum-unit-total-long-positive-negative-blocks-int64"
FROZEN_V2_MANIFEST_HASH = "sha256:e5213ca9d1aaf3691c91db22aa021870b532b653c015c58c4bf90fff8a8539fc"

MAX_BANKS = 9_999
BALANCE_MAGNITUDE = 31_999
LONG_BLOCK_LENGTH = (MAX_BANKS - 1) // 2


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _frozen_long_block_row() -> dict[str, object]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["manifestHash"] == FROZEN_V2_MANIFEST_HASH
    return next(
        row for row in manifest["problems"]["J"] if row["name"] == CASE_NAME
    )


def _reconstruct_full_descriptor_input() -> str:
    """Build the declared input directly, without asking the case generator."""

    balances = chain(
        repeat(BALANCE_MAGNITUDE, LONG_BLOCK_LENGTH),
        repeat(-BALANCE_MAGNITUDE, LONG_BLOCK_LENGTH),
        (1,),
    )
    return f"{MAX_BANKS}\n" + " ".join(map(str, balances)) + "\n"


def _parse_reconstructed_input(text: str) -> tuple[int, ...]:
    """A deliberately tiny local parser, not ``banks.parse``."""

    tokens = text.split()
    assert tokens and int(tokens[0]) == MAX_BANKS
    balances = tuple(map(int, tokens[1:]))
    assert len(balances) == MAX_BANKS
    return balances


def _unit_total_periodic_inversions(balances: tuple[int, ...]) -> int:
    """Count the operation distance through prefix levels for a total-one ring.

    Moving one negative bank unit is an adjacent swap of its two prefix
    levels.  For a total of one, every unordered pair of levels contributes
    exactly its absolute distance over all periods; an increasing pair in the
    original order is counted once from the opposite period and is removed.

    This is intentionally a different, single-case counting oracle from the
    production quotient/remainder + Fenwick algorithm: sorted levels give the
    pair-distance sum by the prefix-sum identity, while a plain sorted list
    counts earlier strictly smaller levels.  The latter is quadratic only in
    list shifts, but remains small and deterministic for this one n=9,999
    offline descriptor.
    """

    level = 0
    prefixes: list[int] = []
    for balance in balances:
        prefixes.append(level)
        level += balance
    assert level == 1

    pair_distance = 0
    earlier_level_sum = 0
    for index, current_level in enumerate(sorted(prefixes)):
        pair_distance += index * current_level - earlier_level_sum
        earlier_level_sum += current_level

    strictly_increasing = 0
    earlier_levels: list[int] = []
    for current_level in prefixes:
        strictly_increasing += bisect_left(earlier_levels, current_level)
        insort_left(earlier_levels, current_level)

    return pair_distance - strictly_increasing


def test_frozen_v2_j_long_block_expected_answer_has_an_independent_oracle() -> None:
    row = _frozen_long_block_row()
    assert row == {
        "name": CASE_NAME,
        "visibility": "hidden",
        "provenance": "banks-stress-v1",
        "inputBytes": 64_994,
        "inputHash": "sha256:fa98a71dce21a581e837f89c0754b11288ddf18071dcc6f2f41b7622c38f1d1a",
        "expectedBytes": 16,
        "expectedHash": "sha256:f17ddb8dfe5e55efc4c8d409c883012a2ee57e3edf8fee8ea564292d52f723ce",
    }

    input_text = _reconstruct_full_descriptor_input()
    assert len(input_text.encode("utf-8")) == row["inputBytes"]
    assert _sha256(input_text.encode("utf-8")) == row["inputHash"]

    balances = _parse_reconstructed_input(input_text)
    assert balances == (
        (BALANCE_MAGNITUDE,) * LONG_BLOCK_LENGTH
        + (-BALANCE_MAGNITUDE,) * LONG_BLOCK_LENGTH
        + (1,)
    )
    assert len(balances) == MAX_BANKS and sum(balances) == 1

    answer = _unit_total_periodic_inversions(balances)
    output = str(answer)
    # This boundary case is deliberately non-trivial: it catches 32-bit
    # counters while remaining a valid signed 64-bit expected output.
    assert answer > 2**31 - 1
    assert -(2**63) <= answer <= 2**63 - 1
    assert answer != 0 and len(output.encode("utf-8")) == row["expectedBytes"]
    assert _sha256(output.encode("utf-8")) == row["expectedHash"]
