"""Validate the standalone B++ references for freshman-contest problems A--D.

The B++ compiler is an optional, separately maintained Windows toolchain.  The
source inventory is always checked; compilation and execution run only when a
local toolchain is explicitly configured with ``BPP_COMPILER``.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Final

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.freshman_contest.a_i import generate, solve


LETTERS: Final = ("A", "B", "C", "D")
STATEMENTS = PROJECT_ROOT / "docs" / "freshman-contest-statements-a-i-2026-09-26.md"
SOURCE_DIRECTORY = PROJECT_ROOT / "tools" / "freshman_contest" / "solutions" / "bpp"
EXPECTED_SOURCE_NAMES = {f"{letter}.bpp" for letter in LETTERS}
MAX_OUTPUT_BYTES: Final = 16 * 1024
MAX_ASSEMBLY_BYTES: Final = 8 * 1024 * 1024
COMPILE_TIMEOUT_SECONDS: Final = 20
RUN_TIMEOUT_SECONDS: Final = 2
STATEMENT_SAMPLE_COUNT: Final = 9


def _statement_examples(letter: str) -> list[tuple[str, str]]:
    document = STATEMENTS.read_text(encoding="utf-8")
    section = re.search(rf"(?ms)^## {letter}\. .+?(?=^## [A-J]\. |^---\s*$)", document)
    assert section is not None, f"missing {letter} statement section"
    blocks = re.findall(r"~~~text\n(.*?)\n~~~", section.group(0), flags=re.S)
    assert len(blocks) % 2 == 0
    return [(blocks[index], blocks[index + 1].strip()) for index in range(0, len(blocks), 2)]


def _drain_stream(
    stream: object,
    captured: bytearray,
    limit_exceeded: threading.Event,
    process: subprocess.Popen[bytes],
) -> None:
    readable = stream
    while chunk := readable.read(4096):  # type: ignore[union-attr]
        available = MAX_OUTPUT_BYTES - len(captured)
        if available > 0:
            captured.extend(chunk[:available])
        if len(chunk) > available:
            limit_exceeded.set()
            try:
                process.kill()
            except ProcessLookupError:
                pass


def _drain_assembly(
    stream: object,
    destination: Path,
    limit_exceeded: threading.Event,
    process: subprocess.Popen[bytes],
) -> None:
    readable = stream
    total = 0
    with destination.open("wb") as output:
        while chunk := readable.read(4096):  # type: ignore[union-attr]
            available = MAX_ASSEMBLY_BYTES - total
            if available > 0:
                output.write(chunk[:available])
                total += min(len(chunk), available)
            if len(chunk) > available:
                limit_exceeded.set()
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                return


def _feed_stdin(stream: object, data: bytes) -> None:
    writable = stream
    try:
        writable.write(data)  # type: ignore[union-attr]
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            writable.close()  # type: ignore[union-attr]
        except (OSError, ValueError):
            pass


def _join_threads(threads: list[threading.Thread]) -> None:
    for thread in threads:
        thread.join(timeout=1)
    assert not any(thread.is_alive() for thread in threads), "process I/O worker did not terminate"


def _run(
    command: list[str],
    *,
    cwd: Path,
    input_text: str | None,
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL if input_text is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    deadline = time.monotonic() + timeout
    standard_output = bytearray()
    standard_error = bytearray()
    output_limit_exceeded = threading.Event()
    output_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stdout, standard_output, output_limit_exceeded, process),
    )
    error_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stderr, standard_error, output_limit_exceeded, process),
    )
    output_thread.start()
    error_thread.start()
    workers = [output_thread, error_thread]
    if input_text is not None:
        assert process.stdin is not None
        input_thread = threading.Thread(target=_feed_stdin, args=(process.stdin, input_text.encode("utf-8")), daemon=True)
        input_thread.start()
        workers.append(input_thread)
    try:
        remaining = deadline - time.monotonic()
        return_code = process.wait(timeout=max(remaining, 0))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        pytest.fail(f"process exceeded its {timeout}-second time cap: {command!r}")
    finally:
        if process.stdin is not None and not process.stdin.closed:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
        _join_threads(workers)
    assert not output_limit_exceeded.is_set(), "reference process exceeded the output cap"
    return subprocess.CompletedProcess(command, return_code, bytes(standard_output), bytes(standard_error))


def _find_kernel32_library() -> Path | None:
    configured = os.environ.get("BPP_KERNEL32_LIB")
    if configured:
        candidate = Path(configured)
        return candidate if candidate.is_file() else None
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if not program_files_x86:
        return None
    candidates = sorted(
        Path(program_files_x86).glob("Windows Kits/10/Lib/*/um/x64/kernel32.Lib"),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _configured_toolchain() -> tuple[Path, Path, Path, Path, Path] | None:
    if os.name != "nt":
        return None
    compiler_text = os.environ.get("BPP_COMPILER")
    if not compiler_text:
        return None
    compiler = Path(compiler_text)
    if not compiler.is_file():
        return None
    compiler_root = Path(os.environ.get("BPP_COMPILER_ROOT", compiler.parent.parent))
    if not (compiler_root / "src" / "std" / "io.bpp").is_file():
        return None
    nasm_text = os.environ.get("BPP_NASM") or shutil.which("nasm.exe") or shutil.which("nasm")
    linker_text = os.environ.get("BPP_LINKER") or shutil.which("link.exe") or shutil.which("lld-link.exe")
    kernel32 = _find_kernel32_library()
    if not nasm_text or not linker_text or kernel32 is None:
        return None
    nasm = Path(nasm_text)
    linker = Path(linker_text)
    if not nasm.is_file() or not linker.is_file():
        return None
    return compiler, compiler_root, nasm, linker, kernel32


def _compile_to_assembly(compiler: Path, compiler_root: Path, source: Path, assembly: Path) -> None:
    process = subprocess.Popen(
        [str(compiler), "--target", "windows-x86_64", "-asm", str(source)],
        cwd=compiler_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    deadline = time.monotonic() + COMPILE_TIMEOUT_SECONDS
    standard_error = bytearray()
    output_limit_exceeded = threading.Event()
    output_thread = threading.Thread(
        target=_drain_assembly,
        args=(process.stdout, assembly, output_limit_exceeded, process),
    )
    error_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stderr, standard_error, output_limit_exceeded, process),
    )
    output_thread.start()
    error_thread.start()
    try:
        remaining = deadline - time.monotonic()
        return_code = process.wait(timeout=max(remaining, 0))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        pytest.fail(f"B++ compilation exceeded its {COMPILE_TIMEOUT_SECONDS}-second cap: {source.name}")
    finally:
        _join_threads([output_thread, error_thread])
    assert not output_limit_exceeded.is_set(), f"oversized B++ assembly or diagnostics for {source.name}"
    assert return_code == 0, standard_error.decode("utf-8", errors="replace")


def test_bpp_a_d_source_inventory_is_complete() -> None:
    assert EXPECTED_SOURCE_NAMES <= {path.name for path in SOURCE_DIRECTORY.glob("*.bpp")}


def test_bpp_a_d_references_match_examples_and_seeded_oracle_cases(tmp_path: Path) -> None:
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
        generated = generate(letter, seed=71)
        generated_count += len(generated)
        cases.extend((letter, text, solve(letter, text)) for text in generated)

    boundary_values = ["-1000000", "+1000000"] + ["0"] * 1023
    cases.extend(
        [
            ("A", "\t+3\r\n+5  ", "8"),
            ("B", "+5\t+2\r\n+5\n", "1500"),
            ("C", "+1025\r\n" + "\t".join(boundary_values) + "\n", "-1000000 1000000"),
            ("D", "+2\r\n+3\tGo\r\n+2 \tB1\n", "GGGooo\nBB11"),
        ]
    )

    assert sample_count == STATEMENT_SAMPLE_COUNT
    assert generated_count > 0
    for letter, text, expected in cases:
        result = _run([str(executables[letter])], cwd=tmp_path, input_text=text, timeout=RUN_TIMEOUT_SECONDS)
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        actual = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n").rstrip("\n")
        assert actual == expected, f"{letter} produced {actual!r} for input {text!r}; expected {expected!r}"
