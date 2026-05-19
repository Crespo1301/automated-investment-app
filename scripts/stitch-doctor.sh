#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_ENV="/home/cresp3/.env.ai.local"
PROJECT_ENV="$ROOT_DIR/.env.ai.local"

if [ -f "$WORKSPACE_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$WORKSPACE_ENV"
  set +a
fi

if [ -f "$PROJECT_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$PROJECT_ENV"
  set +a
fi

npx -y @_davideast/stitch-mcp doctor
