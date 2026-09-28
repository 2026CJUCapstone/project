"""Independent, bounded checks for selected frozen draft maximum descriptors.

These local formula/traversal checks bind generator material to the frozen
manifest.  They are not a second runtime suite and do not establish a contest
policy or language-specific resource limit.  In particular, they do not prove
the non-trivial J long-block formula or distinguish correct slow submissions.
"""

from __future__ import annotations

from collections import Counter, deque
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
for directory in (ROOT, SCRIPTS):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from generate_freshman_corpus_manifest import MANIFEST, case_material


MANIFEST_PATH = MANIFEST


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=None)
def frozen_case(letter: str, name: str) -> tuple[str, str]:
    """Return raw generator material only after binding it to the frozen JSON."""

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    row = next(row for row in manifest["problems"][letter] if row["name"] == name)
    material = next(
        (input_text, expected)
        for candidate_name, _, _, input_text, expected in case_material(letter)
        if candidate_name == name
    )
    input_text, expected = material
    assert row["inputBytes"] == len(input_text.encode("utf-8"))
    assert row["inputHash"] == _sha256(input_text.encode("utf-8"))
    assert row["expectedBytes"] == len(expected.encode("utf-8"))
    assert row["expectedHash"] == _sha256(expected.encode("utf-8"))
    return input_text, expected


def _membership_oracle(text: str) -> str:
    lines = text.splitlines()
    count = int(lines[0])
    registrations = {int(value) for value in lines[1].split()}
    query_count = int(lines[2])
    queries = tuple(map(int, lines[3].split()))
    assert len(lines) == 4 and len(lines[1].split()) == count and len(queries) == query_count
    return "\n".join("1" if value in registrations else "0" for value in queries)


def _shortest_open_grid_path(text: str) -> int:
    lines = text.splitlines()
    rows, columns = map(int, lines[0].split())
    assert rows == columns == 100 and len(lines) == rows + 1
    grid = tuple(lines[1:])
    assert all(len(row) == columns and set(row) <= {"0", "1"} for row in grid)
    assert grid[0][0] == grid[-1][-1] == "1"

    queue = deque([(0, 0, 1)])
    seen = {(0, 0)}
    while queue:
        row, column, distance = queue.popleft()
        if (row, column) == (rows - 1, columns - 1):
            return distance
        for next_row, next_column in ((row - 1, column), (row + 1, column),
                                      (row, column - 1), (row, column + 1)):
            if (0 <= next_row < rows and 0 <= next_column < columns
                    and grid[next_row][next_column] == "1"
                    and (next_row, next_column) not in seen):
                seen.add((next_row, next_column))
                queue.append((next_row, next_column, distance + 1))
    raise AssertionError("frozen H maximum descriptor has no path")


def test_c_maximum_extrema_uses_direct_bound_witnesses() -> None:
    text, expected = frozen_case("C", "c-maximum-extrema-negative-repetitions")
    count_line, values_line = text.splitlines()
    assert int(count_line) == 1_000_000
    assert values_line.startswith("-1000000 1000000 ")
    assert values_line.count("-7") == 999_998
    # The two statement-bound witnesses determine the extrema without invoking
    # the generator/reference solver or allocating a million parsed integers.
    assert expected == "-1000000 1000000"


def test_d_maximum_expansion_is_recomputed_from_each_input_row() -> None:
    text, expected = frozen_case("D", "d-maximum-case-count-repeat-and-length")
    lines = text.splitlines()
    assert int(lines[0]) == 1_000 and len(lines) == 1_001
    actual = "\n".join("".join(character * int(repeats) for character in phrase)
                       for repeats, phrase in (line.split() for line in lines[1:]))
    assert actual == expected


def test_e_maximum_casefolded_counts_are_recomputed() -> None:
    for name in ("e-maximum-case-insensitive-tie", "e-maximum-case-insensitive-winner"):
        text, expected = frozen_case("E", name)
        word = text.strip()
        assert len(word) == 1_000_000 and word.isalpha()
        counts = Counter(word.upper())
        maximum = max(counts.values())
        winners = [letter for letter, value in counts.items() if value == maximum]
        assert expected == (winners[0] if len(winners) == 1 else "?")


def test_f_maximum_membership_descriptors_use_an_independent_set_oracle() -> None:
    for name in (
        "f-maximum-registrations-and-queries-extrema-duplicates-absence",
        "f-asymmetric-one-registration-many-queries",
        "f-linear-scan-discriminator-mostly-absent-queries",
    ):
        text, expected = frozen_case("F", name)
        assert _membership_oracle(text) == expected


def test_g_maximum_equal_and_reverse_closed_forms() -> None:
    equal_cases = (
        ("g-maximum-count-all-largest-durations", 1_000),
        ("g-maximum-count-all-minimum-durations", 1),
    )
    for name, duration in equal_cases:
        text, expected = frozen_case("G", name)
        lines = text.splitlines()
        count = int(lines[0])
        values = tuple(map(int, lines[1].split()))
        assert count == len(values) == 1_000 and set(values) == {duration}
        assert expected == str(duration * count * (count + 1) // 2)

    text, expected = frozen_case("G", "g-maximum-count-reverse-durations")
    lines = text.splitlines()
    count = int(lines[0])
    assert tuple(map(int, lines[1].split())) == tuple(range(count, 0, -1))
    assert expected == str(count * (count + 1) * (count + 2) // 6)


def test_h_all_frozen_100_by_100_paths_have_independent_bfs_outputs() -> None:
    for name in ("h-maximum-open-grid", "h-maximum-serpentine-detour"):
        text, expected = frozen_case("H", name)
        assert str(_shortest_open_grid_path(text)) == expected


def test_i_open_1000_by_1000_frontier_has_manhattan_day_count() -> None:
    text, expected = frozen_case("I", "i-maximum-single-source-frontier")
    lines = text.splitlines()
    columns, rows = map(int, lines[0].split())
    assert columns == rows == 1_000 and len(lines) == rows + 1
    source_row = "1" + " 0" * (columns - 1)
    empty_row = "0" + " 0" * (columns - 1)
    assert lines[1] == source_row and all(line == empty_row for line in lines[2:])
    # With one corner source, no walls, and synchronous day layers, the
    # far-corner day is its Manhattan distance from the source.
    assert expected == str((rows - 1) + (columns - 1))


def test_i_many_source_1000_by_1000_front_delete_discriminator_needs_one_day() -> None:
    text, expected = frozen_case("I", "i-maximum-many-sources-front-delete-discriminator")
    lines = text.splitlines()
    columns, rows = map(int, lines[0].split())
    assert columns == rows == 1_000 and len(lines) == rows + 1
    complete_row = "1 " * (columns - 1) + "1"
    final_row = "1 " * (columns - 1) + "0"
    assert all(line == complete_row for line in lines[1:-1])
    assert lines[-1] == final_row
    # The sole uninstalled cell is orthogonally adjacent to an initial source;
    # synchronous propagation therefore takes exactly one day.
    assert expected == "1"


def test_j_simple_maximum_nonnegative_cases_need_zero_moves() -> None:
    for name in ("j-maximum-all-positive-balances", "j-maximum-nonnegative-unit-total"):
        text, expected = frozen_case("J", name)
        values = tuple(map(int, text.split()))
        count, balances = values[0], values[1:]
        assert count == len(balances) == 9_999
        assert all(value >= 0 for value in balances) and sum(balances) > 0
        assert expected == "0"
