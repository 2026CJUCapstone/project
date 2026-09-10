"""Opt-in live Docker tests, serial and bounded; never call public production APIs."""
import os
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.compiler import DockerCompilerRunner

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    os.getenv('RUN_SANDBOX_INTEGRATION') != '1', reason='Explicit isolated Docker test environment required')]

SAMPLES = [
    ('bpp', 'import emitln from std.io; func main() -> u64 { emitln("42"); return 0; }'),
    ('c', '#include <stdio.h>\nint main(void) { puts("42"); return 0; }'),
    ('cpp', '#include <iostream>\nint main() { std::cout << 42 << std::endl; }'),
    ('python', 'print(42)'),
    ('java', 'public class Main { public static void main(String[] args) { System.out.println(42); } }'),
    ('javascript', 'console.log(42);'),
]


@pytest.fixture(autouse=True)
def isolated_resource_budget():
    if os.getenv('RUN_SANDBOX_INTEGRATION') != '1':
        return
    root = Path(os.environ['AUDIT_ROOT']).resolve()
    sandbox = Path(settings.SANDBOX_WORKDIR_ROOT).resolve()
    assert root.name.startswith('webcompiler-audit-')
    assert sandbox.is_relative_to(root) and sandbox != root
    assert settings.SANDBOX_CPU_LIMIT <= 0.5
    assert settings.SANDBOX_MEMORY_MB <= 256
    assert settings.EXECUTION_TIMEOUT <= 10


@pytest.mark.parametrize('language,code', SAMPLES)
async def test_real_language_run_streams_first_output(language, code):
    result = await DockerCompilerRunner().run(code, language=language)
    assert result['exit_code'] == 0, result['stderr']
    assert result['stdout'].strip() == '42'


async def test_real_output_budget_terminates_before_consuming_all(monkeypatch):
    monkeypatch.setattr(settings, 'SANDBOX_OUTPUT_MAX_BYTES', 16384)
    result = await DockerCompilerRunner().run('for i in range(100): print("x" * 1024)', language='python')
    assert result['exit_code'] != 0
    assert 'Output limit exceeded' in result['stderr']
    assert len(result['stdout'].encode()) <= 16384


async def test_real_timeout_cleans_work_directory(monkeypatch):
    monkeypatch.setattr(settings, 'EXECUTION_TIMEOUT', 1)
    root = Path(settings.SANDBOX_WORKDIR_ROOT)
    before = set(root.glob('job-*'))
    result = await DockerCompilerRunner().run('while True: pass', language='python')
    assert result['exit_code'] == 124
    assert set(root.glob('job-*')) == before
