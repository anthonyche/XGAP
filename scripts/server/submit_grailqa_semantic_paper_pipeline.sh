#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-$(git rev-parse --show-toplevel)}"
PYTHON_BIN="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"
AUTHOR_SELECTION="${XGAP_GRAILQA_SEMANTIC_AUTHOR_SELECTION:-}"
ADMISSION="${XGAP_GRAILQA_SEMANTIC_PREEXECUTION_ADMISSION:-}"
REQUEST="${XGAP_GRAILQA_SEMANTIC_EXECUTION_REQUEST:-}"
AUTHORITY="${XGAP_GRAILQA_SEMANTIC_EXECUTION_AUTHORITY:-}"
PROTOCOL="${XGAP_GRAILQA_SEMANTIC_PROTOCOL:-$REPO_ROOT/experiments/configs/grailqa_semantic_paper_protocol_draft_v1.json}"
CATALOG_ROOT="${XGAP_GRAILQA_PILOT150_CATALOG:-$HOME/xgap-data/freebase/grailqa-local-catalog-v1/pilot150}"
REACHABILITY_SUMMARY="${XGAP_GRAILQA_PILOT150_REACHABILITY_SUMMARY:-$CATALOG_ROOT/audit_summary.json}"
REACHABILITY_ROWS="${XGAP_GRAILQA_PILOT150_REACHABILITY_ROWS:-$CATALOG_ROOT/reachability.jsonl}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Core Python is unavailable: $PYTHON_BIN" >&2
  exit 2
fi
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]]; then
  echo "Refusing a dirty GrailQA semantic-paper checkout." >&2
  exit 2
fi
for path in \
  "$AUTHOR_SELECTION" \
  "$ADMISSION" \
  "$REQUEST" \
  "$AUTHORITY" \
  "$PROTOCOL" \
  "$REACHABILITY_SUMMARY" \
  "$REACHABILITY_ROWS"
do
  if [[ -L "$path" || ! -f "$path" ]]; then
    echo "Required authority-chain artifact is missing or unsafe: $path" >&2
    exit 2
  fi
done
if [[ -L "$CATALOG_ROOT" || ! -d "$CATALOG_ROOT" ]]; then
  echo "Pilot150 catalog is missing or unsafe: $CATALOG_ROOT" >&2
  exit 2
fi

IFS=$'\t' read -r \
  RUN_ID RUNNER_COMMIT REQUEST_SHA256 ADMISSION_SHA256 AUTHORITY_SHA256 < <(
  "$PYTHON_BIN" - "$REQUEST" "$ADMISSION" "$AUTHORITY" <<'PY'
import json
import sys

request = json.load(open(sys.argv[1]))
admission = json.load(open(sys.argv[2]))
authority = json.load(open(sys.argv[3]))

assert request["preexecution_admission_sha256"] == admission[
    "preexecution_admission_sha256"
]
assert authority["execution_request_sha256"] == request[
    "execution_request_sha256"
]
assert authority["preexecution_admission_sha256"] == admission[
    "preexecution_admission_sha256"
]
assert authority["decision"] == "authorize_exact_150_query_semantic_execution"
assert authority["full_150_execution_authorized"] is True
print(
    request["run_id"],
    request["runner_commit"],
    request["execution_request_sha256"],
    admission["preexecution_admission_sha256"],
    authority["execution_authority_sha256"],
    sep="\t",
)
PY
)

if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$ ]]; then
  echo "Authority-bound run_id is unsafe: $RUN_ID" >&2
  exit 2
