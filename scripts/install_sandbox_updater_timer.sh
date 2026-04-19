#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$ROOT_DIR}"
INTERVAL="${SANDBOX_UPDATER_INTERVAL:-60s}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_FILE="$UNIT_DIR/webcompiler-sandbox-updater.service"
TIMER_FILE="$UNIT_DIR/webcompiler-sandbox-updater.timer"

log() {
  printf '[sandbox-updater-install] %s\n' "$*"
}

if ! command -v systemctl >/dev/null 2>&1; then
  log "systemctl is not available; skipping timer install"
  exit 0
fi

mkdir -p "$UNIT_DIR"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Update Bpp compiler sandbox image when upstream main changes

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_ROOT
Environment=PROJECT_ROOT=$PROJECT_ROOT
Environment=BPP_REPO=${BPP_REPO:-https://github.com/Creeper0809/Bpp}
Environment=BPP_BRANCH=${BPP_BRANCH:-main}
ExecStart=/usr/bin/env bash $PROJECT_ROOT/scripts/update_sandbox_image_if_needed.sh
EOF

cat > "$TIMER_FILE" <<EOF
[Unit]
Description=Run Bpp compiler sandbox updater every minute

[Timer]
OnBootSec=30s
OnUnitActiveSec=$INTERVAL
AccuracySec=10s
Persistent=true
Unit=webcompiler-sandbox-updater.service

[Install]
WantedBy=timers.target
EOF

if systemctl --user daemon-reload >/dev/null 2>&1 \
  && systemctl --user enable --now webcompiler-sandbox-updater.timer >/dev/null 2>&1; then
  log "enabled user timer webcompiler-sandbox-updater.timer with interval $INTERVAL"
  exit 0
fi

log "could not enable user timer automatically"
log "manual commands:"
log "  systemctl --user daemon-reload"
log "  systemctl --user enable --now webcompiler-sandbox-updater.timer"
