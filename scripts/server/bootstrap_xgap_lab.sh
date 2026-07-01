#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="${XGAP_LAB_ROOT:-/xgap-lab}"
REPO_ROOT="${XGAP_REPO_ROOT:-$LAB_ROOT/repo/XGAP}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTUAL_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

mkdir -p "$LAB_ROOT/repo" "$LAB_ROOT/data" "$LAB_ROOT/logs"

if [ "$ACTUAL_REPO_ROOT" != "$REPO_ROOT" ]; then
  if [ ! -e "$REPO_ROOT" ]; then
    ln -s "$ACTUAL_REPO_ROOT" "$REPO_ROOT"
    echo "Linked current checkout to expected repo path: $REPO_ROOT"
  else
    echo "Expected repo path already exists: $REPO_ROOT"
    echo "Current checkout is: $ACTUAL_REPO_ROOT"
  fi
fi

if [ ! -f "$REPO_ROOT/services/docker-compose.yml" ]; then
  echo "Missing $REPO_ROOT/services/docker-compose.yml" >&2
  exit 1
fi

if [ ! -f "$REPO_ROOT/services/.env" ]; then
  cp "$REPO_ROOT/services/.env.example" "$REPO_ROOT/services/.env"
  echo "Created $REPO_ROOT/services/.env from .env.example"
else
  echo "Using existing $REPO_ROOT/services/.env"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required but was not found in PATH." >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is available."
elif command -v docker-compose >/dev/null 2>&1; then
  echo "docker-compose is available."
else
  echo "Docker Compose is required but was not found." >&2
  exit 1
fi

echo "XGAP backend lab bootstrap complete."
echo "Repo root: $REPO_ROOT"
echo "Next: bash scripts/server/start_backends.sh"
