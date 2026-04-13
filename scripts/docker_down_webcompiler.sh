#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-webcompiler-local}"
export WEBCOMPILER_BACKEND_PORT_MAPPING="${WEBCOMPILER_BACKEND_PORT_MAPPING:-127.0.0.1:18000:8000}"
export WEBCOMPILER_FRONTEND_PORT_MAPPING="${WEBCOMPILER_FRONTEND_PORT_MAPPING:-127.0.0.1:15173:80}"

docker compose \
  -p "$COMPOSE_PROJECT_NAME" \
  -f "$PROJECT_ROOT/docker-compose.yml" \
  -f "$PROJECT_ROOT/docker-compose.deploy.yml" \
  down -v --remove-orphans
