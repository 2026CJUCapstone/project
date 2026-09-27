import sys


tokens = sys.stdin.buffer.read().split()
count = int(tokens[0])
values = [int(token) for token in tokens[1:count + 1]]
print(min(values), max(values))
