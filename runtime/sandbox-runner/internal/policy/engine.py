from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class EngineType(str, Enum):
    LOCAL = "local"
    NAMESPACE = "namespace"


@dataclass(slots=True)
class EngineRunResult:
    returncode: int
    stdout: str
    stderr: str


class ExecutionEngine:
    engine_type: EngineType

    def run_sample(
        self,
        root_dir: Path,
        sample_name: str,
        *,
        stdin_data: str = "",
        working_directory: str = "",
        args: list[str] | None = None,
    ) -> EngineRunResult:
        raise NotImplementedError


class LocalExecutionEngine(ExecutionEngine):
    engine_type = EngineType.LOCAL

    def run_sample(
        self,
        root_dir: Path,
        sample_name: str,
        *,
        stdin_data: str = "",
        working_directory: str = "",
        args: list[str] | None = None,
    ) -> EngineRunResult:
        command = ["bash", str(root_dir / "scripts" / "run_sample.sh"), sample_name]
        args = args or []

        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as tmp:
            tmp.write(stdin_data)
            stdin_path = tmp.name

        command.extend(["--stdin-file", stdin_path])
        if working_directory:
            command.extend(["--workdir", working_directory])
        for arg in args:
            command.extend(["--arg", arg])

        completed = subprocess.run(command, cwd=root_dir, capture_output=True, text=True)
        Path(stdin_path).unlink(missing_ok=True)
        return EngineRunResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class NamespaceExecutionEngine(ExecutionEngine):
    engine_type = EngineType.NAMESPACE

    def run_sample(
        self,
        root_dir: Path,
        sample_name: str,
        *,
        stdin_data: str = "",
        working_directory: str = "",
        args: list[str] | None = None,
    ) -> EngineRunResult:
        raise RuntimeError(
            "namespace engine is not available in the current environment; "
            "see docs/sandbox-runtime/poc-results-security-blockers.md"
        )
