import sys


values = [int(token) for token in sys.stdin.buffer.read().split()]
counts = [0] * 7
for value in values[:3]:
    counts[value] += 1

highest_count = max(counts[1:])
repeated_value = max(value for value in range(1, 7) if counts[value] == highest_count)
if highest_count == 3:
    print(10_000 + repeated_value * 1_000)
elif highest_count == 2:
    print(1_000 + repeated_value * 100)
else:
    print(repeated_value * 100)
