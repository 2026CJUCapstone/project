#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"

runtime_build_signature() {
  sha256sum \
    "$PROJECT_ROOT/runtime/docker/Dockerfile" \
    "$PROJECT_ROOT/runtime/sandbox/run.sh" \
    "$PROJECT_ROOT/scripts/build_sandbox_image.sh" \
    | sha256sum | awk 'NR==1 { print $1 }'
}

BPP_REPO="${BPP_REPO:-https://github.com/Creeper0809/Bpp}"
BPP_BRANCH="${BPP_BRANCH:-main}"
BPP_REF="${BPP_REF:-}"
BPP_BOOTSTRAP_TAG="${BPP_BOOTSTRAP_TAG:-}"
BPP_BOOTSTRAP_URL="${BPP_BOOTSTRAP_URL:-}"
BPP_BOOTSTRAP_SHA256="${BPP_BOOTSTRAP_SHA256:-}"
SANDBOX_IMAGE_TAG="${SANDBOX_IMAGE_TAG:-compiler-sandbox}"
TEST_SKIP_LLVM_BUILD="${TEST_SKIP_LLVM_BUILD:-1}"
TEST_FAST_IO="${TEST_FAST_IO:-0}"
RUNTIME_BUILD_SIGNATURE="${RUNTIME_BUILD_SIGNATURE:-$(runtime_build_signature)}"

if [[ -z "$BPP_REF" ]]; then
  if ! BPP_REF="$(git ls-remote "$BPP_REPO" "refs/heads/$BPP_BRANCH" | awk 'NR==1 { print $1 }')"; then
    echo "failed to resolve $BPP_REPO branch $BPP_BRANCH" >&2
    exit 1
  fi
fi

if [[ -z "$BPP_REF" ]]; then
  echo "failed to resolve $BPP_REPO branch $BPP_BRANCH" >&2
  exit 1
fi

echo "Building sandbox with Bpp $BPP_BRANCH @ $BPP_REF from source"
echo "  bootstrap_tag=${BPP_BOOTSTRAP_TAG:-<Bpp CMake default>}"
echo "  test_skip_llvm_build=$TEST_SKIP_LLVM_BUILD"
echo "  test_fast_io=$TEST_FAST_IO"
echo "  runtime_build_signature=$RUNTIME_BUILD_SIGNATURE"

docker build \
  --shm-size=2g \
  --build-arg "BPP_REPO=$BPP_REPO" \
  --build-arg "BPP_REF=$BPP_REF" \
  --build-arg "BPP_BOOTSTRAP_TAG=$BPP_BOOTSTRAP_TAG" \
  --build-arg "BPP_BOOTSTRAP_URL=$BPP_BOOTSTRAP_URL" \
  --build-arg "BPP_BOOTSTRAP_SHA256=$BPP_BOOTSTRAP_SHA256" \
  --build-arg "TEST_SKIP_LLVM_BUILD=$TEST_SKIP_LLVM_BUILD" \
  --build-arg "TEST_FAST_IO=$TEST_FAST_IO" \
  --build-arg "RUNTIME_BUILD_SIGNATURE=$RUNTIME_BUILD_SIGNATURE" \
  -t "$SANDBOX_IMAGE_TAG" \
  -f "$PROJECT_ROOT/runtime/docker/Dockerfile" \
  "$PROJECT_ROOT/runtime"
