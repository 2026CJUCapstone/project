#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-webcompiler-local}"
case "$COMPOSE_PROJECT_NAME" in
  webcompiler-local|webcompiler-e2e-*) ;;
  *) printf 'Refusing non-local compose project: %s\n' "$COMPOSE_PROJECT_NAME" >&2; exit 2 ;;
esac
export WEBCOMPILER_WORKER_UID="${WEBCOMPILER_WORKER_UID:-$(id -u)}"
export WEBCOMPILER_WORKER_GID="${WEBCOMPILER_WORKER_GID:-$(id -g)}"
export WEBCOMPILER_DOCKER_GID="${WEBCOMPILER_DOCKER_GID:-$(stat -c %g /var/run/docker.sock)}"
export WEBCOMPILER_SHARED_POSTGRES_NETWORK="${WEBCOMPILER_SHARED_POSTGRES_NETWORK:-${COMPOSE_PROJECT_NAME}-shared}"

docker compose \
  -p "$COMPOSE_PROJECT_NAME" \
  -f "$PROJECT_ROOT/docker-compose.yml" \
  -f "$PROJECT_ROOT/docker-compose.deploy.yml" \
  down --remove-orphans

# External/shared networks and production edge/color stacks are not owned by
# this local helper; leave them alone even if they happen to exist on the host.
