from collections import deque
from itertools import product
from pathlib import Path
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.freshman_contest import banks


def brute(start):
    queue, seen = deque([(tuple(start), 0)]), {tuple(start)}
    while queue:
        state, depth = queue.popleft()
        if min(state) >= 0:
            return depth
        assert depth < 100 and len(seen) < 100000
        for index, value in enumerate(state):
            if value >= 0:
                continue
            updated = list(state)
            updated[index] = -value
            updated[(index - 1) % len(state)] += value
            updated[(index + 1) % len(state)] += value
            next_state = tuple(updated)
            if next_state not in seen:
                seen.add(next_state)
                queue.append((next_state, depth + 1))
    raise AssertionError('No reachable terminal state')


def quadratic(values):
    total, prefixes, value = sum(values), [], 0
    for delta in values:
        prefixes.append(value)
        value += delta
    answer = 0
    for index, left in enumerate(prefixes):
        for right in prefixes[index + 1:]:
            if left > right:
                answer += (left - right + total - 1) // total
            elif left < right:
                answer += (right - left - 1) // total
    return answer


def test_exhaustive_small_against_independent_minimum_search():
    for size in range(1, 5):
        for values in product(range(-2, 3), repeat=size):
            if sum(values) > 0:
                assert banks.minimum_moves(values) == brute(values), values


def test_random_quadratic_and_metamorphic_cases():
    rng = random.Random(26350)
    for _ in range(150):
        values = [rng.randint(-20, 20) for _ in range(rng.randint(1, 40))]
        values.append(max(1, 1 - sum(values)))
        expected = quadratic(values)
        assert banks.minimum_moves(values) == expected
        assert banks.minimum_moves(values[::-1]) == expected
        assert banks.minimum_moves(values[1:] + values[:1]) == expected
        assert banks.minimum_moves([value * 7 for value in values]) == expected


@pytest.mark.parametrize('text', ['0\n', '2\n-1 1', '1\n32000', '2\n1', '1\n1 2', '1\n1.0', '1\n١'])
def test_invalid(text):
    with pytest.raises(ValueError):
        banks.validate(text)


def test_generators_maximum_size_and_samples():
    assert banks.generate(42) == banks.generate(42)
    for text in banks.generate(42):
        banks.validate(text)
        assert 0 <= int(banks.solve(text)) < 2**63
    assert banks.solve('4\n2 -1 -1 1\n') == '5'
    assert banks.solve('2\n5 -3\n') == '2'
