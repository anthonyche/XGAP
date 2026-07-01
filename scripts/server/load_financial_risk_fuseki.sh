#!/usr/bin/env bash
set -euo pipefail

LAB_ROOT="${XGAP_LAB_ROOT:-/xgap-lab}"
REPO_ROOT="${XGAP_REPO_ROOT:-$LAB_ROOT/repo/XGAP}"
ENV_FILE="$REPO_ROOT/services/.env"
DATA_FILE="$REPO_ROOT/examples/financial_risk/load_fuseki.ttl"

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

FUSEKI_ADMIN_USER="${FUSEKI_ADMIN_USER:-admin}"
FUSEKI_ADMIN_PASSWORD="${FUSEKI_ADMIN_PASSWORD:-xgap-lab-password}"
FUSEKI_PORT="${FUSEKI_PORT:-3030}"
FUSEKI_DATASET_NAME="${FUSEKI_DATASET_NAME:-xgap}"
FUSEKI_URL="${FUSEKI_URL:-http://127.0.0.1:$FUSEKI_PORT}"

wait_for_fuseki() {
  for attempt in $(seq 1 90); do
    if curl -fsS -o /dev/null "$FUSEKI_URL/\$/ping"; then
      return 0
    fi
    echo "Waiting for Fuseki ($attempt/90)"
    sleep 2
  done

  echo "Fuseki did not become ready." >&2
  return 1
}

wait_for_fuseki
curl -fsS \
  -u "$FUSEKI_ADMIN_USER:$FUSEKI_ADMIN_PASSWORD" \
  -X PUT \
  -H "Content-Type: text/turtle" \
  --data-binary "@$DATA_FILE" \
  "$FUSEKI_URL/$FUSEKI_DATASET_NAME/data?default"

echo
echo "Loaded financial-risk toy data into Fuseki dataset '$FUSEKI_DATASET_NAME'."