fi
if [[ ! "$RUNNER_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Authority-bound runner commit is invalid." >&2
  exit 2
fi
if [[ ! "$REQUEST_SHA256" =~ ^[0-9a-f]{64}$ \
  || ! "$ADMISSION_SHA256" =~ ^[0-9a-f]{64}$ \
  || ! "$AUTHORITY_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "Authority-chain identity is invalid." >&2
  exit 2
fi
if [[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" != "$RUNNER_COMMIT" ]]; then
  echo "Checkout differs from the authority-bound runner commit." >&2
  exit 2
fi

SUBMISSION_ROOT="$REPO_ROOT/runs/grailqa-semantic-paper-submissions"
SUBMISSION_RECORD="$SUBMISSION_ROOT/$RUN_ID.json"
READINESS_RECORD="$SUBMISSION_ROOT/$RUN_ID-readiness.json"
SUBMISSION_LEASE="$SUBMISSION_ROOT/$RUN_ID.submission-lease"
if [[ -e "$SUBMISSION_RECORD" || -L "$SUBMISSION_RECORD" ]]; then
  echo "Submission record already exists: $SUBMISSION_RECORD" >&2
  exit 2
fi
mkdir -p "$SUBMISSION_ROOT"
if ! mkdir "$SUBMISSION_LEASE"; then
  echo "Submission lease already exists: $SUBMISSION_LEASE" >&2
  exit 2
fi
if [[ -e "$READINESS_RECORD" || -L "$READINESS_RECORD" ]]; then
  echo "Submission readiness record already exists: $READINESS_RECORD" >&2
  exit 2
fi

export XGAP_REPO_ROOT="$REPO_ROOT"
export XGAP_PYTHON="$PYTHON_BIN"
export XGAP_GRAILQA_SEMANTIC_AUTHOR_SELECTION="$AUTHOR_SELECTION"
export XGAP_GRAILQA_SEMANTIC_PREEXECUTION_ADMISSION="$ADMISSION"
export XGAP_GRAILQA_SEMANTIC_EXECUTION_REQUEST="$REQUEST"
export XGAP_GRAILQA_SEMANTIC_EXECUTION_AUTHORITY="$AUTHORITY"
export XGAP_GRAILQA_SEMANTIC_PROTOCOL="$PROTOCOL"
export XGAP_GRAILQA_SEMANTIC_RUNNER_COMMIT="$RUNNER_COMMIT"

PYTHONPATH="$REPO_ROOT/src" "$PYTHON_BIN" \
  -m xgap.experiments.grailqa_semantic_paper_run check \
  --request "$REQUEST" \
  --admission "$ADMISSION" \
  --authority "$AUTHORITY" \
  --protocol "$PROTOCOL" \
  --author-selection "$AUTHOR_SELECTION" \
  --repo-root "$REPO_ROOT" \
  --catalog-root "$CATALOG_ROOT" \
  --reachability-summary "$REACHABILITY_SUMMARY" \
  --reachability-rows "$REACHABILITY_ROWS" \
  > "$READINESS_RECORD"

PAPER_JOB_ID="$({ sbatch --parsable --export=ALL \
  "$REPO_ROOT/scripts/slurm/run_grailqa_semantic_paper.sbatch"; } | tr -d '[:space:]')"

if [[ ! "$PAPER_JOB_ID" =~ ^[0-9]+$ ]]; then
  echo "Slurm returned an invalid paper job identifier." >&2
  exit 2
fi

FINALIZE_JOB_ID="$({ sbatch --parsable \
  --dependency="afterok:$PAPER_JOB_ID" \
  --export="ALL,XGAP_GRAILQA_SEMANTIC_PAPER_JOB_ID=$PAPER_JOB_ID" \
  "$REPO_ROOT/scripts/slurm/finalize_grailqa_semantic_paper.sbatch"; } | tr -d '[:space:]')"

if [[ ! "$FINALIZE_JOB_ID" =~ ^[0-9]+$ ]]; then
  echo "Slurm returned an invalid finalizer job identifier." >&2
  exit 2
fi

"$PYTHON_BIN" - \
  "$SUBMISSION_RECORD" "$RUN_ID" "$RUNNER_COMMIT" "$REQUEST_SHA256" \
  "$ADMISSION_SHA256" "$AUTHORITY_SHA256" "$PAPER_JOB_ID" \
  "$FINALIZE_JOB_ID" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys

output = Path(sys.argv[1])
body = {
    "schema_version": "m13e4-grailqa-semantic-paper-submission-v1",
    "run_id": sys.argv[2],
    "runner_commit": sys.argv[3],
    "execution_request_sha256": sys.argv[4],
    "preexecution_admission_sha256": sys.argv[5],
    "execution_authority_sha256": sys.argv[6],
    "paper_job_id": sys.argv[7],
    "finalize_job_id": sys.argv[8],
    "dependency": f"afterok:{sys.argv[7]}",
    "automatic_retries": 0,
    "paper_result": False,
}
encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
record = {**body, "submission_sha256": hashlib.sha256(encoded).hexdigest()}
temporary = output.with_suffix(output.suffix + ".tmp")
temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
os.replace(temporary, output)
print(json.dumps(record, indent=2, sort_keys=True))
PY

echo "paper_job_id=$PAPER_JOB_ID"
echo "finalize_job_id=$FINALIZE_JOB_ID"
echo "submission_record=$SUBMISSION_RECORD"
