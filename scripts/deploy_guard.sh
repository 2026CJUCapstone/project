#!/usr/bin/env bash
# Source only after PROJECT_ROOT has been resolved to the deployment checkout.
: "${PROJECT_ROOT:?PROJECT_ROOT is required}"
: "${DEPLOY_SHA:?Supply the CI-verified deploy SHA}"
[[ "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ ! -L "$PROJECT_ROOT/.deploy" && ! -L "$PROJECT_ROOT/.deploy/deploy.lock" ]] || exit 2
mkdir -p "$PROJECT_ROOT/.deploy"
if [[ "${WEBCOMPILER_DEPLOY_LOCK_HELD:-0}" == 1 ]]; then
  [[ "$(readlink /proc/self/fd/9)" == "$PROJECT_ROOT/.deploy/deploy.lock" ]] || exit 2
else
  exec 9>"$PROJECT_ROOT/.deploy/deploy.lock"
fi
if ! flock -n 9; then
  echo 'Another deployment is already running' >&2
  exit 1
fi
[[ "$(git -C "$PROJECT_ROOT" rev-parse HEAD)" == "$DEPLOY_SHA" ]] || {
  echo 'Deployment HEAD does not match the verified SHA' >&2; exit 1;
}
git -C "$PROJECT_ROOT" diff --quiet --exit-code
git -C "$PROJECT_ROOT" diff --cached --quiet --exit-code
