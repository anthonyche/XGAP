#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="${XGAP_LAB_ROOT:-/xgap-lab}"
REPO_ROOT="${XGAP_REPO_ROOT:-$LAB_ROOT/repo/XGAP}"
COMPOSE_FILE="$REPO_ROOT/services/docker-compose.yml"
ENV_FILE="$REPO_ROOT/services/.env"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  else
    echo "Docker Compose is required." >&2
    exit 1
  fi
}

compose stop
echo "Stopped XGAP backend containers."
