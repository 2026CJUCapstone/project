"""Regression checks for the opt-in phase frames emitted by the sandbox launcher."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "runtime" / "sandbox" / "run.sh"
TOKEN = "0123456789abcdef0123456789abcdef"
LANGUAGES = ("bpp", "python", "c", "cpp", "java", "javascript")


def test_phase_protocol_is_opt_in_and_nonce_bound():
    source = RUNNER.read_text(encoding="utf-8")
    assert "if [[ \"${COMPILER_PHASE_TOKEN:-}\" =~ ^[0-9a-f]{32}$ ]]; then" in source
    assert "printf '\\036webcompiler:%s:%s\\037\\n' \"$COMPILER_PHASE_TOKEN\" \"$1\" >&2" in source
    assert "Never derive execution phase from diagnostics." in source


def test_compile_phase_is_reported_before_language_dispatch():
    source = RUNNER.read_text(encoding="utf-8")
    compile_frame = source.index("report_phase compile")
    flags = source.index("C_FLAGS=(")
    dispatch = source.index('case "$LANGUAGE" in')
    assert compile_frame < flags < dispatch


@pytest.mark.parametrize("function", ("run_bpp", "run_python", "run_c", "run_cpp", "run_java", "run_javascript"))
def test_each_language_run_function_reports_run_before_execution(function):
    source = RUNNER.read_text(encoding="utf-8")
    start = source.index(f"{function}() {{")
    end = source.index("\n}\n", start) + 3
    block = source[start:end]
    report = block.index("report_phase run")

    execution_markers = {
        "run_bpp": "/tmp/program",
        "run_python": "python3 \"$SOURCE_FILE\"",
        "run_c": "/tmp/program",
        "run_cpp": "/tmp/program",
        "run_java": "java -cp /tmp/java-classes",
        "run_javascript": "node \"$SOURCE_FILE\"",
    }
    assert report < block.index(execution_markers[function], report)


def _write_stub(directory: Path, name: str, body: str = "#!/bin/sh\nexit 0\n") -> None:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o700)


def _adapt_runner_to_fixture_temp(directory: Path) -> tuple[Path, Path]:
    """Adapt only fixed ``/tmp/`` paths in a temporary runner copy.

    The production launcher intentionally uses fixed paths inside its sandbox.
    This optional shell test must not touch the host's global ``/tmp`` files, so
    the harness changes those literals only in the temporary copy being run.
    It is therefore a smoke check of the copied script's protocol, not a claim
    that the unadapted host paths have been exercised.
    """
    fixture_temp = directory / "sandbox-tmp"
    fixture_temp.mkdir()
    adapted_source = RUNNER.read_text(encoding="utf-8").replace(
        "/tmp/", fixture_temp.as_posix() + "/"
    )
    adapted_runner = directory / "run-adapted.sh"
    adapted_runner.write_text(adapted_source, encoding="utf-8")
    adapted_runner.chmod(0o700)
    return adapted_runner, fixture_temp


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only dynamic fixture; Windows is unsupported")
@pytest.mark.skipif(shutil.which("bash") is None, reason="Bash is unavailable on this POSIX host")
def test_bash_stubbed_run_modes_emit_ordered_frames_and_no_nonce_is_silent():
    bash = shutil.which("bash")
    assert bash is not None
    with tempfile.TemporaryDirectory(prefix="execution-phase-") as raw_directory:
        directory = Path(raw_directory)
        adapted_runner, fixture_temp = _adapt_runner_to_fixture_temp(directory)
        bin_directory = directory / "bin"
        bin_directory.mkdir()
        for command in ("bpp", "gcc", "g++", "java", "javac", "ld", "nasm", "node", "python3"):
            _write_stub(bin_directory, command)

        sources = {}
        for language, suffix in (
            ("bpp", ".bpp"),
            ("python", ".py"),
            ("c", ".c"),
            ("cpp", ".cpp"),
            ("java", ".java"),
            ("javascript", ".js"),
        ):
            source = directory / f"Program{suffix}"
            source.write_text("stub\n", encoding="utf-8")
            sources[language] = source

        environment = dict(os.environ)
        environment["PATH"] = os.pathsep.join((str(bin_directory), environment.get("PATH", "")))
        environment["COMPILER_PHASE_TOKEN"] = TOKEN
        # The adapted runner still uses its fixed paths, but all are inside this
        # fixture (including /tmp/program, .asm/.o, and java-classes).
        program = fixture_temp / "program"
        program.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        program.chmod(0o700)

        expected_compile = f"\x1ewebcompiler:{TOKEN}:compile\x1f\n"
        expected_run = f"\x1ewebcompiler:{TOKEN}:run\x1f\n"
        for language in LANGUAGES:
            result = subprocess.run(
                [bash, str(adapted_runner), "run", language, str(sources[language])],
                capture_output=True,
                text=True,
                env=environment,
                timeout=5,
            )
            assert result.returncode == 0, (language, result.stdout, result.stderr)
            assert result.stdout == ""
            assert result.stderr == expected_compile + expected_run

        quiet_environment = dict(environment)
        quiet_environment.pop("COMPILER_PHASE_TOKEN")
        result = subprocess.run(
            [bash, str(adapted_runner), "run", "python", str(sources["python"])],
            capture_output=True,
            text=True,
            env=quiet_environment,
            timeout=5,
        )
        assert result.returncode == 0
        assert result.stdout == "" and result.stderr == ""
