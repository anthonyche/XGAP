#!/usr/bin/env bash
#SBATCH --job-name=xgap-fb-local-catalog
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=1-00:00:00
#SBATCH --output=slurm-freebase-local-catalog-%j.out

set -euo pipefail

module load Miniconda3

REPO_ROOT="${XGAP_REPO_ROOT:-$HOME/XGAP}"
export XGAP_LOCAL_CATALOG_WORKLOAD="${XGAP_LOCAL_CATALOG_WORKLOAD:-preflight18}"
export XGAP_FREEBASE_RAW_DIR="${XGAP_FREEBASE_RAW_DIR:-$HOME/xgap-data/freebase/raw}"
export XGAP_FREEBASE_PARQUET_ROOT="${XGAP_FREEBASE_PARQUET_ROOT:-$XGAP_FREEBASE_RAW_DIR/hf-archival-parquet}"
export XGAP_FREEBASE_SOURCE_MANIFEST="${XGAP_FREEBASE_SOURCE_MANIFEST:-$XGAP_FREEBASE_RAW_DIR/source_manifest.json}"
export XGAP_GRAILQA_LOCAL_CATALOG_ROOT="${XGAP_GRAILQA_LOCAL_CATALOG_ROOT:-$HOME/xgap-data/freebase/grailqa-local-catalog-v1}"
export XGAP_LOCAL_CATALOG_STAGING_ROOT="${XGAP_LOCAL_CATALOG_STAGING_ROOT:-${TMPDIR:-/tmp}}"

cd "$REPO_ROOT"
echo "git_commit=$(git rev-parse HEAD)"
echo "python=$(command -v python)"
python --version
echo "hostname=$(hostname)"
echo "cpus=${SLURM_CPUS_PER_TASK:-unknown}"
echo "workload=$XGAP_LOCAL_CATALOG_WORKLOAD"
echo "source_root=$XGAP_FREEBASE_PARQUET_ROOT"
echo "local_catalog_root=$XGAP_GRAILQA_LOCAL_CATALOG_ROOT"
echo "node_local_staging=$XGAP_LOCAL_CATALOG_STAGING_ROOT"
echo "repo_id=CleverThis/freebase"
echo "revision=dbb1931c2698295653effe9b980a02ab29f004e0"
echo "No GPU or Qwen process is used by this job."

if ! PYTHON=python bash scripts/server/fetch_grailqa_m13d_artifacts.sh \
  --verify-only; then
  echo "Frozen GrailQA runtime artifacts are unavailable." >&2
  echo "Upload both frozen datasets directories or first submit:" >&2
  echo "  sbatch --export=ALL,XGAP_REPO_ROOT=$REPO_ROOT scripts/slurm/prepare_grailqa_m13d_artifacts.sbatch" >&2
  echo "The 32 GB Freebase scan was not started." >&2
  exit 2
fi

SCRIPT_ARGS=()
if [[ "${XGAP_LOCAL_CATALOG_AUDIT_ONLY:-0}" == "1" ]]; then
  SCRIPT_ARGS=(--audit-only)
  echo "audit_only=true"
fi
bash scripts/server/build_grailqa_local_catalog.sh "${SCRIPT_ARGS[@]}"

OUTPUT="$XGAP_GRAILQA_LOCAL_CATALOG_ROOT/$XGAP_LOCAL_CATALOG_WORKLOAD"
python - "$OUTPUT/audit_summary.json" <<'PY'
import json
import sys
from pathlib import Path

summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps({
    "live_preflight_allowed": summary["live_preflight_allowed"],
    "gate": summary["gate"],
}, indent=2, sort_keys=True))
PY

echo "M13-E3B local catalog build and offline reachability audit completed."
