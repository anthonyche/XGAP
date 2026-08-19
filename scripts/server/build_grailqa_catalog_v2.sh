#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Compatibility wrapper retained for the M13-E1 command. New M13-E3 workflows
# keep download, verification, construction, and audit independently restartable.
if [[ "${1:-}" == "--download" ]]; then
  bash "$SCRIPT_DIR/download_freebase_rdf.sh"
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--download]" >&2
  exit 2
fi

bash "$SCRIPT_DIR/build_freebase_catalog_v2.sh"
bash "$SCRIPT_DIR/audit_grailqa_reachability_v2.sh"
