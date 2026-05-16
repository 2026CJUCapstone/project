#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="${PROJECT_ROOT:-$ROOT_DIR}"

runtime_build_signature() {
  sha256sum \
    "$PROJECT_ROOT/runtime/docker/Dockerfile" \
    "$PROJECT_ROOT/runtime/sandbox/run.sh" \
    "$PROJECT_ROOT/scripts/build_sandbox_image.sh" \
    | sha256sum | awk 'NR==1 { print $1 }'
}

BPP_REPO="${BPP_REPO:-https://github.com/Creeper0809/Bpp}"
BPP_BRANCH="${BPP_BRANCH:-main}"
BPP_RELEASE_API="${BPP_RELEASE_API:-https://api.github.com/repos/Creeper0809/Bpp/releases/latest}"
BPP_USE_RELEASE_BINARY="${BPP_USE_RELEASE_BINARY:-1}"
STABLE_IMAGE="${SANDBOX_STABLE_IMAGE:-compiler-sandbox}"
CANDIDATE_IMAGE="${SANDBOX_CANDIDATE_IMAGE:-compiler-sandbox:candidate}"
DEPLOY_DIR="${WEBCOMPILER_DEPLOY_STATE_DIR:-$PROJECT_ROOT/.deploy}"
LOCK_FILE="$DEPLOY_DIR/sandbox-updater.lock"
TEST_SKIP_LLVM_BUILD="${TEST_SKIP_LLVM_BUILD:-1}"
TEST_FAST_IO="${TEST_FAST_IO:-0}"
RUNTIME_BUILD_SIGNATURE="${RUNTIME_BUILD_SIGNATURE:-$(runtime_build_signature)}"

log() {
  printf '[sandbox-updater] %s\n' "$*"
}

current_image_build_key() {
  docker image inspect "$STABLE_IMAGE" \
    --format '{{ index .Config.Labels "io.bpp.ref" }}|skip_llvm={{ index .Config.Labels "io.bpp.test_skip_llvm_build" }}|fast_io={{ index .Config.Labels "io.bpp.test_fast_io" }}|runtime_sig={{ index .Config.Labels "io.bpp.runtime_build_signature" }}' 2>/dev/null || true
}

latest_remote_ref() {
  git ls-remote "$BPP_REPO" "refs/heads/$BPP_BRANCH" | awk 'NR==1 { print $1 }'
}

latest_release_tag() {
  local curl_args
  curl_args=(-fsSL --retry 3 --retry-delay 2)
  local github_token
  github_token="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
  if [[ -n "$github_token" ]]; then
    curl_args+=(
      -H "Authorization: Bearer ${github_token}"
      -H "X-GitHub-Api-Version: 2022-11-28"
    )
  fi
  curl "${curl_args[@]}" "$BPP_RELEASE_API" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("tag_name", ""))'
}

desired_build_key() {
  local ref="$1"
  printf '%s|skip_llvm=%s|fast_io=%s|runtime_sig=%s\n' "$ref" "$TEST_SKIP_LLVM_BUILD" "$TEST_FAST_IO" "$RUNTIME_BUILD_SIGNATURE"
}

smoke_test_candidate() {
  local work_dir
  work_dir="$(mktemp -d "$PROJECT_ROOT/.sandbox-work/sandbox-updater-smoke-XXXXXX")"
  chmod 755 "$work_dir"
  trap 'rm -rf "$work_dir"' RETURN

  cat > "$work_dir/hello.bpp" <<'BPP'
import std.io;

func main() -> u64 {
    println("sandbox updater ok");
    return 0;
}
BPP

  local output
  output="$(
    docker run --rm \
      --network none \
      --read-only \
      --tmpfs /tmp:rw,exec,nosuid,size=256m \
      -v "$work_dir:/sandbox:ro" \
      "$CANDIDATE_IMAGE" run bpp /sandbox/hello.bpp
  )"

  [[ "$output" == *"sandbox updater ok"* ]]
}

mkdir -p "$DEPLOY_DIR" "$PROJECT_ROOT/.sandbox-work"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "another update is already running"
  exit 0
fi

if [[ "$BPP_USE_RELEASE_BINARY" == "1" ]]; then
  latest_ref="release:$(latest_release_tag)"
else
  latest_ref="$(latest_remote_ref)"
fi

if [[ -z "$latest_ref" || "$latest_ref" == "release:" ]]; then
  log "failed to resolve build target for sandbox image"
  exit 1
fi

current_key="$(current_image_build_key)"
desired_key="$(desired_build_key "$latest_ref")"
if [[ "$current_key" == "$desired_key" ]]; then
  log "already up to date: $desired_key"
  exit 0
fi

log "updating sandbox image: ${current_key:-none} -> $desired_key"
SANDBOX_IMAGE_TAG="$CANDIDATE_IMAGE" \
BPP_REPO="$BPP_REPO" \
BPP_BRANCH="$BPP_BRANCH" \
BPP_USE_RELEASE_BINARY="$BPP_USE_RELEASE_BINARY" \
BPP_REF="$latest_ref" \
TEST_SKIP_LLVM_BUILD="$TEST_SKIP_LLVM_BUILD" \
TEST_FAST_IO="$TEST_FAST_IO" \
RUNTIME_BUILD_SIGNATURE="$RUNTIME_BUILD_SIGNATURE" \
bash "$PROJECT_ROOT/scripts/build_sandbox_image.sh"

log "running candidate smoke test"
if ! smoke_test_candidate; then
  log "candidate smoke test failed; keeping $STABLE_IMAGE at ${current_key:-none}"
  exit 1
fi

docker tag "$CANDIDATE_IMAGE" "$STABLE_IMAGE"
printf '%s\n' "$latest_ref" > "$DEPLOY_DIR/sandbox-bpp-ref"
log "promoted $CANDIDATE_IMAGE to $STABLE_IMAGE at $desired_key"
