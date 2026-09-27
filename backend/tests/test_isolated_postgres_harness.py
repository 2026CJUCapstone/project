"""Offline contract tests for the isolated PostgreSQL harness."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'run_isolated_postgres_tests.py'
spec = importlib.util.spec_from_file_location('isolated_postgres_harness', SCRIPT)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def archive_bytes(entries):
    """Build a tiny test archive from (name, kind, data) records."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, kind, data in entries:
            member = tarfile.TarInfo(name)
            if kind == 'file':
                member.size = len(data)
                member.mode = 0o444
                archive.addfile(member, io.BytesIO(data))
            elif kind == 'symlink':
                member.type = tarfile.SYMTYPE
                member.linkname = data.decode()
                archive.addfile(member)
            else:
                raise AssertionError('unknown archive member kind')
    return output.getvalue()


def write_archive(tmp_path, entries):
    archive = tmp_path / 'source.tar.gz'
    archive.write_bytes(archive_bytes(entries))
    return archive


@pytest.mark.parametrize('entries', [
    [('backend/app/../escape.py', 'file', b'bad')],
    [('backend/app/link.py', 'symlink', b'/etc/passwd')],
    [('backend/app/one.py', 'file', b'one'), ('backend/app/one.py', 'file', b'two')],
    [('backend/app/large.py', 'file', b'x' * (2 * 1024**2 + 1))],
    [('frontend/secret.conf', 'file', b'bad')],
], ids=('traversal', 'symlink', 'duplicate', 'member-cap', 'unknown-config'))
def test_unpack_rejects_unsafe_or_unbounded_members(tmp_path, entries):
    archive = write_archive(tmp_path, entries)
    with pytest.raises(ValueError, match='Unexpected source member'):
        harness.unpack(archive, tmp_path / 'source', harness.digest(archive.read_bytes()))


def test_unpack_rejects_wrong_archive_identity_before_extraction(tmp_path):
    archive = write_archive(tmp_path, [('backend/app/main.py', 'file', b'pass\n')])
    with pytest.raises(ValueError, match='identity/cap'):
        harness.unpack(archive, tmp_path / 'source', '0' * 64)
    assert not (tmp_path / 'source').exists()


def test_unpack_requires_the_fixed_source_identity_set(tmp_path):
    archive = write_archive(tmp_path, [('backend/app/main.py', 'file', b'pass\n')])
    with pytest.raises(ValueError, match='Required current source missing'):
        harness.unpack(archive, tmp_path / 'source', harness.digest(archive.read_bytes()))


def options_environment(options):
    values = {}
    for index, value in enumerate(options[:-1]):
        if value == '-e':
            key, item = options[index + 1].split('=', 1)
            values[key] = item
    return values


def mounts(options):
    return [options[index + 1] for index, value in enumerate(options[:-1]) if value == '--mount']


def test_client_has_no_network_docker_socket_or_writable_source(tmp_path):
    options = harness.test_options(tmp_path, 'a' * 32)
    values = options_environment(options)
    bindings = mounts(options)

    assert '--network=none' in options
    assert '--read-only' in options
    assert not any('/var/run/docker.sock' in value for value in options)
    assert f'type=bind,src={tmp_path / "source"},dst=/source,readonly' in bindings
    assert f'type=bind,src={tmp_path / "socket"},dst=/socket,readonly' in bindings
    assert f'type=bind,src={tmp_path / "output"},dst=/output' in bindings
    assert all('dst=/source' not in value or value.endswith(',readonly') for value in bindings)
    assert values['PYTHONPATH'] == '/source/backend:/source'


def test_database_uses_only_bounded_tmpfs_for_its_data_directory(tmp_path):
    options = harness.database_options(tmp_path, 'b' * 32)
    bindings = mounts(options)

    assert '--network=none' in options
    assert '--read-only' in options
    assert '--tmpfs=/var/lib/postgresql/data:rw,noexec,nosuid,nodev,size=256m,uid=70,gid=70,mode=0700' in options
    assert '--encoding=UTF8' in options[-1]
    assert '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777' in options
    assert f'type=bind,src={tmp_path / "socket"},dst=/socket' in bindings
    assert not any('dst=/var/lib/postgresql/data' in value for value in bindings)
    assert not any(value == '-v' or value.startswith('--volume') for value in options)


def test_client_uses_fixed_socket_only_test_urls_and_no_production_credentials(tmp_path):
    options = harness.test_options(tmp_path, 'c' * 32)
    values = options_environment(options)

    assert values['DATABASE_URL'] == 'sqlite:////tmp/app-import.db'
    assert values['TEST_POSTGRES_URL'] == 'postgresql+psycopg2://isolated@/postgres?host=/socket'
    assert values['TEST_POSTGRES_URL'].endswith('host=/socket')
    assert values['REDIS_URL'] == values['TEST_REDIS_URL'] == ''
    assert values['AUTO_INITIALIZE_DB'] == values['EMBEDDED_EXECUTION_WORKER'] == 'true'
    assert values['SECRET_KEY'].startswith('isolated-')
    assert '-not-production-' in values['SECRET_KEY']
    assert all('postgresql://' not in value or value == values['TEST_POSTGRES_URL']
               for value in values.values())


