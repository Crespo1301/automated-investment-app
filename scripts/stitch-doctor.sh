#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$ROOT_DIR/.env.ai.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.ai.local"
  set +a
fi

npx -y @_davideast/stitch-mcp doctor
