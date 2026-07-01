#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"
QUERY_FILE="$REPO_ROOT/examples/financial_risk/smoke_fuseki.rq"

load_env_file

FUSEKI_PORT="${FUSEKI_PORT:-3030}"
FUSEKI_DATASET_NAME="${FUSEKI_DATASET_NAME:-xgap}"
FUSEKI_URL="${FUSEKI_URL:-http://127.0.0.1:$FUSEKI_PORT}"

RESULT="$(
  curl -fsS \
    -H "Accept: text/csv" \
    --data-urlencode "query@$QUERY_FILE" \
    "$FUSEKI_URL/$FUSEKI_DATASET_NAME/sparql"
)"
printf '%s\n' "$RESULT"

if printf '%s\n' "$RESULT" | grep -Eq 'Redstone Analytics|BlackPeak Trading'; then
  echo "Fuseki smoke query returned high-risk companies."
else
  echo "Fuseki smoke query returned no expected high-risk company rows." >&2
  exit 1
fi
