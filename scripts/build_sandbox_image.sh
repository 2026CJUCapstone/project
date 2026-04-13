#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PROJECT_ROOT="$ROOT_DIR"

BPP_REPO="${BPP_REPO:-https://github.com/Creeper0809/Bpp}"
BPP_BRANCH="${BPP_BRANCH:-main}"
BPP_REF="$(git ls-remote "$BPP_REPO" "refs/heads/$BPP_BRANCH" | awk 'NR==1 { print $1 }')"

if [[ -z "$BPP_REF" ]]; then
  echo "failed to resolve $BPP_REPO branch $BPP_BRANCH" >&2
  exit 1
fi

BPP_RELEASE_API="${BPP_RELEASE_API:-https://api.github.com/repos/Creeper0809/Bpp/releases/latest}"
bootstrap_json="$(curl -fsSL "$BPP_RELEASE_API")"
read -r BPP_BOOTSTRAP_TAG BPP_BOOTSTRAP_URL BPP_BOOTSTRAP_SHA256 < <(
  printf '%s' "$bootstrap_json" | python3 -c '
import json, sys

data = json.load(sys.stdin)
tag = data.get("tag_name", "")
assets = data.get("assets", [])
binary = next((a for a in assets if a.get("name", "").endswith("linux-x86_64") and not a.get("name", "").endswith(".sha256")), None)
if binary is None:
    raise SystemExit("latest release does not contain linux bootstrap asset")
digest = binary.get("digest", "")
sha256 = digest.split("sha256:", 1)[1] if digest.startswith("sha256:") else ""
print(tag, binary.get("browser_download_url", ""), sha256)
'
)

if [[ -z "$BPP_BOOTSTRAP_TAG" || -z "$BPP_BOOTSTRAP_URL" || -z "$BPP_BOOTSTRAP_SHA256" ]]; then
  echo "failed to resolve latest Bpp bootstrap release asset" >&2
  exit 1
fi

echo "Building sandbox with Bpp $BPP_BRANCH @ $BPP_REF using bootstrap $BPP_BOOTSTRAP_TAG"

docker build \
  --shm-size=2g \
  --build-arg "BPP_REPO=$BPP_REPO" \
  --build-arg "BPP_REF=$BPP_REF" \
  --build-arg "BPP_BOOTSTRAP_TAG=$BPP_BOOTSTRAP_TAG" \
  --build-arg "BPP_BOOTSTRAP_URL=$BPP_BOOTSTRAP_URL" \
  --build-arg "BPP_BOOTSTRAP_SHA256=$BPP_BOOTSTRAP_SHA256" \
  -t compiler-sandbox \
  -f "$PROJECT_ROOT/runtime/docker/Dockerfile" \
  "$PROJECT_ROOT/runtime"
