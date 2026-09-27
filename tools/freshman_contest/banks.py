"""Independently derived O(n log n) reference for J (periodic inversions).

See docs/banks-reference-proof-2026-09-26.md. No external solution/code copied.
This is an offline authoring reference, not a six-runtime benchmark or license approval.
"""
from bisect import bisect_left
import random
import re


class Fenwick:
    def __init__(self, size):
        self.tree = [0] * (size + 1)

    def add(self, index):
        index += 1
        while index < len(self.tree):
            self.tree[index] += 1
            index += index & -index

    def before(self, index):
        result = 0
        while index:
            result += self.tree[index]
            index -= index & -index
        return result


def parse(text):
    tokens = text.split()
    if not tokens or any(not re.fullmatch(r'[+-]?[0-9]+', token) or len(token) > 8 for token in tokens):
        raise ValueError('Expected bounded decimal integer tokens')
    count = int(tokens[0])
    if not 1 <= count < 10000 or len(tokens) != count + 1:
        raise ValueError('Expected N in 1..9999 and exactly N balances')
    balances = [int(value) for value in tokens[1:]]
    if any(not -32000 < value < 32000 for value in balances) or sum(balances) <= 0:
        raise ValueError('Balances must be in -31999..31999 with positive total')
    return balances


def validate(text):
    parse(text)


def minimum_moves(balances):
    total = sum(balances)
    if not balances or total <= 0:
        raise ValueError('Positive total required')
    prefixes, current = [], 0
    for value in balances:
        prefixes.append(current)
        current += value

    # Sum ceil(abs(x-y)/total) for unordered pairs. Sorted x<=y means
    # ceil((y-x)/total) = q_y-q_x + [r_y > r_x].
    remainders = sorted({value % total for value in prefixes})
    counts = Fenwick(len(remainders))
    quotient_sum, answer = 0, 0
    for index, value in enumerate(sorted(prefixes)):
        quotient, remainder = divmod(value, total)
        rank = bisect_left(remainders, remainder)
        answer += index * quotient - quotient_sum + counts.before(rank)
        quotient_sum += quotient
        counts.add(rank)

    # For original-order pairs x<y, subtract one. Equal prefix values
    # contribute zero and must not count as increasing pairs.
    values = sorted(set(prefixes))
    counts = Fenwick(len(values))
    for value in prefixes:
        rank = bisect_left(values, value)
        answer -= counts.before(rank)
        counts.add(rank)
    return answer


def solve(text):
    return str(minimum_moves(parse(text)))


def generate(seed=0):
    rng = random.Random(seed)
    cases = [[7], [0, 1, 0], [-31999, 31999, 1], [5, -3],
             [2, -1, -1, 1], [31999] * 4999 + [-31999] * 4999 + [1]]
    for count in (2, 3, 8, 31, 100):
        values = [rng.randint(-20, 20) for _ in range(count - 1)]
        values.append(1 - sum(values))
        cases.append(values)
    return [f'{len(values)}\n' + ' '.join(map(str, values)) + '\n' for values in cases]
