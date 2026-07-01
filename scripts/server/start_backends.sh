#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="${XGAP_LAB_ROOT:-/xgap-lab}"
REPO_ROOT="${XGAP_REPO_ROOT:-$LAB_ROOT/repo/XGAP}"
COMPOSE_FILE="$REPO_ROOT/services/docker-compose.yml"
ENV_FILE="$REPO_ROOT/services/.env"

if [ ! -f "$ENV_FILE" ]; then
  cp "$REPO_ROOT/services/.env.example" "$ENV_FILE"
  echo "Created $ENV_FILE from .env.example"
fi

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

compose up -d

echo "Neo4j and Fuseki containers are starting."
echo "Run: bash scripts/server/healthcheck_backends.sh"
