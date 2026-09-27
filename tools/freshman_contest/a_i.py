"""Strict offline validators, reference solvers, and compact generators for A--I.

This module is intentionally separate from the web application and does not execute
submissions, access a database, or perform network I/O.  Inputs are constrained to
the draft statements in ``docs/freshman-contest-statements-a-i-2026-09-26.md``.
"""

from __future__ import annotations

from collections import Counter, deque
from copy import deepcopy
import random
import re
from typing import Any


SUPPORTED_LETTERS = tuple("ABCDEFGHI")
_INTEGER = re.compile(r"[+-]?\d+")
_ASCII_ALNUM = re.compile(r"[A-Za-z0-9]+")
_ASCII_ALPHA = re.compile(r"[A-Za-z]+")


# These records deliberately do not turn unreviewed candidate references into
# verified provenance, difficulty, or licensing claims.
METADATA: dict[str, dict[str, Any]] = {
    "A": {
        "title": "Two participant groups",
        "source": {"status": "PENDING", "references": ()},
        "external_review": "PENDING",
        "tier_verification": "PENDING",
        "license_verification": "PENDING",
        "reference_algorithm": "Add the two counts.",
        "complexity": "O(1) time, O(1) extra space",
        "wrong_strategies": (
            {"id": "subtract", "kind": "wrong", "description": "Subtracts one group from the other."},
        ),
    },
    "B": {
        "title": "Event draw score",
        "source": {"status": "PENDING", "references": ()},
        "external_review": "PENDING",
        "tier_verification": "PENDING",
        "license_verification": "PENDING",
        "reference_algorithm": "Count the three values and branch on multiplicity.",
        "complexity": "O(1) time, O(1) extra space",
        "wrong_strategies": (
            {
                "id": "pair_before_triple",
                "kind": "wrong",
                "description": "Recognizes a matching pair before recognizing three equal cards.",
            },
        ),
    },
    "C": {
        "title": "Club record survey",
        "source": {"status": "PENDING", "references": ()},
        "external_review": "PENDING",
        "tier_verification": "PENDING",
        "license_verification": "PENDING",
        "reference_algorithm": "Scan once while tracking the minimum and maximum.",
        "complexity": "O(N) time, O(1) solver working space",
        "wrong_strategies": (
            {
                "id": "zero_initialization",
                "kind": "wrong",
                "description": "Initializes both extrema to zero, which fails for one-sided data.",
            },
        ),
    },
    "D": {
        "title": "Cheer phrase expansion",
        "source": {"status": "PENDING", "references": ()},
        "external_review": "PENDING",
        "tier_verification": "PENDING",
        "license_verification": "PENDING",
        "reference_algorithm": "Repeat each character of every phrase R times.",
        "complexity": "O(total output length) time and space",
        "wrong_strategies": (
            {
                "id": "whole_string_repeat",
                "kind": "wrong",
                "description": "Repeats the complete string instead of each character.",
            },
        ),
    },
    "E": {
        "title": "Most frequent English letter",
        "source": {"status": "PENDING", "references": ()},
        "external_review": "PENDING",
        "tier_verification": "PENDING",
        "license_verification": "PENDING",
        "reference_algorithm": "Count uppercase-normalized letters and detect a tied maximum.",
        "complexity": "O(|S|) time, O(1) extra space",
        "wrong_strategies": (
            {
                "id": "case_sensitive",
                "kind": "wrong",
                "description": "Counts uppercase and lowercase letters separately.",
            },
        ),
    },
    "F": {
        "title": "Application lookup",
        "source": {"status": "PENDING", "references": ()},
        "external_review": "PENDING",
        "tier_verification": "PENDING",
        "license_verification": "PENDING",
        "reference_algorithm": "Build a set of registrations, then answer membership queries.",
        "complexity": "Expected O(N + M) time, O(N) extra space",
        "wrong_strategies": (
            {
                "id": "linear_scan_per_query",
                "kind": "slow",
                "description": "Scans the full registration list for every query: O(NM).",
            },
        ),
    },
    "G": {
        "title": "Equipment rental queue",
        "source": {"status": "PENDING", "references": ()},
        "external_review": "PENDING",
        "tier_verification": "PENDING",
        "license_verification": "PENDING",
        "reference_algorithm": "Sort processing times ascending and sum prefix sums.",
        "complexity": "O(N log N) time, O(N) extra space for the sorted copy",
        "wrong_strategies": (
            {
                "id": "input_order",
                "kind": "wrong",
                "description": "Uses the input order without minimizing total completion time.",
            },
        ),
    },
    "H": {
        "title": "Shortest walk to the classroom",
        "source": {"status": "PENDING", "references": ()},
        "external_review": "PENDING",
        "tier_verification": "PENDING",
        "license_verification": "PENDING",
        "reference_algorithm": "Use breadth-first search from the upper-left cell.",
        "complexity": "O(NM) time, O(NM) extra space",
        "wrong_strategies": (
            {
                "id": "first_dfs_path",
                "kind": "wrong",
                "description": "Reports the first depth-first route, which need not be shortest.",
            },
            {
                "id": "edge_count",
                "kind": "wrong",
                "description": "Reports moves rather than the required count of visited cells.",
            },
        ),
    },
    "I": {
        "title": "Lab update propagation",
        "source": {"status": "PENDING", "references": ()},
        "external_review": "PENDING",
        "tier_verification": "PENDING",
        "license_verification": "PENDING",
        "reference_algorithm": "Run multi-source breadth-first search from all installed computers.",
        "complexity": "O(NM) time, O(NM) extra space in the worst case",
        "wrong_strategies": (
            {
                "id": "single_source",
                "kind": "wrong",
                "description": "Starts from only one initially installed computer.",
            },
            {
                "id": "same_day_chain",
                "kind": "wrong",
                "description": "Lets a newly installed computer propagate again on the same day.",
            },
            {
                "id": "front_list_pop",
                "kind": "slow",
                "description": "Uses front deletion from a list instead of a queue.",
            },
        ),
    },
}


