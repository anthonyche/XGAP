#!/usr/bin/env bash
#SBATCH --job-name=xgap-grailqa-preflight-audit
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=slurm-grailqa-preflight-audit-%j.out

set -euo pipefail

module load Miniconda3

REPO_ROOT="${XGAP_REPO_ROOT:-$HOME/XGAP}"
PYTHON_BIN="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"
PRODUCER_COMMIT="${XGAP_GRAILQA_PREFLIGHT_PRODUCER_COMMIT:-}"
PREFLIGHT_JOB_ID="${XGAP_GRAILQA_PREFLIGHT_JOB_ID:-}"
DEFAULT_RUN_ROOT="$REPO_ROOT/runs/cwru-grailqa-preflight-v2-$PREFLIGHT_JOB_ID"
RUN_ROOT="${XGAP_GRAILQA_PREFLIGHT_RUN_ROOT:-$DEFAULT_RUN_ROOT}"
DEFAULT_OUTPUT="$REPO_ROOT/runs/audits/grailqa-semantic-preflight-v2-$PREFLIGHT_JOB_ID.json"
OUTPUT="${XGAP_GRAILQA_PREFLIGHT_AUDIT_OUTPUT:-$DEFAULT_OUTPUT}"

if [[ ! "$PRODUCER_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "XGAP_GRAILQA_PREFLIGHT_PRODUCER_COMMIT must be exact 40-hex." >&2
  exit 2
fi
if [[ ! "$PREFLIGHT_JOB_ID" =~ ^[0-9]+$ ]]; then
  echo "XGAP_GRAILQA_PREFLIGHT_JOB_ID must be a Slurm job ID." >&2
  exit 2
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "XGAP Python environment is unavailable: $PYTHON_BIN" >&2
  exit 2
fi
if [[ -L "$RUN_ROOT" || ! -d "$RUN_ROOT" ]]; then
  echo "Preflight result root is missing or unsafe: $RUN_ROOT" >&2
  exit 2
fi
if [[ -e "$OUTPUT" || -L "$OUTPUT" ]]; then
  echo "Preflight audit output already exists: $OUTPUT" >&2
  exit 2
fi

cd "$REPO_ROOT"
mkdir -p "$(dirname "$OUTPUT")"

PYTHONPATH="$REPO_ROOT/src" "$PYTHON_BIN" \
  -m xgap.experiments.grailqa_preflight_evidence \
  --run-root "$RUN_ROOT" \
  --repo-root "$REPO_ROOT" \
  --expected-commit "$PRODUCER_COMMIT" \
  --output "$OUTPUT"

echo "auditor_commit=$(git rev-parse HEAD)"
echo "producer_commit=$PRODUCER_COMMIT"
echo "preflight_job_id=$PREFLIGHT_JOB_ID"
echo "preflight_run_root=$RUN_ROOT"
echo "audit_output=$OUTPUT"
