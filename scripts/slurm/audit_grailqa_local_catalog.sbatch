#!/usr/bin/env bash
#SBATCH --job-name=xgap-grailqa-catalog-audit
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=slurm-grailqa-local-catalog-audit-%j.out

set -euo pipefail

module load Miniconda3

REPO_ROOT="${XGAP_REPO_ROOT:-$HOME/XGAP}"
PYTHON_BIN="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"
DEFAULT_CATALOG_ROOT="$HOME/xgap-data/freebase/grailqa-local-catalog-v1/pilot150"
DEFAULT_SOURCE_MANIFEST="$HOME/xgap-data/freebase/raw/source_manifest.json"
CATALOG_ROOT="${XGAP_GRAILQA_PILOT150_CATALOG:-$DEFAULT_CATALOG_ROOT}"
SOURCE_MANIFEST="${XGAP_FREEBASE_SOURCE_MANIFEST:-$DEFAULT_SOURCE_MANIFEST}"
BUILDER_COMMIT="${XGAP_GRAILQA_CATALOG_BUILDER_COMMIT:-}"
DEFAULT_OUTPUT="$REPO_ROOT/runs/audits/grailqa-local-catalog-pilot150-${SLURM_JOB_ID}.json"
OUTPUT="${XGAP_GRAILQA_CATALOG_AUDIT_OUTPUT:-$DEFAULT_OUTPUT}"

if [[ ! "$BUILDER_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "XGAP_GRAILQA_CATALOG_BUILDER_COMMIT must be exact 40-hex." >&2
  exit 2
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "XGAP Python environment is unavailable: $PYTHON_BIN" >&2
  exit 2
fi

cd "$REPO_ROOT"
mkdir -p "$(dirname "$OUTPUT")"

PYTHONPATH="$REPO_ROOT/src" "$PYTHON_BIN" \
  -m xgap.experiments.grailqa_local_catalog_evidence \
  --catalog-root "$CATALOG_ROOT" \
  --repo-root "$REPO_ROOT" \
  --source-manifest "$SOURCE_MANIFEST" \
  --expected-builder-commit "$BUILDER_COMMIT" \
  --output "$OUTPUT"

echo "auditor_commit=$(git rev-parse HEAD)"
echo "builder_commit=$BUILDER_COMMIT"
echo "catalog_root=$CATALOG_ROOT"
echo "audit_output=$OUTPUT"
