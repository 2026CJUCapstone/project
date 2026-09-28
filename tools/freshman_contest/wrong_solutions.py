"""Bounded, intentional wrong-answer mutants for the draft freshman A--I tasks.

These are offline test fixtures, not contestant submissions or performance probes.
Each function assumes a statement-valid input and returns a candidate output without
a trailing newline.  The mutants model common functional mistakes only; none relies
on an unbounded loop, excessive allocation, or a runtime-limit claim.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Callable, Final, Iterator

from .a_i import SUPPORTED_LETTERS, validate


MutantSolver = Callable[[str], str]


@dataclass(frozen=True)
class Mutant:
    """One named, intentionally incorrect implementation strategy."""

    letter: str
    identifier: str
    category: str
    description: str
    solve: MutantSolver


def a_subtract_groups(text: str) -> str:
    first, second = map(int, text.split())
    return str(first - second)


def a_multiply_groups(text: str) -> str:
    first, second = map(int, text.split())
    return str(first * second)


def b_pair_before_triple(text: str) -> str:
    first, second, third = map(int, text.split())
    if first == second:
        return str(1_000 + first * 100)
    if first == third:
        return str(1_000 + first * 100)
    if second == third:
        return str(1_000 + second * 100)
    return str(max(first, second, third) * 100)


def b_middle_card_when_distinct(text: str) -> str:
    values = list(map(int, text.split()))
    counts = Counter(values)
    repeated_value, repeated_count = counts.most_common(1)[0]
    if repeated_count == 3:
        return str(10_000 + repeated_value * 1_000)
    if repeated_count == 2:
        return str(1_000 + repeated_value * 100)
    return str(values[1] * 100)


def _c_values(text: str) -> list[int]:
    return list(map(int, text.splitlines()[1].split()))


def c_zero_initialized_extrema(text: str) -> str:
    minimum = 0
    maximum = 0
    for value in _c_values(text):
        minimum = min(minimum, value)
        maximum = max(maximum, value)
    return f"{minimum} {maximum}"


def c_assume_input_extrema_order(text: str) -> str:
    values = _c_values(text)
    return f"{values[0]} {values[-1]}"


def _d_cases(text: str) -> list[tuple[int, str]]:
    return [(int(repeats), phrase) for repeats, phrase in (line.split() for line in text.splitlines()[1:])]


def d_repeat_whole_phrase(text: str) -> str:
    return "\n".join(phrase * repeats for repeats, phrase in _d_cases(text))


def d_ignore_repeat_count(text: str) -> str:
    return "\n".join(phrase for _, phrase in _d_cases(text))


def e_case_sensitive_counts(text: str) -> str:
    counts = Counter(text.strip())
    highest = max(counts.values())
    winners = [character for character, count in counts.items() if count == highest]
    return winners[0].upper() if len(winners) == 1 else "?"


def e_return_first_tied_letter(text: str) -> str:
    counts = Counter(text.strip().upper())
    highest = max(counts.values())
    return next(letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if counts[letter] == highest)


def _f_parts(text: str) -> tuple[set[int], list[int]]:
    lines = text.splitlines()
    return set(map(int, lines[1].split())), list(map(int, lines[3].split()))


def f_remove_after_query(text: str) -> str:
    registrations, queries = _f_parts(text)
    answers: list[str] = []
    for value in queries:
        answers.append("1" if value in registrations else "0")
        registrations.discard(value)
    return "\n".join(answers)


def f_ignore_nonpositive_numbers(text: str) -> str:
    registrations, queries = _f_parts(text)
    positive_registrations = {value for value in registrations if value > 0}
    return "\n".join("1" if value in positive_registrations else "0" for value in queries)


def _g_values(text: str) -> list[int]:
    return list(map(int, text.splitlines()[1].split()))


def g_keep_input_order(text: str) -> str:
    elapsed = 0
    total = 0
    for processing_time in _g_values(text):
        elapsed += processing_time
        total += elapsed
    return str(total)


def g_sum_processing_times_only(text: str) -> str:
    return str(sum(_g_values(text)))


def _h_grid(text: str) -> tuple[int, int, list[str]]:
    lines = text.splitlines()
    rows, columns = map(int, lines[0].split())
    return rows, columns, lines[1:]


def _h_shortest_distance(rows: int, columns: int, grid: list[str], directions: tuple[tuple[int, int], ...]) -> int:
    queue = deque([0])
    distances = [-1] * (rows * columns)
    distances[0] = 1
    while queue:
        current = queue.popleft()
        row, column = divmod(current, columns)
        for row_step, column_step in directions:
            next_row = row + row_step
            next_column = column + column_step
            if not (0 <= next_row < rows and 0 <= next_column < columns):
                continue
            following = next_row * columns + next_column
            if grid[next_row][next_column] == "1" and distances[following] == -1:
                distances[following] = distances[current] + 1
                queue.append(following)
    return distances[-1]


def h_count_moves_not_cells(text: str) -> str:
    rows, columns, grid = _h_grid(text)
    cells = _h_shortest_distance(rows, columns, grid, ((-1, 0), (1, 0), (0, -1), (0, 1)))
    return str(cells - 1)


def h_only_moves_right_or_down(text: str) -> str:
    rows, columns, grid = _h_grid(text)
    return str(_h_shortest_distance(rows, columns, grid, ((1, 0), (0, 1))))


def _i_grid(text: str) -> tuple[int, int, list[int]]:
    lines = text.splitlines()
    columns, rows = map(int, lines[0].split())
    return columns, rows, [int(value) for line in lines[1:] for value in line.split()]


def _i_layered_days(columns: int, rows: int, original: list[int], sources: list[int]) -> int:
    cells = original.copy()
    remaining = cells.count(0)
    if remaining == 0:
        return 0
    if not sources:
        return -1

    queue = deque(sources)
    days = 0
    while queue and remaining:
        for _ in range(len(queue)):
            current = queue.popleft()
            row, column = divmod(current, columns)
            for next_row, next_column in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
                if not (0 <= next_row < rows and 0 <= next_column < columns):
                    continue
                following = next_row * columns + next_column
                if cells[following] == 0:
                    cells[following] = 1
                    remaining -= 1
                    queue.append(following)
        days += 1
    return days if remaining == 0 else -1


def i_single_initial_source(text: str) -> str:
    columns, rows, cells = _i_grid(text)
    sources = [index for index, value in enumerate(cells) if value == 1]
    return str(_i_layered_days(columns, rows, cells, sources[:1]))


def i_allow_same_day_chain(text: str) -> str:
    columns, rows, cells = _i_grid(text)
    queue = deque(index for index, value in enumerate(cells) if value == 1)
    remaining = cells.count(0)
    if remaining == 0:
        return "0"
    if not queue:
        return "-1"

    while queue:
        current = queue.popleft()
        row, column = divmod(current, columns)
        for next_row, next_column in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
            if not (0 <= next_row < rows and 0 <= next_column < columns):
                continue
            following = next_row * columns + next_column
            if cells[following] == 0:
                cells[following] = 1
                remaining -= 1
                queue.append(following)
    return "0" if remaining == 0 else "-1"


MUTANTS: Final[dict[str, tuple[Mutant, ...]]] = {
    "A": (
        Mutant("A", "subtract_groups", "arithmetic", "Subtracts the two group counts.", a_subtract_groups),
        Mutant("A", "multiply_groups", "arithmetic", "Multiplies the group counts.", a_multiply_groups),
    ),
    "B": (
        Mutant("B", "pair_before_triple", "branch_order", "Handles a pair before checking three equal cards.", b_pair_before_triple),
        Mutant("B", "middle_card_when_distinct", "wrong_statistic", "Uses the middle input card instead of the largest distinct card.", b_middle_card_when_distinct),
    ),
    "C": (
        Mutant("C", "zero_initialized_extrema", "initialization", "Initializes both extrema to zero.", c_zero_initialized_extrema),
        Mutant("C", "assume_input_extrema_order", "ordering_assumption", "Treats the first and last records as the extrema.", c_assume_input_extrema_order),
    ),
    "D": (
        Mutant("D", "repeat_whole_phrase", "repeat_scope", "Repeats each complete phrase rather than every character.", d_repeat_whole_phrase),
        Mutant("D", "ignore_repeat_count", "ignored_input", "Outputs each phrase once regardless of R.", d_ignore_repeat_count),
    ),
    "E": (
        Mutant("E", "case_sensitive_counts", "normalization", "Counts lowercase and uppercase letters separately.", e_case_sensitive_counts),
        Mutant("E", "return_first_tied_letter", "tie_handling", "Returns one tied letter instead of a question mark.", e_return_first_tied_letter),
    ),
    "F": (
        Mutant("F", "remove_after_query", "state_mutation", "Deletes a registration after answering a query.", f_remove_after_query),
        Mutant("F", "ignore_nonpositive_numbers", "domain_assumption", "Excludes zero and negative registration numbers.", f_ignore_nonpositive_numbers),
    ),
    "G": (
        Mutant("G", "keep_input_order", "missing_optimization", "Uses the supplied order without sorting.", g_keep_input_order),
        Mutant("G", "sum_processing_times_only", "objective_misread", "Sums service times but omits waiting time.", g_sum_processing_times_only),
    ),
    "H": (
        Mutant("H", "count_moves_not_cells", "off_by_one", "Reports moves instead of visited cells.", h_count_moves_not_cells),
        Mutant("H", "only_moves_right_or_down", "incomplete_search", "Never explores leftward or upward moves.", h_only_moves_right_or_down),
    ),
    "I": (
        Mutant("I", "single_initial_source", "missing_sources", "Starts propagation from only the first installed computer.", i_single_initial_source),
        Mutant("I", "allow_same_day_chain", "synchronization", "Lets a newly updated computer transmit on the same day.", i_allow_same_day_chain),
    ),
}


def iter_mutants() -> Iterator[Mutant]:
    """Yield every A--I mutant in statement-letter order."""

    for letter in SUPPORTED_LETTERS:
        yield from MUTANTS[letter]


def solve_mutant(letter: str, identifier: str, text: str) -> str:
    """Validate a statement input and run one named incorrect strategy offline."""

    if letter not in SUPPORTED_LETTERS:
        raise ValueError(f"letter must be one of {', '.join(SUPPORTED_LETTERS)}")
    validate(letter, text)
    for mutant in MUTANTS[letter]:
        if mutant.identifier == identifier:
            return mutant.solve(text)
    raise ValueError(f"unknown {letter} mutant: {identifier}")


__all__ = ["MUTANTS", "Mutant", "iter_mutants", "solve_mutant"]
