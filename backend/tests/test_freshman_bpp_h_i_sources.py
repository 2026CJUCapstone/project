"""Validate the standalone B++ references for freshman-contest problems H and I."""

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


LETTERS: Final = ("H", "I")
SOURCE_DIRECTORY = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "bpp"
EXPECTED_SOURCE_NAMES = {f"{letter}.bpp" for letter in LETTERS}
STATEMENT_SAMPLE_COUNT: Final = 6


def _maximum_contract_cases() -> list[tuple[str, str, str]]:
    open_h_grid = "\n".join(["1" * 100] * 100)
    all_ripe_row = " ".join(["+1"] * 1000)
    all_ripe_i_grid = "\n".join([all_ripe_row] * 1000)
    return [
        ("H", "+100\t+100\n" + open_h_grid + "\n", "199"),
        ("I", "+1000 +1000\n" + all_ripe_i_grid + "\n", "0"),
    ]


def test_bpp_h_i_source_inventory_is_complete() -> None:
    assert EXPECTED_SOURCE_NAMES <= {path.name for path in SOURCE_DIRECTORY.glob("*.bpp")}


def test_bpp_h_i_references_match_examples_generated_and_maximum_contract_cases(tmp_path: Path) -> None:
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
        for seed in (71, 1847):
            generated = generate(letter, seed=seed)
            generated_count += len(generated)
            cases.extend((letter, text, solve(letter, text)) for text in generated)

    cases.extend(
        [
            ("H", "+2\t+2\r\n11\r\n11\n", "3"),
            ("I", "+3\t+3\r\n+1 +0 +0\n+0 +0 +0\n+0 +0 +0\n", "4"),
            ("I", "+3 +2\n+1 -1 +0\n+0 -1 +0\n", "-1"),
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