def _require_letter(letter: str) -> str:
    if not isinstance(letter, str) or letter not in SUPPORTED_LETTERS:
        raise ValueError(f"letter must be one of {', '.join(SUPPORTED_LETTERS)}")
    return letter


def _input_lines(text: str) -> list[str]:
    if not isinstance(text, str):
        raise ValueError("input text must be a string")
    if "\x00" in text:
        raise ValueError("input must not contain NUL characters")
    lines = text.splitlines()
    if not lines or any(line == "" for line in lines):
        raise ValueError("input must contain the required non-empty lines only")
    return lines


def _ints(line: str, where: str) -> list[int]:
    tokens = line.split()
    if not tokens or any(_INTEGER.fullmatch(token) is None for token in tokens):
        raise ValueError(f"{where} must contain only space-separated integers")
    return [int(token) for token in tokens]


def _one_int(line: str, where: str) -> int:
    values = _ints(line, where)
    if len(values) != 1:
        raise ValueError(f"{where} must contain exactly one integer")
    return values[0]


def _in_range(value: int, minimum: int, maximum: int, where: str) -> None:
    if not minimum <= value <= maximum:
        raise ValueError(f"{where} must be between {minimum} and {maximum}")


def _exact_lines(text: str, count: int, letter: str) -> list[str]:
    lines = _input_lines(text)
    if len(lines) != count:
        raise ValueError(f"{letter} requires exactly {count} input lines; trailing data is not allowed")
    return lines


def _parse_a(text: str) -> tuple[int, int]:
    values = _ints(_exact_lines(text, 1, "A")[0], "A input")
    if len(values) != 2:
        raise ValueError("A requires exactly two integers")
    for value in values:
        _in_range(value, 1, 9, "A group size")
    return values[0], values[1]


def _parse_b(text: str) -> tuple[int, int, int]:
    values = _ints(_exact_lines(text, 1, "B")[0], "B input")
    if len(values) != 3:
        raise ValueError("B requires exactly three card values")
    for value in values:
        _in_range(value, 1, 6, "B card value")
    return values[0], values[1], values[2]


def _parse_c(text: str) -> list[int]:
    lines = _exact_lines(text, 2, "C")
    n = _one_int(lines[0], "C first line")
    _in_range(n, 1, 1_000_000, "C N")
    values = _ints(lines[1], "C second line")
    if len(values) != n:
        raise ValueError("C must provide exactly N score changes")
    for value in values:
        _in_range(value, -1_000_000, 1_000_000, "C score change")
    return values


