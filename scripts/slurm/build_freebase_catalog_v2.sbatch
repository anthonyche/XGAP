#!/usr/bin/env bash
#SBATCH --job-name=xgap-fb-catalog-v2
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=2-00:00:00
#SBATCH --output=slurm-freebase-catalog-v2-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-$HOME/XGAP}"
export XGAP_FREEBASE_RAW_DIR="${XGAP_FREEBASE_RAW_DIR:-$HOME/xgap-data/freebase/raw}"
export XGAP_FREEBASE_CATALOG_DIR="${XGAP_FREEBASE_CATALOG_DIR:-$HOME/xgap-data/freebase/catalog-v2}"
export XGAP_GRAILQA_REACHABILITY_V2="${XGAP_GRAILQA_REACHABILITY_V2:-$HOME/xgap-data/freebase/grailqa-reachability-v2}"

cd "$REPO_ROOT"
echo "git_commit=$(git rev-parse HEAD)"
echo "hostname=$(hostname)"
echo "cpus=${SLURM_CPUS_PER_TASK:-unknown}"
echo "raw_dir=$XGAP_FREEBASE_RAW_DIR"
echo "catalog_dir=$XGAP_FREEBASE_CATALOG_DIR"
echo "reachability_dir=$XGAP_GRAILQA_REACHABILITY_V2"

bash scripts/server/verify_freebase_rdf.sh
bash scripts/server/build_freebase_catalog_v2.sh

set +e
bash scripts/server/audit_grailqa_reachability_v2.sh
AUDIT_STATUS=$?
set -e
if [[ "$AUDIT_STATUS" -ne 0 && "$AUDIT_STATUS" -ne 2 ]]; then
  echo "Reachability audit failed before producing a valid GO/NO-GO result." >&2
  exit "$AUDIT_STATUS"
fi

python - "$XGAP_GRAILQA_REACHABILITY_V2/audit_summary.json" <<'PY'
import json
import sys
from pathlib import Path

summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps({
    "live_preflight_allowed": summary["live_preflight_allowed"],
    "gate": summary["gate"],
}, indent=2, sort_keys=True))
PY

echo "M13-E3 catalog construction and offline audit completed."
exit 0
