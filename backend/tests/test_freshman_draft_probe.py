"""Offline identity tests for the separate frozen-draft measurement mode."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import stat
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT, ROOT / "scripts"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from tools.freshman_contest.coverage_cases import iter_coverage_cases
import verify_freshman_measurements as probe
import build_freshman_measurement_package as package_builder
import run_isolated_runtime_matrix as host_probe
import summarize_freshman_measurements as aggregator


BASE = ROOT / "tools" / "freshman_contest"
SOURCE_FILES = ("a_i.py", "banks.py", "stress_cases.py", "coverage_cases.py", "banks_stress_cases.py")
MANIFEST_NAME = "corpus-manifest-draft-v2.json"


def _test_base(tmp_path: Path) -> Path:
    for name in (*SOURCE_FILES, MANIFEST_NAME):
        shutil.copyfile(BASE / name, tmp_path / name)
    return tmp_path


def test_draft_probe_uses_exact_separate_79_case_manifest() -> None:
    hashes = set()
    total = 0
    for letter in probe.LETTERS:
        samples, hidden, identities, manifest_hash = probe.draft_cases_for(letter, BASE)
        assert len(samples) == probe.DRAFT_SAMPLE_COUNTS[letter]
        assert len(samples) + len(hidden) == probe.DRAFT_CASE_COUNTS[letter]
        assert [row["visibility"] for row in identities] == ["sample"] * len(samples) + ["hidden"] * len(hidden)
        assert len({row["name"] for row in identities}) == len(identities)
        hashes.add(manifest_hash)
        total += len(identities)
    assert total == 79
    assert len(hashes) == 1
    assert sum(len(probe.cases_for(letter)[0]) for letter in probe.LETTERS) == 31
    assert not any(row["visibility"] == "sample" for row in probe.draft_cases_for("B", BASE)[2][3:])
    assert len(tuple(iter_coverage_cases("B"))) == 213  # 216 checked offline, only 6 measured


def test_frozen_manifest_and_archive_identities_are_aligned() -> None:
    manifest = json.loads((BASE / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["manifestHash"] == probe.FROZEN_DRAFT_HASH == aggregator.FROZEN_DRAFT_HASH
    assert hashlib.sha256(package_builder.build_archive_bytes(ROOT)).hexdigest() == host_probe.DRAFT_REFERENCE_ARCHIVE_SHA256
    assert hashlib.sha256(package_builder.build_archive_bytes(ROOT, include_slow=True)).hexdigest() == host_probe.SLOW_REFERENCE_ARCHIVE_SHA256
    assert 10_000 + max(probe.DRAFT_CASE_COUNTS.values()) * probe.DRAFT_DIAGNOSTIC_RUN_WALL_MS + 5_000 <= 120_000


def test_staged_reference_archive_identity_when_available() -> None:
    archive = ROOT / '.deploy/freshman-measurement-package-v1.tar.gz'
    if not archive.is_file():
        pytest.skip('historical reference archive is an external staged artifact')
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == host_probe.REFERENCE_ARCHIVE_SHA256


def test_host_watchdog_covers_every_frozen_inner_deadline_without_becoming_unbounded() -> None:
    expected = {
        ('mechanics', 'all'): 780,
        ('mechanics', 'bpp'): 150,
        ('freshman', 'python'): 520,
        ('freshman-candidate', 'bpp'): 520,
        ('freshman-draft', 'python'): 842,
        ('freshman-draft-candidate', 'bpp'): 842,
        ('freshman-slow', 'python'): 198,
        ('bpp-diagnostic', 'bpp'): 168,
    }
    # The exact draft count is tied to the archive/manifest check above.
    assert sum(probe.DRAFT_CASE_COUNTS.values()) == host_probe.DRAFT_CASE_COUNT == 79
    assert sum(len(probe.cases_for(letter)[0]) for letter in probe.LETTERS) == host_probe.REFERENCE_CASE_COUNT == 31
    for key, seconds in expected.items():
        assert host_probe.controller_timeout_seconds(*key) == seconds
        assert 60 <= seconds <= 1200
    with pytest.raises(ValueError, match='Unknown'):
        host_probe.controller_timeout_seconds('other', 'python')


def test_host_watchdog_evidence_serializes_exact_budget_language_and_elapsed_time() -> None:
    evidence = host_probe.controller_watchdog_evidence('freshman-draft', 'python', 12.3456, True)
    assert evidence == {
        'language': 'python',
        'controllerTimeoutSeconds': 842,
        'controllerTimeoutBasis': {
            'kind': 'frozen-suite-inner-deadlines-plus-reviewed-overhead',
            'frozenInnerDeadlineSeconds': 782,
            'reviewedNonJobOverheadSeconds': 60,
        },
        'controllerElapsedSeconds': 12.346,
        'timedOut': True,
    }


def test_runtime_harness_requires_exact_nondefault_dedicated_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket = tmp_path / 'isolated-docker.sock'
    socket.write_bytes(b'fixture')
    daemon_id = 'dedicated-test-daemon'
    expected = hashlib.sha256(daemon_id.encode()).hexdigest()
    calls = []

    def docker_command(*args, **kwargs):
        calls.append((args, kwargs, host_probe.os.environ.get('DOCKER_HOST')))
        return daemon_id.encode()

    monkeypatch.delenv('DOCKER_HOST', raising=False)
    resolved, actual = host_probe.bind_dedicated_daemon(
        socket,
        expected,
        socket_checker=lambda candidate: candidate == socket.resolve(),
        docker_command=docker_command,
    )
    assert resolved == socket.resolve()
    assert actual == expected
    assert calls == [(('info', '--format={{.ID}}'), {'timeout': 10},
                       'unix://' + socket.resolve().as_posix())]


@pytest.mark.parametrize('expected', ['', '0' * 63, 'G' * 64])
def test_runtime_harness_rejects_invalid_daemon_fingerprint_before_docker(
    tmp_path: Path, expected: str
) -> None:
    socket = tmp_path / 'isolated-docker.sock'
    socket.write_bytes(b'fixture')
    with pytest.raises(ValueError, match='SHA-256'):
        host_probe.bind_dedicated_daemon(
            socket,
            expected,
            socket_checker=lambda _candidate: True,
            docker_command=lambda *_args, **_kwargs: pytest.fail('Docker must not be contacted'),
        )


def test_runtime_harness_rejects_default_or_wrong_dedicated_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(RuntimeError, match='Default'):
        host_probe.bind_dedicated_daemon(
            Path('/var/run/docker.sock'),
            '0' * 64,
            socket_checker=lambda _candidate: True,
            docker_command=lambda *_args, **_kwargs: pytest.fail('Docker must not be contacted'),
        )

    socket = tmp_path / 'isolated-docker.sock'
    socket.write_bytes(b'fixture')
    monkeypatch.setenv('DOCKER_HOST', 'unix:///previous/daemon.sock')
    with pytest.raises(RuntimeError, match='identity mismatch'):
        host_probe.bind_dedicated_daemon(
            socket,
            '0' * 64,
            socket_checker=lambda _candidate: True,
            docker_command=lambda *_args, **_kwargs: b'another-daemon',
        )
    assert host_probe.os.environ['DOCKER_HOST']=='unix:///previous/daemon.sock'


def test_runtime_harness_clears_new_daemon_binding_when_identity_probe_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket=tmp_path/'isolated-docker.sock'
    socket.write_bytes(b'fixture')
    monkeypatch.delenv('DOCKER_HOST',raising=False)
    with pytest.raises(OSError,match='probe failed'):
        host_probe.bind_dedicated_daemon(
            socket,'0'*64,
            socket_checker=lambda _candidate:True,
            docker_command=lambda *_args,**_kwargs:(_ for _ in ()).throw(OSError('probe failed')),
        )
    assert 'DOCKER_HOST' not in host_probe.os.environ


def test_runtime_harness_rejects_unbounded_socket_path_before_docker(tmp_path: Path) -> None:
    socket = tmp_path / 'isolated,docker.sock'
    socket.write_bytes(b'fixture')
    with pytest.raises(ValueError, match='path'):
        host_probe.bind_dedicated_daemon(
            socket,
            '0' * 64,
            socket_checker=lambda _candidate: True,
            docker_command=lambda *_args, **_kwargs: pytest.fail('Docker must not be contacted'),
        )


def test_runtime_harness_requires_owner_only_canonical_root(tmp_path: Path) -> None:
    safe=SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=123)
    assert host_probe.require_private_root(
        tmp_path,platform_name='posix',effective_uid=123,
        stat_reader=lambda _path:safe,
    )==tmp_path.resolve()
    for metadata in (
        SimpleNamespace(st_mode=stat.S_IFDIR|0o770,st_uid=123),
        SimpleNamespace(st_mode=stat.S_IFLNK|0o700,st_uid=123),
        SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_uid=456),
    ):
        with pytest.raises(RuntimeError,match='owner-only'):
            host_probe.require_private_root(
                tmp_path,platform_name='posix',effective_uid=123,
                stat_reader=lambda _path,value=metadata:value,
            )


def test_reference_probe_reuses_private_empty_workspace_guard(tmp_path: Path) -> None:
    workspace=tmp_path/'webcompiler-launcher-test.Reference123'/'work'
    workspace.parent.mkdir()
    workspace.mkdir()
    safe=SimpleNamespace(st_mode=stat.S_IFDIR|0o700)
    assert probe.require_disposable_workspace(
        workspace,expected_parent=tmp_path,metadata=safe)==workspace.resolve()
    (workspace/'jobs').mkdir()
    with pytest.raises(RuntimeError,match='Private empty'):
        probe.require_disposable_workspace(workspace,expected_parent=tmp_path,metadata=safe)
    (workspace/'jobs').rmdir()
    with pytest.raises(RuntimeError,match='Private empty'):
        probe.require_disposable_workspace(
            workspace,expected_parent=tmp_path,
            metadata=SimpleNamespace(st_mode=stat.S_IFLNK|0o700))
    with pytest.raises(RuntimeError,match='Exact disposable'):
        probe.require_disposable_workspace(
            workspace,expected_parent=tmp_path.parent,metadata=safe)


def test_reference_probe_rejects_symlinked_jobs_path(tmp_path: Path) -> None:
    workspace=tmp_path/'webcompiler-launcher-test.ReferenceLinks'/'work'
    workspace.mkdir(parents=True)
    jobs=workspace/'jobs'
    try:
        jobs.symlink_to(workspace/'missing-jobs-target',target_is_directory=True)
    except OSError as error:
        pytest.skip(f'symlink creation is unavailable: {error}')
    with pytest.raises(RuntimeError,match='Private empty'):
        probe.require_disposable_workspace(
            workspace,expected_parent=tmp_path,
            metadata=SimpleNamespace(st_mode=stat.S_IFDIR|0o700))


def test_runtime_harness_pins_every_controller_input_before_docker(tmp_path: Path) -> None:
    files={
        'run_isolated_runtime_matrix.py':b'outer harness',
        'measured-app-source.tar.gz':b'fixed app archive',
        'verify_runtime_matrix.py':b'fixed verifier',
    }
    for name,data in files.items(): (tmp_path/name).write_bytes(data)
    digest=lambda data:hashlib.sha256(data).hexdigest()
    identities=host_probe.verify_fixed_inputs(
        tmp_path,suite='mechanics',
        harness_sha256=digest(files['run_isolated_runtime_matrix.py']),
        trusted_files={'verify_runtime_matrix.py':digest(files['verify_runtime_matrix.py'])},
        source_sha256=digest(files['measured-app-source.tar.gz']),
    )
    assert identities=={name:digest(data) for name,data in files.items()}
    (tmp_path/'verify_runtime_matrix.py').write_bytes(b'one-byte-mutation!')
    with pytest.raises(RuntimeError,match='identity mismatch'):
        host_probe.verify_fixed_inputs(
            tmp_path,suite='mechanics',
            harness_sha256=digest(files['run_isolated_runtime_matrix.py']),
            trusted_files={'verify_runtime_matrix.py':digest(files['verify_runtime_matrix.py'])},
            source_sha256=digest(files['measured-app-source.tar.gz']),
        )


def test_runtime_harness_trusted_manifest_matches_current_sources() -> None:
    for name,expected in host_probe.TRUSTED_CONTROLLER_FILES.items():
        assert hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest()==expected
    assert hashlib.sha256((ROOT/'.deploy/runtime-matrix-source-bpp-v2.tar.gz').read_bytes()).hexdigest()==host_probe.MEASURED_APP_SOURCE_ARCHIVE_SHA256
    assert hashlib.sha256((ROOT/'.deploy/bpp-candidate-9859a2d-src.tar.gz').read_bytes()).hexdigest()==host_probe.CANDIDATE_SOURCE_ARCHIVE_SHA256
    assert hashlib.sha256((ROOT/'.deploy/bpp-candidate-9859a2d-stage2.gz').read_bytes()).hexdigest()==host_probe.CANDIDATE_STAGE2_GZIP_SHA256


def test_runtime_harness_selects_exact_archive_for_each_reference_suite() -> None:
    expected = {
        'mechanics': None,
        'freshman': host_probe.REFERENCE_ARCHIVE_SHA256,
        'freshman-candidate': host_probe.REFERENCE_ARCHIVE_SHA256,
        'bpp-diagnostic': host_probe.REFERENCE_ARCHIVE_SHA256,
        'freshman-draft': host_probe.DRAFT_REFERENCE_ARCHIVE_SHA256,
        'freshman-draft-candidate': host_probe.DRAFT_REFERENCE_ARCHIVE_SHA256,
        'freshman-slow': host_probe.SLOW_REFERENCE_ARCHIVE_SHA256,
    }
    assert {suite: host_probe.reference_archive_sha256(suite) for suite in expected} == expected
    with pytest.raises(ValueError, match='Unknown'):
        host_probe.reference_archive_sha256('unreviewed-suite')


@pytest.mark.parametrize(
    ('suite', 'probe_name', 'candidate'),
    (
        ('freshman', 'verify_freshman_measurements.py', False),
        ('freshman-candidate', 'verify_freshman_measurements.py', True),
        ('bpp-diagnostic', 'verify_freshman_measurements.py', False),
        ('freshman-draft', 'verify_freshman_measurements.py', False),
        ('freshman-draft-candidate', 'verify_freshman_measurements.py', True),
        ('freshman-slow', 'verify_freshman_slow.py', False),
    ),
)
def test_runtime_harness_verifies_the_archive_selected_by_each_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
    probe_name: str,
    candidate: bool,
) -> None:
    digest=lambda data:hashlib.sha256(data).hexdigest()
    archive=(suite+' archive').encode()
    source=b'fixed app archive'
    harness=b'outer harness'
    script_names={'verify_runtime_matrix.py',probe_name}
    if suite=='freshman-slow': script_names.add('verify_freshman_measurements.py')
    if candidate: script_names.update(('bpp_candidate_overlay.py','probe_bpp_candidate.py'))
    scripts={name:('fixed '+name).encode() for name in script_names}
    candidate_files={
        'compiler.tar.gz':b'candidate source archive',
        'candidate-stage2.gz':b'candidate stage2 gzip',
    } if candidate else {}
    for name,data in {
        'run_isolated_runtime_matrix.py':harness,
        'measured-app-source.tar.gz':source,
        'freshman-package.tar.gz':archive,
        **scripts,
        **candidate_files,
    }.items():
        (tmp_path/name).write_bytes(data)
    expected=digest(archive)
    if suite in ('freshman','freshman-candidate','bpp-diagnostic'):
        monkeypatch.setattr(host_probe,'REFERENCE_ARCHIVE_SHA256',expected)
    elif suite in ('freshman-draft','freshman-draft-candidate'):
        monkeypatch.setattr(host_probe,'DRAFT_REFERENCE_ARCHIVE_SHA256',expected)
    else:
        monkeypatch.setattr(host_probe,'SLOW_REFERENCE_ARCHIVE_SHA256',expected)
    if candidate:
        monkeypatch.setattr(host_probe,'CANDIDATE_SOURCE_ARCHIVE_SHA256',digest(candidate_files['compiler.tar.gz']))
        monkeypatch.setattr(host_probe,'CANDIDATE_STAGE2_GZIP_SHA256',digest(candidate_files['candidate-stage2.gz']))
    identities=host_probe.verify_fixed_inputs(
        tmp_path,suite=suite,harness_sha256=digest(harness),
        trusted_files={name:digest(data) for name,data in scripts.items()},
        source_sha256=digest(source),
    )
    assert identities['freshman-package.tar.gz']==expected
    if candidate:
        assert identities['compiler.tar.gz']==digest(candidate_files['compiler.tar.gz'])
        assert identities['candidate-stage2.gz']==digest(candidate_files['candidate-stage2.gz'])
    (tmp_path/'freshman-package.tar.gz').write_bytes(b'wrong suite archive')
    with pytest.raises(RuntimeError,match='identity mismatch'):
        host_probe.verify_fixed_inputs(
            tmp_path,suite=suite,harness_sha256=digest(harness),
            trusted_files={name:digest(data) for name,data in scripts.items()},
            source_sha256=digest(source),
        )


def test_draft_probe_rejects_changed_sample_even_with_recomputed_manifest_hash(tmp_path: Path) -> None:
    base = _test_base(tmp_path)
    path = base / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["sampleData"]["A"][0]["input"] = "9 9\n"
    unsigned = {key: value for key, value in manifest.items() if key != "manifestHash"}
    manifest["manifestHash"] = probe.sha(json.dumps(unsigned, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode())
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        probe.draft_cases_for("A", base)


def test_draft_probe_rejects_mutated_generator_and_fabricated_approval(tmp_path: Path) -> None:
    base = _test_base(tmp_path)
    generator = base / "coverage_cases.py"
    generator.write_bytes(generator.read_bytes() + b"\n# changed\n")
    with pytest.raises(ValueError, match="generator source changed"):
        probe.draft_cases_for("A", base)
    shutil.copyfile(BASE / "coverage_cases.py", generator)
    path = base / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["status"] = "approved"
    unsigned = {key: value for key, value in manifest.items() if key != "manifestHash"}
    manifest["manifestHash"] = probe.sha(json.dumps(unsigned, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode())
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        probe.draft_cases_for("A", base)


def test_draft_probe_rejects_unreviewed_b_subset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "DRAFT_B_COVERAGE", frozenset({"b-exhaustive-triple-1-2-3"}))
    with pytest.raises(ValueError, match="frozen manifest"):
        probe.draft_cases_for("B", BASE)
