"""Cross-language J checks, including mathematical floor and large 64-bit counts."""
import random

import pytest

from tests.test_freshman_cpp_sources import _find_cpp_compiler, _run, _statement_examples, SOURCE_DIRECTORY
from tools.freshman_contest.banks import generate, solve


def test_banks_cpp17_matches_checked_python_reference(tmp_path):
    compiler = _find_cpp_compiler()
    if compiler is None:
        pytest.skip('No installed C++ compiler on PATH; no installation requested')
    executable = tmp_path / 'banks-reference'
    built = _run([compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-pedantic',
                  str(SOURCE_DIRECTORY / 'J.cpp'), '-o', str(executable)], input_text=None, timeout=20)
    assert built.returncode == 0, built.stderr.decode(errors='replace')
    cases = _statement_examples('J')
    for seed in (0, 73, 1926):
        cases.extend((text, solve(text)) for text in generate(seed))
    rng = random.Random(10350)
    for _ in range(50):
        n = rng.randrange(2, 35)
        values = [rng.randrange(-100, 101) for _ in range(n - 1)]
        values.append(1 - sum(values))
        text = f'{n}\n' + ' '.join(map(str, values)) + '\n'
        cases.append((text, solve(text)))
    # Negative-prefix remainder must use floor, not truncating integer division.
    for text in ('3\n-7 3 7\n', '4\n-15 5 8 6\n'):
        cases.append((text, solve(text)))
    assert len(cases) == 89
    assert max(int(expected) for _, expected in cases) > 2**31
    for text, expected in cases:
        result = _run([str(executable)], input_text=text, timeout=2)
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        assert result.stdout.decode().strip() == expected
