#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$ROOT_DIR/.env.ai.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.ai.local"
  set +a
fi

if [ -z "${STITCH_API_KEY:-}" ]; then
  echo "STITCH_API_KEY is not set."
  echo "Create $ROOT_DIR/.env.ai.local from .env.ai.example and add your Stitch key."
  exit 1
fi

npx -y @_davideast/stitch-mcp proxy
