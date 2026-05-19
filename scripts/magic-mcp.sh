#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE_ENV="/home/cresp3/.env.ai.local"
PROJECT_ENV="$ROOT_DIR/.env.ai.local"

# Load workspace defaults first, then allow project-local overrides.
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

if [ -z "${TWENTYFIRST_API_KEY:-}" ]; then
  echo "TWENTYFIRST_API_KEY is not set."
  echo "Create $PROJECT_ENV from .env.ai.example, or set it once in $WORKSPACE_ENV."
  exit 1
fi

API_KEY="$TWENTYFIRST_API_KEY" npx -y @21st-dev/magic@latest
