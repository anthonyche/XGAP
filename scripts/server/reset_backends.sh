#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="${XGAP_REPO_ROOT:-$DEFAULT_REPO_ROOT}"
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

if [ "${1:-}" != "--yes" ]; then
  echo "This will stop containers and delete persistent Neo4j/Fuseki volumes."
  read -r -p "Type RESET to continue: " answer
  if [ "$answer" != "RESET" ]; then
    echo "Reset cancelled."
    exit 0
  fi
fi

compose down -v --remove-orphans
echo "Removed XGAP backend containers and persistent volumes."
