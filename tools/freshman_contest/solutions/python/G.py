import sys


tokens = sys.stdin.buffer.read().split()
count = int(tokens[0])
elapsed = 0
total = 0
for processing_time in sorted(int(token) for token in tokens[1:count + 1]):
    elapsed += processing_time
    total += elapsed
print(total)
