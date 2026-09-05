#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-native-adaptive
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export XGAP_M15_WORKLOAD_MODE=adaptive
source "$SCRIPT_DIR/run_m15_native_services.sbatch"
