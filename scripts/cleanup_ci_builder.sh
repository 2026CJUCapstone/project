#!/usr/bin/env bash
# Only clean up a builder successfully bound by this CI job's setup step.
set -euo pipefail

if [[ -z "${WEBCOMPILER_BUILD_CONTAINER_ID:-}" ]]; then
  echo 'No successfully bound CI builder; cleanup skipped.'
  exit 0
fi

[[ "${WEBCOMPILER_BUILD_BUILDER:-}" == 'webcompiler-ci' ]] || {
  echo 'Refusing cleanup of a non-CI builder.' >&2
  exit 1
}
[[ "$WEBCOMPILER_BUILD_CONTAINER_ID" =~ ^[0-9a-f]{64}$ ]] || {
  echo 'Refusing cleanup without a full bound container identity.' >&2
  exit 1
}

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verified_id="$(python3 "$PROJECT_ROOT/scripts/verify_build_builder.py")"
[[ "$verified_id" == "$WEBCOMPILER_BUILD_CONTAINER_ID" ]] || {
  echo 'Refusing cleanup after builder identity changed.' >&2
  exit 1
}
docker buildx rm --force "$WEBCOMPILER_BUILD_BUILDER"
