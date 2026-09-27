import importlib.util
from contextlib import nullcontext
from contextlib import contextmanager
import inspect as python_inspect
from pathlib import Path
import stat

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install_host_nginx_include.py"
SPEC = importlib.util.spec_from_file_location("install_host_nginx_include", SCRIPT)
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def candidate() -> bytes:
    return (ROOT / "deploy" / "nginx" / "webcompiler.locations.conf").read_bytes()


def old_config() -> bytes:
    return b"""location = /webcompiler {
    return 302 /webcompiler/;
}
location = /webcompiler/health {
    proxy_pass http://127.0.0.1:18000/health;
}
location /webcompiler/ {
    proxy_pass http://127.0.0.1:15173/;
}
"""


def setup_files(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source.conf"
    target = tmp_path / "target.conf"
    source.write_bytes(candidate())
    target.write_bytes(old_config())
    target.chmod(0o754)
    return source, target


def invoke(source: Path, target: Path, runner, verifier, expected: str | None = None,
           source_expected: str | None = None, observer=lambda _url: {"baseline": True},
           trust_validator=lambda _path, _stat: None,
           installed_validator=lambda _data, _stat, _expected, _uid, _gid: None,
           lock_factory=lambda _path: nullcontext()):
    return installer.apply(
        source,
        target,
        expected_source_sha256=source_expected or installer.sha256(source.read_bytes()),
        expected_current_sha256=expected or installer.sha256(target.read_bytes()),
        nginx_binary="/usr/sbin/nginx",
        verify_url="https://example.test/webcompiler/ready",
        runner=runner,
        verifier=verifier,
        observer=observer,
        trust_validator=trust_validator,
        installed_validator=installed_validator,
        lock_factory=lock_factory,
        effective_uid=0,
        platform_name="posix",
    )


def test_check_reports_hashes_and_never_mutates_target(tmp_path: Path):
    source, target = setup_files(tmp_path)
    before = target.read_bytes()

    result = installer.inspect(source, target)

    assert result["sourceSha256"] == installer.sha256(candidate())
    assert result["targetSha256"] == installer.sha256(before)
    assert result["matches"] is False
    assert target.read_bytes() == before


def test_apply_is_root_posix_only_and_requires_exact_observed_hash(tmp_path: Path):
    source, target = setup_files(tmp_path)
    noop = lambda _value: None

    with pytest.raises(installer.InstallError, match="root on the target POSIX host"):
        installer.apply(source, target, expected_current_sha256=installer.sha256(old_config()),
            expected_source_sha256=installer.sha256(candidate()), nginx_binary="nginx",
            verify_url="https://example.test/ready", runner=noop,
            verifier=noop, effective_uid=1000, platform_name="posix")
    with pytest.raises(installer.InstallError, match="target drift"):
        invoke(source, target, noop, noop, expected="0" * 64)
    with pytest.raises(installer.InstallError, match="source drift"):
        invoke(source, target, noop, noop, source_expected="0" * 64)
    assert target.read_bytes() == old_config()


def test_apply_rejects_symlink_target(tmp_path: Path):
    source, target = setup_files(tmp_path)
    link = tmp_path / "linked.conf"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("host cannot create a test symlink")

    with pytest.raises(installer.InstallError, match="non-symlink"):
        invoke(source, link, lambda _value: None, lambda _value: None)


def test_apply_preserves_metadata_keeps_backup_and_verifies(tmp_path: Path):
    source, target = setup_files(tmp_path)
    calls = []
    verified = []
    before_mode = stat.S_IMODE(target.stat().st_mode)
    before_hash = installer.sha256(target.read_bytes())

    result = invoke(source, target, calls.append, verified.append)

    assert target.read_bytes() == candidate()
    if installer.os.name == "posix":
        assert before_mode == 0o754
        assert stat.S_IMODE(target.stat().st_mode) == 0o644
    backup = Path(result["rollbackBackup"])
    assert backup.read_bytes() == old_config()
    assert calls == [('/usr/sbin/nginx', '-t'), ('/usr/sbin/nginx', '-s', 'reload')]
    assert verified == ["https://example.test/webcompiler/ready"]
    assert result["previousTargetSha256"] == before_hash


@pytest.mark.parametrize("failure_at", ("test", "reload", "verify"))
def test_any_activation_failure_restores_exact_prior_bytes(tmp_path: Path, failure_at: str):
    source, target = setup_files(tmp_path)
    before = target.read_bytes()
    before_mode = stat.S_IMODE(target.stat().st_mode)
    calls = []

    def runner(command):
        calls.append(tuple(command))
        activation_index = len(calls)
        if failure_at == "test" and activation_index == 1:
            raise installer.InstallError("candidate syntax")
        if failure_at == "reload" and activation_index == 2:
            raise installer.InstallError("candidate reload")

    def verifier(_url):
        if failure_at == "verify":
            raise installer.InstallError("candidate response")

    with pytest.raises(installer.InstallError, match="rollback verified"):
        invoke(source, target, runner, verifier)

    assert target.read_bytes() == before
    assert stat.S_IMODE(target.stat().st_mode) == before_mode
    assert calls[-2:] == [('/usr/sbin/nginx', '-t'), ('/usr/sbin/nginx', '-s', 'reload')]


def test_failure_after_replace_before_return_still_rolls_back(tmp_path: Path, monkeypatch):
    source, target = setup_files(tmp_path)
    before_mode = stat.S_IMODE(target.stat().st_mode)
    original = installer._atomic_replace
    invocations = 0

    def fail_once_after_replace(path, data, metadata, *, mode=None):
        nonlocal invocations
        invocations += 1
        original(path, data, metadata, mode=mode)
        if invocations == 1:
            raise OSError("directory fsync failed after replace")

    monkeypatch.setattr(installer, "_atomic_replace", fail_once_after_replace)
    with pytest.raises(installer.InstallError, match="rollback verified"):
        invoke(source, target, lambda _value: None, lambda _value: None)

    assert target.read_bytes() == old_config()
    assert stat.S_IMODE(target.stat().st_mode) == before_mode


def test_target_is_revalidated_only_after_installation_lock_is_held(tmp_path: Path):
    source, target = setup_files(tmp_path)
    observed_hash = installer.sha256(target.read_bytes())

    @contextmanager
    def competing_manager(_path):
        target.write_bytes(b"authorized concurrent update")
        yield

    with pytest.raises(installer.InstallError, match="target drift"):
        invoke(source, target, lambda _value: None, lambda _value: None,
               expected=observed_hash, lock_factory=competing_manager)
    assert target.read_bytes() == b"authorized concurrent update"


def test_atomic_replace_persists_metadata_before_data_and_directory_commit():
    source = python_inspect.getsource(installer._atomic_replace)
    metadata = source.index("os.fchmod")
    file_sync = source.index("os.fsync(output.fileno())")
    replace = source.index("os.replace")
    directory_sync = source.index("_fsync_directory")
    assert metadata < file_sync < replace < directory_sync


def test_rollback_public_response_must_match_pre_apply_observation(tmp_path: Path):
    source, target = setup_files(tmp_path)
    observations = iter(({"status": 200, "body": "before"}, {"status": 200, "body": "different"}))

    with pytest.raises(installer.InstallError, match="public response differs"):
        invoke(source, target, lambda command: (_ for _ in ()).throw(
            installer.InstallError("candidate test")) if command[-1] == "-t" else None,
            lambda _url: None, observer=lambda _url: next(observations))


def test_default_target_trust_rejects_insecure_target_and_parent(tmp_path: Path):
    source, target = setup_files(tmp_path)
    metadata = target.stat()

    with pytest.raises(installer.InstallError, match="target must be owned by root"):
        installer.validate_target_trust(target, type("Metadata", (), {
            "st_uid": 1000, "st_gid": 1000, "st_mode": metadata.st_mode,
        })())

    with pytest.raises(installer.InstallError, match="group/other writable"):
        installer.validate_target_trust(target, type("Metadata", (), {
            "st_uid": 0, "st_gid": 0, "st_mode": stat.S_IFREG | 0o664,
        })())


@pytest.mark.parametrize("mode,uid,message", (
    (stat.S_IFLNK | 0o777, 0, "real directory"),
    (stat.S_IFDIR | 0o755, 1000, "owned by root"),
    (stat.S_IFDIR | 0o775, 0, "group/other writable"),
))
def test_default_target_trust_rejects_unsafe_parent_chain(
    tmp_path: Path, monkeypatch, mode: int, uid: int, message: str,
):
    target = tmp_path / "parent" / "target.conf"
    target.parent.mkdir()
    trusted = type("Metadata", (), {
        "st_uid": 0, "st_gid": 0, "st_mode": stat.S_IFDIR | 0o755,
    })()
    unsafe = type("Metadata", (), {"st_uid": uid, "st_gid": 0, "st_mode": mode})()
    original = Path.lstat

    def fake_lstat(path):
        if path == target.parent:
            return unsafe
        if path in target.parents:
            return trusted
        return original(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    target_metadata = type("Metadata", (), {
        "st_uid": 0, "st_gid": 0, "st_mode": stat.S_IFREG | 0o644,
    })()
    with pytest.raises(installer.InstallError, match=message):
        installer.validate_target_trust(target, target_metadata)


def test_installed_target_validator_requires_exact_bytes_owner_and_mode():
    expected = b"approved"
    good = type("Metadata", (), {
        "st_uid": 0, "st_gid": 0, "st_mode": stat.S_IFREG | 0o644,
    })()
    installer.validate_installed_target(expected, good, expected, 0, 0)

    for data, uid, gid, mode in (
        (b"changed", 0, 0, 0o644),
        (expected, 1, 0, 0o644),
        (expected, 0, 1, 0o644),
        (expected, 0, 0, 0o664),
    ):
        bad = type("Metadata", (), {
            "st_uid": uid, "st_gid": gid, "st_mode": stat.S_IFREG | mode,
        })()
        with pytest.raises(installer.InstallError, match="bytes or metadata"):
            installer.validate_installed_target(data, bad, expected, 0, 0)


def test_identical_target_is_read_only_but_revalidated(tmp_path: Path):
    source, target = setup_files(tmp_path)
    target.write_bytes(candidate())
    calls = []
    verified = []

    result = invoke(source, target, calls.append, verified.append,
                    expected=installer.sha256(candidate()))

    assert result["changed"] is False
    assert calls == [('/usr/sbin/nginx', '-t')]
    assert verified == ["https://example.test/webcompiler/ready"]
    assert not list(tmp_path.glob("*.rollback-*"))


def test_candidate_contract_rejects_missing_exact_readiness_route():
    with pytest.raises(installer.InstallError, match="webcompiler/ready"):
        installer.validate_candidate(candidate().replace(b"location = /webcompiler/ready", b"location /webcompiler/ready"))


def test_public_verifier_accepts_only_ready_json_200_no_store(monkeypatch):
    monkeypatch.setattr(installer, "_fetch_public",
                        lambda _url, _timeout=8.0: (200, "application/json", "no-store", b'{"status":"ready"}'))
    installer.verify_ready_url("https://example.test/webcompiler/ready")


@pytest.mark.parametrize("response,message", (
    ((503, "application/json", "no-store", b'{"status":"unavailable"}'), "unexpected readiness"),
    ((200, "text/html", "no-store", b"<html>spa</html>"), "not JSON"),
    ((200, "application/json", "public", b'{"status":"ready"}'), "no-store"),
    ((200, "application/json", "no-store", b"not-json"), "invalid JSON"),
))
def test_public_verifier_rejects_unready_spa_cacheable_or_invalid(
    monkeypatch, response, message: str,
):
    monkeypatch.setattr(installer, "_fetch_public",
                        lambda _url, _timeout=8.0: response)
    with pytest.raises(installer.InstallError, match=message):
        installer.verify_ready_url("https://example.test/webcompiler/ready")
