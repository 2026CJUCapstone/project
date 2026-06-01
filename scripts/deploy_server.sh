#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"

mkdir -p "$PROJECT_ROOT/.sandbox-work" "$PROJECT_ROOT/.deploy"
exec 9>"$PROJECT_ROOT/.deploy/deploy.lock"
if ! flock -n 9; then
  printf '[webcompiler-deploy] %s\n' "another deployment is already running"
  exit 1
fi

RUNTIME_SECRETS_FILE="$PROJECT_ROOT/.deploy/runtime-secrets.env"

ensure_runtime_secret() {
  local key="$1"
  local bytes="$2"
  if [[ -f "$RUNTIME_SECRETS_FILE" ]] && grep -q "^${key}=" "$RUNTIME_SECRETS_FILE"; then
    return
  fi
  umask 077
  printf '%s=%s\n' "$key" "$(python3 -c "import secrets; print(secrets.token_urlsafe(${bytes}))")" >> "$RUNTIME_SECRETS_FILE"
}

ensure_runtime_secret WEBCOMPILER_SECRET_KEY 48
ensure_runtime_secret WEBCOMPILER_ADMIN_PASSWORD 32
chmod 600 "$RUNTIME_SECRETS_FILE"

set -a
source "$RUNTIME_SECRETS_FILE"
set +a
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
export WEBCOMPILER_POSTGRES_PASSWORD="${WEBCOMPILER_POSTGRES_PASSWORD:-compiler}"

export WEBCOMPILER_SHARED_POSTGRES_NETWORK="${WEBCOMPILER_SHARED_POSTGRES_NETWORK:-webcompiler-shared}"
SHARED_POSTGRES_NAME="${WEBCOMPILER_SHARED_POSTGRES_NAME:-webcompiler-postgres}"
SHARED_POSTGRES_VOLUME="${WEBCOMPILER_SHARED_POSTGRES_VOLUME:-webcompiler-postgres-data}"
SHARED_POSTGRES_NETWORK="$WEBCOMPILER_SHARED_POSTGRES_NETWORK"
SHARED_POSTGRES_IMAGE="${WEBCOMPILER_SHARED_POSTGRES_IMAGE:-postgres:16-alpine}"
export WEBCOMPILER_POSTGRES_HOST="${WEBCOMPILER_POSTGRES_HOST:-$SHARED_POSTGRES_NAME}"
export WEBCOMPILER_POSTGRES_PORT="${WEBCOMPILER_POSTGRES_PORT:-5432}"

BLUE_BACKEND_PORT="${WEBCOMPILER_BLUE_BACKEND_PORT:-18001}"
BLUE_FRONTEND_PORT="${WEBCOMPILER_BLUE_FRONTEND_PORT:-15174}"
GREEN_BACKEND_PORT="${WEBCOMPILER_GREEN_BACKEND_PORT:-18002}"
GREEN_FRONTEND_PORT="${WEBCOMPILER_GREEN_FRONTEND_PORT:-15175}"
EDGE_BACKEND_PORT="${WEBCOMPILER_EDGE_BACKEND_PORT:-18000}"
EDGE_FRONTEND_PORT="${WEBCOMPILER_EDGE_FRONTEND_PORT:-15173}"
STATE_FILE="${WEBCOMPILER_ACTIVE_COLOR_FILE:-$PROJECT_ROOT/.deploy/active-color}"
LEGACY_PROJECT_NAME="${WEBCOMPILER_LEGACY_PROJECT_NAME:-webcompiler}"

FRONTEND_EDGE_NAME="${WEBCOMPILER_FRONTEND_EDGE_NAME:-webcompiler-edge-frontend}"
BACKEND_EDGE_NAME="${WEBCOMPILER_BACKEND_EDGE_NAME:-webcompiler-edge-backend}"
FRONTEND_EDGE_CONF="$PROJECT_ROOT/.deploy/frontend-edge.conf"
BACKEND_EDGE_CONF="$PROJECT_ROOT/.deploy/backend-edge.conf"

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

  until curl -fsS "$url" >/dev/null; do
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

  COMPOSE_PROJECT_NAME="webcompiler-$color" \
  WEBCOMPILER_BACKEND_PORT_MAPPING="127.0.0.1:${backend_port}:8000" \
  WEBCOMPILER_FRONTEND_PORT_MAPPING="127.0.0.1:${frontend_port}:80" \
  PROJECT_ROOT="$PROJECT_ROOT" \
  docker compose \
    -p "webcompiler-$color" \
    -f "$PROJECT_ROOT/docker-compose.yml" \
    -f "$PROJECT_ROOT/docker-compose.deploy.yml" \
    "${@:2}"
}

postgres_container_name() {
  printf 'webcompiler-%s-postgres-1\n' "$1"
}

backend_container_name() {
  printf 'webcompiler-%s-backend-1\n' "$1"
}

