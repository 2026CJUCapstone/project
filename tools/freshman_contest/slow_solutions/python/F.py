"""Correct but deliberately O(NM) F submission for limit separation only.

Never package this as a reference solution or publish it to contestants.
"""

import sys


def solve(text: str) -> str:
    values = list(map(int, text.split()))
    n = values[0]
    registrations = values[1 : n + 1]
    m = values[n + 1]
    queries = values[n + 2 : n + 2 + m]
    answers = []
    for query in queries:
        found = False
        for registration in registrations:
            if registration == query:
                found = True
                break
        answers.append("1" if found else "0")
    return "\n".join(answers)


if __name__ == "__main__":
    sys.stdout.write(solve(sys.stdin.buffer.read().decode()))
