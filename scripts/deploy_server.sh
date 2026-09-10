#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"
export WEBCOMPILER_PROJECT_PREFIX="${WEBCOMPILER_PROJECT_PREFIX:-webcompiler}"
export SANDBOX_POOL_ID="${SANDBOX_POOL_ID:-$WEBCOMPILER_PROJECT_PREFIX}"

# The optional updater owns global systemd units and stable compiler tags.
# A separate deployment namespace must never install or alter those resources.
if [[ "$WEBCOMPILER_PROJECT_PREFIX" != webcompiler && "${WEBCOMPILER_ENABLE_SANDBOX_UPDATER:-0}" != 0 ]]; then
  echo 'Sandbox updater is unsupported for a custom deployment namespace' >&2
  exit 2
fi

source "$PROJECT_ROOT/scripts/deploy_guard.sh"
# The server explicitly selects an adopted basic pool. Never let this pool
# fall through into managed blue/green ownership or migration logic.
if [[ -e "$PROJECT_ROOT/.deploy/basic-pool.json" || -L "$PROJECT_ROOT/.deploy/basic-pool.json" ]]; then
  export WEBCOMPILER_DEPLOY_LOCK_HELD=1
  exec python3 -I "$PROJECT_ROOT/scripts/basic_pool_deploy.py"
fi
python3 "$PROJECT_ROOT/scripts/validate_ingress.py"
python3 "$PROJECT_ROOT/scripts/runtime_secrets.py" validate --deployment --allow-missing --file "$PROJECT_ROOT/.deploy/runtime-secrets.env"
# Image builds have a separate budget from running API/worker containers.
WEBCOMPILER_BUILD_CONTAINER_ID="$(python3 "$PROJECT_ROOT/scripts/verify_build_builder.py")"
export WEBCOMPILER_BUILD_CONTAINER_ID
# Read-only legacy/port/owner checks before archive, secret, DB or runtime changes.
# A legacy edge handoff needs explicit approval; never free ports by stopping it.
if [[ "${WEBCOMPILER_STOP_OLD_AFTER_DEPLOY:-0}" != "0" ]]; then
  echo 'Automatic legacy stop is disabled; use verified drain/retirement' >&2
  exit 2
fi
python3 "$PROJECT_ROOT/scripts/edge_deploy.py" preflight
# Capture the exact validated mapping, never re-read the pathname after prepare.
runtime_secret_exports="$(python3 "$PROJECT_ROOT/scripts/runtime_secrets.py" ensure --emit-exports --file "$PROJECT_ROOT/.deploy/runtime-secrets.env")"
eval "$runtime_secret_exports"
unset runtime_secret_exports
active_color="$(python3 "$PROJECT_ROOT/scripts/edge_deploy.py" prepare)"
# Never build/re-tag the other color's currently running application image.
export WEBCOMPILER_BACKEND_IMAGE="$WEBCOMPILER_PROJECT_PREFIX-backend:$DEPLOY_SHA"
# A clean tracked tree is not sufficient: ignored/untracked files can enter
# Docker COPY or Compose .env. Build from the committed archive only; retain
# this exact source context for rollback/audit, outside all Docker mounts.
SOURCE_ROOT="$(bash "$PROJECT_ROOT/scripts/materialize_deploy_source.sh")"

compose_version="$(docker compose version --short)"
if [[ ! "$compose_version" =~ ^v?([0-9]+)\.([0-9]+)\.([0-9]+) ]] ||
   (( BASH_REMATCH[1] < 2 || (BASH_REMATCH[1] == 2 && (BASH_REMATCH[2] < 24 || (BASH_REMATCH[2] == 24 && BASH_REMATCH[3] < 4))) )); then
  printf 'Docker Compose >= 2.24.4 is required for shared-runtime overrides\n' >&2
  exit 2
fi

mkdir -p "$PROJECT_ROOT/.sandbox-work"
export WEBCOMPILER_WORKER_UID="$(stat -c %u "$PROJECT_ROOT/.sandbox-work")"
export WEBCOMPILER_WORKER_GID="$(stat -c %g "$PROJECT_ROOT/.sandbox-work")"
export WEBCOMPILER_DOCKER_GID="$(stat -c %g /var/run/docker.sock)"

