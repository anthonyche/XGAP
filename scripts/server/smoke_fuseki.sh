#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="${XGAP_REPO_ROOT:-$DEFAULT_REPO_ROOT}"
ENV_FILE="$REPO_ROOT/services/.env"
QUERY_FILE="$REPO_ROOT/examples/financial_risk/smoke_fuseki.rq"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

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
