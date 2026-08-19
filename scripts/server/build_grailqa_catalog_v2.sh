#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_MODE="${XGAP_FREEBASE_SOURCE_MODE:-hf_archival_parquet}"

# Compatibility wrapper retained for the M13-E1 command. New M13-E3 workflows
# keep download, verification, construction, and audit independently restartable.
if [[ "${1:-}" == "--download" ]]; then
  case "$SOURCE_MODE" in
    google_rdf_gzip)
      bash "$SCRIPT_DIR/download_freebase_rdf.sh"
      ;;
    hf_archival_parquet)
      bash "$SCRIPT_DIR/download_freebase_archival_parquet.sh"
      ;;
    *)
      echo "Unsupported XGAP_FREEBASE_SOURCE_MODE: $SOURCE_MODE" >&2
      exit 2
      ;;
  esac
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--download]" >&2
  exit 2
fi

bash "$SCRIPT_DIR/build_freebase_catalog_v2.sh"
bash "$SCRIPT_DIR/audit_grailqa_reachability_v2.sh"
