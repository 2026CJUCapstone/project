#!/usr/bin/env bash

set -euo pipefail

: "${DEPLOY_SHA:?DEPLOY_SHA is required}"
: "${DEPLOY_PATH:?DEPLOY_PATH is required}"
: "${DEPLOY_REPO:?DEPLOY_REPO is required}"

RUN_DEPLOY_SCRIPT="${RUN_DEPLOY_SCRIPT:-1}"
[[ "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid deploy SHA' >&2; exit 2; }
[[ "$RUN_DEPLOY_SCRIPT" == 0 || "$RUN_DEPLOY_SCRIPT" == 1 ]] || exit 2
[[ "$DEPLOY_PATH" == /* && "$DEPLOY_PATH" != / && ! -L "$DEPLOY_PATH" ]] || exit 2
[[ "$DEPLOY_REPO" != -* && -n "$DEPLOY_REPO" ]] || exit 2

mkdir -p "$DEPLOY_PATH"
DEPLOY_PATH="$(cd "$DEPLOY_PATH" && pwd -P)"
[[ "$DEPLOY_PATH" != / && "$DEPLOY_PATH" != "$HOME" ]] || exit 2
[[ ! -L "$DEPLOY_PATH/.deploy" && ! -L "$DEPLOY_PATH/.deploy/deploy.lock" ]] || exit 2
mkdir -p "$DEPLOY_PATH/.deploy"
# Keep the SAME lock across fetch, checkout, image build and edge switch. A
# second workflow/SSH process must never move HEAD while the first is building.
exec 9>"$DEPLOY_PATH/.deploy/deploy.lock"
flock -n 9 || { echo 'Another deployment is already running' >&2; exit 1; }
# DEPLOY_FRONTEND_PAYLOAD

if [ ! -d "$DEPLOY_PATH/.git" ]; then
  [[ ! -e "$DEPLOY_PATH/.git" ]] || exit 2
  git -C "$DEPLOY_PATH" init
  git -C "$DEPLOY_PATH" remote add origin "$DEPLOY_REPO"
else
  [[ ! -L "$DEPLOY_PATH/.git" ]] || exit 2
  [[ "$(git -C "$DEPLOY_PATH" remote get-url origin)" == "$DEPLOY_REPO" ]] || {
    echo 'Deployment repository origin mismatch' >&2; exit 1;
  }
  git -C "$DEPLOY_PATH" diff --quiet --exit-code
  git -C "$DEPLOY_PATH" diff --cached --quiet --exit-code
fi

git -C "$DEPLOY_PATH" fetch --no-tags --depth 1 origin "$DEPLOY_SHA"
[[ "$(git -C "$DEPLOY_PATH" rev-parse 'FETCH_HEAD^{commit}')" == "$DEPLOY_SHA" ]] || exit 1
# No --force and no git clean: abort on collisions, preserve local state/data.
git -C "$DEPLOY_PATH" checkout --detach --no-overwrite-ignore "$DEPLOY_SHA"
[[ "$(git -C "$DEPLOY_PATH" rev-parse HEAD)" == "$DEPLOY_SHA" ]] || exit 1
git -C "$DEPLOY_PATH" diff --quiet --exit-code
git -C "$DEPLOY_PATH" diff --cached --quiet --exit-code

printf '[webcompiler-deploy] verified source %s\n' "$DEPLOY_SHA"

if [ "$RUN_DEPLOY_SCRIPT" = "1" ]; then
  cd "$DEPLOY_PATH"
  # FD9 is inherited; the child checks its path and reacquires that open file
  # description rather than opening a second, self-conflicting lock.
  DEPLOY_SHA="$DEPLOY_SHA" WEBCOMPILER_DEPLOY_LOCK_HELD=1 bash scripts/deploy_server.sh
fi
