#!/usr/bin/env bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${XGAP_REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="${XGAP_CWRU_PROBE_ROOT:-$REPO_ROOT/runs/cwru-m15-probe-$STAMP}"
REPORT="$RUN_ROOT/environment_probe.txt"

mkdir -p "$RUN_ROOT"
exec > >(tee "$REPORT") 2>&1

record() {
  printf '%s=%s\n' "$1" "$2"
}

command_available() {
  command -v "$1" >/dev/null 2>&1
}

record probe_version "m15-b0-v2"
record timestamp_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
record hostname "$(hostname)"
record repo_root "$REPO_ROOT"

core_ready=true
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  record git_commit "$(git -C "$REPO_ROOT" rev-parse HEAD)"
  record git_branch "$(git -C "$REPO_ROOT" branch --show-current)"
  if [[ -z "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    record git_clean true
  else
    record git_clean false
    core_ready=false
  fi
else
  record git_checkout false
  core_ready=false
fi

PYTHON_BIN="${XGAP_PYTHON:-python}"
record python_module_hint "${XGAP_PYTHON_MODULE:-Miniconda3}"
record python_command "$PYTHON_BIN"
if command_available "$PYTHON_BIN"; then
  record python_version "$($PYTHON_BIN --version 2>&1)"
  if "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    record python_310_plus true
  else
    record python_310_plus false
    core_ready=false
  fi
  if "$PYTHON_BIN" -c 'import pytest' >/dev/null 2>&1; then
    record pytest_available true
  else
    record pytest_available false
    core_ready=false
  fi
else
  record python_available false
  core_ready=false
fi

slurm_ready=true
for slurm_command in sbatch squeue sacct scontrol sinfo; do
  if command_available "$slurm_command"; then
    record "${slurm_command}_available" true
  else
    record "${slurm_command}_available" false
    slurm_ready=false
    core_ready=false
  fi
done

gpu2h100_visible=false
if command_available sinfo; then
  SLURM_GPU_FEATURES="$(sinfo -h -p gpu -o '%f' 2>/dev/null | sort -u | paste -sd, - || true)"
  record slurm_gpu_features "${SLURM_GPU_FEATURES:-unavailable}"
  if printf '%s\n' "$SLURM_GPU_FEATURES" | grep -Eq '(^|,)gpu2h100(,|$)'; then
    gpu2h100_visible=true
  fi
fi
record gpu2h100_visible "$gpu2h100_visible"
record slurm_ready "$slurm_ready"

VLLM_ENV="${VLLM_ENV:-$HOME/venvs/xgap-vllm}"
record vllm_env "$VLLM_ENV"
if [[ -x "$VLLM_ENV/bin/python" && -x "$VLLM_ENV/bin/vllm" ]]; then
  record vllm_environment_available true
else
  record vllm_environment_available false
fi

backend_runtime=none
if command_available docker && docker info >/dev/null 2>&1; then
  backend_runtime=docker
elif command_available apptainer; then
  backend_runtime=apptainer
elif command_available singularity; then
  backend_runtime=singularity
elif command_available podman; then
  backend_runtime=podman
fi
record backend_runtime "$backend_runtime"
record docker_command_available "$(command_available docker && printf true || printf false)"
record apptainer_command_available "$(command_available apptainer && printf true || printf false)"
record singularity_command_available "$(command_available singularity && printf true || printf false)"
record podman_command_available "$(command_available podman && printf true || printf false)"

record core_smoke_ready "$core_ready"
record live_backend_packaging_ready "$( [[ "$backend_runtime" != none ]] && printf true || printf false )"
record report_path "$REPORT"

if [[ "$core_ready" == true ]]; then
  echo "M15 core smoke may be submitted with scripts/slurm/run_m15_core_smoke.sbatch."
else
  echo "M15 core smoke is not ready. Return this report before changing the server." >&2
fi
