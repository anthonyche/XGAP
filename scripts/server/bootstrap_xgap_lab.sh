#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"
LAB_ROOT="${XGAP_LAB_ROOT:-$REPO_ROOT}"

if [ ! -f "$REPO_ROOT/services/docker-compose.yml" ]; then
  echo "Missing $REPO_ROOT/services/docker-compose.yml" >&2
  exit 1
fi

if [ -f "$REPO_ROOT/services/.env" ]; then
  echo "Using existing $REPO_ROOT/services/.env"
else
  ensure_env_file
fi

ensure_docker_cmd
if "${DOCKER_CMD[@]}" compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is available."
elif command -v docker-compose >/dev/null 2>&1; then
  echo "docker-compose is available."
else
  echo "Docker Compose is required but was not found." >&2
  exit 1
fi

echo "XGAP backend lab bootstrap complete."
echo "Repo root: $REPO_ROOT"
echo "Lab root: $LAB_ROOT"
echo "Next: bash scripts/server/start_backends.sh"
