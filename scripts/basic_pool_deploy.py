"""Guarded source-only automatic updates for an explicitly adopted basic 2-API pool.

No schema/dependency/topology migrations. See docs/basic-pool-autodeploy.md.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import re
import tarfile
import time
from urllib.request import urlopen
from uuid import uuid4

if not __debug__:
    raise RuntimeError('Optimized Python is not supported for deployment safety checks')

# Config is private server state, never a repository secret or inferred topology.
ROOT = OLD = PROD = STATE = SHA = PROJECT = None

class Host:
    BASEENV = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS') if k in os.environ}
    BASEENV.update(DOCKER_HOST='unix:///var/run/docker.sock', COMPOSE_DISABLE_ENV_FILE='1')
    def run(self, *args, env=None, timeout=60, data=None):
        result = subprocess.run(args, cwd=OLD, env=env or self.BASEENV, input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            raise RuntimeError('Command failed: ' + args[0] + ' exit ' + str(result.returncode))
        return result.stdout
    def inspect(self, name):
        return json.loads(self.run('docker', 'inspect', name))[0]
    @property
    def STATE(self):
        return OLD / 'operator-state.json'
    def save(self, value):
        atomic_json(self.STATE, value)
    def sql(self, pg, query):
        return self.run('docker', 'exec', pg, 'psql', '-U', 'compiler', '-d', 'compiler', '-Atc', query).decode().strip()

o = Host()

def atomic_json(path, value):
    assert not path.is_symlink()
    fd, name = tempfile.mkstemp(prefix=path.name + '-', dir=path.parent)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())
    os.replace(name, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(directory)
    finally: os.close(directory)

def configure(project_root, sha):
    global ROOT, OLD, PROD, STATE, SHA, PROJECT
    assert re.fullmatch(r'[0-9a-f]{40}', sha)
    PROD = Path(project_root).resolve()
    config_path = PROD / '.deploy/basic-pool.json'
    assert not config_path.is_symlink()
    cfg = json.loads(config_path.read_text())
    assert cfg['version'] == 1
    OLD = Path(cfg['pool_root'])
    assert OLD.is_absolute() and OLD.resolve() == OLD and OLD.is_dir()
    PROJECT = cfg['project']
    assert re.fullmatch(r'[a-z0-9][a-z0-9-]+', PROJECT)
    # Current supported shape is intentionally fixed; no adoption or discovery.
    assert cfg['postgres'] == 'webcompiler-postgres'
    assert cfg['backend_port'] == 18003 and cfg['frontend_port'] == 15176
    SHA = sha
    pending = PROD / '.deploy/basic-pool-pending.json'
    if pending.exists():
        previous = Path(json.loads(pending.read_text())['root'])
        assert previous.is_relative_to(PROD / '.deploy')
        phase = json.loads((previous / 'release-state.json').read_text())['phase']
        assert phase in ('deployed', 'rolled-back'), 'Interrupted release requires recorded recovery'
    ROOT = Path(tempfile.mkdtemp(prefix='basic-release-' + SHA + '-', dir=PROD / '.deploy'))
    STATE = ROOT / 'release-state.json'

CONTRACTS = ['backend/app/models/database.py', 'backend/app/core/database.py',
    'backend/app/core/bootstrap.py', 'backend/app/core/config.py', 'backend/app/initialize.py',
    'backend/requirements.lock', 'backend/Dockerfile', 'frontend/Dockerfile', 'frontend/nginx.conf',
    'docker-compose.yml', 'docker-compose.lb.yml', 'scripts/basic-lb.compose.yml',
    'scripts/basic-lb.production.compose.yml', 'scripts/e2e_stack_test.py']

def check_contracts(previous, candidate):
    assert {str(p.relative_to(previous)) for p in (previous / 'runtime').rglob('*') if p.is_file()} == {str(p.relative_to(candidate)) for p in (candidate / 'runtime').rglob('*') if p.is_file()}, 'Runtime file-set change requires clean build'
    paths = CONTRACTS + [str(p.relative_to(previous)) for p in (previous / 'runtime').rglob('*')
                         if p.is_file() and p.relative_to(previous).as_posix() != 'runtime/sandbox/run.sh']
    for relative in paths:
        assert contract_bytes(candidate / relative) == contract_bytes(previous / relative), 'Dependency/schema/topology change requires reviewed migration: ' + relative
    assert {str(p.relative_to(previous / 'backend/app')) for p in (previous / 'backend/app').rglob('*.py')} <= {str(p.relative_to(candidate / 'backend/app')) for p in (candidate / 'backend/app').rglob('*.py')}, 'Removed module requires clean image build'
    for path in (candidate / 'runtime').rglob('*.sh'):
        assert b'\r' not in path.read_bytes(), 'Shell archive must contain LF only'


def contract_bytes(path):
    data = path.read_bytes()
    # The adopted release was exported by Windows Git. Compare recognized
    # UTF-8 text contracts across CRLF/LF, but preserve every other byte.
    # Binary/unknown files and runtime filename additions stay exact.
    if path.suffix.lower() in {'.py', '.sh', '.yml', '.yaml', '.json', '.txt', '.md', '.conf', '.lock', '.toml', '.env', '.c', '.cpp', '.h', '.bpp'} or path.name in {'Dockerfile', '.gitignore'}:
        data.decode('utf-8')  # invalid text is an error, never lossy decoding
        return data.replace(b'\r\n', b'\n')
    return data


def save(s):
    atomic_json(STATE, s)

def pc(env, *args):
    return o.run('docker', 'compose', '--project-directory', str(OLD), '--env-file', '/dev/null',
        '-f', 'docker-compose.yml', '-f', 'docker-compose.lb.yml', '-f', 'scripts/basic-lb.compose.yml',
        '-f', 'scripts/basic-lb.production.compose.yml', *args, env={**o.BASEENV, **env}, timeout=240)

def extract(archive, prefix=None):
    with tarfile.open(archive) as tar:
        assert sum(m.size for m in tar.getmembers()) <= 256 * 1024**2
        for member in tar.getmembers():
            assert '..' not in member.name.split('/'), 'Parent traversal is not a deployment archive path'
            path = (ROOT / member.name).resolve()
            assert path.is_relative_to(ROOT) and (member.isdir() or member.isfile())
            assert member.size <= 128 * 1024**2
            if prefix: assert path.is_relative_to(ROOT / prefix)
        tar.extractall(ROOT, filter='data')
        # SSH receives secrets with umask077. Tar's data filter intentionally
        # drops directory modes, including implicit parents in frontend bundles.
        # Only extracted asset/source directories become traversable by the
        # non-root runtime. ROOT and its private journal/backups remain0700/0600.
        for member in tar.getmembers():
            assert '..' not in member.name.split('/'), 'Parent traversal is not a deployment archive path'
            path = (ROOT / member.name).resolve()
            directory = path if path.is_dir() else path.parent
            while directory != ROOT:
                directory.chmod(0o755)
                directory = directory.parent

def prepare():
    assert not STATE.exists()
    assert shutil.disk_usage(ROOT).free >= 8 * 1024**3
    old = json.loads(o.STATE.read_text())
    assert old['phase'] == 'deployed'
    previous = Path(old['functional_release_root'])
    assert previous.is_absolute() and previous.is_dir()
    # Committed Linux archive only. Never Docker COPY from checkout extras.
    source = o.run('git', '-C', str(PROD), 'archive', '--format=tar', SHA, timeout=60)
    (ROOT / 'source.tar').write_bytes(source)
    extract(ROOT / 'source.tar')
    check_contracts(previous, ROOT)
    bundle = Path(os.environ['WEBCOMPILER_FRONTEND_ARCHIVE'])
    assert bundle.is_relative_to(PROD / '.deploy') and not bundle.is_symlink()
    assert bundle.stat().st_size <= 32 * 1024**2
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == os.environ['WEBCOMPILER_FRONTEND_SHA256']
    shutil.copyfile(bundle, ROOT / 'frontend-tested.tar.gz')
    extract(ROOT / 'frontend-tested.tar.gz', 'frontend-dist')
    assert json.loads((ROOT / 'frontend-dist/.well-known/webcompiler-release.json').read_text()) == {'deployment_sha': SHA}
    assert (ROOT / 'frontend-dist/index.html').is_file()
    (ROOT / 'runtime/sandbox/run.sh').chmod(0o755)
    bases = {'backend': old['backend_id'], 'frontend': old['frontend_id'], 'sandbox': old['env']['SANDBOX_IMAGE']}
    assert all(o.inspect(value)['Id'] == value for value in bases.values())
    assert {str(p.relative_to(OLD / 'backend/app')) for p in (OLD / 'backend/app').rglob('*.py')} <= {str(p.relative_to(ROOT / 'backend/app')) for p in (ROOT / 'backend/app').rglob('*.py')}
    ids = {r: o.inspect(PROJECT + '-' + r + '-1')['Id'] for r in ('worker', 'frontend', 'redis', 'pgbouncer', 'api-proxy')}
    ids.update({f'backend-{n}': o.inspect(PROJECT + f'-backend-{n}')['Id'] for n in (1, 2)})
    s = {'phase': 'building', 'sha': SHA, 'old': old, 'old_ids': ids, 'bases': bases, 'images': {},
         'postgres_id': o.inspect('webcompiler-postgres')['Id'], 'tags': []}
    save(s)
    atomic_json(PROD / '.deploy/basic-pool-pending.json', {'root': str(ROOT)})
    build()

def build_context(role):
    context = Path(tempfile.mkdtemp(prefix='build-' + role + '-', dir=ROOT))
    inputs = {'backend': ['backend/app'], 'frontend': ['frontend-dist'],
              'sandbox': ['runtime/sandbox/run.sh']}
    for relative in inputs[role]:
        source, target = ROOT / relative, context / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir(): shutil.copytree(source, target)
        else: shutil.copyfile(source, target)
    if role == 'sandbox': (context / 'runtime/sandbox/run.sh').chmod(0o755)
    return context


def build():
    s = json.loads(STATE.read_text()); assert s['phase'] == 'building'
    copies = {'backend': 'COPY backend/app /app/app\n',
        'frontend': 'COPY frontend-dist /usr/share/nginx/html\n',
        'sandbox': 'COPY runtime/sandbox/run.sh /usr/local/bin/run.sh\n'}
    for role, body in copies.items():
        if role in s['images']: continue
        assert shutil.disk_usage(ROOT).free >= 8 * 1024**3
        tag = 'webcompiler-functional-' + role + ':' + SHA
        if tag not in s['tags']: s['tags'].append(tag)
        save(s)
        df = ROOT / ('Release.' + role + '.Dockerfile')
        df.write_text('FROM ' + s['bases'][role] + '\nLABEL io.webcompiler.release.owner="' + str(ROOT) + '" org.opencontainers.image.revision="' + SHA + '"\n' + body)
        context = build_context(role)
        output = o.run('docker', 'build', '--pull=false', '--network', 'none', '--memory', '2g', '--memory-swap', '2g',
            '--cpu-quota', '100000', '--cpu-period', '100000', '-t', tag, '-f', str(df), str(context),
            env={**o.BASEENV, 'DOCKER_BUILDKIT': '0'}, timeout=240)
        (ROOT / (role + '-build.log')).write_bytes(output)
        s['images'][role] = o.inspect(tag)['Id']; save(s)
    s['phase'] = 'built'; save(s)
    print(json.dumps({'phase': s['phase'], 'sha': SHA, 'images': s['images'], 'schema_change': False}), flush=True)

def edge(s, configs):
    for role, content in configs.items():
        path = PROD / '.deploy' / (role + '-edge.conf')
        assert path.is_file() and not path.is_symlink()
        assert o.inspect('webcompiler-edge-' + role)['Id'] == s['edge_ids'][role]
        path.write_text(content)
    for cid in s['edge_ids'].values(): o.run('docker', 'exec', cid, 'nginx', '-t')
    for cid in s['edge_ids'].values(): o.run('docker', 'exec', cid, 'nginx', '-s', 'reload')

def fingerprints():
    tables = ['users', 'problems', 'comments', 'code_projects', 'submissions', 'user_problem_scores',
              'contests', 'contest_problems', 'contest_participants', 'contest_submissions', 'password_reset_tokens']
    return {table: o.sql('webcompiler-postgres', "SELECT count(*)::text || ':' || md5(coalesce(string_agg(j,E'\\n' ORDER BY j),'')) FROM (SELECT row_to_json(t)::text j FROM " + table + ' t) q') for table in tables}

def unsettled():
    return int(o.sql('webcompiler-postgres', "SELECT count(*) FROM execution_jobs WHERE status NOT IN ('completed','failed','canceled') OR sandbox_operation IS NOT NULL OR lease_token IS NOT NULL OR lease_until IS NOT NULL"))

def stop_current():
    # Stop admission first, then finish every accepted request before worker exit.
    for n in (1, 2):
        cid = o.inspect(PROJECT + f'-backend-{n}')['Id']
        o.run('docker', 'stop', '--time', '150', cid, timeout=165)
        row = o.inspect(cid)['State']; assert not row['Running'] and not row['OOMKilled'] and row['ExitCode'] in (0, 143)
    deadline = time.monotonic() + 120
    while unsettled():
        assert time.monotonic() < deadline, 'Accepted jobs have not drained'
        time.sleep(1)
    for role in ('worker', 'frontend'):
        cid = o.inspect(PROJECT + '-' + role + '-1')['Id']
        o.run('docker', 'stop', '--time', '150', cid, timeout=165)
        row = o.inspect(cid)['State']; assert not row['Running'] and not row['OOMKilled'] and row['ExitCode'] == 0
    assert unsettled() == 0
    assert not o.run('docker', 'ps', '-q', '--filter', 'label=webcompiler.pool=' + PROJECT + '-production').strip()

def ready(env):
    deadline = time.monotonic() + 120
    for role in ('backend-1', 'backend-2', 'worker-1', 'frontend-1'):
        while o.inspect(PROJECT + '-' + role)['State'].get('Health', {}).get('Status') != 'healthy':
            assert time.monotonic() < deadline, 'Candidate health timed out: ' + role
            time.sleep(1)
    for path in ('http://127.0.0.1:18003/ready', 'http://127.0.0.1:18003/health'):
        with urlopen(path, timeout=10) as response:
            data = json.load(response)
            if path.endswith('/health'): assert data['deploymentSha'] == env['DEPLOY_SHA']
    with urlopen('http://127.0.0.1:15176/.well-known/webcompiler-release.json', timeout=10) as response:
        assert json.load(response)['deployment_sha'] == env['DEPLOY_SHA']

def candidate_smoke(env):
    spec = importlib.util.spec_from_file_location('candidate_smoke', ROOT / 'scripts/e2e_stack_test.py')
    app = importlib.util.module_from_spec(spec); spec.loader.exec_module(app)
    app.FRONTEND_BASE_URL = 'http://127.0.0.1:15176'
    headers = app.login('admin', env['ADMIN_PASSWORD'])
    for language, code in app.LANGUAGE_SMOKE_CODES.items():
        result = app.submit_execution('/api/v1/compiler/run', {'language': language, 'code': code}, headers)
        value = result.get('value') or {}
        assert result.get('ok') and value.get('exit_code') == 0 and value.get('stdout', '').strip() == '42', 'Pre-public execution failed: ' + language
        print('Pre-public execution PASS: ' + language, flush=True)

def rollout():
    s = json.loads(STATE.read_text()); assert s['phase'] == 'built'
    current = json.loads(o.STATE.read_text())
    assert current['source_sha'] == s['old']['source_sha'] and current['phase'] == 'deployed'
    for role, cid in s['old_ids'].items():
        name = PROJECT + '-' + role + ('' if role.startswith('backend-') else '-1')
        assert o.inspect(name)['Id'] == cid
    assert o.inspect('webcompiler-postgres')['Id'] == s['postgres_id']
    s['edge_ids'] = {r: o.inspect('webcompiler-edge-' + r)['Id'] for r in ('backend', 'frontend')}
    s['edge_configs'] = {r: (PROD / '.deploy' / (r + '-edge.conf')).read_text() for r in s['edge_ids']}
    assert '127.0.0.1:18003' in s['edge_configs']['backend'] and '127.0.0.1:15176' in s['edge_configs']['frontend']
    s['phase'] = 'maintenance'; save(s)
    maintenance = {r: 'server { listen 127.0.0.1:' + p + '; add_header Retry-After 120 always; location / { return 503; } }\n' for r, p in [('backend', '18000'), ('frontend', '15173')]}
    services_touched = False
    try:
        edge(s, maintenance)
        services_touched = True
        stop_current()
        s['fingerprints'] = fingerprints(); save(s)
        backup = ROOT / 'pre-update-production.dump'
        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            result = subprocess.run(['docker', 'exec', s['postgres_id'], 'pg_dump', '-U', 'compiler', '-d', 'compiler', '-Fc'], stdout=stream, stderr=subprocess.PIPE, timeout=90)
        assert result.returncode == 0 and backup.stat().st_size > 0, 'Backup failed'
        # Validate the complete archive directory before changing application images.
        o.run('docker', 'exec', '-i', s['postgres_id'], 'pg_restore', '--list', data=backup.read_bytes())
        env = dict(s['old']['env'])
        env.update(DEPLOY_SHA=SHA, BASIC_LB_RUNTIME_ID=uuid4().hex,
            WEBCOMPILER_BACKEND_IMAGE=s['images']['backend'], BASIC_LB_FRONTEND_IMAGE=s['images']['frontend'], SANDBOX_IMAGE=s['images']['sandbox'])
        s['env'] = env; s['phase'] = 'starting'; save(s)
        pc(env, 'up', '--no-build', '--pull', 'never', '--no-deps', '-d', 'backend', 'worker', 'frontend')
        ready(env)
        candidate_smoke(env)
        assert fingerprints() == s['fingerprints'], 'Business rows changed'
        for role in ('redis', 'pgbouncer', 'api-proxy'):
            assert o.inspect(PROJECT + '-' + role + '-1')['Id'] == s['old_ids'][role]
        assert o.inspect('webcompiler-postgres')['Id'] == s['postgres_id']
        edge(s, s['edge_configs'])
        current.update(env=env, source_sha=SHA, backend_id=s['images']['backend'], frontend_id=s['images']['frontend'],
            functional_release_root=str(ROOT), functional_previous_sha=s['old']['source_sha'])
        o.save(current)
        s['phase'] = 'deployed'; save(s)
        print(json.dumps({'phase': 'deployed', 'sha': SHA, 'database_unchanged': True, 'rollback_root': str(ROOT)}), flush=True)
    except BaseException:
        s['phase'] = 'failed'; save(s)
        print('Release failed; maintenance retained. Use the recorded rollback action.', flush=True)
        if services_touched:
            rollback()
        else:
            edge(s, s['edge_configs'])
            s['phase'] = 'rolled-back'; save(s)
        raise

def rollback():
    s = json.loads(STATE.read_text()); assert s['phase'] == 'failed'
    stop_current()
    env = dict(s['old']['env']); env['BASIC_LB_RUNTIME_ID'] = uuid4().hex
    pc(env, 'up', '--no-build', '--pull', 'never', '--no-deps', '-d', 'backend', 'worker', 'frontend')
    ready(env)
    edge(s, s['edge_configs'])
    old = s['old']; old['env'] = env; o.save(old)
    s['phase'] = 'rolled-back'; save(s)
    print('Previous images restored with a fresh incarnation; no database backup overwrite.', flush=True)

def main():
    import fcntl
    assert os.environ.get('WEBCOMPILER_DEPLOY_LOCK_HELD') == '1'
    project_root = Path(os.environ['PROJECT_ROOT']).resolve()
    assert Path(os.readlink('/proc/self/fd/9')) == project_root / '.deploy/deploy.lock'
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
    configure(project_root, os.environ['DEPLOY_SHA'])
    assert o.run('git', '-C', str(PROD), 'rev-parse', 'HEAD').decode().strip() == SHA
    prepare()
    rollout()

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not print credentials, subprocess argv, SQL or private state.
        print('Basic-pool deployment stopped: ' + type(exc).__name__ + '. Inspect private release journal.', file=sys.stderr)
        raise SystemExit(1)
