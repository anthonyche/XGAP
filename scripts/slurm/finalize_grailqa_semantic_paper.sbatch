#!/usr/bin/env bash
#SBATCH --job-name=xgap-grailqa-paper-finalize
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=slurm-grailqa-paper-finalize-%j.out

set -euo pipefail

module load Miniconda3

REPO_ROOT="${XGAP_REPO_ROOT:-$HOME/XGAP}"
PYTHON_BIN="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"
PAPER_JOB_ID="${XGAP_GRAILQA_SEMANTIC_PAPER_JOB_ID:-}"
RUNNER_COMMIT="${XGAP_GRAILQA_SEMANTIC_RUNNER_COMMIT:-}"
REQUEST="${XGAP_GRAILQA_SEMANTIC_EXECUTION_REQUEST:-}"
AUTHORITY="${XGAP_GRAILQA_SEMANTIC_EXECUTION_AUTHORITY:-}"
AUTHOR_SELECTION="${XGAP_GRAILQA_SEMANTIC_AUTHOR_SELECTION:-}"
PROTOCOL="${XGAP_GRAILQA_SEMANTIC_PROTOCOL:-$REPO_ROOT/experiments/configs/grailqa_semantic_paper_protocol_draft_v1.json}"

if [[ ! "$PAPER_JOB_ID" =~ ^[0-9]+$ ]]; then
  echo "XGAP_GRAILQA_SEMANTIC_PAPER_JOB_ID must be a Slurm job ID." >&2
  exit 2
fi
if [[ ! "$RUNNER_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "XGAP_GRAILQA_SEMANTIC_RUNNER_COMMIT must be exact 40-hex." >&2
  exit 2
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Core Python is unavailable: $PYTHON_BIN" >&2
  exit 2
fi
for path in "$REQUEST" "$AUTHORITY" "$AUTHOR_SELECTION" "$PROTOCOL"; do
  if [[ -L "$path" || ! -f "$path" ]]; then
    echo "Required control artifact is missing or unsafe: $path" >&2
    exit 2
  fi
done
if [[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" != "$RUNNER_COMMIT" ]]; then
  echo "Finalizer checkout differs from the authority-bound runner commit." >&2
  exit 2
fi
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]]; then
  echo "Refusing a dirty semantic-paper finalizer checkout." >&2
  exit 2
fi

RUN_ID="$("$PYTHON_BIN" - "$REQUEST" <<'PY'
import json
import sys

print(json.load(open(sys.argv[1]))["run_id"])
PY
)"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$ ]]; then
  echo "Authority-bound run_id is unsafe: $RUN_ID" >&2
  exit 2
fi

OUTER_RUN_ROOT="${XGAP_CWRU_RUN_ROOT:-$REPO_ROOT/runs/cwru-grailqa-semantic-paper-$PAPER_JOB_ID}"
SOURCE_RUN_ROOT="${XGAP_GRAILQA_SEMANTIC_SOURCE_RUN_ROOT:-$OUTER_RUN_ROOT/results/$RUN_ID}"
FINAL_ROOT="${XGAP_GRAILQA_SEMANTIC_FINAL_ROOT:-$REPO_ROOT/runs/grailqa-semantic-paper-finalizations/$RUN_ID-$PAPER_JOB_ID}"
RUN_AUDIT="$FINAL_ROOT/run_audit.json"
ANALYSIS="$FINAL_ROOT/analysis.json"
ANALYSIS_AUDIT="$FINAL_ROOT/analysis_audit.json"
PAPER_RESULT="$FINAL_ROOT/paper_result.json"
OUTCOMES="$SOURCE_RUN_ROOT/evaluation/query_outcomes.jsonl"

if [[ -L "$SOURCE_RUN_ROOT" || ! -d "$SOURCE_RUN_ROOT" ]]; then
  echo "Semantic source run is missing or unsafe: $SOURCE_RUN_ROOT" >&2
  exit 2
fi
if [[ -e "$FINAL_ROOT" || -L "$FINAL_ROOT" ]]; then
  echo "Semantic finalization root already exists: $FINAL_ROOT" >&2
  exit 2
fi

# A source-root override must still identify the submitted request and authority.
"$PYTHON_BIN" - "$REQUEST" "$AUTHORITY" "$SOURCE_RUN_ROOT/run_manifest.json" <<'PY'
import json
import sys

request, authority, manifest = [json.load(open(path)) for path in sys.argv[1:]]
for field in (
    "run_id", "runner_commit", "protocol_sha256", "author_selection_sha256",
    "preexecution_admission_sha256", "execution_request_sha256",
):
    if manifest[field] != request[field]:
        raise ValueError(f"Source run differs from submitted request: {field}")
if manifest["execution_authority_sha256"] != authority["execution_authority_sha256"]:
    raise ValueError("Source run differs from submitted execution authority")
PY

mkdir -p "$FINAL_ROOT"

cd "$REPO_ROOT"

PYTHONPATH="$REPO_ROOT/src" "$PYTHON_BIN" \
  -m xgap.experiments.grailqa_semantic_paper_run_evidence \
  --run-root "$SOURCE_RUN_ROOT" \
  --expected-commit "$RUNNER_COMMIT" \
  --output "$RUN_AUDIT"

SOURCE_RUN_SHA256="$("$PYTHON_BIN" - "$SOURCE_RUN_ROOT/run_manifest.json" <<'PY'
import json
import sys

print(json.load(open(sys.argv[1]))["source_run_sha256"])
PY
)"

PYTHONPATH="$REPO_ROOT/src" "$PYTHON_BIN" \
  -m xgap.experiments.grailqa_semantic_analysis \
  --outcomes "$OUTCOMES" \
  --protocol "$PROTOCOL" \
  --author-selection "$AUTHOR_SELECTION" \
  --repo-root "$REPO_ROOT" \
  --source-run-sha256 "$SOURCE_RUN_SHA256" \
  --output "$ANALYSIS"

PYTHONPATH="$REPO_ROOT/src" "$PYTHON_BIN" \
  -m xgap.experiments.grailqa_semantic_analysis_evidence \
  --outcomes "$OUTCOMES" \
  --analysis "$ANALYSIS" \
  --protocol "$PROTOCOL" \
  --author-selection "$AUTHOR_SELECTION" \
  --repo-root "$REPO_ROOT" \
  --source-run-sha256 "$SOURCE_RUN_SHA256" \
  --output "$ANALYSIS_AUDIT"

PYTHONPATH="$REPO_ROOT/src" "$PYTHON_BIN" \
  -m xgap.experiments.grailqa_semantic_paper_result admit \
  --run-root "$SOURCE_RUN_ROOT" \
  --run-audit "$RUN_AUDIT" \
  --analysis "$ANALYSIS" \
  --analysis-audit "$ANALYSIS_AUDIT" \
  --protocol "$PROTOCOL" \
  --author-selection "$AUTHOR_SELECTION" \
  --repo-root "$REPO_ROOT" \
  --expected-commit "$RUNNER_COMMIT" \
  --output "$PAPER_RESULT"

echo "paper_job_id=$PAPER_JOB_ID"
echo "source_run_root=$SOURCE_RUN_ROOT"
echo "finalization_root=$FINAL_ROOT"
echo "paper_result=$PAPER_RESULT"
