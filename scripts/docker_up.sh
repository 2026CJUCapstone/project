#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"

e2e_cache_release_enabled() {
  case "${WEBCOMPILER_E2E_RELEASE_BUILD_CACHE:-0}" in
    0|'') return 1 ;;
    1) return 0 ;;
    *) echo 'WEBCOMPILER_E2E_RELEASE_BUILD_CACHE must be 0 or 1' >&2; exit 2 ;;
  esac
}

e2e_cache_release_arguments() {
  : "${COMPOSE_PROJECT_NAME:?An E2E Compose project is required}"
  : "${WEBCOMPILER_BUILD_BUILDER:?Explicit bounded builder required}"
  : "${WEBCOMPILER_BUILD_CONTAINER_ID:?Exact bounded builder identity required}"
  : "${SANDBOX_IMAGE:?E2E sandbox image is required}"
  : "${WEBCOMPILER_BACKEND_IMAGE:?E2E backend image is required}"
  : "${E2E_FRONTEND_IMAGE:?E2E frontend image is required}"
  printf '%s\0' \
    --root "$ROOT_DIR" \
    --project "$COMPOSE_PROJECT_NAME" \
    --builder "$WEBCOMPILER_BUILD_BUILDER" \
    --sandbox-image "$SANDBOX_IMAGE" \
    --backend-image "$WEBCOMPILER_BACKEND_IMAGE" \
    --frontend-image "$E2E_FRONTEND_IMAGE"
}

validate_e2e_cache_release_scope() {
  if e2e_cache_release_enabled; then
    mapfile -d '' -t release_args < <(e2e_cache_release_arguments)
    python3 "$PROJECT_ROOT/scripts/release_e2e_build_cache.py" "${release_args[@]}" --validate-only
  fi
}

release_e2e_build_cache() {
  if e2e_cache_release_enabled; then
    mapfile -d '' -t release_args < <(e2e_cache_release_arguments)
    # The helper reuses the exact immutable builder verifier immediately
    # before and after prune, then proves all three loaded nonce image IDs did
    # not change.  Any failure stops before Compose can create a service.
    python3 "$PROJECT_ROOT/scripts/release_e2e_build_cache.py" "${release_args[@]}"
  fi
}

# Refuse before creating local state if the caller has not selected the exact
# bounded BuildKit container.  The sandbox helper and the Compose phase each
# re-check this full ID before/after their own build work.
WEBCOMPILER_BUILD_CONTAINER_ID="$(python3 "$PROJECT_ROOT/scripts/verify_build_builder.py")"
export WEBCOMPILER_BUILD_CONTAINER_ID
validate_e2e_cache_release_scope
export WEBCOMPILER_BACKEND_PORT_MAPPING="${WEBCOMPILER_BACKEND_PORT_MAPPING:-127.0.0.1:18010:8000}"
export WEBCOMPILER_FRONTEND_PORT_MAPPING="${WEBCOMPILER_FRONTEND_PORT_MAPPING:-127.0.0.1:15180:8080}"

export WEBCOMPILER_DATA_DIR="${WEBCOMPILER_DATA_DIR:-$PROJECT_ROOT/.data/webcompiler}"
mkdir -p "$PROJECT_ROOT/.sandbox-work" "$WEBCOMPILER_DATA_DIR"
export WEBCOMPILER_WORKER_UID="$(stat -c %u "$PROJECT_ROOT/.sandbox-work")"
export WEBCOMPILER_WORKER_GID="$(stat -c %g "$PROJECT_ROOT/.sandbox-work")"
export WEBCOMPILER_DOCKER_GID="$(stat -c %g /var/run/docker.sock)"

if [[ ! -f "$WEBCOMPILER_DATA_DIR/bpp_project.db" ]]; then
  for legacy_db in "$PROJECT_ROOT/backend/bpp_project.db" "$PROJECT_ROOT/bpp_project.db"; do
    if [[ -f "$legacy_db" ]]; then
      cp "$legacy_db" "$WEBCOMPILER_DATA_DIR/bpp_project.db"
      break
    fi
  done
fi

bash "$PROJECT_ROOT/scripts/build_sandbox_image.sh"
python3 "$PROJECT_ROOT/scripts/verify_build_builder.py" >/dev/null
docker compose build --builder "$WEBCOMPILER_BUILD_BUILDER"
python3 "$PROJECT_ROOT/scripts/verify_build_builder.py" >/dev/null
release_e2e_build_cache
docker compose up --no-build -d
