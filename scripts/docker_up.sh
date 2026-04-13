#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"

mkdir -p "$PROJECT_ROOT/.sandbox-work"

bash "$PROJECT_ROOT/scripts/build_sandbox_image.sh"
docker compose up --build -d