def _parse_d(text: str) -> list[tuple[int, str]]:
    lines = _input_lines(text)
    t = _one_int(lines[0], "D first line")
    _in_range(t, 1, 1_000, "D T")
    if len(lines) != t + 1:
        raise ValueError("D must provide exactly T phrase lines; trailing data is not allowed")
    cases: list[tuple[int, str]] = []
    for index, line in enumerate(lines[1:], start=1):
        tokens = line.split()
        if len(tokens) != 2 or _INTEGER.fullmatch(tokens[0]) is None:
            raise ValueError(f"D phrase line {index} must contain R and S only")
        repeats = int(tokens[0])
        phrase = tokens[1]
        _in_range(repeats, 1, 8, f"D R on phrase line {index}")
        if _ASCII_ALNUM.fullmatch(phrase) is None or not 1 <= len(phrase) <= 20:
            raise ValueError(f"D S on phrase line {index} must be 1--20 ASCII letters or digits")
        cases.append((repeats, phrase))
    return cases


def _parse_e(text: str) -> str:
    line = _exact_lines(text, 1, "E")[0]
    if _ASCII_ALPHA.fullmatch(line) is None or not 1 <= len(line) <= 1_000_000:
        raise ValueError("E S must be 1--1,000,000 ASCII English letters with no whitespace")
    return line


def _parse_f(text: str) -> tuple[set[int], list[int]]:
    lines = _exact_lines(text, 4, "F")
    n = _one_int(lines[0], "F first line")
    _in_range(n, 1, 100_000, "F N")
    registrations = _ints(lines[1], "F second line")
    if len(registrations) != n:
        raise ValueError("F must provide exactly N registration numbers")
    m = _one_int(lines[2], "F third line")
    _in_range(m, 1, 100_000, "F M")
    queries = _ints(lines[3], "F fourth line")
    if len(queries) != m:
        raise ValueError("F must provide exactly M query numbers")
    for value in registrations + queries:
        _in_range(value, -2_147_483_648, 2_147_483_647, "F number")
    return set(registrations), queries


def _parse_g(text: str) -> list[int]:
    lines = _exact_lines(text, 2, "G")
    n = _one_int(lines[0], "G first line")
    _in_range(n, 1, 1_000, "G N")
    times = _ints(lines[1], "G second line")
    if len(times) != n:
        raise ValueError("G must provide exactly N processing times")
    for value in times:
        _in_range(value, 1, 1_000, "G processing time")
    return times


def _h_shortest(grid: list[str], rows: int, columns: int) -> int | None:
    queue = deque([0])
    distances = [-1] * (rows * columns)
    distances[0] = 1
    while queue:
        position = queue.popleft()
        if position == rows * columns - 1:
            return distances[position]
        row, column = divmod(position, columns)
        for next_row, next_column in (
            (row - 1, column),
            (row + 1, column),
            (row, column - 1),
            (row, column + 1),
        ):
            if not (0 <= next_row < rows and 0 <= next_column < columns):
                continue
            following = next_row * columns + next_column
            if distances[following] == -1 and grid[next_row][next_column] == "1":
                distances[following] = distances[position] + 1
                queue.append(following)
    return None


def _parse_h(text: str) -> tuple[int, int, list[str]]:
    lines = _input_lines(text)
    dimensions = _ints(lines[0], "H first line")
    if len(dimensions) != 2:
        raise ValueError("H first line requires N and M")
    rows, columns = dimensions
    _in_range(rows, 2, 100, "H N")
    _in_range(columns, 2, 100, "H M")
    if len(lines) != rows + 1:
        raise ValueError("H must provide exactly N grid rows; trailing data is not allowed")
    grid = lines[1:]
    if any(re.fullmatch(rf"[01]{{{columns}}}", row) is None for row in grid):
        raise ValueError("H grid rows must be unspaced binary strings of length M")
    if grid[0][0] != "1" or grid[-1][-1] != "1":
        raise ValueError("H start and destination cells must both be passable")
    if _h_shortest(grid, rows, columns) is None:
        raise ValueError("H requires a route from start to destination")
    return rows, columns, grid