export SECRET_KEY="${SECRET_KEY:-$WEBCOMPILER_SECRET_KEY}"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-$WEBCOMPILER_ADMIN_PASSWORD}"
export ENVIRONMENT="${ENVIRONMENT:-production}"
export PASSWORD_RESET_BASE_URL="${PASSWORD_RESET_BASE_URL:-${WEBCOMPILER_PASSWORD_RESET_BASE_URL:-https://cuha.cju.ac.kr/webcompiler/}}"
export SMTP_HOST="${SMTP_HOST:-${WEBCOMPILER_SMTP_HOST:-}}"
export SMTP_PORT="${SMTP_PORT:-${WEBCOMPILER_SMTP_PORT:-587}}"
export SMTP_USERNAME="${SMTP_USERNAME:-${WEBCOMPILER_SMTP_USERNAME:-}}"
export SMTP_PASSWORD="${SMTP_PASSWORD:-${WEBCOMPILER_SMTP_PASSWORD:-}}"
export SMTP_FROM="${SMTP_FROM:-${WEBCOMPILER_SMTP_FROM:-}}"
export SMTP_STARTTLS="${SMTP_STARTTLS:-${WEBCOMPILER_SMTP_STARTTLS:-true}}"

export WEBCOMPILER_DATA_DIR="${WEBCOMPILER_DATA_DIR:-$PROJECT_ROOT/.data/webcompiler}"
mkdir -p "$WEBCOMPILER_DATA_DIR"

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
export WEBCOMPILER_CORS_ORIGINS="${WEBCOMPILER_CORS_ORIGINS:-https://cuha.cju.ac.kr}"
export WEBCOMPILER_POSTGRES_DB="${WEBCOMPILER_POSTGRES_DB:-compiler}"
export WEBCOMPILER_POSTGRES_USER="${WEBCOMPILER_POSTGRES_USER:-compiler}"
# Never provision a production database with the development password. Existing
# credentials must be supplied by the operator; changing this does not rotate data.
export WEBCOMPILER_POSTGRES_PASSWORD="${WEBCOMPILER_POSTGRES_PASSWORD:?Set the existing or explicitly approved PostgreSQL credential}"

export WEBCOMPILER_SHARED_POSTGRES_NETWORK="${WEBCOMPILER_SHARED_POSTGRES_NETWORK:-$WEBCOMPILER_PROJECT_PREFIX-shared}"
export WEBCOMPILER_SHARED_POSTGRES_NAME="${WEBCOMPILER_SHARED_POSTGRES_NAME:-$WEBCOMPILER_PROJECT_PREFIX-postgres}"
export WEBCOMPILER_SHARED_POSTGRES_VOLUME="${WEBCOMPILER_SHARED_POSTGRES_VOLUME:-$WEBCOMPILER_PROJECT_PREFIX-postgres-data}"
SHARED_POSTGRES_NAME="$WEBCOMPILER_SHARED_POSTGRES_NAME"
SHARED_POSTGRES_VOLUME="$WEBCOMPILER_SHARED_POSTGRES_VOLUME"
SHARED_POSTGRES_NETWORK="$WEBCOMPILER_SHARED_POSTGRES_NETWORK"
SHARED_POSTGRES_IMAGE="${WEBCOMPILER_SHARED_POSTGRES_IMAGE:-postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685}"
export WEBCOMPILER_POSTGRES_HOST="${WEBCOMPILER_POSTGRES_HOST:-$SHARED_POSTGRES_NAME}"
export WEBCOMPILER_POSTGRES_PORT="${WEBCOMPILER_POSTGRES_PORT:-5432}"
export WEBCOMPILER_SHARED_REDIS_NAME="${WEBCOMPILER_SHARED_REDIS_NAME:-$WEBCOMPILER_PROJECT_PREFIX-redis}"
export WEBCOMPILER_SHARED_REDIS_VOLUME="${WEBCOMPILER_SHARED_REDIS_VOLUME:-$WEBCOMPILER_PROJECT_PREFIX-redis-data}"
managed_redis_url="redis://${WEBCOMPILER_SHARED_REDIS_NAME}:6379/0"
export WEBCOMPILER_REDIS_URL="${WEBCOMPILER_REDIS_URL:-$managed_redis_url}"
export WEBCOMPILER_REDIS_KEY_PREFIX="${WEBCOMPILER_REDIS_KEY_PREFIX:-$WEBCOMPILER_PROJECT_PREFIX}"

