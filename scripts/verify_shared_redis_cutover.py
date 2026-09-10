#!/usr/bin/env python3
"""Read-only guard against silently moving live clients to a different Redis.

Changing an endpoint/namespace needs a separately verified offline transition;
this script never drains, migrates, resets or changes any runtime resource.
"""
import json
import os
import re
import subprocess
import sys

from ensure_shared_redis import SharedRedisError, docker


def verify(active_color, legacy_project, endpoint, prefix, *, call=docker, project_prefix='webcompiler'):
    if active_color not in ('', 'blue', 'green'):
        raise ValueError('Invalid active color')
    if re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', legacy_project) is None:
        raise ValueError('Invalid legacy project')
    if not isinstance(project_prefix,str) or re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,65}',project_prefix) is None:
        raise ValueError('Invalid deployment project prefix')
    if not endpoint or not prefix:
        raise ValueError('Shared Redis settings are required')
    # The old color may still drain after the edge changed. Check both colors,
    # not just the marker, so two different quota/lease namespaces cannot coexist.
    projects = {legacy_project, project_prefix+'-blue', project_prefix+'-green'}
    active_seen = False
    for project in sorted(projects):
        ids = call(['container','ls','-q','--filter','label=com.docker.compose.project='+project]).split()
        if not ids:
            continue
        containers = json.loads(call(['container','inspect',*ids]))
        for container in containers:
            config = container['Config']
            labels = config.get('Labels') or {}
            if labels.get('com.docker.compose.project') != project:
                raise SharedRedisError('Unexpected runtime project')
            if labels.get('com.docker.compose.service') not in ('backend','worker'):
                continue
            if project == project_prefix+'-'+active_color:
                active_seen = True
            env = dict(item.split('=',1) for item in config.get('Env',[]) if '=' in item)
            if env.get('REDIS_URL','') != endpoint or env.get('REDIS_KEY_PREFIX','webcompiler') != prefix:
                raise SharedRedisError('A live runtime uses a different Redis endpoint or namespace')
    if active_color and not active_seen:
        raise SharedRedisError('Active color runtime could not be verified')


def main():
    try:
        project_prefix=os.environ.get('WEBCOMPILER_PROJECT_PREFIX','webcompiler')
        verify(os.environ.get('WEBCOMPILER_DEPLOY_ACTIVE_COLOR',''),
               os.environ.get('WEBCOMPILER_LEGACY_PROJECT_NAME',project_prefix),
               os.environ['WEBCOMPILER_REDIS_URL'], os.environ['WEBCOMPILER_REDIS_KEY_PREFIX'],
               project_prefix=project_prefix)
    except (KeyError, ValueError, SharedRedisError, OSError, subprocess.SubprocessError):
        # Neither Redis credentials nor Docker inspect output belong in logs.
        print('Shared Redis cutover refused; verify the current runtime and complete an offline transition before deployment',file=sys.stderr)
        return 1
    print('Existing runtime Redis endpoints match the deployment')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
