import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "scripts" / "backup_database.sh"
RESTORE = ROOT / "scripts" / "restore_database.sh"


@pytest.fixture()
def shell() -> str:
    executable = shutil.which("sh")
    if not executable and os.name == "nt":
        git_shell = Path(r"C:\Program Files\Git\usr\bin\sh.exe")
        if git_shell.exists():
            executable = str(git_shell)
    if not executable:
        pytest.skip("POSIX shell is not available")
    return executable


def shell_path(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if os.name == "nt" and len(resolved) > 2 and resolved[1] == ":":
        return f"/{resolved[0].lower()}/{resolved[3:]}"
    return resolved


def run(shell: str, script: Path, *args: str, env: dict[str, str], cwd: Path):
    normalized_args = [arg.replace("\\", "/") for arg in args] if os.name == "nt" else list(args)
    return subprocess.run(
        [shell, script.as_posix(), *normalized_args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_backup_script_has_private_custom_format_and_failure_cleanup():
    source = BACKUP.read_text()
    assert "umask 077" in source
    assert "--format=custom" in source
    assert 'checksum=$(sha256sum < "$partial")' in source
    assert "trap cleanup EXIT HUP INT TERM" in source
    assert "Refusing to overwrite existing backup" in source


def test_restore_script_requires_empty_target_and_transactional_restore():
    source = RESTORE.read_text()
    assert "Refusing to restore into a non-empty database" in source
    invocation = 'pg_restore --exit-on-error --single-transaction --dbname="$database" "$backup"'
    assert invocation in source
    assert "PGSERVICE" in source and "PGHOST" in source and "PGUSER" in source


def test_backup_refuses_overwrite_without_running_pg_dump(shell: str, tmp_path: Path):
    output = tmp_path / "backup.dump"
    output.write_bytes(b"keep")
    env = {**os.environ, "PGSERVICE": "staging", "PATH": "/usr/bin:/bin"}

    result = run(shell, BACKUP, "--database", "target", "--output", str(output), env=env, cwd=tmp_path)

    assert result.returncode == 2
    assert output.read_bytes() == b"keep"
    assert "overwrite" in result.stderr.lower()


def test_failed_dump_removes_partial_file(shell: str, tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pg_dump = bin_dir / "pg_dump"
    pg_dump.write_text('#!/bin/sh\nfor arg in "$@"; do case "$arg" in --file=*) : > "${arg#--file=}";; esac; done\nexit 9\n')
    pg_dump.chmod(0o700)
    output = tmp_path / "backup.dump"
    env = {**os.environ, "PGSERVICE": "staging", "PATH": f"{shell_path(bin_dir)}:/usr/bin:/bin"}

    result = run(shell, BACKUP, "--database", "target", "--output", str(output), env=env, cwd=tmp_path)

    assert result.returncode == 9
    assert not output.exists()
    assert not list(tmp_path.glob(".backup.*"))


def test_concurrent_backup_has_exactly_one_winner(shell: str, tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pg_dump = bin_dir / "pg_dump"
    pg_dump.write_text(
        '#!/bin/sh\nfor arg in "$@"; do case "$arg" in --file=*) output=${arg#--file=};; esac; done\n'
        'printf "backup-from-%s\\n" "$$" > "$output"\nsleep 0.2\n'
    )
    pg_dump.chmod(0o700)
    output = tmp_path / "backup.dump"
    env = {**os.environ, "PGSERVICE": "staging", "PATH": f"{shell_path(bin_dir)}:/usr/bin:/bin"}
    command = [shell, BACKUP.as_posix(), "--database", "target", "--output", output.as_posix()]

    processes = [
        subprocess.Popen(command, cwd=tmp_path, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(2)
    ]
    results = [process.communicate(timeout=10) + (process.returncode,) for process in processes]

    assert sorted(result[2] for result in results) == [0, 2]
    published = output.read_bytes()
    time.sleep(0.05)
    assert output.read_bytes() == published
    assert (tmp_path / "backup.dump.sha256").exists()
    assert not list(tmp_path.glob(".backup.*"))


def test_restore_uses_safe_flags_after_empty_database_check(shell: str, tmp_path: Path):
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"custom-format-placeholder")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    (tmp_path / "backup.dump.sha256").write_bytes(f"{digest}  backup.dump\n".encode())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "restore.args"
    for name, body in {
        "sha256sum": '#!/bin/sh\nexec /usr/bin/sha256sum "$@"\n',
        "psql": "#!/bin/sh\necho 0\n",
        "pg_restore": f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\n',
    }.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o700)
    env = {**os.environ, "PGSERVICE": "isolated", "PATH": f"{shell_path(bin_dir)}:/usr/bin:/bin"}

    result = run(shell, RESTORE, "--database", "new_empty_db", "--backup", str(backup), env=env, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    arguments = log.read_text().splitlines()
    assert "--exit-on-error" in arguments
    assert "--single-transaction" in arguments
    assert "--dbname=new_empty_db" in arguments
    assert "--clean" not in arguments
    assert "--create" not in arguments


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX special filename semantics")
@pytest.mark.parametrize("parent_name", ("restore\r", "restore\\"))
def test_restore_hashes_special_parent_paths_from_stdin(
    shell: str, tmp_path: Path, parent_name: str
):
    parent = tmp_path / parent_name
    parent.mkdir()
    backup = parent / "backup.dump"
    payload = b"custom-format-bytes-with-a-special-parent"
    backup.write_bytes(payload)
    checksum_file = parent / "backup.dump.sha256"
    checksum_file.write_text(f"{hashlib.sha256(payload).hexdigest()}  backup.dump\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    restore_log = tmp_path / "restore.args"
    restored = tmp_path / "restored.dump"
    for name, body in {
        "sha256sum": "#!/bin/sh\nexec /usr/bin/sha256sum \"$@\"\n",
        "psql": "#!/bin/sh\necho 0\n",
        "pg_restore": (
            "#!/bin/sh\n"
            'cat -- "$4" > "$RESTORED_BACKUP"\n'
            'printf "%s\\n" "$@" > "$RESTORE_LOG"\n'
        ),
    }.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o700)
    env = {
        **os.environ,
        "PGSERVICE": "isolated",
        "PATH": f"{shell_path(bin_dir)}:/usr/bin:/bin",
        "RESTORED_BACKUP": str(restored),
        "RESTORE_LOG": str(restore_log),
    }

    valid = run(
        shell,
        RESTORE,
        "--database",
        "new_empty_db",
        "--backup",
        str(backup),
        env=env,
        cwd=tmp_path,
    )

    assert valid.returncode == 0, valid.stderr
    assert restored.read_bytes() == payload
    assert restore_log.exists()

    checksum_file.write_text(f"{'0' * 64}  backup.dump\n")
    restore_log.unlink()
    restored.unlink()
    mismatched = run(
        shell,
        RESTORE,
        "--database",
        "new_empty_db",
        "--backup",
        str(backup),
        env=env,
        cwd=tmp_path,
    )

    assert mismatched.returncode == 1
    assert "checksum" in mismatched.stderr.lower()
    assert not restore_log.exists()
    assert not restored.exists()
