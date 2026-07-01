#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="${XGAP_REPO_ROOT:-$DEFAULT_REPO_ROOT}"
COMPOSE_FILE="$REPO_ROOT/services/docker-compose.yml"
ENV_FILE="$REPO_ROOT/services/.env"
QUERY_FILE="/var/lib/neo4j/import/financial_risk/smoke_neo4j.cypher"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-xgap-lab-password}"

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

RESULT="$(compose exec -T neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" --format plain -f "$QUERY_FILE")"
printf '%s\n' "$RESULT"

if printf '%s\n' "$RESULT" | grep -Eq 'Redstone Analytics|BlackPeak Trading'; then
  echo "Neo4j smoke query returned high-risk companies."
else
  echo "Neo4j smoke query returned no expected high-risk company rows." >&2
  exit 1
fi
