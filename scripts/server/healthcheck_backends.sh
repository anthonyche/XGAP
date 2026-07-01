#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"

load_env_file

NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-7474}"
FUSEKI_PORT="${FUSEKI_PORT:-3030}"

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
