#!/usr/bin/env bash
# Retain an exact committed build context, excluding working-tree extras.
set -euo pipefail
: "${PROJECT_ROOT:?PROJECT_ROOT is required}"
: "${DEPLOY_SHA:?DEPLOY_SHA is required}"
[[ "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$(git -C "$PROJECT_ROOT" rev-parse HEAD)" == "$DEPLOY_SHA" ]] || exit 1
[[ ! -L "$PROJECT_ROOT/.deploy" ]] || exit 2
mkdir -p "$PROJECT_ROOT/.deploy"
source_root="$(mktemp -d "$PROJECT_ROOT/.deploy/source-$DEPLOY_SHA-XXXXXX")"
git -C "$PROJECT_ROOT" archive "$DEPLOY_SHA" | tar -x -C "$source_root"
printf '%s\n' "$source_root"
