#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$ROOT_DIR/.env.ai.local" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.ai.local"
  set +a
fi

if [ -z "${TWENTYFIRST_API_KEY:-}" ]; then
  echo "TWENTYFIRST_API_KEY is not set."
  echo "Create $ROOT_DIR/.env.ai.local from .env.ai.example and add your 21st.dev key."
  exit 1
fi

API_KEY="$TWENTYFIRST_API_KEY" npx -y @21st-dev/magic@latest
