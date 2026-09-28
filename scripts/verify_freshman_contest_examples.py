"""Check the A-J Markdown examples only; not a judge or performance test."""

from collections import Counter, deque
from itertools import permutations
from pathlib import Path
import re


DOCUMENT = Path(__file__).resolve().parents[1] / "docs/freshman-contest-statements-a-i-2026-09-26.md"
EXPECTED_COUNTS = dict(zip("ABCDEFGHIJ", (2, 3, 2, 2, 3, 2, 2, 2, 4, 4)))


def banks_min_moves(start: tuple[int, ...]) -> int:
    """Bounded exhaustive oracle for tiny samples, never a production solver."""
    assert 1 <= len(start) <= 8 and sum(start) > 0
    assert all(-32000 < value < 32000 for value in start)
    queue = deque([(start, 0)])
    seen = {start}
    while queue:
        state, depth = queue.popleft()
        if all(value >= 0 for value in state):
            return depth
        if depth >= 64:
            raise AssertionError("Sample oracle depth budget exceeded")
        for i, value in enumerate(state):
            if value >= 0:
                continue
            updated = list(state)
            updated[i] = -value
            # Keep two assignments: with N=2 they must hit the same neighbor twice.
            updated[(i - 1) % len(state)] += value
            updated[(i + 1) % len(state)] += value
            following = tuple(updated)
            assert sum(following) == sum(start)
            if following not in seen:
                seen.add(following)
                if len(seen) > 100_000:
                    raise AssertionError("Sample oracle state budget exceeded")
                queue.append((following, depth + 1))
    raise AssertionError("No reachable target in sample")


def calculate(problem: str, source: str) -> str:
    tokens = source.split()
    if problem == "A":
        return str(sum(map(int, tokens)))
    if problem == "B":
        counts = Counter(map(int, tokens))
        value, count = counts.most_common(1)[0]
        if count == 3:
            return str(10000 + value * 1000)
        if count == 2:
            return str(1000 + value * 100)
        return str(max(counts) * 100)
    if problem == "C":
        values = list(map(int, tokens[1:]))
        assert len(values) == int(tokens[0])
        return f"{min(values)} {max(values)}"
    if problem == "D":
        count = int(tokens[0])
        assert len(tokens) == 1 + 2 * count
        return "\n".join(
            "".join(letter * int(tokens[1 + i * 2]) for letter in tokens[2 + i * 2])
            for i in range(count)
        )
    if problem == "E":
        counts = Counter(tokens[0].upper())
        winners = [letter for letter, count in counts.items() if count == max(counts.values())]
        return winners[0] if len(winners) == 1 else "?"
    if problem == "F":
        n = int(tokens[0])
        values = set(map(int, tokens[1:n + 1]))
        m = int(tokens[n + 1])
        queries = list(map(int, tokens[n + 2:]))
        assert len(queries) == m
        return "\n".join(str(int(value in values)) for value in queries)
    if problem == "G":
        values = list(map(int, tokens[1:]))
        assert len(values) == int(tokens[0])
        # Tiny statement samples: enumerate all orders, independent of greedy proof.
        assert len(values) <= 8
        return str(min(sum(sum(order[:i + 1]) for i in range(len(order))) for order in permutations(values)))
    if problem == "H":
        n, m = map(int, tokens[:2])
        grid = tokens[2:]
        assert len(grid) == n and all(len(row) == m for row in grid)
        queue = deque([(0, 0, 1)])
        visited = {(0, 0)}
        while queue:
            r, c, distance = queue.popleft()
            if (r, c) == (n - 1, m - 1):
                return str(distance)
            for nr, nc in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if 0 <= nr < n and 0 <= nc < m and grid[nr][nc] == "1" and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append((nr, nc, distance + 1))
        raise AssertionError("H requires a reachable destination")
    if problem == "I":
        m, n = map(int, tokens[:2])
        values = list(map(int, tokens[2:]))
        assert len(values) == m * n
        grid = [values[r * m:(r + 1) * m] for r in range(n)]
        # Independent synchronous simulation, not the intended multi-source BFS.
        days = 0
        while any(0 in row for row in grid):
            changes = []
            for r in range(n):
                for c in range(m):
                    if grid[r][c] != 0:
                        continue
                    neighbors = ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))
                    if any(0 <= nr < n and 0 <= nc < m and grid[nr][nc] == 1 for nr, nc in neighbors):
                        changes.append((r, c))
            if not changes:
                return "-1"
            for r, c in changes:
                grid[r][c] = 1
            days += 1
        return str(days)
    if problem == "J":
        values = tuple(map(int, tokens[1:]))
        assert len(values) == int(tokens[0])
        return str(banks_min_moves(values))
    raise AssertionError(f"Unexpected problem {problem}")


def main() -> None:
    document = DOCUMENT.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ([A-J])\. .+$", document)
    assert sections[1::2] == list(EXPECTED_COUNTS)
    total = 0
    for problem, content in zip(sections[1::2], sections[2::2]):
        blocks = re.findall(r"~~~text\n(.*?)\n~~~", content, flags=re.S)
        assert len(blocks) == EXPECTED_COUNTS[problem] * 2
        for index in range(0, len(blocks), 2):
            actual = calculate(problem, blocks[index])
            expected = blocks[index + 1].strip()
            assert actual == expected, f"{problem} sample {index // 2 + 1}: {actual!r} != {expected!r}"
            total += 1
        print(f"{problem}: {EXPECTED_COUNTS[problem]} examples PASS")
    assert total == 26
    print(f"TOTAL: {total} examples PASS (local statement calculations only)")
    checks = 0
    for seed, expected in (((2, -1, 2), 1), ((2, -1, -1, 1), 5), ((5, -3), 2), ((7,), 0)):
        variants = set()
        for direction in (seed, seed[::-1]):
            for offset in range(len(seed)):
                rotated = direction[offset:] + direction[:offset]
                for factor in (1, 2, 3):
                    variants.add(tuple(value * factor for value in rotated))
        for variant in variants:
            assert banks_min_moves(variant) == expected, variant
            checks += 1
    assert banks_min_moves((0, 1, 0)) == 0
    print(f"J: {checks} rotated/reversed/scaled tiny cases and nonnegative zero case PASS")


if __name__ == "__main__":
    main()