container_is_on_network() {
  local container="$1"
  local network="$2"
  docker inspect "$container" --format '{{json .NetworkSettings.Networks}}' 2>/dev/null \
    | grep -q "\"$network\""
}

wait_for_shared_postgres() {
  local timeout="${1:-60}"
  local deadline
  deadline=$((SECONDS + timeout))

  until docker exec "$SHARED_POSTGRES_NAME" \
    pg_isready \
      -U "$WEBCOMPILER_POSTGRES_USER" \
      -d "$WEBCOMPILER_POSTGRES_DB" \
      >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      log "shared postgres did not become ready"
      return 1
    fi
    sleep 1
  done
}

ensure_shared_postgres() {
  if ! docker network inspect "$SHARED_POSTGRES_NETWORK" >/dev/null 2>&1; then
    log "creating shared postgres network $SHARED_POSTGRES_NETWORK"
    docker network create "$SHARED_POSTGRES_NETWORK" >/dev/null
  fi

  if docker ps -a --format '{{.Names}}' | grep -Fxq "$SHARED_POSTGRES_NAME"; then
    if ! docker ps --format '{{.Names}}' | grep -Fxq "$SHARED_POSTGRES_NAME"; then
      log "starting shared postgres $SHARED_POSTGRES_NAME"
      docker start "$SHARED_POSTGRES_NAME" >/dev/null
    fi
    if ! container_is_on_network "$SHARED_POSTGRES_NAME" "$SHARED_POSTGRES_NETWORK"; then
      docker network connect "$SHARED_POSTGRES_NETWORK" "$SHARED_POSTGRES_NAME"
    fi
  else
    log "creating shared postgres $SHARED_POSTGRES_NAME"
    docker run -d \
      --name "$SHARED_POSTGRES_NAME" \
      --restart unless-stopped \
      --network "$SHARED_POSTGRES_NETWORK" \
      -e "POSTGRES_DB=$WEBCOMPILER_POSTGRES_DB" \
      -e "POSTGRES_USER=$WEBCOMPILER_POSTGRES_USER" \
      -e "POSTGRES_PASSWORD=$WEBCOMPILER_POSTGRES_PASSWORD" \
      -v "$SHARED_POSTGRES_VOLUME:/var/lib/postgresql/data" \
      "$SHARED_POSTGRES_IMAGE" >/dev/null
  fi

  wait_for_shared_postgres
}

shared_database_has_app_tables() {
  local table_count
  table_count="$(
    docker exec "$SHARED_POSTGRES_NAME" \
      psql \
        -U "$WEBCOMPILER_POSTGRES_USER" \
        -d "$WEBCOMPILER_POSTGRES_DB" \
        -tAc "select count(*) from information_schema.tables where table_schema = 'public' and table_name in ('problems', 'users', 'user_problem_scores');"
  )"
  [[ "${table_count//[[:space:]]/}" != "0" ]]
}

bootstrap_shared_database_from_color() {
  local source_color="$1"

  if [[ -z "$source_color" ]]; then
    return
  fi

  if shared_database_has_app_tables; then
    log "shared postgres already has application tables; skipping bootstrap"
    return
  fi

  local source_container
  source_container="$(postgres_container_name "$source_color")"

  if ! docker ps --format '{{.Names}}' | grep -Fxq "$source_container"; then
    log "active postgres $source_container is not running; skipping shared database bootstrap"
    return
  fi

  log "bootstrapping shared postgres from $source_color database"
  docker exec "$source_container" \
    pg_dump \
      -U "$WEBCOMPILER_POSTGRES_USER" \
      -d "$WEBCOMPILER_POSTGRES_DB" \
      --clean \
      --if-exists \
      --no-owner \
      --no-privileges \
    | docker exec -i "$SHARED_POSTGRES_NAME" \
        psql \
          -v ON_ERROR_STOP=1 \
          -U "$WEBCOMPILER_POSTGRES_USER" \
          -d "$WEBCOMPILER_POSTGRES_DB" \
          >/dev/null
}

connect_backend_to_shared_postgres() {
  local color="$1"
  local backend_container
  backend_container="$(backend_container_name "$color")"

  if ! docker ps -a --format '{{.Names}}' | grep -Fxq "$backend_container"; then
    log "backend $backend_container does not exist; skipping shared postgres network attach"
    return
  fi

  if ! container_is_on_network "$backend_container" "$SHARED_POSTGRES_NETWORK"; then
    log "attaching $backend_container to shared postgres network"
    docker network connect "$SHARED_POSTGRES_NETWORK" "$backend_container"
  fi

  compose_for_color "$color" restart backend
}