BLUE_BACKEND_PORT="${WEBCOMPILER_BLUE_BACKEND_PORT:-18001}"
BLUE_FRONTEND_PORT="${WEBCOMPILER_BLUE_FRONTEND_PORT:-15174}"
GREEN_BACKEND_PORT="${WEBCOMPILER_GREEN_BACKEND_PORT:-18002}"
GREEN_FRONTEND_PORT="${WEBCOMPILER_GREEN_FRONTEND_PORT:-15175}"
EDGE_BACKEND_PORT="${WEBCOMPILER_EDGE_BACKEND_PORT:-18000}"
EDGE_FRONTEND_PORT="${WEBCOMPILER_EDGE_FRONTEND_PORT:-15173}"

log() {
  printf '[webcompiler-deploy] %s\n' "$*"
}

color_backend_port() {
  case "$1" in
    blue) printf '%s\n' "$BLUE_BACKEND_PORT" ;;
    green) printf '%s\n' "$GREEN_BACKEND_PORT" ;;
    *) log "invalid color: $1"; exit 2 ;;
  esac
}

color_frontend_port() {
  case "$1" in
    blue) printf '%s\n' "$BLUE_FRONTEND_PORT" ;;
    green) printf '%s\n' "$GREEN_FRONTEND_PORT" ;;
    *) log "invalid color: $1"; exit 2 ;;
  esac
}

next_color() {
  case "$1" in
    blue) printf 'green\n' ;;
    green) printf 'blue\n' ;;
    *) printf 'blue\n' ;;
  esac
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local timeout="${3:-60}"
  local deadline
  deadline=$((SECONDS + timeout))

  until curl --connect-timeout 2 --max-time 5 -fsS "$url" >/dev/null; do
    if (( SECONDS >= deadline )); then
      log "health check failed for $label: $url"
      return 1
    fi
    sleep 1
  done
}

compose_for_color() {
  local color="$1"
  local backend_port
  local frontend_port
  backend_port="$(color_backend_port "$color")"
  frontend_port="$(color_frontend_port "$color")"

  COMPOSE_PROFILES="" \
  COMPOSE_PROJECT_NAME="$WEBCOMPILER_PROJECT_PREFIX-$color" \
  WEBCOMPILER_API_PROXY_PORT_MAPPING="127.0.0.1:${backend_port}:8080" \
  WEBCOMPILER_FRONTEND_PORT_MAPPING="127.0.0.1:${frontend_port}:8080" \
  PROJECT_ROOT="$PROJECT_ROOT" \
  docker compose \
    -p "$WEBCOMPILER_PROJECT_PREFIX-$color" \
    --project-directory "$SOURCE_ROOT" \
    --env-file /dev/null \
    -f "$SOURCE_ROOT/docker-compose.yml" \
    -f "$SOURCE_ROOT/docker-compose.deploy.yml" \
    -f "$SOURCE_ROOT/docker-compose.shared-runtime.yml" \
    -f "$SOURCE_ROOT/docker-compose.lb.yml" \
    -f "$SOURCE_ROOT/docker-compose.ready-lb.yml" \
    "${@:2}"
}

wait_for_color_pool() {
  local color="$1"
  compose_for_color "$color" exec -T proxy-controller \
    python -m app.proxy_promotion --release "$DEPLOY_SHA" --pool "$WEBCOMPILER_PROJECT_PREFIX-$color" --runtime "$WEBCOMPILER_RUNTIME_INSTANCE_ID"
}

ensure_shared_postgres() {
  # Read the app-table gate in the same identity-bound readiness operation;
  # a second name lookup must not silently switch to a replacement database.
  SHARED_DATABASE_HAS_APP_TABLES="$(python3 "$SOURCE_ROOT/scripts/ensure_shared_postgres.py" --has-app-tables)"
  [[ "$SHARED_DATABASE_HAS_APP_TABLES" == "yes" || "$SHARED_DATABASE_HAS_APP_TABLES" == "no" ]]
}

shared_database_has_app_tables() {
  [[ "$SHARED_DATABASE_HAS_APP_TABLES" == "yes" ]]
}

bootstrap_shared_database_from_color() {
  local source_color="$1"
  if [[ -z "$source_color" ]]; then
    return
  fi
  if shared_database_has_app_tables; then
    log "shared postgres already has application tables"
    return
  fi
  # An online snapshot loses writes accepted after the snapshot. Refuse an
  # automatic cutover; an explicit offline backup/restore rehearsal is required.
  log "shared database is empty while a previous color exists; complete verified offline migration before deployment"
  return 1
}

target_color="${WEBCOMPILER_TARGET_COLOR:-$(next_color "$active_color")}"
if [[ "$target_color" == "$active_color" ]]; then
  log "refusing to rebuild the active color in place"
  exit 2
