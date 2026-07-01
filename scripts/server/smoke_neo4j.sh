#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"
QUERY_FILE="$REPO_ROOT/examples/financial_risk/smoke_neo4j.cypher"

load_env_file

NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-xgap-lab-password}"

RESULT="$(compose exec -T neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" --format plain < "$QUERY_FILE")"
printf '%s\n' "$RESULT"

if printf '%s\n' "$RESULT" | grep -Eq 'Redstone Analytics|BlackPeak Trading'; then
  echo "Neo4j smoke query returned high-risk companies."
else
  echo "Neo4j smoke query returned no expected high-risk company rows." >&2
  echo "Neo4j diagnostic counts:" >&2
  printf 'MATCH (n) RETURN labels(n) AS labels, count(*) AS count ORDER BY labels;\nMATCH ()-[r]->() RETURN type(r) AS relationship, count(*) AS count ORDER BY relationship;\nMATCH (:Person {name: "Alice"})-[:OWNS]->(:Account)-[:TRANSFER]->(:Account)<-[:OWNS]-(:Company {risk_level: "HIGH"}) RETURN count(*) AS high_risk_paths;\n' \
    | compose exec -T neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" --format plain >&2 || true
  exit 1
fi
