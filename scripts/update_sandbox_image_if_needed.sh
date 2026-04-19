#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="${PROJECT_ROOT:-$ROOT_DIR}"

BPP_REPO="${BPP_REPO:-https://github.com/Creeper0809/Bpp}"
BPP_BRANCH="${BPP_BRANCH:-main}"
STABLE_IMAGE="${SANDBOX_STABLE_IMAGE:-compiler-sandbox}"
CANDIDATE_IMAGE="${SANDBOX_CANDIDATE_IMAGE:-compiler-sandbox:candidate}"
DEPLOY_DIR="${WEBCOMPILER_DEPLOY_STATE_DIR:-$PROJECT_ROOT/.deploy}"
LOCK_FILE="$DEPLOY_DIR/sandbox-updater.lock"

log() {
  printf '[sandbox-updater] %s\n' "$*"
}

current_image_ref() {
  docker image inspect "$STABLE_IMAGE" \
    --format '{{ index .Config.Labels "io.bpp.ref" }}' 2>/dev/null || true
}

latest_remote_ref() {
  git ls-remote "$BPP_REPO" "refs/heads/$BPP_BRANCH" | awk 'NR==1 { print $1 }'
}

smoke_test_candidate() {
  local work_dir
  work_dir="$(mktemp -d "$PROJECT_ROOT/.sandbox-work/sandbox-updater-smoke-XXXXXX")"
  trap 'rm -rf "$work_dir"' RETURN

  cat > "$work_dir/hello.bpp" <<'BPP'
import emitln from std.io;

func main() -> u64 {
    emitln("sandbox updater ok");
    return 0;
}
BPP

  local output
  output="$(
    docker run --rm \
      --network none \
      --read-only \
      --tmpfs /tmp:rw,exec,nosuid,size=256m \
      -v "$work_dir:/workspace:ro" \
      "$CANDIDATE_IMAGE" run bpp /workspace/hello.bpp
  )"

  [[ "$output" == *"sandbox updater ok"* ]]
}

mkdir -p "$DEPLOY_DIR" "$PROJECT_ROOT/.sandbox-work"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "another update is already running"
  exit 0
fi

latest_ref="$(latest_remote_ref)"
if [[ -z "$latest_ref" ]]; then
  log "failed to resolve $BPP_REPO $BPP_BRANCH"
  exit 1
fi

current_ref="$(current_image_ref)"
if [[ "$current_ref" == "$latest_ref" ]]; then
  log "already up to date: $latest_ref"
  exit 0
fi

log "updating sandbox image: ${current_ref:-none} -> $latest_ref"
SANDBOX_IMAGE_TAG="$CANDIDATE_IMAGE" \
BPP_REPO="$BPP_REPO" \
BPP_BRANCH="$BPP_BRANCH" \
BPP_REF="$latest_ref" \
bash "$PROJECT_ROOT/scripts/build_sandbox_image.sh"

log "running candidate smoke test"
if ! smoke_test_candidate; then
  log "candidate smoke test failed; keeping $STABLE_IMAGE at ${current_ref:-none}"
  exit 1
fi

docker tag "$CANDIDATE_IMAGE" "$STABLE_IMAGE"
printf '%s\n' "$latest_ref" > "$DEPLOY_DIR/sandbox-bpp-ref"
log "promoted $CANDIDATE_IMAGE to $STABLE_IMAGE at $latest_ref"
