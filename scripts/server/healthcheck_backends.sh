#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"

load_env_file

NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-7474}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-xgap-lab-password}"
FUSEKI_PORT="${FUSEKI_PORT:-3030}"

wait_for_neo4j() {
  local attempts="${1:-120}"
  local delay="${2:-2}"

  for attempt in $(seq 1 "$attempts"); do
    if printf 'RETURN 1;\n' | compose exec -T neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" >/dev/null 2>&1; then
      echo "Neo4j Bolt/cypher-shell is ready."
      if curl -fs -o /dev/null "http://127.0.0.1:$NEO4J_HTTP_PORT/"; then
        echo "Neo4j HTTP is reachable: http://127.0.0.1:$NEO4J_HTTP_PORT/"
      else
        echo "Neo4j Bolt is ready; HTTP browser may still be warming up on port $NEO4J_HTTP_PORT."
      fi
      return 0
    fi

    if compose ps | grep -E "xgap-neo4j|neo4j" | grep -q "Restarting"; then
      echo "Neo4j container is restarting. Recent neo4j logs:" >&2
      compose logs --tail=120 neo4j >&2 || true
      return 1
    fi

    echo "Waiting for Neo4j Bolt/cypher-shell ($attempt/$attempts)"
    sleep "$delay"
  done

  echo "Neo4j did not become ready." >&2
  echo "Recent neo4j logs:" >&2
  compose logs --tail=120 neo4j >&2 || true
  return 1
}

wait_for_fuseki_url() {
  local name="$1"
  local url="$2"
  local service="${3:-}"
  local attempts="${4:-90}"
  local delay="${5:-2}"

  for attempt in $(seq 1 "$attempts"); do
    if curl -fsS -o /dev/null "$url"; then
      echo "$name is reachable: $url"
      return 0
    fi

    if [ -n "$service" ] && compose ps | grep -E "xgap-$service|$service" | grep -q "Restarting"; then
      echo "$name container is restarting. Recent $service logs:" >&2
      compose logs --tail=120 "$service" >&2 || true
      return 1
    fi

    echo "Waiting for $name ($attempt/$attempts): $url"
    sleep "$delay"
  done

  echo "$name did not become reachable: $url" >&2
  if [ -n "$service" ]; then
    echo "Recent $service logs:" >&2
    compose logs --tail=120 "$service" >&2 || true
  fi
  return 1
}

compose ps
wait_for_neo4j
wait_for_fuseki_url "Fuseki ping" "http://127.0.0.1:$FUSEKI_PORT/\$/ping" "fuseki"

echo "Backend healthcheck passed."
