#!/usr/bin/env bash

set -euo pipefail

: "${DEPLOY_BRANCH:?DEPLOY_BRANCH is required}"
: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${DEPLOY_REPO:?DEPLOY_REPO is required}"

RUN_DEPLOY_SCRIPT="${RUN_DEPLOY_SCRIPT:-1}"

mkdir -p "$DEPLOY_PATH"

if [ ! -d "$DEPLOY_PATH/.git" ]; then
  git -C "$DEPLOY_PATH" init
  git -C "$DEPLOY_PATH" remote add origin "$DEPLOY_REPO"
else
  if git -C "$DEPLOY_PATH" remote get-url origin >/dev/null 2>&1; then
    git -C "$DEPLOY_PATH" remote set-url origin "$DEPLOY_REPO"
  else
    git -C "$DEPLOY_PATH" remote add origin "$DEPLOY_REPO"
  fi
fi

git -C "$DEPLOY_PATH" fetch --depth 1 origin "$DEPLOY_BRANCH"
git -C "$DEPLOY_PATH" checkout --force -B "$DEPLOY_BRANCH" FETCH_HEAD

git -C "$DEPLOY_PATH" clean -fdx \
  -e .sandbox-work/ \
  -e backend/.venv/ \
  -e frontend/dist/ \
  -e frontend/node_modules/ \
  -e .data/

if [ "$RUN_DEPLOY_SCRIPT" = "1" ]; then
  cd "$DEPLOY_PATH"
  bash scripts/deploy_server.sh
fi
