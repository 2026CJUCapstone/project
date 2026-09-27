import sys


class Fenwick:
    def __init__(self, size):
        self.tree = [0] * (size + 1)

    def add(self, index):
        index += 1
        while index < len(self.tree):
            self.tree[index] += 1
            index += index & -index

    def before(self, index):
        result = 0
        while index:
            result += self.tree[index]
            index -= index & -index
        return result


tokens = sys.stdin.buffer.read().split()
count = int(tokens[0])
prefixes = []
total = 0
for token in tokens[1:count + 1]:
    prefixes.append(total)
    total += int(token)

remainders = sorted({value % total for value in prefixes})
remainder_ranks = {value: index for index, value in enumerate(remainders)}
counts = Fenwick(len(remainders))
quotient_sum = 0
answer = 0
for index, value in enumerate(sorted(prefixes)):
    quotient, remainder = divmod(value, total)
    rank = remainder_ranks[remainder]
    answer += index * quotient - quotient_sum + counts.before(rank)
    quotient_sum += quotient
    counts.add(rank)

prefix_values = sorted(set(prefixes))
prefix_ranks = {value: index for index, value in enumerate(prefix_values)}
counts = Fenwick(len(prefix_values))
for value in prefixes:
    rank = prefix_ranks[value]
    answer -= counts.before(rank)
    counts.add(rank)

print(answer)
