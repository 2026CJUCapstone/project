"""Executable regression coverage for the B++ ``compile-json`` launcher mode."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "runtime" / "sandbox" / "run.sh"
POSIX_SHELL = shutil.which("bash")
GRAPH_JSON = '{"schemaVersion":1,"views":{"ast":{"nodes":[],"edges":[]}}}'
NATIVE_ASM = "global _start\n_start:\n    mov rax, 60\n    xor rdi, rdi\n    syscall\n"

pytestmark = pytest.mark.skipif(
    POSIX_SHELL is None,
    reason="POSIX shell is unavailable; compile-json launcher execution test requires bash",
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _isolated_launcher(tmp_path: Path) -> tuple[Path, Path]:
    launcher_tmp = tmp_path / "launcher-tmp"
    launcher_tmp.mkdir()
    # The launcher normally owns /tmp/program*, so every such path must be
    # private to this test before it is executed.
    launcher = tmp_path / "run.sh"
    launcher.write_text(
        LAUNCHER.read_text(encoding="utf-8").replace("/tmp/", f"{launcher_tmp.as_posix()}/"),
        encoding="utf-8",
        newline="\n",
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    return launcher, launcher_tmp


def _tool_environment(tmp_path: Path, failing_tool: str | None = None) -> tuple[dict[str, str], Path]:
    tool_dir = tmp_path / "tools"
    tool_dir.mkdir()
    log = tmp_path / "tool.log"
    _write_executable(
        tool_dir / "bpp",
        f"""#!/usr/bin/env bash
set -eu
printf 'bpp\\n' >> "$FAKE_TOOL_LOG"
if [[ "${{FAKE_FAIL_TOOL:-}}" == "bpp" ]]; then
  printf '%s\\n' '{GRAPH_JSON}'
  printf 'forced bpp failure\\n' >&2
  exit 17
fi
printf '%s' '{NATIVE_ASM}' >&3
printf '%s\\n' '{GRAPH_JSON}'
""",
    )
    _write_executable(
        tool_dir / "nasm",
        """#!/usr/bin/env bash
set -eu
printf 'nasm\\n' >> "$FAKE_TOOL_LOG"
if [[ "${FAKE_FAIL_TOOL:-}" == "nasm" ]]; then
  printf 'forced nasm failure\\n' >&2
  exit 18
fi
while (($#)); do
  if [[ "$1" == "-o" ]]; then
    : > "$2"
    break
  fi
  shift
done
""",
    )
    _write_executable(
        tool_dir / "ld",
        """#!/usr/bin/env bash
set -eu
printf 'ld\\n' >> "$FAKE_TOOL_LOG"
if [[ "${FAKE_FAIL_TOOL:-}" == "ld" ]]; then
  printf 'forced ld failure\\n' >&2
  exit 19
fi
while (($#)); do
  if [[ "$1" == "-o" ]]; then
    : > "$2"
    break
  fi
  shift
done
""",
    )
    environment = os.environ.copy()
    environment["PATH"] = str(tool_dir) + os.pathsep + environment["PATH"]
    environment["FAKE_TOOL_LOG"] = str(log)
    if failing_tool is not None:
        environment["FAKE_FAIL_TOOL"] = failing_tool
    return environment, log


def _run_compile_json(tmp_path: Path, failing_tool: str | None = None) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    launcher, launcher_tmp = _isolated_launcher(tmp_path)
    environment, log = _tool_environment(tmp_path, failing_tool)
    source = tmp_path / "main.bpp"
    source.write_text("func main() -> u64 { return 0; }\n", encoding="utf-8")
    result = subprocess.run(
        [POSIX_SHELL, str(launcher), "compile-json", "bpp", str(source)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    return result, launcher_tmp, log


@pytest.mark.parametrize("failing_tool", ["bpp", "nasm", "ld"])
def test_compile_json_never_publishes_graph_json_before_native_success(tmp_path: Path, failing_tool: str) -> None:
    result, launcher_tmp, log = _run_compile_json(tmp_path, failing_tool)

    assert result.returncode != 0
    assert result.stdout == ""
    assert GRAPH_JSON not in result.stdout
    assert log.read_text(encoding="utf-8").splitlines() == {
        "bpp": ["bpp"],
        "nasm": ["bpp", "nasm"],
        "ld": ["bpp", "nasm", "ld"],
    }[failing_tool]
    if failing_tool == "bpp":
        assert (launcher_tmp / "program.asm").read_bytes() == b""
    else:
        assert (launcher_tmp / "graphs.json").read_text(encoding="utf-8").strip() == GRAPH_JSON


def test_compile_json_returns_graph_json_after_native_assembly_and_link(tmp_path: Path) -> None:
    result, launcher_tmp, log = _run_compile_json(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == GRAPH_JSON + "\n"
    assert log.read_text(encoding="utf-8").splitlines() == ["bpp", "nasm", "ld"]
    assert (launcher_tmp / "program.asm").read_text(encoding="utf-8") == NATIVE_ASM
    assert (launcher_tmp / "program.o").is_file()
    assert (launcher_tmp / "program").is_file()
