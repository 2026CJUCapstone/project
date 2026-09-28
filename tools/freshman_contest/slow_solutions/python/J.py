"""Correct quadratic J formula for bounded limit-separation probes only.

It implements the pair formula proved in docs/banks-reference-proof-2026-09-26.md,
without importing or calling the fast Fenwick reference.  Never package it as
a reference solution or publish it to contestants.
"""

import sys


def solve(text: str) -> str:
    values = list(map(int, text.split()))
    balances = values[1:]
    total = sum(balances)
    prefixes = []
    running = 0
    for balance in balances:
        prefixes.append(running)
        running += balance
    answer = 0
    for right, current in enumerate(prefixes):
        for left in range(right):
            earlier = prefixes[left]
            answer += (abs(current - earlier) + total - 1) // total
            if earlier < current:
                answer -= 1
    return str(answer)


if __name__ == "__main__":
    sys.stdout.write(solve(sys.stdin.buffer.read().decode()))
