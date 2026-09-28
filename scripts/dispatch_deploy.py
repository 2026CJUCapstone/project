#!/usr/bin/env python3
"""Pinned SSH deployment with a dedicated frontend upload stream.

This helper does not choose a revision. verify_deploy_ci.py must first prove the
provided full SHA passed CI. No host-key scan or branch fallback is allowed.
"""
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


class DeployConfigurationError(ValueError):
    pass


MAX_FRONTEND_ARCHIVE_BYTES = 32 * 1024 * 1024


def configuration(env):
    required = ('DEPLOY_SHA', 'DEPLOY_HOST', 'DEPLOY_USER', 'DEPLOY_PATH',
                'DEPLOY_PORT', 'DEPLOY_REPO', 'DEPLOY_KNOWN_HOSTS')
    if any(not env.get(key) for key in required):
        raise DeployConfigurationError('Required deployment configuration is missing')
    if not re.fullmatch(r'[0-9a-f]{40}', env['DEPLOY_SHA']):
        raise DeployConfigurationError('Invalid deploy SHA')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', env['DEPLOY_HOST']):
        raise DeployConfigurationError('Invalid deploy host')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', env['DEPLOY_USER']):
        raise DeployConfigurationError('Invalid deploy user')
    if not re.fullmatch(r'[0-9]{1,5}', env['DEPLOY_PORT']) or not 1 <= int(env['DEPLOY_PORT']) <= 65535:
        raise DeployConfigurationError('Invalid deploy port')
    path = env['DEPLOY_PATH']
    if not path.startswith('/') or len(Path(path).parts) < 3 or any(c in path for c in '\r\n\0'):
        raise DeployConfigurationError('Invalid deploy path')
    if not re.fullmatch(r'https://[A-Za-z0-9.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git', env['DEPLOY_REPO']):
        raise DeployConfigurationError('Invalid deploy repository URL')
    if len(env['DEPLOY_KNOWN_HOSTS']) > 65536:
        raise DeployConfigurationError('Host key configuration is too large')
    return {key: env[key] for key in required}


def _read_frontend_archive(path):
    """Read a bounded local archive and return its bytes plus SHA-256 digest."""
    try:
        with Path(path).open('rb') as archive:
            data = archive.read(MAX_FRONTEND_ARCHIVE_BYTES + 1)
    except FileNotFoundError as exc:
        raise DeployConfigurationError('Frontend archive is missing') from exc
    except (OSError, ValueError) as exc:
        raise DeployConfigurationError('Frontend archive is unreadable') from exc
    if len(data) > MAX_FRONTEND_ARCHIVE_BYTES:
        raise DeployConfigurationError('Frontend archive is too large')
    return data, hashlib.sha256(data).hexdigest()


def _ssh_command(config, known_hosts):
    return [
        'ssh', '-F', '/dev/null', '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes',
        '-o', f'UserKnownHostsFile={known_hosts}',
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no',
        '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=20', '-p', config['DEPLOY_PORT'],
        config['DEPLOY_USER'] + '@' + config['DEPLOY_HOST'],
    ]


def _upload_frontend(config, known_hosts, archive, *, run):
    """Stream the archive directly to cat; never make Bash parse binary data."""
    data, digest = archive
    upload_path = (
        f"{config['DEPLOY_PATH'].rstrip('/')}/.deploy/"
        f"frontend-upload-{config['DEPLOY_SHA']}-{digest}.tar.gz"
    )
    script = '\n'.join((
        'set -euo pipefail',
        'umask 077',
        f"DEPLOY_PATH={shlex.quote(config['DEPLOY_PATH'])}",
        f"UPLOAD_PATH={shlex.quote(upload_path)}",
        '[[ "$DEPLOY_PATH" == /* && "$DEPLOY_PATH" != / && ! -L "$DEPLOY_PATH" ]]',
        'mkdir -p "$DEPLOY_PATH/.deploy"',
        '[[ ! -L "$DEPLOY_PATH/.deploy" && ! -L "$UPLOAD_PATH" ]]',
        'TMP_PATH="$UPLOAD_PATH.part.$$"',
        "trap 'rm -f -- \"$TMP_PATH\"' EXIT",
        'cat >"$TMP_PATH"',
        'chmod 600 "$TMP_PATH"',
        'mv -f -- "$TMP_PATH" "$UPLOAD_PATH"',
        'trap - EXIT',
    ))
    command = _ssh_command(config, known_hosts) + [f"bash -c {shlex.quote(script)}"]
    run(command, input=data, check=True)
    return upload_path, digest


def _remove_frontend_upload(config, known_hosts, upload_path, *, run):
    cleanup = f"rm -f -- {shlex.quote(upload_path)}"
    run(
        _ssh_command(config, known_hosts) + [f"bash -c {shlex.quote(cleanup)}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def dispatch(env, *, run=subprocess.run):
    config = configuration(env)
    script = Path(__file__).with_name('sync_remote_repo.sh').read_text(encoding='utf-8')
    archive_path = env.get('DEPLOY_FRONTEND_ARCHIVE')
    archive = None
    if archive_path:
        archive = _read_frontend_archive(archive_path)
    # Never put the token or secret fields in the SSH command line or a log.
    values = {key:config[key] for key in ('DEPLOY_SHA','DEPLOY_PATH','DEPLOY_REPO')}
    if env.get('GITHUB_TOKEN'):
        values['GITHUB_TOKEN'] = env['GITHUB_TOKEN']
    payload = ''.join(f'export {key}={shlex.quote(value)}\n' for key,value in values.items())
    payload += 'export RUN_DEPLOY_SCRIPT=1\n' + script
    with tempfile.TemporaryDirectory(prefix='webcompiler-ssh-') as folder:
        known_hosts = Path(folder)/'known_hosts'
        known_hosts.write_text(config['DEPLOY_KNOWN_HOSTS']+'\n', encoding='utf-8')
        known_hosts.chmod(0o600)
        host_key_name = config['DEPLOY_HOST'] if int(config['DEPLOY_PORT']) == 22 else f"[{config['DEPLOY_HOST']}]:{config['DEPLOY_PORT']}"
        found = run(['ssh-keygen','-F',host_key_name,'-f',str(known_hosts)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if found.returncode:
            raise DeployConfigurationError('Pinned key for the exact host and port is missing')
        upload_path = None
        if archive is not None:
            upload_path, digest = _upload_frontend(config, known_hosts, archive, run=run)
            payload = (
                f'export WEBCOMPILER_FRONTEND_UPLOAD={shlex.quote(upload_path)}\n'
                f'export WEBCOMPILER_FRONTEND_SHA256={shlex.quote(digest)}\n'
                + payload
            )
        command = _ssh_command(config, known_hosts) + ['bash -s']
        try:
            run(command, input=payload, text=True, check=True)
        except (OSError, subprocess.SubprocessError):
            if upload_path is not None:
                _remove_frontend_upload(config, known_hosts, upload_path, run=run)
            raise


def main():
    try:
        dispatch(os.environ)
    except (DeployConfigurationError, OSError, subprocess.SubprocessError) as exc:
        # Subprocess repr may contain credentials: emit only fixed messages.
        message = str(exc) if isinstance(exc, DeployConfigurationError) else 'SSH deployment failed'
        print(message, file=__import__('sys').stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
