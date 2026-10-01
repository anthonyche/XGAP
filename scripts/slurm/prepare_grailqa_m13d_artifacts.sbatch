#!/usr/bin/env bash
#SBATCH --job-name=xgap-grailqa-artifacts
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-grailqa-m13d-artifacts-%j.out

set -euo pipefail

module load Miniconda3

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$HOME/XGAP}}"
PYTHON_BIN="${XGAP_PYTHON:-$HOME/venvs/xgap-core/bin/python}"
ARTIFACT_CACHE="${XGAP_ARTIFACT_CACHE:-$HOME/xgap-data/grailqa-m13d-v1}"
RUN_ROOT="${XGAP_GRAILQA_ARTIFACT_RUN_ROOT:-$REPO_ROOT/runs/cwru-grailqa-m13d-artifacts-${SLURM_JOB_ID:-manual}}"
FETCH_LOG="$RUN_ROOT/fetch.log"
VERIFY_LOG="$RUN_ROOT/verify.log"
RECEIPT="$RUN_ROOT/artifact_receipt.json"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "XGAP Python environment is unavailable: $PYTHON_BIN" >&2
  exit 2
fi
if [[ ! -d "$REPO_ROOT/.git" && ! -f "$REPO_ROOT/.git" ]]; then
  echo "XGAP_REPO_ROOT is not a Git checkout: $REPO_ROOT" >&2
  exit 2
fi

cd "$REPO_ROOT"
mkdir -p "$RUN_ROOT"

echo "git_commit=$(git rev-parse HEAD)"
echo "python=$PYTHON_BIN"
"$PYTHON_BIN" --version
echo "hostname=$(hostname)"
echo "cpus=${SLURM_CPUS_PER_TASK:-unknown}"
echo "artifact_cache=$ARTIFACT_CACHE"
echo "run_root=$RUN_ROOT"
echo "This CPU-only job prepares pinned GrailQA and ontology artifacts."
echo "It does not scan the 32 GB Freebase parquet source or start Qwen."

export PYTHON="$PYTHON_BIN"
export XGAP_ARTIFACT_CACHE="$ARTIFACT_CACHE"

bash scripts/server/fetch_grailqa_m13d_artifacts.sh \
  2>&1 | tee "$FETCH_LOG"

bash scripts/server/fetch_grailqa_m13d_artifacts.sh --verify-only \
  2>&1 | tee "$VERIFY_LOG"

PYTHONPATH="$REPO_ROOT/src" "$PYTHON_BIN" - \
  "$REPO_ROOT" "$RECEIPT" "${SLURM_JOB_ID:-manual}" <<'PY'
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from xgap.experiments.grailqa_semantic_pilot import (
    GrailQASemanticPilotSpec,
    validate_frozen_artifacts,
)
from xgap.experiments.hashing import content_hash


repo = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2])
job_id = sys.argv[3]
spec_path = repo / "experiments/specs/grailqa_semantic_pilot_v1.json"
source_path = repo / "experiments/sources/grailqa_m13d_sources.json"
spec = GrailQASemanticPilotSpec.load(spec_path)
catalog, model = validate_frozen_artifacts(spec, repo)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


pilot_root = spec.resolve(repo, "pilot_bundle_root")
catalog_root = spec.resolve(repo, "catalog_root")
records = []
for name, expected in sorted(spec.data["pilot_artifact_hashes"].items()):
    path = pilot_root / name
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"unsafe or missing pilot artifact: {name}")
    observed = sha256_file(path)
    if observed != expected:
        raise SystemExit(f"pilot artifact hash mismatch: {name}")
    records.append(
        {
            "path": path.relative_to(repo).as_posix(),
            "sha256": observed,
            "size_bytes": path.stat().st_size,
        }
    )

catalog_manifest_path = catalog_root / "manifest.json"
catalog_manifest = json.loads(catalog_manifest_path.read_text(encoding="utf-8"))
for name, expected in sorted(catalog_manifest["file_hashes"].items()):
    path = catalog_root / name
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"unsafe or missing inference-catalog artifact: {name}")
    observed = sha256_file(path)
    if observed != expected:
        raise SystemExit(f"inference-catalog artifact hash mismatch: {name}")
    records.append(
        {
            "path": path.relative_to(repo).as_posix(),
            "sha256": observed,
            "size_bytes": path.stat().st_size,
        }
    )

body = {
    "schema_version": "m13e4-grailqa-runtime-artifact-receipt-v1",
    "status": "success",
    "verified_at": datetime.now(timezone.utc).isoformat(),
    "slurm_job_id": job_id,
    "git_commit": subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip(),
    "spec_sha256": sha256_file(spec_path),
    "source_manifest_sha256": sha256_file(source_path),
    "pilot_bundle_hash": spec.data["pilot_bundle_hash"],
    "question_count": len(spec.question_ids),
    "catalog_hash": catalog.catalog_hash,
    "ontology_hash": catalog.ontology.ontology_hash,
    "model_bundle_hash": model.bundle_hash,
    "artifacts": records,
    "verification_external_calls": {
        "llm_calls": 0,
        "backend_calls": 0,
        "ontology_service_calls": 0,
    },
    "freebase_parquet_bytes_scanned": 0,
    "paper_result": False,
}
receipt = {**body, "receipt_sha256": content_hash(body)}
output.parent.mkdir(parents=True, exist_ok=True)
with output.open("x", encoding="utf-8") as handle:
    json.dump(receipt, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(json.dumps(receipt, indent=2, sort_keys=True))
PY

echo "artifact_receipt=$RECEIPT"
echo "M13-D GrailQA runtime artifacts are installed and frozen-spec verified."
