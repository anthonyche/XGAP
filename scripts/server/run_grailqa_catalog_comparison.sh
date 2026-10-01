#!/usr/bin/env bash
# CPU-only development comparison. No download, model, submission, or retry.
set -euo pipefail

fail() { printf '%s\n' "$1" >&2; exit 2; }
[[ $# -eq 0 ]] || fail "This entrypoint takes explicit environment inputs, not arguments."
for COMPARISON_NAME in XGAP_REPO_ROOT XGAP_PYTHON XGAP_GRAILQA_REPAIR_RUNNER_COMMIT; do
  [[ -n "${!COMPARISON_NAME:-}" ]] || fail "Required input is missing: $COMPARISON_NAME"
done
[[ "${SLURM_JOB_ID:-}" =~ ^[0-9]+$ ]] || fail "A Slurm allocation is required."
[[ "$XGAP_GRAILQA_REPAIR_RUNNER_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail "An exact runner commit is required."
[[ "$XGAP_REPO_ROOT" = /* && "$XGAP_PYTHON" = /* ]] || fail "Use absolute repository and Python paths."
[[ -x "$XGAP_PYTHON" ]] || fail "The supplied Python interpreter is unavailable."
while IFS= read -r COMPARISON_NAME; do unset "$COMPARISON_NAME"; done < <(compgen -v GIT_)
cd -- "$XGAP_REPO_ROOT"
[[ "$(git rev-parse HEAD)" == "$XGAP_GRAILQA_REPAIR_RUNNER_COMMIT" ]] || fail "Runner commit mismatch."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "Checkout is dirty."

export PYTHONPATH="$XGAP_REPO_ROOT/src"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export XGAP_GIT_COMMIT="$XGAP_GRAILQA_REPAIR_RUNNER_COMMIT"
export XGAP_FREEBASE_PARQUET_ROOT="${XGAP_FREEBASE_PARQUET_ROOT:-$HOME/xgap-data/freebase/raw/hf-archival-parquet}"
export XGAP_FREEBASE_SOURCE_MANIFEST="${XGAP_FREEBASE_SOURCE_MANIFEST:-$HOME/xgap-data/freebase/raw/source_manifest.json}"
export XGAP_GRAILQA_LEGACY_CATALOG="${XGAP_GRAILQA_LEGACY_CATALOG:-$HOME/xgap-data/freebase/grailqa-local-catalog-v1/preflight18}"
export XGAP_GRAILQA_COMPARISON_RUN="$XGAP_REPO_ROOT/runs/cwru-grailqa-catalog-comparison-$SLURM_JOB_ID"
export XGAP_LOCAL_CATALOG_STAGING_ROOT="${XGAP_LOCAL_CATALOG_STAGING_ROOT:-${TMPDIR:-/tmp}}"

# Verify small inputs and baseline before paying for the full frozen-source
# scan. Reference content is not opened: evaluation occurs after BOTH retrievals.
COMPARISON_IDS="$("$XGAP_PYTHON" - <<'PY'
import json
import os
from pathlib import Path

from xgap.experiments.grailqa_catalog import sha256_file
from xgap.experiments.grailqa_local_catalog import (
    LOCAL_CATALOG_SCHEMA_VERSION, load_inference_questions, validate_local_catalog,
)

repo = Path(os.environ["XGAP_REPO_ROOT"])
root = Path(os.environ["XGAP_GRAILQA_COMPARISON_RUN"])
baseline = Path(os.environ["XGAP_GRAILQA_LEGACY_CATALOG"])
source = Path(os.environ["XGAP_FREEBASE_SOURCE_MANIFEST"])
parquet = Path(os.environ["XGAP_FREEBASE_PARQUET_ROOT"])
scratch = Path(os.environ["XGAP_LOCAL_CATALOG_STAGING_ROOT"])
config = repo / "experiments/specs/grailqa_local_catalog_v1.json"
pilot = repo / "datasets/grailqa_pilot_v1"
for path in (repo, root, baseline, source, parquet, scratch, config, pilot):
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Comparison paths must be absolute and have no symlink ancestors.")
if root.exists():
    raise ValueError("Comparison run exists; no overwrite or automatic resume.")
if not all(p.is_dir() for p in (repo, baseline, parquet, scratch)) or not source.is_file():
    raise ValueError("Frozen source, baseline, or scratch prerequisite is missing.")
if any(scratch == p or scratch.is_relative_to(p) for p in (baseline, parquet, pilot)):
    raise ValueError("Scratch must be outside protected catalog/source/pilot trees.")
for name in ("inference_questions.jsonl", "reference_interpretations.jsonl", "ontology.yaml"):
    path = pilot / name
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Frozen GrailQA input is missing or unsafe: {name}")
reverse = repo / "datasets/grailqa_inference_catalog_v1/reverse_properties.json"
if not reverse.is_file() or any(p.is_symlink() for p in (reverse, *reverse.parents)):
    raise ValueError("Frozen reverse-property input is missing or unsafe.")
cfg = json.loads(config.read_text())
ids = cfg["workloads"]["preflight18"]["question_ids"]
if len(ids) != 18 or len(set(ids)) != 18:
    raise ValueError("The comparison requires the complete development18 population.")
questions = load_inference_questions(pilot / "inference_questions.jsonl", question_ids=ids)
validate_local_catalog(baseline)
manifest = json.loads((baseline / "manifest.json").read_text())
if manifest["local_catalog_schema_version"] != LOCAL_CATALOG_SCHEMA_VERSION:
    raise ValueError("The baseline must be the preserved v1 query-local catalog.")
if manifest.get("question_ids") != ids:
    raise ValueError("Baseline question IDs/order must match development18.")
if manifest.get("anchor_extraction") != cfg["anchor_extraction"]:
    raise ValueError("Baseline and new build must preserve the anchor policy.")
if manifest.get("sources", {}).get("inference_questions", {}).get("sha256") != sha256_file(pilot / "inference_questions.jsonl"):
    raise ValueError("Baseline inference-question source file differs.")
if manifest["sources"]["freebase_archival_parquet"]["source_manifest_sha256"] != sha256_file(source):
    raise ValueError("Baseline and new build must use the same frozen source manifest.")
ontology_source = manifest["sources"]["ontology"]
if (ontology_source["sha256"] != sha256_file(pilot / "ontology.yaml")
        or ontology_source["reverse_properties_sha256"] != sha256_file(reverse)):
    raise ValueError("Baseline and new build must preserve ontology and reverse properties.")
stored = [json.loads(line) for line in (baseline / "local_queries.jsonl").read_text().splitlines() if line.strip()]
if (len(stored) != len(questions)
        or {row["question_id"]: row["text"] for row in stored} != {q.question_id: q.text for q in questions}):
    raise ValueError("Baseline question identities/text do not match development18.")
root.parent.mkdir(parents=True, exist_ok=True)
root.mkdir(exist_ok=False)
with (root / "run_inputs.json").open("x", encoding="utf-8") as handle:
    json.dump({
        "schema_version": "grailqa-catalog-comparison-launch-v1",
        "runner_commit": os.environ["XGAP_GRAILQA_REPAIR_RUNNER_COMMIT"],
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "legacy_catalog_root": str(baseline), "source_manifest_sha256": sha256_file(source),
        "question_ids": ids, "paper_result": False, "automatic_retries": 0,
        "llm_calls": 0, "backend_calls": 0,
    }, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(",".join(ids))
PY
)"

[[ "$(git rev-parse HEAD)" == "$XGAP_GRAILQA_REPAIR_RUNNER_COMMIT" ]] || fail "Runner changed during precheck."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "Checkout changed during precheck."
printf 'runner_commit=%s\nrun_root=%s\n' "$XGAP_GRAILQA_REPAIR_RUNNER_COMMIT" "$XGAP_GRAILQA_COMPARISON_RUN"
printf '%s\n' "Building only the new eligibility-first development18 catalog; the old catalog is read-only."
"$XGAP_PYTHON" -m xgap.experiments.grailqa_local_catalog build \
  --config "$XGAP_REPO_ROOT/experiments/specs/grailqa_local_catalog_v1.json" \
  --workload preflight18 \
  --candidate-selection canonical_eligible_topk_v2 \
  --parquet-root "$XGAP_FREEBASE_PARQUET_ROOT" \
  --source-manifest "$XGAP_FREEBASE_SOURCE_MANIFEST" \
  --local-root "$XGAP_GRAILQA_COMPARISON_RUN/catalog" \
  --staging-root "$XGAP_LOCAL_CATALOG_STAGING_ROOT"

[[ "$(git rev-parse HEAD)" == "$XGAP_GRAILQA_REPAIR_RUNNER_COMMIT" ]] || fail "Runner changed during build."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "Checkout changed during build."
exec "$XGAP_PYTHON" -m xgap.experiments.grailqa_catalog_comparison \
  --legacy-catalog-root "$XGAP_GRAILQA_LEGACY_CATALOG" \
  --eligible-catalog-root "$XGAP_GRAILQA_COMPARISON_RUN/catalog/preflight18-eligible-v2" \
  --inference-questions "$XGAP_REPO_ROOT/datasets/grailqa_pilot_v1/inference_questions.jsonl" \
  --question-ids "$COMPARISON_IDS" \
  --reference-interpretations "$XGAP_REPO_ROOT/datasets/grailqa_pilot_v1/reference_interpretations.jsonl" \
  --output-root "$XGAP_GRAILQA_COMPARISON_RUN/comparison"
