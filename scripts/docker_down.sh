#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"
export WEBCOMPILER_WORKER_UID="${WEBCOMPILER_WORKER_UID:-$(id -u)}"
export WEBCOMPILER_WORKER_GID="${WEBCOMPILER_WORKER_GID:-$(id -g)}"
export WEBCOMPILER_DOCKER_GID="${WEBCOMPILER_DOCKER_GID:-$(stat -c %g /var/run/docker.sock)}"

docker compose down --remove-orphans
