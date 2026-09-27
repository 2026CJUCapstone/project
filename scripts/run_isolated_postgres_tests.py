"""Existing-image, socket-only PostgreSQL integration tests; no deployment.

Pack current Python sources locally, transfer to an owned temporary root, then
explicitly execute there. Neither container has network or a Docker socket.
Database data lives on a bounded tmpfs; no named/anonymous data volumes.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import time
import uuid

PG_IMAGE = 'sha256:20edbde7749f822887a1a022ad526fde0a47d6b2be9a8364433605cf65099416'
TEST_IMAGE = 'sha256:d7ab3494aad02142fe7fc4abee8175283a2ce68e57cfc7bb24da034753065930'
REDIS_IMAGE = 'sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf'
LABEL = 'webcompiler.isolated-postgres'
TESTS = (
    'tests/test_durable_queue.py',
    'tests/test_worker_schema_migration.py',
    'tests/test_authoring_migration.py',
    'tests/test_contest_postgres.py',
    'tests/test_queue_process_restart.py',
    'tests/test_execution_worker_process.py',
)
RECENT_REGRESSION_TESTS = (
    'tests/test_contests.py',
    'tests/test_contest_package_authoring.py',
    'tests/test_authoring_validation.py',
    'tests/test_measured_judge.py',
    'tests/test_execution_worker.py',
    'tests/test_execution_resource_budget.py',
    'tests/test_judge_policy.py',
    'tests/test_judge_test_manifest.py',
    'tests/test_problem_suite_boundaries.py',
    'tests/test_private_import_cli.py',
    'tests/test_private_bundle_apply_cli.py',
    'tests/test_stored_case_integration.py',
    'tests/test_test_data_transport.py',
    'tests/test_judge_supervisor_record.py',
    'tests/test_contest_submit_resource_injection.py',
    'tests/test_practice_submit_resource_injection.py',
    'tests/test_problem_delete_submit_race.py',
    'tests/test_freshman_measurement_summary.py',
    'tests/test_freshman_draft_summary.py',
)
PREFIXES = ('backend/app/', 'backend/tests/', 'runtime/sandbox/', 'scripts/', 'tools/freshman_contest/')
CONFIG_FILES = ('frontend/nginx.conf', 'deploy/nginx/webcompiler.locations.conf')
FIXED_TEST_ASSETS = (
    'tools/freshman_contest/corpus-manifest-draft-v1.json',
    'tools/freshman_contest/corpus-manifest-draft-v2.json',
    'docs/freshman-contest-statements-a-i-2026-09-26.md',
    'docs/banks-reference-proof-2026-09-26.md',
)
FIXED_FILES = CONFIG_FILES + FIXED_TEST_ASSETS
SOLUTION_PREFIX = 'tools/freshman_contest/solutions/'
SOLUTION_SUFFIXES = {'.bpp', '.c', '.cpp', '.java', '.js', '.py'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pack(base, output):
    manifest = {}
    with output.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for prefix in PREFIXES:
            for path in sorted((base / prefix).rglob('*.py')):
                if path.is_symlink() or '__pycache__' in path.parts:
                    continue
                data = path.read_bytes()
                name = path.relative_to(base).as_posix()
                info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o444
                archive.addfile(info, io.BytesIO(data))
                manifest[name] = digest(data)
        for path in sorted((base / SOLUTION_PREFIX).rglob('*')):
            if path.is_symlink() or not path.is_file() or path.suffix not in SOLUTION_SUFFIXES:
                continue
            data = path.read_bytes()
            name = path.relative_to(base).as_posix()
            if name in manifest:  # Python solutions were already packed above.
                continue
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o444
            archive.addfile(info, io.BytesIO(data))
            manifest[name] = digest(data)
        for name in FIXED_FILES:
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('Required fixed config is not a regular file')
            data = path.read_bytes()
            info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o444
            archive.addfile(info, io.BytesIO(data))
            manifest[name] = digest(data)
    return dict(archiveSha256=digest(output.read_bytes()), files=manifest)


def unpack(archive, target, expected):
    data = archive.read_bytes()
    if len(data) > 8 * 1024**2 or digest(data) != expected:
        raise ValueError('Source archive identity/cap mismatch')
    target.mkdir(mode=0o755)
    manifest = {}; total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as source:
        for member in source:
            path = PurePosixPath(member.name)
            total += member.size
            if (not member.isfile() or path.is_absolute() or '..' in path.parts
                or str(path) != member.name or '\\' in member.name
                or not ((member.name.startswith(PREFIXES) and path.suffix == '.py')
                        or member.name in FIXED_FILES
                        or (member.name.startswith(SOLUTION_PREFIX)
                            and path.suffix in SOLUTION_SUFFIXES))
                or member.name in manifest or member.size > 2 * 1024**2
                or total > 32 * 1024**2 or len(manifest) >= 1500):
                raise ValueError('Unexpected source member')
            content = source.extractfile(member).read()
            destination = target.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(content)
            destination.chmod(0o444)
            manifest[member.name] = digest(content)
    for name in ('backend/app/main.py', 'backend/tests/conftest.py', 'backend/tests/test_contest_postgres.py',
                 *FIXED_FILES):
        if name not in manifest:
            raise ValueError('Required current source missing')
    return manifest


def command(*args, timeout=15):
    result = subprocess.run(['docker', *args], capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Docker {args[0]} failed: {result.stderr.decode(errors="replace")[:2000]}')
    return result.stdout


def common(name, token, user):
    return ['--pull=never', '--name=' + name, '--label=' + LABEL + '=' + token,
        '--network=none', '--read-only', '--user=' + user, '--cap-drop=ALL',
        '--security-opt=no-new-privileges', '--memory=512m', '--memory-swap=512m',
        '--cpus=0.5', '--pids-limit=48', '--ulimit=nofile=128:128',
        '--log-driver=none', '--no-healthcheck']


def database_options(root, token):
    return [*common('webcompiler-pg-test-' + token, token, '70:70'),
        '--tmpfs=/var/lib/postgresql/data:rw,noexec,nosuid,nodev,size=256m,uid=70,gid=70,mode=0700',
        '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777',
        '--mount', f'type=bind,src={root / "socket"},dst=/socket',
        '--entrypoint=/bin/sh', PG_IMAGE, '-ec',
        'initdb -D /var/lib/postgresql/data -U isolated -A trust --no-locale --encoding=UTF8 >/tmp/init.log; '
        'exec postgres -D /var/lib/postgresql/data -c listen_addresses= '
        '-c unix_socket_directories=/socket -c shared_buffers=32MB -c max_connections=25 '
        '-c work_mem=2MB -c maintenance_work_mem=16MB -c max_wal_size=64MB '
        '-c temp_file_limit=65536 -c statement_timeout=20000 -c lock_timeout=10000']


def redis_options(root, token):
    options = common('webcompiler-redis-test-' + token, token, '65534:65534')
    memory = options.index('--memory=512m')
    options[memory] = '--memory=128m'
    options[options.index('--memory-swap=512m')] = '--memory-swap=128m'
    return [*options,
        '--tmpfs=/data:rw,noexec,nosuid,nodev,size=32m,uid=65534,gid=65534,mode=0700',
        '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777',
        '--mount', f'type=bind,src={root / "socket"},dst=/socket',
        '--entrypoint=redis-server', REDIS_IMAGE,
        '--port', '0', '--unixsocket', '/socket/redis.sock', '--unixsocketperm', '777',
        '--save', '', '--appendonly', 'no']


def selected_tests(*, only_restart=False, only_managed_worker=False,
                   only_contest_boundaries=False, only_frozen_receipt=False,
                   only_recent_regressions=False):
    if sum((only_restart, only_managed_worker, only_contest_boundaries,
            only_frozen_receipt, only_recent_regressions)) > 1:
        raise ValueError('Select one isolated test mode')
    if only_recent_regressions:
        return RECENT_REGRESSION_TESTS, None
    if only_frozen_receipt:
        return ('tests/test_measured_judge.py', 'tests/test_execution_worker.py'), (
            'frozen_receipt_remains_valid or measured_retry_uses_receipt_deadline')
    if only_contest_boundaries:
        return ('tests/test_contests.py',), 'test_existing_problem_cannot_bypass_contest_test_suite_bounds'
    if only_managed_worker:
        return ('tests/test_managed_worker_isolated.py',), 'postgres'
    if only_restart:
        return ('tests/test_execution_worker_process.py',), 'postgres'
    return TESTS, 'postgres'


def test_options(root, token, *, only_restart=False, only_managed_worker=False,
                 only_contest_boundaries=False, only_frozen_receipt=False,
                 only_recent_regressions=False):
    tests, keyword = selected_tests(only_restart=only_restart,
        only_managed_worker=only_managed_worker, only_contest_boundaries=only_contest_boundaries,
        only_frozen_receipt=only_frozen_receipt,
        only_recent_regressions=only_recent_regressions)
    env = dict(ENVIRONMENT='development', DATABASE_URL='sqlite:////tmp/app-import.db',
        SECRET_KEY='isolated-integration-only-not-production-20260927',
        AUTO_INITIALIZE_DB='true', EMBEDDED_EXECUTION_WORKER='true', REDIS_URL='',
        TEST_POSTGRES_URL='postgresql+psycopg2://isolated@/postgres?host=/socket',
        PYTHONDONTWRITEBYTECODE='1', PYTHONPATH='/source/backend:/source', HOME='/tmp',
        TEST_REDIS_URL='unix:///socket/redis.sock?db=0' if only_managed_worker else '',
        RUN_SANDBOX_INTEGRATION='0')
    pytest_options = [
        '-q', '-ra', '--tb=short', '-p', 'no:cacheprovider',
        '--junitxml=/output/results.xml',
    ]
    if keyword:
        pytest_options.extend(('-k', keyword))
    return [*common('webcompiler-pg-client-' + token, token, '65534:65534'),
        '--tmpfs=/tmp:rw,nosuid,nodev,size=128m,mode=1777',
        '--mount', f'type=bind,src={root / "socket"},dst=/socket,readonly',
        '--mount', f'type=bind,src={root / "source"},dst=/source,readonly',
        '--mount', f'type=bind,src={root / "output"},dst=/output',
        '--workdir=/source/backend',
        *[arg for key, value in env.items() for arg in ('-e', key + '=' + value)],
        '--entrypoint=/opt/venv/bin/python', TEST_IMAGE, '-m', 'pytest',
        *pytest_options, *tests]


def execute(root, expected, *, only_restart=False, only_managed_worker=False,
            only_contest_boundaries=False, only_frozen_receipt=False,
            only_recent_regressions=False):
    tests, _ = selected_tests(only_restart=only_restart,
        only_managed_worker=only_managed_worker, only_contest_boundaries=only_contest_boundaries,
        only_frozen_receipt=only_frozen_receipt,
        only_recent_regressions=only_recent_regressions)
    if (not re.fullmatch(r'/tmp/webcompiler-launcher-test\.[A-Za-z0-9]+', str(root))
        or root.resolve() != root or root.stat().st_uid != os.getuid()):
        raise ValueError('Exact owned isolated root required')
    fields = {line.split(':')[0]: int(line.split()[1]) * 1024
              for line in Path('/proc/meminfo').read_text().splitlines()}
    if fields['MemAvailable'] < 3 * 1024**3 or shutil.disk_usage(root).free < 4 * 1024**3:
        raise RuntimeError('Capacity safety floor not met')
    for image in (PG_IMAGE, TEST_IMAGE, *((REDIS_IMAGE,) if only_managed_worker else ())):
        if command('image', 'inspect', '--format={{.Id}}', image).decode().strip() != image:
            raise RuntimeError('Existing immutable image required')
    files = unpack(root / 'source.tar.gz', root / 'source', expected)
    root.chmod(0o755)
    for name in ('socket', 'output'):
        directory = root / name; directory.mkdir(mode=0o777); directory.chmod(0o777)
    token = uuid.uuid4().hex; containers = []
    report = dict(scope=('real PostgreSQL/Redis/app.worker processes with synthetic execution lane; '
                         'no Docker sandbox proof') if only_managed_worker else
                        'real PostgreSQL; synthetic judge; no Docker-backed app.worker crash proof',
        mode='recent-regressions' if only_recent_regressions else
             'frozen-receipt-retry' if only_frozen_receipt else
             'contest-boundary-http' if only_contest_boundaries else
             'managed-worker-process-restart' if only_managed_worker else
             'execution-worker-process-restart' if only_restart else 'postgresql-transactions',
        harnessSha256=digest(Path(__file__).read_bytes()),
        sourceSha256=expected, sourceFiles=files, postgresImage=PG_IMAGE, testImage=TEST_IMAGE,
        redisImage=REDIS_IMAGE if only_managed_worker else None,
        tests=list(tests),
        owner=token, network='none', storage='bounded tmpfs',
        maxSeconds=300, memoryBytesPerContainer=512 * 1024**2, cpuPerContainer=0.5)
    def create(options):
        cid = command('create', *options).decode().strip()
        if not re.fullmatch('[a-f0-9]{64}', cid):
            raise RuntimeError('Invalid created container identity')
        containers.append(cid)
        return cid
    try:
        pg = create(database_options(root, token)); command('start', pg)
        for _ in range(30):
            result = subprocess.run(['docker', 'exec', pg, 'pg_isready', '-h', '/socket', '-U', 'isolated'],
                                    capture_output=True, timeout=5)
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Isolated PostgreSQL readiness timed out')
        report['database'] = command('exec', pg, 'psql', '-h', '/socket', '-U', 'isolated', '-d', 'postgres',
            '-Atc', 'SELECT version(); SHOW listen_addresses; SHOW data_directory; SHOW server_encoding;').decode()
        if report['database'].splitlines()[-1] != 'UTF8':
            raise RuntimeError('UTF8 database required for Korean content')
        if only_managed_worker:
            redis = create(redis_options(root, token)); command('start', redis)
            for _ in range(30):
                response = subprocess.run(['docker', 'exec', redis, 'redis-cli',
                    '-s', '/socket/redis.sock', 'ping'], capture_output=True, timeout=5)
                if response.returncode == 0 and response.stdout.strip() == b'PONG':
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError('Isolated Redis readiness timed out')
            report['redis'] = 'Unix socket only; no TCP listener'
        client = create(test_options(root, token, only_restart=only_restart,
            only_managed_worker=only_managed_worker, only_contest_boundaries=only_contest_boundaries,
            only_frozen_receipt=only_frozen_receipt,
            only_recent_regressions=only_recent_regressions))
        result = subprocess.run(['docker', 'start', '-a', client], capture_output=True, timeout=300)
        report.update(exitCode=result.returncode, stdout=result.stdout.decode(errors='replace'),
                      stderr=result.stderr.decode(errors='replace'))
        report['leftoverSchemas'] = command('exec', pg, 'psql', '-h', '/socket', '-U', 'isolated', '-d', 'postgres',
            '-Atc', "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'audit_%' ORDER BY nspname").decode().splitlines()
        report['states'] = [json.loads(command('inspect', '--format={{json .State}}', cid)) for cid in containers]
        if report['leftoverSchemas']:
            report['exitCode'] = 1
    except Exception as error:
        report.update(exitCode=1, error=f'{type(error).__name__}: {error}')
    finally:
        cleanup = []
        for cid in reversed(containers):
            try:
                labels = json.loads(command('inspect', '--format={{json .Config.Labels}}', cid))
                if labels.get(LABEL) != token:
                    raise RuntimeError('Cleanup ownership mismatch')
                command('rm', '-f', cid)
                cleanup.append(dict(container=cid, removed=True))
            except Exception as error:
                cleanup.append(dict(container=cid, removed=False, error=str(error)))
        report['cleanup'] = cleanup
        if any(not item['removed'] for item in cleanup):
            report['exitCode'] = 1
        with (root / 'postgres-report.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key != 'sourceFiles'}), flush=True)
    return report['exitCode']


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', type=Path)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--execute', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--only-restart', action='store_true')
    mode.add_argument('--only-managed-worker', action='store_true')
    mode.add_argument('--only-contest-boundaries', action='store_true')
    mode.add_argument('--only-frozen-receipt', action='store_true')
    mode.add_argument('--only-recent-regressions', action='store_true')
    return parser


def parse_arguments(argv=None):
    parser = argument_parser()
    return parser.parse_args(argv)


if __name__ == '__main__':
    parser = argument_parser()
    args = parser.parse_args()
    if args.pack and not args.execute:
        value = pack(Path(__file__).resolve().parents[1], args.pack)
        print(json.dumps(dict(archiveSha256=value['archiveSha256'], fileCount=len(value['files']))))
    elif args.execute and args.root and re.fullmatch('[a-f0-9]{64}', args.sha256 or ''):
        raise SystemExit(execute(args.root, args.sha256, only_restart=args.only_restart,
            only_managed_worker=args.only_managed_worker,
            only_contest_boundaries=args.only_contest_boundaries,
            only_frozen_receipt=args.only_frozen_receipt,
            only_recent_regressions=args.only_recent_regressions))
    else:
        parser.error('Use --pack or explicit --execute --root --sha256')
