#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-webcompiler-local}"

export WEBCOMPILER_DATA_DIR="${WEBCOMPILER_DATA_DIR:-$PROJECT_ROOT/.data/webcompiler}"
mkdir -p "$PROJECT_ROOT/.sandbox-work" "$WEBCOMPILER_DATA_DIR"

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
export WEBCOMPILER_FRONTEND_PORT_MAPPING="${WEBCOMPILER_FRONTEND_PORT_MAPPING:-127.0.0.1:15173:80}"

bash "$PROJECT_ROOT/scripts/build_sandbox_image.sh"

docker compose \
  -p "$COMPOSE_PROJECT_NAME" \
  -f "$PROJECT_ROOT/docker-compose.yml" \
  -f "$PROJECT_ROOT/docker-compose.deploy.yml" \
  up --build -d --remove-orphans
