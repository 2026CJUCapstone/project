"""Contract checks for the lazy deterministic freshman-contest stress corpus."""

from __future__ import annotations

from collections import Counter
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
from typing import Final, Iterator

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DIRECTORY = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(TEST_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(TEST_DIRECTORY))

import test_freshman_bpp_a_d_sources as bounded_process
from tools.freshman_contest.a_i import SUPPORTED_LETTERS, solve, validate
from tools.freshman_contest.stress_cases import (
    MAX_C_VALUES,
    MAX_D_CASES,
    MAX_E_LENGTH,
    MAX_F_VALUES,
    MAX_G_VALUES,
    MAX_H_DIMENSION,
    MAX_I_DIMENSION,
    StressCase,
    iter_cases,
)


EXPECTED_CASE_COUNTS: Final = {
    "A": 2,
    "B": 3,
    "C": 2,
    "D": 2,
    "E": 3,
    "F": 2,
    "G": 3,
    "H": 3,
    "I": 3,
}
SMALL_ORACLE_CASES: Final = {
    "a-minimum-groups",
    "a-maximum-groups",
    "b-minimum-triple",
    "b-maximum-triple",
    "b-pair-and-largest-distinct",
    "c-single-minimum",
    "d-minimum-repeat-and-length",
    "e-single-lowercase-letter",
    "f-small-extrema-duplicate-membership",
    "g-single-largest-duration",
    "h-small-open-grid",
    "i-small-multi-source",
    "i-small-unreachable",
}
PYTHON_SOURCE_DIRECTORY = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "python"
PYTHON_STRESS_TIMEOUT_SECONDS: Final = 10
PYTHON_STRESS_OUTPUT_CAP: Final = 512 * 1024


def _iter_integers(text: str) -> Iterator[int]:
    sign = 1
    value = 0
    started = False
    for character in text:
        if "0" <= character <= "9":
            value = value * 10 + ord(character) - ord("0")
            started = True
        elif character == "+" and not started:
            sign = 1
        elif character == "-" and not started:
            sign = -1
        else:
            if started:
                yield sign * value
            sign = 1
            value = 0
            started = False
    if started:
        yield sign * value


def _assert_closed_form(case: StressCase) -> None:
    if case.name == "c-maximum-extrema-negative-repetitions":
        values = _iter_integers(case.input_text)
        declared_count = next(values)
        assert declared_count == MAX_C_VALUES
        minimum = maximum = next(values)
        for _ in range(1, declared_count):
            value = next(values)
            minimum = min(minimum, value)
            maximum = max(maximum, value)
        assert next(values, None) is None
        assert case.expected_output == f"{minimum} {maximum}"
    elif case.name == "d-maximum-case-count-repeat-and-length":
        rows = case.input_text.splitlines()
        assert int(rows[0]) == MAX_D_CASES
        assert len(rows) == MAX_D_CASES + 1
        derived = []
        for row in rows[1:]:
            repeat_text, phrase = row.split()
            derived.append("".join(character * int(repeat_text) for character in phrase))
        assert case.expected_output == "\n".join(derived)
    elif case.name.startswith("e-maximum-case-insensitive-"):
        word = case.input_text.strip()
        assert len(word) == MAX_E_LENGTH
        counts = Counter(word.casefold())
        highest = max(counts.values())
        winners = [letter for letter, count in counts.items() if count == highest]
        expected = "?" if len(winners) != 1 else winners[0].upper()
        assert case.expected_output == expected
    elif case.name == "f-maximum-registrations-and-queries-extrema-duplicates-absence":
        lines = case.input_text.splitlines()
        assert len(lines) == 4
        assert int(lines[0]) == MAX_F_VALUES
        registration_tokens = lines[1].split()
        assert len(registration_tokens) == MAX_F_VALUES
        registrations = {int(token) for token in registration_tokens}
        assert int(lines[2]) == MAX_F_VALUES
        queries = [int(token) for token in lines[3].split()]
        assert len(queries) == MAX_F_VALUES
        assert {-2_147_483_648, 0, 2_147_483_647} <= registrations
        assert len(registrations) < MAX_F_VALUES
        assert -1 in queries and -1 not in registrations
        expected = "\n".join("1" if query in registrations else "0" for query in queries)
        assert case.expected_output == expected
    elif case.name.startswith("g-maximum-count-"):
        values = _iter_integers(case.input_text)
        declared_count = next(values)
        assert declared_count == MAX_G_VALUES
        durations = [next(values) for _ in range(declared_count)]
        assert next(values, None) is None
        elapsed = 0
        total = 0
        for duration in sorted(durations):
            elapsed += duration
            total += elapsed
        assert case.expected_output == str(total)
    elif case.name.startswith("h-maximum-"):
        assert solve("H", case.input_text) == case.expected_output
    elif case.name == "i-maximum-single-source-frontier":
        rows = case.input_text.splitlines()
        columns, row_count = (int(value) for value in rows[0].split())
        assert columns == MAX_I_DIMENSION
        assert row_count == MAX_I_DIMENSION
        assert len(rows) == row_count + 1
        first_row = rows[1].split()
        assert len(first_row) == columns
        assert first_row[0] == "1"
        assert all(value == "0" for value in first_row[1:])
        empty_row = "0" + " 0" * (columns - 1)
        assert all(row == empty_row for row in rows[2:])
        assert case.expected_output == str((columns - 1) + (row_count - 1))


def test_stress_cases_are_lazy_deterministic_and_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.freshman_contest.stress_cases as stress_cases

    monkeypatch.setattr(stress_cases, "_c_maximum_case", lambda: (_ for _ in ()).throw(AssertionError("eager")))
    first = next(stress_cases.iter_cases("C"))
    assert first.name == "c-single-minimum"
    assert next(iter_cases("A")) == next(iter_cases("A"))
    with pytest.raises(FrozenInstanceError):
        first.name = "replacement"  # type: ignore[misc]
    with pytest.raises(ValueError):
        next(iter_cases("J"))


def test_stress_cases_validate_and_match_closed_form_or_small_oracles() -> None:
    for letter in SUPPORTED_LETTERS:
        count = 0
        names: set[str] = set()
        for case in iter_cases(letter):
            count += 1
            assert case.name not in names
            names.add(case.name)
            validate(letter, case.input_text)
            _assert_closed_form(case)
            if case.name in SMALL_ORACLE_CASES:
                assert solve(letter, case.input_text) == case.expected_output
        assert count == EXPECTED_CASE_COUNTS[letter]


def test_python_references_match_every_stress_case_sequentially(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run one descriptor at a time through the trusted standalone Python references."""

    monkeypatch.setattr(bounded_process, "MAX_OUTPUT_BYTES", PYTHON_STRESS_OUTPUT_CAP)
    executed = 0
    for letter in SUPPORTED_LETTERS:
        source = PYTHON_SOURCE_DIRECTORY / f"{letter}.py"
        assert source.is_file(), f"missing standalone Python reference for {letter}"
        for case in iter_cases(letter):
            executed += 1
            result = bounded_process._run(
                [sys.executable, str(source)],
                cwd=PROJECT_ROOT,
                input_text=case.input_text,
                timeout=PYTHON_STRESS_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                pytest.fail(f"{letter}/{case.name} standalone Python reference exited {result.returncode}")
            try:
                actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").rstrip("\n")
            except UnicodeDecodeError:
                pytest.fail(f"{letter}/{case.name} standalone Python reference emitted non-UTF-8 output")
            if actual != case.expected_output:
                pytest.fail(f"{letter}/{case.name} standalone Python output mismatch")
    assert executed == sum(EXPECTED_CASE_COUNTS.values())
