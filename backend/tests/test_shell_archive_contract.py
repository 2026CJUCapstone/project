import io
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest


def test_windows_git_archive_keeps_executable_shell_shebang_lf(tmp_path):
    git = shutil.which('git')
    if not git:
        pytest.skip('git executable required for archive integration')
    root = Path(__file__).resolve().parents[2]
    (tmp_path / '.gitattributes').write_bytes((root / '.gitattributes').read_bytes())
    script = b'#!/bin/bash\nset -eu\nprintf "42\\n"\n'
    (tmp_path / 'run.sh').write_bytes(script)

    def run(*args):
        return subprocess.run([git, *args], cwd=tmp_path, check=True, capture_output=True).stdout

    run('init', '-q')
    run('config', 'core.autocrlf', 'true')
    run('config', 'user.name', 'Archive fixture')
    run('config', 'user.email', 'archive@example.test')
    run('add', '.gitattributes', 'run.sh')
    run('commit', '-qm', 'Archive fixture')
    with tarfile.open(fileobj=io.BytesIO(run('archive', '--format=tar', 'HEAD'))) as archive:
        archived = archive.extractfile('run.sh').read()
    assert archived == script
    assert b'\r' not in archived.split(b'\n', 1)[0]
