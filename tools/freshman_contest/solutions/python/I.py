from collections import deque
import sys


values = [int(token) for token in sys.stdin.buffer.read().split()]
columns, rows = values[:2]
cells = values[2:]
queue = deque(index for index, value in enumerate(cells) if value == 1)
remaining = cells.count(0)

if remaining == 0:
    print(0)
elif not queue:
    print(-1)
else:
    days = 0
    while queue and remaining:
        for _ in range(len(queue)):
            current = queue.popleft()
            row, column = divmod(current, columns)
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
    print(days if remaining == 0 else -1)