def _parse_i(text: str) -> tuple[int, int, list[int]]:
    lines = _input_lines(text)
    dimensions = _ints(lines[0], "I first line")
    if len(dimensions) != 2:
        raise ValueError("I first line requires M and N")
    columns, rows = dimensions
    _in_range(columns, 2, 1_000, "I M")
    _in_range(rows, 2, 1_000, "I N")
    if len(lines) != rows + 1:
        raise ValueError("I must provide exactly N grid rows; trailing data is not allowed")
    cells: list[int] = []
    for index, line in enumerate(lines[1:], start=1):
        row = _ints(line, f"I grid row {index}")
        if len(row) != columns:
            raise ValueError("I each grid row must contain exactly M values")
        if any(value not in (-1, 0, 1) for value in row):
            raise ValueError("I grid values must be -1, 0, or 1")
        cells.extend(row)
    if all(value == -1 for value in cells):
        raise ValueError("I requires at least one computer")
    return columns, rows, cells


def _parse(letter: str, text: str) -> Any:
    parser = {
        "A": _parse_a,
        "B": _parse_b,
        "C": _parse_c,
        "D": _parse_d,
        "E": _parse_e,
        "F": _parse_f,
        "G": _parse_g,
        "H": _parse_h,
        "I": _parse_i,
    }[letter]
    return parser(text)


def validate(letter: str, text: str) -> None:
    """Validate one complete A--I statement input or raise ``ValueError``.

    Validation includes exact token/row counts and statement guarantees such as H's
    reachable destination.  It accepts normal terminal newlines but no extra lines
    or tokens.
    """

    _parse(_require_letter(letter), text)


def solve(letter: str, text: str) -> str:
    """Validate and solve one A--I input, returning output without a final newline."""

    letter = _require_letter(letter)
    parsed = _parse(letter, text)
    if letter == "A":
        first, second = parsed
        return str(first + second)
    if letter == "B":
        counts = Counter(parsed)
        value, count = counts.most_common(1)[0]
        if count == 3:
            return str(10_000 + value * 1_000)
        if count == 2:
            return str(1_000 + value * 100)
        return str(max(counts) * 100)
    if letter == "C":
        return f"{min(parsed)} {max(parsed)}"
    if letter == "D":
        return "\n".join("".join(character * repeats for character in phrase) for repeats, phrase in parsed)
    if letter == "E":
        counts = Counter(parsed.upper())
        highest = max(counts.values())
        winners = [character for character, count in counts.items() if count == highest]
        return winners[0] if len(winners) == 1 else "?"
    if letter == "F":
        registrations, queries = parsed
        return "\n".join("1" if value in registrations else "0" for value in queries)
    if letter == "G":
        elapsed = 0
        total = 0
        for processing_time in sorted(parsed):
            elapsed += processing_time
            total += elapsed
        return str(total)
    if letter == "H":
        rows, columns, grid = parsed
        distance = _h_shortest(grid, rows, columns)
        if distance is None:  # _parse_h already enforces this statement guarantee.
            raise AssertionError("validated H input unexpectedly has no route")
        return str(distance)
    columns, rows, cells = parsed
    queue = deque(index for index, value in enumerate(cells) if value == 1)
    remaining = cells.count(0)
    if remaining == 0:
        return "0"
    if not queue:
        return "-1"
    days = 0
    while queue and remaining:
        for _ in range(len(queue)):
            position = queue.popleft()
            row, column = divmod(position, columns)
            for next_row, next_column in (
                (row - 1, column),
                (row + 1, column),
                (row, column - 1),
                (row, column + 1),
            ):
                if not (0 <= next_row < rows and 0 <= next_column < columns):
                    continue
                following = next_row * columns + next_column
                if cells[following] == 0:
                    cells[following] = 1
                    remaining -= 1
                    queue.append(following)
        days += 1
    return str(days if remaining == 0 else -1)


def _case_i(columns: int, rows: int, cells: list[int]) -> str:
    return f"{columns} {rows}\n" + "\n".join(
        " ".join(str(value) for value in cells[row * columns:(row + 1) * columns])
        for row in range(rows)
    )


def _random_word(rng: random.Random, length: int, alphabet: str) -> str:
    return "".join(rng.choice(alphabet) for _ in range(length))


