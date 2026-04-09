#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BPP_RUNNER="$ROOT_DIR/sandbox-runner/cmd/bpp_runner.py"

print_usage() {
  cat <<EOF
Usage:
  run.sh bpp <source.bpp> [--mode run|dump-ir|dump-ssa|asm] [--opt-level O0|O1]
  run.sh bpp-json <request.json>
EOF
}

if [[ $# -lt 1 ]]; then
  print_usage
  exit 2
fi

MODE="$1"
shift

case "$MODE" in
  bpp)
    if [[ $# -lt 1 ]]; then
      print_usage
      exit 2
    fi
    SOURCE_FILE="$1"
    shift
    exec python3 "$BPP_RUNNER" --source "$SOURCE_FILE" "$@"
    ;;
  bpp-json)
    if [[ $# -ne 1 ]]; then
      print_usage
      exit 2
    fi
    exec python3 "$BPP_RUNNER" --request "$1"
    ;;
  *)
    echo "Unsupported runtime mode: $MODE" >&2
    print_usage
    exit 1
    ;;
esac
