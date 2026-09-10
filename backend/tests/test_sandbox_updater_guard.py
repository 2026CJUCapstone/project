from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPDATER = ROOT / "scripts" / "update_sandbox_image_if_needed.sh"


def updater_source() -> str:
    return UPDATER.read_text(encoding="utf-8")


def test_deploy_lock_precedes_updater_lock_and_busy_paths_are_nonfatal():
    source = updater_source()

    deploy_open = source.index('exec 8>"$DEPLOY_DIR/deploy.lock"')
    deploy_flock = source.index("flock -n 8", deploy_open)
    updater_open = source.index('exec 9>"$LOCK_FILE"')
    updater_flock = source.index("flock -n 9", updater_open)

    assert deploy_open < deploy_flock < updater_open < updater_flock
    assert source[deploy_flock:updater_open].count("exit 0") == 1
    assert source[updater_flock:].count("exit 0") >= 1
    assert "another deployment is already running; skipping update" in source
    assert "another sandbox update is already running; skipping update" in source


def test_deploy_state_and_both_lock_paths_reject_symlinks_before_redirection():
    source = updater_source()
    guard = '[[ -L "$DEPLOY_DIR" || -L "$DEPLOY_DIR/deploy.lock" || -L "$LOCK_FILE" ]]'

    assert source.count(guard) == 1
    assert source.count("refuse_symlinked_state_paths") >= 3
    assert source.index(guard) < source.index('exec 8>"$DEPLOY_DIR/deploy.lock"')


def test_runtime_signature_is_computed_after_both_locks():
    source = updater_source()
    signature = 'RUNTIME_BUILD_SIGNATURE="${RUNTIME_BUILD_SIGNATURE:-$(runtime_build_signature)}"'

    assert source.index(signature) > source.index("flock -n 9")
    assert signature not in source[:source.index('exec 8>"$DEPLOY_DIR/deploy.lock"')]


def test_candidate_build_overrides_inherited_stable_image_tag():
    source = updater_source()
    build_start = source.index('SANDBOX_IMAGE="$CANDIDATE_IMAGE"')
    build_end = source.index('bash "$PROJECT_ROOT/scripts/build_sandbox_image.sh"', build_start)
    build_block = source[build_start:build_end]

    assert 'SANDBOX_IMAGE="$CANDIDATE_IMAGE" \\' in build_block
    assert 'SANDBOX_IMAGE_TAG="$CANDIDATE_IMAGE" \\' in build_block