def generate(letter: str, seed: int = 0) -> list[str]:
    """Return compact boundary and seeded-random valid inputs for one problem.

    The returned corpus is intentionally small (at most 16 cases) so it is useful
    in unit and harness tests.  It covers value and logic boundaries, not full-size
    resource benchmarking; language-specific maximum-input testing remains a
    separate judge-validation task.
    """

    letter = _require_letter(letter)
    if not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    rng = random.Random(seed)
    cases: list[str]
    if letter == "A":
        cases = ["1 1\n", "9 9\n", f"{rng.randint(1, 9)} {rng.randint(1, 9)}\n"]
    elif letter == "B":
        cases = ["1 1 1\n", "6 2 6\n", "1 4 6\n"]
        cases.extend(" ".join(str(rng.randint(1, 6)) for _ in range(3)) + "\n" for _ in range(6))
    elif letter == "C":
        cases = [
            "1\n-1000000\n",
            "1\n1000000\n",
            "5\n-1000000 -4 0 8 1000000\n",
        ]
        for _ in range(5):
            count = rng.randint(1, 24)
            cases.append(f"{count}\n" + " ".join(str(rng.randint(-1_000_000, 1_000_000)) for _ in range(count)) + "\n")
    elif letter == "D":
        cases = ["1\n1 a\n", "2\n8 Z9z\n1 A1b2C3d4E5f6G7h8I9j\n"]
        for _ in range(4):
            count = rng.randint(1, 5)
            rows = [str(count)]
            for _ in range(count):
                rows.append(f"{rng.randint(1, 8)} {_random_word(rng, rng.randint(1, 20), 'abcXYZ019')}")
            cases.append("\n".join(rows) + "\n")
    elif letter == "E":
        cases = ["z\n", "AaBb\n", "Z" * 80 + "a" * 79 + "\n"]
        cases.extend(_random_word(rng, rng.randint(1, 120), "abcXYZ") + "\n" for _ in range(5))
    elif letter == "F":
        cases = [
            "1\n-2147483648\n2\n-2147483648 2147483647\n",
            "4\n7 7 0 2147483647\n5\n7 -1 0 2147483647 7\n",
        ]
        for _ in range(4):
            count = rng.randint(1, 30)
            query_count = rng.randint(1, 30)
            values = [rng.randint(-2_147_483_648, 2_147_483_647) for _ in range(count)]
            queries = [rng.choice(values) if rng.randrange(2) else rng.randint(-2_147_483_648, 2_147_483_647) for _ in range(query_count)]
            cases.append(
                f"{count}\n{' '.join(map(str, values))}\n{query_count}\n{' '.join(map(str, queries))}\n"
            )
    elif letter == "G":
        cases = ["1\n1000\n", "5\n1000 999 2 1 500\n", "4\n7 7 7 7\n"]
        for _ in range(5):
            count = rng.randint(1, 12)
            cases.append(f"{count}\n" + " ".join(str(rng.randint(1, 1_000)) for _ in range(count)) + "\n")
    elif letter == "H":
        cases = ["2 2\n11\n11\n", "2 5\n11111\n00001\n"]
        for _ in range(5):
            rows, columns = rng.randint(2, 8), rng.randint(2, 8)
            grid = [["1"] * columns for _ in range(rows)]
            # Preserve a top-row/right-column route while adding obstacles elsewhere.
            for row in range(1, rows):
                for column in range(columns - 1):
                    if rng.randrange(3) == 0:
                        grid[row][column] = "0"
            cases.append(f"{rows} {columns}\n" + "\n".join("".join(row) for row in grid) + "\n")
    else:  # I
        cases = [
            "2 2\n1 -1\n1 1\n",
            "2 2\n0 0\n0 -1\n",
            "5 3\n1 0 0 0 0\n0 0 -1 0 0\n0 0 0 0 1\n",
        ]
        for _ in range(5):
            columns, rows = rng.randint(2, 8), rng.randint(2, 8)
            cells = [rng.choice((-1, 0, 0, 1)) for _ in range(columns * rows)]
            cells[0] = 1
            cases.append(_case_i(columns, rows, cells))
    if len(cases) > 200:
        raise AssertionError("generator corpus exceeded its bounded case limit")
    for case in cases:
        validate(letter, case)
    return cases


def metadata(letter: str) -> dict[str, Any]:
    """Return a defensive copy of the unverified A--I metadata record."""

    return deepcopy(METADATA[_require_letter(letter)])


__all__ = ["METADATA", "SUPPORTED_LETTERS", "generate", "metadata", "solve", "validate"]
