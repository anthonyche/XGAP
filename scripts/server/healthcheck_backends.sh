#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="${XGAP_REPO_ROOT:-$DEFAULT_REPO_ROOT}"
COMPOSE_FILE="$REPO_ROOT/services/docker-compose.yml"
ENV_FILE="$REPO_ROOT/services/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-7474}"
FUSEKI_PORT="${FUSEKI_PORT:-3030}"

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

wait_for_url() {
  local name="$1"
  local url="$2"
  local attempts="${3:-90}"
  local delay="${4:-2}"

  for attempt in $(seq 1 "$attempts"); do
    if curl -fsS -o /dev/null "$url"; then
      echo "$name is reachable: $url"
      return 0
    fi
    echo "Waiting for $name ($attempt/$attempts): $url"
    sleep "$delay"
  done

  echo "$name did not become reachable: $url" >&2
  return 1
}

compose ps
wait_for_url "Neo4j HTTP" "http://127.0.0.1:$NEO4J_HTTP_PORT/"
wait_for_url "Fuseki ping" "http://127.0.0.1:$FUSEKI_PORT/\$/ping"

echo "Backend healthcheck passed."
