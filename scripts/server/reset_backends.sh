#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"

if [ "${1:-}" != "--yes" ]; then
  echo "This will stop containers and delete persistent Neo4j/Fuseki volumes."
  read -r -p "Type RESET to continue: " answer
  if [ "$answer" != "RESET" ]; then
    echo "Reset cancelled."
    exit 0
  fi
fi

compose down -v --remove-orphans
echo "Removed XGAP backend containers and persistent volumes."
