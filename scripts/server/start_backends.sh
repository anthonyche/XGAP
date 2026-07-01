#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH="$SCRIPT_DIR/common.sh"
# shellcheck source=scripts/server/common.sh
. "$COMMON_SH"

compose up -d

echo "Neo4j and Fuseki containers are starting."
echo "Run: bash scripts/server/healthcheck_backends.sh"
