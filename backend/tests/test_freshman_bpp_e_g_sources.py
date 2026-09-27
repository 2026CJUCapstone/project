"""Validate the standalone B++ references for freshman-contest problems E--G."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Final

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DIRECTORY = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(TEST_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(TEST_DIRECTORY))

from test_freshman_bpp_a_d_sources import (
    COMPILE_TIMEOUT_SECONDS,
    RUN_TIMEOUT_SECONDS,
    _compile_to_assembly,
    _configured_toolchain,
    _run,
    _statement_examples,
)
from tools.freshman_contest.a_i import generate, solve


LETTERS: Final = ("E", "F", "G")
SOURCE_DIRECTORY = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "bpp"
EXPECTED_SOURCE_NAMES = {f"{letter}.bpp" for letter in LETTERS}
STATEMENT_SAMPLE_COUNT: Final = 7


def _maximum_contract_cases() -> list[tuple[str, str, str]]:
    registrations = " ".join(f"+{value}" for value in range(100_000, 0, -1))
    return [
        ("E", "Z" * 1_000_000 + "\n", "Z"),
        (
            "F",
            "+100000\r\n" + registrations + "\r\n+3\n+1 +100000 +100001\n",
            "1\n1\n0",
        ),
        ("G", "+1000\n" + " ".join(["+1000"] * 1000) + "\n", "500500000"),
    ]


def test_bpp_e_g_source_inventory_is_complete() -> None:
    assert EXPECTED_SOURCE_NAMES <= {path.name for path in SOURCE_DIRECTORY.glob("*.bpp")}


def test_bpp_e_g_references_match_examples_generated_and_maximum_contract_cases(tmp_path: Path) -> None:
    toolchain = _configured_toolchain()
    if toolchain is None:
        pytest.skip(
            "B++ Windows toolchain is not configured; set BPP_COMPILER, BPP_NASM, and BPP_LINKER to run it."
        )
    compiler, compiler_root, nasm, linker, kernel32 = toolchain

    executables: dict[str, Path] = {}
    for letter in LETTERS:
        source = SOURCE_DIRECTORY / f"{letter}.bpp"
        assembly = tmp_path / f"freshman_{letter}.asm"
        object_file = tmp_path / f"freshman_{letter}.obj"
        executable = tmp_path / f"freshman_{letter}.exe"
        _compile_to_assembly(compiler, compiler_root, source, assembly)
        assembly_result = _run(
            [str(nasm), "-f", "win64", "-O1", str(assembly), "-o", str(object_file)],
            cwd=compiler_root,
            input_text=None,
            timeout=COMPILE_TIMEOUT_SECONDS,
        )
        assert assembly_result.returncode == 0, assembly_result.stderr.decode("utf-8", errors="replace")
        link_result = _run(
            [
                str(linker),
                "/nologo",
                "/Brepro",
                "/subsystem:console",
                "/entry:mainCRTStartup",
                f"/out:{executable}",
                str(object_file),
                str(kernel32),
            ],
            cwd=compiler_root,
            input_text=None,
            timeout=COMPILE_TIMEOUT_SECONDS,
        )
        assert link_result.returncode == 0, link_result.stderr.decode("utf-8", errors="replace")
        executables[letter] = executable

    cases: list[tuple[str, str, str]] = []
    sample_count = 0
    generated_count = 0
    for letter in LETTERS:
        examples = _statement_examples(letter)
        sample_count += len(examples)
        cases.extend((letter, text, expected) for text, expected in examples)
        generated = generate(letter, seed=1847)
        generated_count += len(generated)
        cases.extend((letter, text, solve(letter, text)) for text in generated)

    cases.extend(
        [
            ("F", "+4\r\n+7 \t-2 +0 +7\n+5\r\n+7 +1 -2 +0 +7\n", "1\n0\n1\n1\n1"),
            ("G", "+4\r\n+4\t+1 +3 +2\n", "20"),
        ]
    )
    cases.extend(_maximum_contract_cases())

    assert sample_count == STATEMENT_SAMPLE_COUNT
    assert generated_count > 0
    for letter, text, expected in cases:
        result = _run([str(executables[letter])], cwd=tmp_path, input_text=text, timeout=RUN_TIMEOUT_SECONDS)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").rstrip("\n")
        assert actual == expected, f"{letter} produced {actual!r} for input {text!r}; expected {expected!r}"