fi
target_backend_port="$(color_backend_port "$target_color")"
target_frontend_port="$(color_frontend_port "$target_color")"
# Refuse rebuilding either a committed color or an unresolved drain target.
WEBCOMPILER_RUNTIME_INSTANCE_ID="$(python3 "$SOURCE_ROOT/scripts/edge_deploy.py" candidate --color "$target_color")"
[[ "$WEBCOMPILER_RUNTIME_INSTANCE_ID" =~ ^[0-9a-f]{32}$ && "$WEBCOMPILER_RUNTIME_INSTANCE_ID" != 00000000000000000000000000000000 ]] || exit 2
export WEBCOMPILER_RUNTIME_INSTANCE_ID

# A legacy @pgbouncer override is ambiguous on the shared blue/green network.
# Do not silently rewrite an operator's external DB URL or migrate its data.
if [[ -n "${WEBCOMPILER_DATABASE_URL:-}" || -n "${WEBCOMPILER_MIGRATION_DATABASE_URL:-}" ]]; then
  log "explicit database URL overrides require a verified shared-target configuration before managed deployment"
  exit 2
fi

WEBCOMPILER_DEPLOY_ACTIVE_COLOR="$active_color" python3 "$SOURCE_ROOT/scripts/verify_shared_redis_cutover.py"
ensure_shared_postgres
bootstrap_shared_database_from_color "$active_color"
if [[ "$WEBCOMPILER_REDIS_URL" == "$managed_redis_url" ]]; then
  python3 "$SOURCE_ROOT/scripts/ensure_shared_redis.py"
else
  log "using explicitly configured shared Redis; runtime readiness must pass"
fi

# Derive the discovery allowlist from an owned private bridge, not a guessed
# subnet or an operator-supplied broad CIDR. Never attach the worker/frontend.
WEBCOMPILER_API_NETWORK_CIDRS="$(COMPOSE_PROJECT_NAME="$WEBCOMPILER_PROJECT_PREFIX-$target_color" \
  python3 "$SOURCE_ROOT/scripts/ensure_api_network.py")"
export WEBCOMPILER_API_NETWORK_CIDRS

log "building sandbox compiler image"
if [[ "$WEBCOMPILER_PROJECT_PREFIX" == webcompiler ]]; then
  export SANDBOX_IMAGE="compiler-sandbox:$DEPLOY_SHA"
else
  export SANDBOX_IMAGE="$WEBCOMPILER_PROJECT_PREFIX-sandbox:$DEPLOY_SHA"
fi
pinned_bpp_ref="$(tr -d '\r\n' < "$SOURCE_ROOT/runtime/bpp-ref.txt")"
[[ "$pinned_bpp_ref" =~ ^[0-9a-f]{40}$ ]] || exit 2
BPP_REPO="https://github.com/Creeper0809/Bpp" BPP_REF="$pinned_bpp_ref" \
  bash "$SOURCE_ROOT/scripts/build_sandbox_image.sh"

log "deploying $target_color stack on frontend:$target_frontend_port backend:$target_backend_port"
# Do not remove color-local legacy database/Redis containers as orphans. Their
# data migration/retirement needs a separate verified offline procedure.
python3 "$SOURCE_ROOT/scripts/verify_build_builder.py" >/dev/null
compose_for_color "$target_color" build --builder "$WEBCOMPILER_BUILD_BUILDER"
python3 "$SOURCE_ROOT/scripts/verify_build_builder.py" >/dev/null
compose_for_color "$target_color" up --no-build -d

log "checking $target_color stack readiness"
wait_for_color_pool "$target_color"
wait_for_url "http://127.0.0.1:${target_backend_port}/ready" "$target_color backend"
wait_for_url "http://127.0.0.1:${target_frontend_port}/health" "$target_color frontend"

log "transactionally switching edge to $target_color"
actual_active_color="$(python3 "$SOURCE_ROOT/scripts/edge_deploy.py" switch --color "$target_color")"
[[ "$actual_active_color" == "$target_color" ]] || exit 1
log "committed color is now $target_color; prior runtimes retained until verified drain"

if [[ "${WEBCOMPILER_ENABLE_SANDBOX_UPDATER:-0}" == "1" ]]; then
  log "installing sandbox updater timer"
  if ! bash "$PROJECT_ROOT/scripts/install_sandbox_updater_timer.sh"; then
    log "sandbox updater timer install failed; continuing deployment"
  fi
fi

# Runtime retirement is a separate verified operation. Never stop a color
# merely because edge HUP/postflight succeeded; held HTTP/WS/jobs may remain.
