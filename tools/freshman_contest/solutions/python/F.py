import sys


tokens = sys.stdin.buffer.read().split()
position = 0
registration_count = int(tokens[position])
position += 1
registrations = {int(token) for token in tokens[position:position + registration_count]}
position += registration_count
query_count = int(tokens[position])
position += 1
answers = ["1" if int(token) in registrations else "0" for token in tokens[position:position + query_count]]
sys.stdout.write("\n".join(answers) + "\n")
