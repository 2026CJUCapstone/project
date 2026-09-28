from collections import deque
import sys


tokens = sys.stdin.buffer.read().split()
rows = int(tokens[0])
columns = int(tokens[1])
grid = tokens[2:rows + 2]

distances = [-1] * (rows * columns)
distances[0] = 1
queue = deque([0])
while queue:
    current = queue.popleft()
    if current == rows * columns - 1:
        break
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
        if grid[next_row][next_column] == ord("1") and distances[following] == -1:
            distances[following] = distances[current] + 1
            queue.append(following)

print(distances[-1])
