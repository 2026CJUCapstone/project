import sys


values = [int(token) for token in sys.stdin.buffer.read().split()]
print(values[0] + values[1])
