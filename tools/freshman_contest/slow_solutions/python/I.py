"""Correct but deliberately front-deleting I BFS for limit separation only.

Never package this as a reference solution or publish it to contestants.
"""

import sys


def solve(text: str) -> str:
    values = list(map(int, text.split()))
    columns, rows = values[:2]
    cells = values[2:]
    queue = [index for index, value in enumerate(cells) if value == 1]
    remaining = cells.count(0)
    if remaining == 0:
        return "0"
    if not queue:
        return "-1"
    days = 0
    while queue and remaining:
        frontier = len(queue)
        for _ in range(frontier):
            position = queue.pop(0)
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


if __name__ == "__main__":
    sys.stdout.write(solve(sys.stdin.buffer.read().decode()))
