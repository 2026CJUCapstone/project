#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-webcompiler-local}"
# Bind the named builder before creating the private network or any local
# state.  Subsequent verifier calls retain this exact full container ID.
WEBCOMPILER_BUILD_CONTAINER_ID="$(python3 "$PROJECT_ROOT/scripts/verify_build_builder.py")"
export WEBCOMPILER_BUILD_CONTAINER_ID

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

export WEBCOMPILER_BASE_PATH="${WEBCOMPILER_BASE_PATH:-/webcompiler/}"
export WEBCOMPILER_API_BASE="${WEBCOMPILER_API_BASE:-/webcompiler}"
export WEBCOMPILER_CORS_ORIGINS="${WEBCOMPILER_CORS_ORIGINS:-http://127.0.0.1:15173}"
export WEBCOMPILER_BACKEND_PORT_MAPPING="${WEBCOMPILER_BACKEND_PORT_MAPPING:-127.0.0.1:18000:8000}"
export WEBCOMPILER_FRONTEND_PORT_MAPPING="${WEBCOMPILER_FRONTEND_PORT_MAPPING:-127.0.0.1:15173:8080}"
export WEBCOMPILER_SHARED_POSTGRES_NETWORK="${WEBCOMPILER_SHARED_POSTGRES_NETWORK:-${COMPOSE_PROJECT_NAME}-shared}"

if ! docker network inspect "$WEBCOMPILER_SHARED_POSTGRES_NETWORK" >/dev/null 2>&1; then
  docker network create "$WEBCOMPILER_SHARED_POSTGRES_NETWORK" >/dev/null
fi

bash "$PROJECT_ROOT/scripts/build_sandbox_image.sh"
python3 "$PROJECT_ROOT/scripts/verify_build_builder.py" >/dev/null

docker compose \
  -p "$COMPOSE_PROJECT_NAME" \
  -f "$PROJECT_ROOT/docker-compose.yml" \
  -f "$PROJECT_ROOT/docker-compose.deploy.yml" \
  build --builder "$WEBCOMPILER_BUILD_BUILDER"
python3 "$PROJECT_ROOT/scripts/verify_build_builder.py" >/dev/null
docker compose \
  -p "$COMPOSE_PROJECT_NAME" \
  -f "$PROJECT_ROOT/docker-compose.yml" \
  -f "$PROJECT_ROOT/docker-compose.deploy.yml" \
  up --no-build -d --remove-orphans
