import sys


tokens = sys.stdin.buffer.read().split()
case_count = int(tokens[0])
position = 1
answers = []
for _ in range(case_count):
    repeats = int(tokens[position])
    phrase = tokens[position + 1]
    position += 2
    answers.append(b"".join(bytes((character,)) * repeats for character in phrase))

sys.stdout.buffer.write(b"\n".join(answers) + b"\n")
