#!/usr/bin/env bash
# New development scope only; no default spec, author receipt, resume or retry.
set -euo pipefail

fail() { printf '%s\n' "$1" >&2; exit 2; }
GUARDED_PHASE=prelaunch
if [[ $# -eq 1 && "$1" == --after-model ]]; then
  GUARDED_PHASE=postlaunch
elif [[ $# -ne 0 ]]; then
  fail "Unsupported guarded handoff arguments."
fi
for GUARDED_NAME in XGAP_REPO_ROOT XGAP_PYTHON XGAP_GRAILQA_GUARDED_SPEC \
  XGAP_GRAILQA_GUARDED_SPEC_SHA256 XGAP_GRAILQA_GUARDED_RUNNER_COMMIT VLLM_ENV
do
  [[ -n "${!GUARDED_NAME:-}" ]] || fail "Required input is missing: $GUARDED_NAME"
done
[[ "${SLURM_JOB_ID:-}" =~ ^[0-9]+$ ]] || fail "A Slurm allocation is required."
[[ "$XGAP_GRAILQA_GUARDED_SPEC_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "A canonical spec freeze hash is required."
[[ "$XGAP_GRAILQA_GUARDED_RUNNER_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "An exact runner commit is required."

GUARDED_ENTRY_DIRECTORY="$(pwd -P)"
anchor() {
  case "$1" in /*) printf '%s\n' "$1";; *) printf '%s/%s\n' "$GUARDED_ENTRY_DIRECTORY" "$1";; esac
}
export XGAP_REPO_ROOT="$(anchor "$XGAP_REPO_ROOT")"
export XGAP_PYTHON="$(anchor "$XGAP_PYTHON")"
export XGAP_GRAILQA_GUARDED_SPEC="$(anchor "$XGAP_GRAILQA_GUARDED_SPEC")"
export VLLM_ENV="$(anchor "$VLLM_ENV")"
export XGAP_CWRU_RUN_ROOT="$(anchor "${XGAP_CWRU_RUN_ROOT:-$XGAP_REPO_ROOT/runs/cwru-grailqa-guarded-$SLURM_JOB_ID}")"
[[ -f "$XGAP_PYTHON" && -x "$XGAP_PYTHON" ]] || fail "Explicit control Python is unavailable."
[[ -x "$VLLM_ENV/bin/python" && -x "$VLLM_ENV/bin/vllm" && -f "$VLLM_ENV/bin/activate" ]] || fail "Explicit frozen serving environment is unavailable."
[[ -f "$XGAP_GRAILQA_GUARDED_SPEC" && ! -L "$XGAP_GRAILQA_GUARDED_SPEC" ]] || fail "Explicit spec is missing or symlinked."
[[ -d "$XGAP_REPO_ROOT/src/xgap" ]] || fail "Explicit XGAP checkout is unavailable."

# Disallow Git overrides that could make the checks inspect another checkout.
while IFS= read -r GUARDED_NAME; do unset "$GUARDED_NAME"; done < <(compgen -v GIT_)
cd -- "$XGAP_REPO_ROOT"
[[ "$(git rev-parse HEAD)" == "$XGAP_GRAILQA_GUARDED_RUNNER_COMMIT" ]] || fail "Runner commit mismatch."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "Experiment checkout is dirty."

GUARDED_LOCAL_ROOT="${XGAP_GRAILQA_LOCAL_PREFLIGHT_ROOT:-$HOME/xgap-data/freebase/grailqa-local-catalog-v1/preflight18}"
# Existing loaders own the resolution of explicitly supplied catalog overrides.
export XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE="${XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE-query_local_e3b4}"
export XGAP_GRAILQA_CATALOG_V2="${XGAP_GRAILQA_CATALOG_V2-$GUARDED_LOCAL_ROOT}"
export XGAP_GRAILQA_REACHABILITY_V2="${XGAP_GRAILQA_REACHABILITY_V2-$GUARDED_LOCAL_ROOT}"
export XGAP_GRAILQA_REACHABILITY_SUMMARY="${XGAP_GRAILQA_REACHABILITY_SUMMARY-$GUARDED_LOCAL_ROOT/audit_summary.json}"
export XGAP_GRAILQA_REACHABILITY_ROWS="${XGAP_GRAILQA_REACHABILITY_ROWS-$GUARDED_LOCAL_ROOT/reachability.jsonl}"
export PYTHONPATH="$XGAP_REPO_ROOT/src"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
export XGAP_SKIP_VLLM_STRUCTURED_SMOKE=1 XGAP_ALLOW_DIRTY=0 XGAP_ALLOW_NON_SLURM_VLLM=0
# Log/PID overrides cannot redirect this job into prior evidence.
export XGAP_VLLM_LOG="$XGAP_CWRU_RUN_ROOT/vllm.log"
export XGAP_VLLM_PID_FILE="$XGAP_CWRU_RUN_ROOT/vllm.pid"

# Use only offline control imports here. The supplied spec is validated, never
# selected implicitly. Reachability stays gate metadata, not model input.
GUARDED_SETTINGS="$("$XGAP_PYTHON" - "$GUARDED_PHASE" <<'PY'
import json
import os
from pathlib import Path
import sys

from xgap.experiments.cwru_vllm import CWRUVLLMContract, verify_preflight_token_budget
from xgap.experiments.grailqa_preflight import GrailQAPreflightSpec, preflight_readiness

def require(value, message):
    if not value:
        raise ValueError(message)

phase = sys.argv[1]
repo = Path(os.environ["XGAP_REPO_ROOT"])
root = Path(os.environ["XGAP_CWRU_RUN_ROOT"])
require(not any(p.is_symlink() for p in (root, *root.parents)), "Run output has a symlinked ancestor.")
require(root == root.resolve() and repo == repo.resolve(), "Repository/output paths must be canonical.")
require(root.parent == repo / "runs" and root.name.startswith("cwru-grailqa-guarded-")
        and len(root.name) > len("cwru-grailqa-guarded-"), "Use a new direct guarded child of repository runs.")

def repository_input(raw):
    path = repo / raw
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Frozen input has a symlinked ancestor.")
    resolved = path.resolve(strict=True)
    require(resolved != repo and resolved.is_relative_to(repo) and resolved.is_file(),
            "Frozen spec and contract must be regular repository-contained files.")
    return resolved

# The unchanged environment collector records these paths relative to repo.
# Reject unsupported external/aliased inputs before model startup, not during
# its later environment capture or the guarded runner identity binding.
spec_path = repository_input(os.environ["XGAP_GRAILQA_GUARDED_SPEC"])
spec = GrailQAPreflightSpec.load(spec_path)
require(spec.path == spec_path, "Loaded spec source mismatch.")
require(spec.data["freeze_hash"] == os.environ["XGAP_GRAILQA_GUARDED_SPEC_SHA256"], "Spec acknowledgement mismatch.")
require(len(spec.question_ids) == 18, "Only the explicitly frozen 18-query development scope is supported.")
require(all(spec.data.get(k) is False for k in (
    "backend_execution", "gold_exposed_to_inference", "full_150_run_permitted",
)), "Development scope mismatch.")
contract_path = repository_input(spec.data["deployment_contract"])
contract = CWRUVLLMContract.load(contract_path)
require(contract.path == contract_path, "Loaded contract source mismatch.")
verify_preflight_token_budget(repo_root=repo, spec_path=spec.path, contract_path=contract.path)
shared = contract.data["shared_paths"]
require(Path(os.environ["VLLM_ENV"]) == Path(shared["vllm_env"]), "Serving interpreter contract mismatch.")
hf_home = os.environ.get("HF_HOME", str(shared["hf_home"]))
require(Path(hf_home) == Path(shared["hf_home"]), "Serving cache contract mismatch.")
require(not os.environ.get("XGAP_CWRU_CONTRACT") or Path(os.environ["XGAP_CWRU_CONTRACT"]) == contract.path,
        "Deployment contract override mismatch.")
require(os.environ.get("XGAP_LLM_MODEL", contract.model) == contract.model, "Served model override mismatch.")
require(os.environ.get("XGAP_LLM_BASE_URL", "http://127.0.0.1:8000/v1") == "http://127.0.0.1:8000/v1",
        "Only the frozen job-local endpoint is supported.")
for value in (str(contract.path), hf_home, contract.model):
    require("\n" not in value and "\r" not in value, "Unsupported handoff path.")
binding = {
    "schema_version": "grailqa-guarded-launch-binding-v1",
    "runner_commit": os.environ["XGAP_GRAILQA_GUARDED_RUNNER_COMMIT"],
    "spec_freeze_hash": spec.data["freeze_hash"], "slurm_job_id": os.environ["SLURM_JOB_ID"],
    "question_count": 18, "serving_python": str(Path(shared["vllm_env"]) / "bin/python"),
    "contract_hash": contract.contract_hash, "paper_result": False,
    "automatic_retries": 0, "author_receipt_created": False,
}
if phase == "prelaunch":
    require(not root.exists(), "Run output already exists; no automatic resume.")
    readiness = preflight_readiness(spec, repo, require_credentials=False)
    require(readiness.get("ready") is True, "Offline readiness failed; no model startup.")
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(exist_ok=False)
    for name, value in (("preflight_readiness.json", readiness), ("guarded_launch_binding.json", binding)):
        with (root / name).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
else:
    require(root.is_dir(), "Job-owned run root is missing.")
    path = root / "guarded_launch_binding.json"
    require(path.is_file() and not path.is_symlink(), "Prelaunch binding is missing or unsafe.")
    require(json.loads(path.read_text()) == binding, "Prelaunch binding changed.")
for value in (str(contract.path), hf_home, contract.model):
    print(value)
PY
)"
GUARDED_VALUES=()
while IFS= read -r GUARDED_VALUE; do GUARDED_VALUES+=("$GUARDED_VALUE"); done <<< "$GUARDED_SETTINGS"
[[ ${#GUARDED_VALUES[@]} -eq 3 ]] || fail "Invalid offline handoff settings."
export XGAP_CWRU_CONTRACT="${GUARDED_VALUES[0]}" HF_HOME="${GUARDED_VALUES[1]}" XGAP_LLM_MODEL="${GUARDED_VALUES[2]}"
export XGAP_LLM_BASE_URL="${XGAP_LLM_BASE_URL:-http://127.0.0.1:8000/v1}"
export XGAP_LLM_API_KEY="${XGAP_LLM_API_KEY:-local}"

# Check again after offline validation and again when this helper is re-entered
# after model startup. The guarded Python runner also binds current HEAD.
[[ "$(git rev-parse HEAD)" == "$XGAP_GRAILQA_GUARDED_RUNNER_COMMIT" ]] || fail "Runner changed during handoff."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "Checkout changed during handoff."
if [[ "$GUARDED_PHASE" == prelaunch ]]; then
  exec bash "$XGAP_REPO_ROOT/scripts/slurm/cwru_xgap_vllm.sbatch" \
    "$XGAP_GRAILQA_GUARDED_SPEC" \
    bash "$XGAP_REPO_ROOT/scripts/server/run_grailqa_guarded_preflight.sh" --after-model
fi

[[ "${XGAP_RUN_ENVIRONMENT_FILE:-}" == "$XGAP_CWRU_RUN_ROOT/cwru_environment.json" ]] || fail "Captured run environment must belong to this job."
[[ -f "$XGAP_RUN_ENVIRONMENT_FILE" && ! -L "$XGAP_RUN_ENVIRONMENT_FILE" ]] || fail "Captured run environment is missing or unsafe."
[[ "${XGAP_RESOLVED_MODEL_REVISION:-}" =~ ^[0-9a-f]{40}$ ]] || fail "An exact launcher-resolved model revision is required."
GUARDED_SNAPSHOT="$HF_HOME/hub/models--${XGAP_LLM_MODEL//\//--}/snapshots/$XGAP_RESOLVED_MODEL_REVISION"
[[ -d "$GUARDED_SNAPSHOT" && ! -L "$GUARDED_SNAPSHOT" ]] || fail "Launcher-resolved local tokenizer snapshot is unavailable."
GUARDED_RESULT="$XGAP_CWRU_RUN_ROOT/results/grailqa-guarded-preflight"
[[ ! -e "$GUARDED_RESULT" && ! -L "$GUARDED_RESULT" && ! -L "$XGAP_CWRU_RUN_ROOT/results" ]] || fail "Guarded results already exist or are unsafe."

# Inference/tokenization uses the exact serving interpreter, never PATH python.
exec "$VLLM_ENV/bin/python" -m xgap.experiments.grailqa_guarded_preflight \
  --spec "$XGAP_GRAILQA_GUARDED_SPEC" --repo-root "$XGAP_REPO_ROOT" \
  --output-root "$GUARDED_RESULT" --run-environment-path "$XGAP_RUN_ENVIRONMENT_FILE" \
  --tokenizer-snapshot "$GUARDED_SNAPSHOT" --tokenizer-revision "$XGAP_RESOLVED_MODEL_REVISION" \
  --expected-runner-commit "$XGAP_GRAILQA_GUARDED_RUNNER_COMMIT" \
  --execute-development-spec-sha256 "$XGAP_GRAILQA_GUARDED_SPEC_SHA256" \
  --verify-server-tokenization