def test_harness_module_compiles_and_uses_immutable_images():
    compile(SCRIPT.read_text(encoding='utf-8'), str(SCRIPT), 'exec')
    assert harness.PG_IMAGE.startswith('sha256:') and len(harness.PG_IMAGE) == 71
    assert harness.TEST_IMAGE.startswith('sha256:') and len(harness.TEST_IMAGE) == 71
    assert harness.REDIS_IMAGE.startswith('sha256:') and len(harness.REDIS_IMAGE) == 71
    assert hashlib.sha256(b'fixture').hexdigest() == harness.digest(b'fixture')


def test_managed_worker_mode_adds_only_disposable_socket_redis(tmp_path):
    redis = harness.redis_options(tmp_path, 'd' * 32)
    client = harness.test_options(tmp_path, 'd' * 32, only_managed_worker=True)
    values = options_environment(client)
    assert '--network=none' in redis and '--read-only' in redis
    assert '--memory=128m' in redis and '--memory-swap=128m' in redis
    assert '--port' in redis and redis[redis.index('--port') + 1] == '0'
    assert '--unixsocket' in redis and redis[redis.index('--unixsocket') + 1] == '/socket/redis.sock'
    assert not any('/var/run/docker.sock' in value for value in redis + client)
    assert f'type=bind,src={tmp_path / "socket"},dst=/socket' in mounts(redis)
    assert f'type=bind,src={tmp_path / "socket"},dst=/socket,readonly' in mounts(client)
    assert values['TEST_REDIS_URL'] == 'unix:///socket/redis.sock?db=0'
    assert values['REDIS_URL'] == ''
    assert 'tests/test_managed_worker_isolated.py' in client


def test_contest_boundary_mode_selects_only_owned_http_regression(tmp_path):
    tests, keyword = harness.selected_tests(only_contest_boundaries=True)
    options = harness.test_options(tmp_path, 'e' * 32, only_contest_boundaries=True)
    assert tests == ('tests/test_contests.py',)
    assert keyword == 'test_existing_problem_cannot_bypass_contest_test_suite_bounds'
    assert options[-1] == tests[0]
    assert options[options.index('-k') + 1] == keyword
    assert '--network=none' in options and '--read-only' in options
    assert not any('/var/run/docker.sock' in value for value in options)
    with pytest.raises(ValueError, match='one isolated test mode'):
        harness.selected_tests(only_contest_boundaries=True, only_restart=True)


def test_frozen_receipt_mode_selects_only_prior_policy_regressions(tmp_path):
    tests, keyword = harness.selected_tests(only_frozen_receipt=True)
    options = harness.test_options(tmp_path, 'f' * 32, only_frozen_receipt=True)
    assert tests == ('tests/test_measured_judge.py', 'tests/test_execution_worker.py')
    assert 'frozen_receipt_remains_valid' in keyword
    assert 'measured_retry_uses_receipt_deadline' in keyword
    assert options[options.index('-k') + 1] == keyword
    assert options[-2:] == list(tests)
    assert '--network=none' in options and '--read-only' in options
    assert not any('/var/run/docker.sock' in value for value in options)


def test_recent_regressions_mode_selects_exact_modules_without_keyword_filter(tmp_path):
    expected = (
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
        'tests/test_freshman_measurement_summary.py',
        'tests/test_freshman_draft_summary.py',
    )
    tests, keyword = harness.selected_tests(only_recent_regressions=True)
    options = harness.test_options(tmp_path, 'g' * 32, only_recent_regressions=True)

    assert tests == harness.RECENT_REGRESSION_TESTS == expected
    assert keyword is None
    assert '-k' not in options
    assert options[-len(expected):] == list(expected)
    assert '--network=none' in options and '--read-only' in options
    assert not any('/var/run/docker.sock' in value for value in options)


def test_recent_regression_archive_includes_exact_draft_summary_manifests(tmp_path):
    archive = tmp_path / 'source.tar.gz'
    packed = harness.pack(harness.Path(__file__).resolve().parents[2], archive)
    for name in harness.FIXED_TEST_ASSETS:
        assert name in packed['files']
    target = tmp_path / 'unpacked'
    extracted = harness.unpack(archive, target, packed['archiveSha256'])
    for name in harness.FIXED_TEST_ASSETS:
        assert extracted[name] == packed['files'][name]
    solution_root = harness.Path(__file__).resolve().parents[2] / harness.SOLUTION_PREFIX
    expected_solutions = {
        path.relative_to(harness.Path(__file__).resolve().parents[2]).as_posix()
        for path in solution_root.rglob('*')
        if path.is_file() and not path.is_symlink() and path.suffix in harness.SOLUTION_SUFFIXES
    }
    assert expected_solutions
    assert expected_solutions <= packed['files'].keys()
    assert expected_solutions <= extracted.keys()


def test_recent_regressions_mode_is_exclusive_with_existing_modes():
    with pytest.raises(ValueError, match='one isolated test mode'):
        harness.selected_tests(only_recent_regressions=True, only_frozen_receipt=True)


def test_recent_regressions_cli_mode_is_explicit_and_mutually_exclusive():
    args = harness.parse_arguments(['--only-recent-regressions'])
    assert args.only_recent_regressions is True
    with pytest.raises(SystemExit):
        harness.parse_arguments(['--only-recent-regressions', '--only-restart'])
