#!/usr/bin/env python3
"""Single SSH deployment with pinned host identity and stdin-only credentials.

This helper does not choose a revision. verify_deploy_ci.py must first prove the
provided full SHA passed CI. No host-key scan or branch fallback is allowed.
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


class DeployConfigurationError(ValueError):
    pass


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


def dispatch(env, *, run=subprocess.run):
    config = configuration(env)
    script = Path(__file__).with_name('sync_remote_repo.sh').read_text(encoding='utf-8')
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
        command = ['ssh','-F','/dev/null','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                   '-o',f'UserKnownHostsFile={known_hosts}', '-o','GlobalKnownHostsFile=/dev/null',
                   '-o','UpdateHostKeys=no','-o','ConnectTimeout=15','-o','ServerAliveInterval=30',
                   '-o','ServerAliveCountMax=20','-p',config['DEPLOY_PORT'],
                   config['DEPLOY_USER']+'@'+config['DEPLOY_HOST'], 'bash -s']
        run(command, input=payload, text=True, check=True)


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
