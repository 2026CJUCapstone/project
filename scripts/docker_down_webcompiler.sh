#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"

for color in blue green; do
  docker compose \
    -p "webcompiler-$color" \
    -f "$PROJECT_ROOT/docker-compose.yml" \
    -f "$PROJECT_ROOT/docker-compose.deploy.yml" \
    down --remove-orphans
done

docker compose \
  -p "${COMPOSE_PROJECT_NAME:-webcompiler}" \
  -f "$PROJECT_ROOT/docker-compose.yml" \
  -f "$PROJECT_ROOT/docker-compose.deploy.yml" \
  down --remove-orphans

docker rm -f webcompiler-edge-frontend webcompiler-edge-backend >/dev/null 2>&1 || true
