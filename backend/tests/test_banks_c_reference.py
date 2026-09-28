"""Cross-check the offline C17 J reference against the proved Python oracle.

This is a function-correctness comparison only; it does not measure judge time or
memory limits.
"""

from __future__ import annotations

from pathlib import Path
import random
import shutil
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.test_freshman_cpp_sources import _run, _statement_examples
from tools.freshman_contest.banks import generate, solve


SOURCE = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "c" / "J.c"
COMPILE_TIMEOUT_SECONDS = 20
RUN_TIMEOUT_SECONDS = 2


def _find_c_compiler() -> str | None:
    for candidate in ("gcc", "C:/mingw64/bin/gcc.exe"):
        compiler = shutil.which(candidate)
        if compiler:
            return compiler
    return None


def test_banks_c17_matches_checked_python_reference(tmp_path: Path) -> None:
    """Use only a C compiler already on PATH; no compiler installation occurs."""

    compiler = _find_c_compiler()
    if compiler is None:
        pytest.skip("No local gcc compiler is available on PATH.")
    executable = tmp_path / "banks-reference"
    compilation = _run(
        [compiler, "-std=c17", "-O2", "-Wall", "-Wextra", "-pedantic", str(SOURCE), "-o", str(executable)],
        input_text=None,
        timeout=COMPILE_TIMEOUT_SECONDS,
    )
    assert compilation.returncode == 0, compilation.stderr.decode("utf-8", errors="replace")

    cases = _statement_examples("J")
    for seed in (0, 73, 1926):
        cases.extend((text, solve(text)) for text in generate(seed))
    rng = random.Random(10350)
    for _ in range(50):
        count = rng.randrange(2, 35)
        values = [rng.randrange(-100, 101) for _ in range(count - 1)]
        values.append(1 - sum(values))
        text = f"{count}\n" + " ".join(map(str, values)) + "\n"
        cases.append((text, solve(text)))
    # C division truncates toward zero, so the reference must explicitly floor negative prefixes.
    for text in ("3\n-7 3 7\n", "4\n-15 5 8 6\n"):
        cases.append((text, solve(text)))

    assert len(cases) == 89
    assert max(len(text.split()) - 1 for text, _ in cases) == 9_999
    assert max(int(expected) for _, expected in cases) > 2**31
    for text, expected in cases:
        result = _run([str(executable)], input_text=text, timeout=RUN_TIMEOUT_SECONDS)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").strip()
        assert actual == expected
