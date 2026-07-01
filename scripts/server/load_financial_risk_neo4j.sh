#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"
IMPORT_FILE="$REPO_ROOT/examples/financial_risk/load_neo4j.cypher"

load_env_file

NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-xgap-lab-password}"

wait_for_cypher() {
  for attempt in $(seq 1 90); do
    if printf 'RETURN 1;\n' | compose exec -T neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" >/dev/null 2>&1; then
      return 0
    fi
    echo "Waiting for Neo4j Bolt/cypher-shell ($attempt/90)"
    sleep 2
  done

  echo "Neo4j cypher-shell did not become ready." >&2
  return 1
}

wait_for_cypher
compose exec -T neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" < "$IMPORT_FILE"
echo "Loaded financial-risk toy data into Neo4j."
