#!/usr/bin/env bash
#SBATCH --job-name=xgap-ch6-cpu
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:15:00
#SBATCH --no-requeue
set -euo pipefail
module load Miniconda3/23.10.0-1
test "$#" -eq 3
XGAP_REPO_PATH="$1"
XGAP_PYTHON_PATH="$2"
XGAP_OUTPUT_PATH="$3"
cd "$XGAP_REPO_PATH"
export PYTHONPATH="$XGAP_REPO_PATH/src:$XGAP_REPO_PATH/tests:$XGAP_REPO_PATH/scripts"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
"$XGAP_PYTHON_PATH" scripts/check_ch6_cpu_host.py --output "$XGAP_OUTPUT_PATH" --model-smoke
