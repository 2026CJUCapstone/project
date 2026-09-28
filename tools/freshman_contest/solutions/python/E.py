import sys


text = sys.stdin.buffer.read().split()[0].upper()
counts = [0] * 26
for character in text:
    counts[character - ord("A")] += 1

highest_count = max(counts)
if counts.count(highest_count) != 1:
    print("?")
else:
    print(chr(ord("A") + counts.index(highest_count)))
