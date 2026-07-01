#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"

service="${1:-}"

case "$service" in
  "")
    compose logs --tail=200 neo4j fuseki
    ;;
  neo4j|fuseki)
    compose logs --tail=200 "$service"
    ;;
  *)
    echo "Usage: bash scripts/server/log_backends.sh [neo4j|fuseki]" >&2
    exit 1
    ;;
esac