write_edge_configs() {
  local backend_port="$1"
  local frontend_port="$2"
  local edge_backend_port="$3"
  local edge_frontend_port="$4"

  cat > "$BACKEND_EDGE_CONF" <<EOF
server {
    listen 127.0.0.1:${edge_backend_port};
    server_name _;

    location /ws/terminal {
        proxy_pass http://127.0.0.1:${backend_port}/ws/terminal;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:${backend_port}/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:${backend_port};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

  cat > "$FRONTEND_EDGE_CONF" <<EOF
server {
    listen 127.0.0.1:${edge_frontend_port};
    server_name _;

    location /webcompiler/ws/terminal {
        proxy_pass http://127.0.0.1:${backend_port}/ws/terminal;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location /ws/terminal {
        proxy_pass http://127.0.0.1:${backend_port}/ws/terminal;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location /webcompiler/api/ {
        proxy_pass http://127.0.0.1:${backend_port}/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:${backend_port}/api/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location = /webcompiler/health {
        proxy_pass http://127.0.0.1:${backend_port}/health;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location = /health {
        proxy_pass http://127.0.0.1:${backend_port}/health;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:${frontend_port};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
}

ensure_edge_container() {
  local name="$1"
  local conf_path="$2"

  if docker ps --format '{{.Names}}' | grep -Fxq "$name"; then
    local network_mode
    network_mode="$(docker inspect "$name" --format '{{.HostConfig.NetworkMode}}')"
    if [[ "$network_mode" == "host" ]]; then
      docker exec "$name" nginx -s reload
      return
    fi
  fi

  if docker ps -a --format '{{.Names}}' | grep -Fxq "$name"; then
    docker rm -f "$name" >/dev/null
  fi

  docker run -d \
    --name "$name" \
    --restart unless-stopped \
    --network host \
    -v "$conf_path:/etc/nginx/conf.d/default.conf:ro" \
    nginx:1.27-alpine >/dev/null
}

stop_legacy_stack_if_present() {
  if docker ps --format '{{.Names}}' | grep -Eq "^${LEGACY_PROJECT_NAME}-(backend|frontend)-1$"; then
    log "stopping legacy single-stack deployment to free edge ports"
    COMPOSE_PROJECT_NAME="$LEGACY_PROJECT_NAME" \
    PROJECT_ROOT="$PROJECT_ROOT" \
    docker compose \
      -p "$LEGACY_PROJECT_NAME" \
      -f "$PROJECT_ROOT/docker-compose.yml" \
      -f "$PROJECT_ROOT/docker-compose.deploy.yml" \
      down --remove-orphans
  fi
}

active_color=""
if [[ -f "$STATE_FILE" ]]; then
  active_color="$(tr -d '[:space:]' < "$STATE_FILE")"
fi

ensure_shared_postgres
bootstrap_shared_database_from_color "$active_color"

target_color="${WEBCOMPILER_TARGET_COLOR:-$(next_color "$active_color")}"
target_backend_port="$(color_backend_port "$target_color")"
target_frontend_port="$(color_frontend_port "$target_color")"

log "building sandbox compiler image"
bash "$PROJECT_ROOT/scripts/build_sandbox_image.sh"

log "deploying $target_color stack on frontend:$target_frontend_port backend:$target_backend_port"
compose_for_color "$target_color" up --build -d --remove-orphans

connect_backend_to_shared_postgres "$target_color"

log "checking $target_color stack health"
wait_for_url "http://127.0.0.1:${target_backend_port}/health" "$target_color backend"
wait_for_url "http://127.0.0.1:${target_frontend_port}/health" "$target_color frontend"

stop_legacy_stack_if_present

log "switching edge proxies to $target_color"
write_edge_configs "$target_backend_port" "$target_frontend_port" "$EDGE_BACKEND_PORT" "$EDGE_FRONTEND_PORT"
ensure_edge_container "$BACKEND_EDGE_NAME" "$BACKEND_EDGE_CONF"
ensure_edge_container "$FRONTEND_EDGE_NAME" "$FRONTEND_EDGE_CONF"

wait_for_url "http://127.0.0.1:${EDGE_BACKEND_PORT}/health" "edge backend"
wait_for_url "http://127.0.0.1:${EDGE_FRONTEND_PORT}/health" "edge frontend"

printf '%s\n' "$target_color" > "$STATE_FILE"
actual_active_color="$(tr -d '[:space:]' < "$STATE_FILE")"
if [[ "$actual_active_color" != "$target_color" ]]; then
  log "active color file mismatch: expected $target_color, got $actual_active_color"
  exit 1
fi
log "active color is now $target_color"

if [[ "${WEBCOMPILER_ENABLE_SANDBOX_UPDATER:-1}" == "1" ]]; then
  log "installing sandbox updater timer"
  if ! bash "$PROJECT_ROOT/scripts/install_sandbox_updater_timer.sh"; then
    log "sandbox updater timer install failed; continuing deployment"
  fi
fi

if [[ "${WEBCOMPILER_STOP_OLD_AFTER_DEPLOY:-0}" == "1" && -n "$active_color" && "$active_color" != "$target_color" ]]; then
  log "stopping previous $active_color stack"
  compose_for_color "$active_color" down --remove-orphans
fi
