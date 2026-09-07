#!/usr/bin/env bash
#SBATCH --job-name=xgap-m15-native-services
#SBATCH --partition=batch
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_ROOT="${XGAP_REPO_ROOT:-${SLURM_SUBMIT_DIR:-$PWD}}"
PYTHON_MODULE="${XGAP_PYTHON_MODULE:-Miniconda3}"
JAVA_MODULE="${XGAP_JAVA_MODULE:-Java/17.0.6}"
PYTHON_BIN="${XGAP_PYTHON:-python}"
CACHE_ROOT="${XGAP_NATIVE_ARTIFACT_CACHE:-$HOME/xgap-data/m15-native/artifacts}"
WORKLOAD_MODE="${XGAP_M15_WORKLOAD_MODE:-vertical_slice}"
WORKLOAD_PROFILE="${XGAP_M15_WORKLOAD_PROFILE:-selective}"
case "$WORKLOAD_MODE" in
  vertical_slice)
    RUN_PREFIX="cwru-m15-native-services"
    RUN_VERSION="m15-b2d-native-services-v1"
    ;;
  adaptive)
    RUN_PREFIX="cwru-m15-native-adaptive"
    RUN_VERSION="m15-d2-native-adaptive-services-v1"
    ;;
  scaled_adaptive)
    RUN_PREFIX="cwru-m15-native-scaled-adaptive"
    RUN_VERSION="m15-f0-native-scaled-adaptive-services-v1"
    case "$WORKLOAD_PROFILE" in
      selective)
        WORKLOAD_CONFIG="experiments/configs/m15_f0_selective.json"
        ;;
      broad_hot)
        WORKLOAD_CONFIG="experiments/configs/m15_f0_broad_hot.json"
        ;;
      *)
        echo "Unsupported XGAP_M15_WORKLOAD_PROFILE: $WORKLOAD_PROFILE" >&2
        exit 2
        ;;
    esac
    ;;
  scaled_method_matrix)
    RUN_PREFIX="cwru-m15-native-method-matrix"
    RUN_VERSION="m15-f1-native-live-method-matrix-services-v1"
    case "$WORKLOAD_PROFILE" in
      selective)
        WORKLOAD_CONFIG="experiments/configs/m15_f0_selective.json"
        ;;
      broad_hot)
        WORKLOAD_CONFIG="experiments/configs/m15_f0_broad_hot.json"
        ;;
      *)
        echo "Unsupported XGAP_M15_WORKLOAD_PROFILE: $WORKLOAD_PROFILE" >&2
        exit 2
        ;;
    esac
    ;;
  scaled_campaign_session)
    RUN_PREFIX="cwru-m15-native-campaign-session"
    RUN_VERSION="m15-f2-native-live-campaign-session-services-v1"
    CAMPAIGN_CONFIG="experiments/configs/m15_f2_campaign_dev.json"
    : "${XGAP_M15_CAMPAIGN_SESSION_ID:?XGAP_M15_CAMPAIGN_SESSION_ID is required}"
    : "${XGAP_M15_CAMPAIGN_SPEC_SHA256:?XGAP_M15_CAMPAIGN_SPEC_SHA256 is required}"
    : "${XGAP_M15_CAMPAIGN_SCHEDULE_SHA256:?XGAP_M15_CAMPAIGN_SCHEDULE_SHA256 is required}"
    case "$WORKLOAD_PROFILE" in
      selective)
        WORKLOAD_CONFIG="experiments/configs/m15_f0_selective.json"
        ;;
      broad_hot)
        WORKLOAD_CONFIG="experiments/configs/m15_f0_broad_hot.json"
        ;;
      *)
        echo "Unsupported XGAP_M15_WORKLOAD_PROFILE: $WORKLOAD_PROFILE" >&2
        exit 2
        ;;
    esac
    ;;
  scaled_query_bound_session)
    RUN_PREFIX="cwru-m15-native-query-bound-session"
    RUN_VERSION="m15-f2b-native-live-query-bound-session-services-v1"
    QUERY_BOUND_REGISTRY="experiments/configs/m15_f2_query_bound_campaign_dev.json"
    : "${XGAP_M15_QUERY_BOUND_SESSION_ID:?XGAP_M15_QUERY_BOUND_SESSION_ID is required}"
    : "${XGAP_M15_QUERY_BOUND_REGISTRY_SPEC_SHA256:?XGAP_M15_QUERY_BOUND_REGISTRY_SPEC_SHA256 is required}"
    : "${XGAP_M15_QUERY_BOUND_SCHEDULE_SHA256:?XGAP_M15_QUERY_BOUND_SCHEDULE_SHA256 is required}"
    case "$WORKLOAD_PROFILE" in
      selective)
        WORKLOAD_CONFIG="experiments/configs/m15_f0_selective.json"
        ;;
      broad_hot)
        WORKLOAD_CONFIG="experiments/configs/m15_f0_broad_hot.json"
        ;;
      *)
        echo "Unsupported XGAP_M15_WORKLOAD_PROFILE: $WORKLOAD_PROFILE" >&2
        exit 2
        ;;
    esac
    ;;
  parameterized_stream)
    RUN_PREFIX="cwru-m15-native-parameterized-stream"
    RUN_VERSION="m15-f2c4-native-live-parameterized-stream-services-v1"
    ;;
  parameterized_family_transfer)
    RUN_PREFIX="cwru-m15-native-family-transfer"
    RUN_VERSION="m15-f2c5-native-live-family-transfer-services-v1"
    ;;
  semantic_risk_relaxation)
    RUN_PREFIX="cwru-m15-native-semantic-risk-relaxation"
    RUN_VERSION="m15-f2c7b2-native-live-semantic-risk-relaxation-services-v1"
    ;;
  semantic_predicate_relaxation)
    RUN_PREFIX="cwru-m15-native-semantic-predicate-relaxation"
    RUN_VERSION="m15-f2c8b-native-live-semantic-predicate-relaxation-services-v1"
    ;;
  semantic_direct_frontier)
    RUN_PREFIX="cwru-m15-native-semantic-direct-frontier"
    RUN_VERSION="m15-f2c9b-native-live-direct-semantic-frontier-services-v1"
    ;;
  direct_family_pilot)
    RUN_PREFIX="cwru-m15-native-direct-family-pilot"
    RUN_VERSION="m15-f2c10d-native-live-direct-family-pilot-services-v1"
    ;;
  current_query_profile_baseline)
    RUN_PREFIX="cwru-m15-native-current-query-profile-baseline"
    RUN_VERSION="m15-f2c12b-native-current-query-profile-services-v1"
    ;;
  paired_physical_comparison)
    RUN_PREFIX="cwru-m15-native-paired-physical-comparison"
    RUN_VERSION="m15-f2c13b-native-live-paired-physical-comparison-services-v1"
    ;;
  resolution_execution_bridge)
    RUN_PREFIX="cwru-m15-native-resolution-execution-bridge"
    RUN_VERSION="m15-e4b-native-live-resolution-execution-bridge-services-v1"
    ;;
  selected_interpretation_session)
    RUN_PREFIX="cwru-m15-native-selected-interpretation-session"
    RUN_VERSION="m15-e5d-native-live-selected-interpretation-session-services-v1"
    : "${XGAP_M15_SELECTED_TRAINING_MEMORY:?XGAP_M15_SELECTED_TRAINING_MEMORY is required}"
    : "${XGAP_M15_SELECTED_MEMORY_SHA256:?XGAP_M15_SELECTED_MEMORY_SHA256 is required}"
    : "${XGAP_M15_SELECTED_SESSION_ID:?XGAP_M15_SELECTED_SESSION_ID is required}"
    : "${XGAP_M15_SELECTED_STRUCTURAL_CANDIDATE:?XGAP_M15_SELECTED_STRUCTURAL_CANDIDATE is required}"
    : "${XGAP_M15_SELECTED_PREDICATE_CANDIDATE:?XGAP_M15_SELECTED_PREDICATE_CANDIDATE is required}"
    : "${XGAP_M15_SELECTED_AUTHORITY_SOURCE_ID:?XGAP_M15_SELECTED_AUTHORITY_SOURCE_ID is required}"
    ;;
  finbench_correctness)
    RUN_PREFIX="cwru-m15-native-finbench-correctness"
    RUN_VERSION="m15-finbench-native-live-correctness-services-v1"
    ;;
  *)
    echo "Unsupported XGAP_M15_WORKLOAD_MODE: $WORKLOAD_MODE" >&2
    exit 2
    ;;
esac
RUN_ROOT="${XGAP_CWRU_RUN_ROOT:-$REPO_ROOT/runs/${RUN_PREFIX}-${SLURM_JOB_ID:-manual}}"
STATUS_FILE="$RUN_ROOT/run_status.json"
STAGING_MANIFEST="$RUN_ROOT/runtime_staging.json"
RUNTIME_ROOT=""
LOCAL_BASE=""
RUNTIME_REMOVED=false
CLEANUP_ERROR=""

if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  echo "XGAP_REPO_ROOT is not an XGAP checkout: $REPO_ROOT" >&2
  exit 2
fi
if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo "This entry point requires a real Slurm allocation." >&2
  exit 2
fi
if [[ "$CACHE_ROOT" != /* ]]; then
  echo "XGAP_NATIVE_ARTIFACT_CACHE must be an absolute path." >&2
  exit 2
fi

mkdir -p "$RUN_ROOT"
exec > >(tee -a "$RUN_ROOT/job.log") 2>&1

cleanup_runtime() {
  if [[ -z "$RUNTIME_ROOT" ]]; then
    RUNTIME_REMOVED=true
    return 0
  fi
  case "$RUNTIME_ROOT" in
    "$LOCAL_BASE"/xgap-m15-"$SLURM_JOB_ID".*) ;;
    *)
      CLEANUP_ERROR="runtime path failed the job-owned prefix check"
      return 1
      ;;
  esac
  if [[ -L "$RUNTIME_ROOT" || ! -d "$RUNTIME_ROOT" ]]; then
    CLEANUP_ERROR="runtime path is not the expected real directory"
    return 1
  fi
  if [[ "$(stat -c %u "$RUNTIME_ROOT")" != "$(id -u)" ]]; then
    CLEANUP_ERROR="runtime path is not owned by the job user"
    return 1
  fi
  if ! rm -rf -- "$RUNTIME_ROOT"; then
    CLEANUP_ERROR="failed to remove the validated runtime path"
    return 1
  fi
  if [[ -e "$RUNTIME_ROOT" || -L "$RUNTIME_ROOT" ]]; then
    CLEANUP_ERROR="validated runtime path still exists after cleanup"
    return 1
  fi
  RUNTIME_REMOVED=true
}

finalize() {
  local exit_code=$?
  local state=failed
  trap - EXIT
  set +e
  if ! cleanup_runtime; then
    exit_code=1
  fi
  if [[ "$exit_code" -eq 0 && "$RUNTIME_REMOVED" == true ]]; then
    state=success
  fi
  local cleanup_json=null
  if [[ -n "$CLEANUP_ERROR" ]]; then
    cleanup_json="\"$CLEANUP_ERROR\""
  fi
  printf '{"status":"%s","exit_code":%d,"slurm_job_id":"%s","git_commit":"%s","workload_mode":"%s","runtime_removed":%s,"cleanup_error":%s}\n' \
    "$state" \
    "$exit_code" \
    "$SLURM_JOB_ID" \
    "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || printf unavailable)" \
    "$WORKLOAD_MODE" \
    "$RUNTIME_REMOVED" \
    "$cleanup_json" \
    > "$STATUS_FILE"
  echo "M15 native-service artifacts: $RUN_ROOT"
  exit "$exit_code"
}
trap finalize EXIT

cd "$REPO_ROOT"
if [[ -n "$(git status --porcelain)" && "${XGAP_ALLOW_DIRTY:-0}" != 1 ]]; then
  echo "Refusing a dirty experiment checkout." >&2
  exit 2
fi
if ! type module >/dev/null 2>&1; then
  echo "Environment Modules is unavailable." >&2
  exit 2
fi
module load "$PYTHON_MODULE"
module load "$JAVA_MODULE"
hash -r
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python command is unavailable: $PYTHON_BIN" >&2
  exit 2
fi
if ! command -v java >/dev/null 2>&1; then
  echo "Java is unavailable after loading $JAVA_MODULE." >&2
  exit 2
fi
JAVA_BIN="$(command -v java)"

LOCAL_BASE="${SLURM_TMPDIR:-/tmp}"
if [[ "$LOCAL_BASE" != /* || ! -d "$LOCAL_BASE" || -L "$LOCAL_BASE" ]]; then
  echo "Allocation-local base must be an absolute real directory: $LOCAL_BASE" >&2
  exit 2
fi
LOCAL_BASE="$(cd "$LOCAL_BASE" && pwd -P)"
FILESYSTEM_TYPE="$(stat -f -c %T "$LOCAL_BASE")"
case "${FILESYSTEM_TYPE,,}" in
  tmpfs|xfs|ext2/ext3|ext4|btrfs|zfs|overlay|overlayfs) ;;
  *)
    echo "Allocation runtime filesystem is not allowlisted: $FILESYSTEM_TYPE" >&2
    exit 2
    ;;
esac
RUNTIME_ROOT="$(mktemp -d "$LOCAL_BASE/xgap-m15-${SLURM_JOB_ID}.XXXXXX")"

{
  printf 'run_version=%s\n' "$RUN_VERSION"
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname=%s\n' "$(hostname)"
  printf 'slurm_job_id=%s\n' "$SLURM_JOB_ID"
  printf 'git_commit=%s\n' "$(git rev-parse HEAD)"
  printf 'python_module=%s\n' "$PYTHON_MODULE"
  printf 'python_version=%s\n' "$($PYTHON_BIN --version 2>&1)"
  printf 'java_module=%s\n' "$JAVA_MODULE"
  printf 'java_command=%s\n' "$JAVA_BIN"
  printf 'runtime_base=%s\n' "$LOCAL_BASE"
  printf 'runtime_root=%s\n' "$RUNTIME_ROOT"
  printf 'runtime_filesystem_type=%s\n' "$FILESYSTEM_TYPE"
  printf 'cache_root=%s\n' "$CACHE_ROOT"
  printf 'loopback_only=true\n'
  printf 'automatic_retries=0\n'
  printf 'workload_mode=%s\n' "$WORKLOAD_MODE"
  printf 'workload_profile=%s\n' "$WORKLOAD_PROFILE"
} > "$RUN_ROOT/environment.txt"
if command -v findmnt >/dev/null 2>&1; then
  findmnt -T "$LOCAL_BASE" -o TARGET,SOURCE,FSTYPE,OPTIONS \
    > "$RUN_ROOT/runtime_mount.txt"
else
  printf 'findmnt_unavailable=true\n' > "$RUN_ROOT/runtime_mount.txt"
fi
java -version > "$RUN_ROOT/java_version.txt" 2>&1
cp -- "$REPO_ROOT/services/m15-native-runtime.lock.json" \
  "$RUN_ROOT/runtime_lock.json"

XGAP_STAGE_M15_NATIVE_RUNTIME=1 \
PYTHONPATH="$REPO_ROOT/src" \
"$PYTHON_BIN" -m xgap.experiments.m15_native_runtime \
  --lock "$REPO_ROOT/services/m15-native-runtime.lock.json" \
  --cache-root "$CACHE_ROOT" \
  --runtime-root "$RUNTIME_ROOT" \
  --manifest "$STAGING_MANIFEST" \
  | tee "$RUN_ROOT/runtime_staging_result.json"

WORKLOAD_ARGS=()
if [[ "$WORKLOAD_MODE" == finbench_correctness ]]; then
  FINBENCH_ARCHIVE="${XGAP_FINBENCH_ARCHIVE:-$HOME/.cache/xgap/finbench-v0.1.0/sf0.01.tar.gz}"
  if [[ "$FINBENCH_ARCHIVE" != /* || ! -f "$FINBENCH_ARCHIVE" || -L "$FINBENCH_ARCHIVE" ]]; then
    echo "Verified FinBench archive is missing or unsafe: $FINBENCH_ARCHIVE" >&2
    echo "Run scripts/server/prepare_m15_finbench_sf001.sh before submission." >&2
    exit 2
  fi
  FINBENCH_PARTITION="$RUN_ROOT/finbench-source-partition"
  FINBENCH_WORKLOAD="$RUN_ROOT/finbench-primary-workload"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_finbench_partition \
    --archive "$FINBENCH_ARCHIVE" \
    --lock "$REPO_ROOT/experiments/artifacts/m15_finbench_v010_sources.json" \
    --output-root "$FINBENCH_PARTITION" \
    --batch-size 250 \
    | tee "$RUN_ROOT/finbench_partition_generation.json"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_finbench_workload \
    --archive "$FINBENCH_ARCHIVE" \
    --partition-root "$FINBENCH_PARTITION" \
    --lock "$REPO_ROOT/experiments/artifacts/m15_finbench_v010_sources.json" \
    --spec "$REPO_ROOT/experiments/configs/m15_finbench_primary_population_v1.json" \
    --output-root "$FINBENCH_WORKLOAD" \
    | tee "$RUN_ROOT/finbench_workload_generation.json"
  WORKLOAD_ARGS=(
    --finbench-workload "$FINBENCH_WORKLOAD"
    --finbench-partition "$FINBENCH_PARTITION"
  )
  if [[ -n "${XGAP_FINBENCH_QUERY_IDS:-}" ]]; then
    IFS=',' read -r -a FINBENCH_QUERY_IDS <<< "$XGAP_FINBENCH_QUERY_IDS"
    for FINBENCH_QUERY_ID in "${FINBENCH_QUERY_IDS[@]}"; do
      if [[ -z "$FINBENCH_QUERY_ID" ]]; then
        echo "XGAP_FINBENCH_QUERY_IDS contains an empty query ID." >&2
        exit 2
      fi
      WORKLOAD_ARGS+=(--finbench-query-id "$FINBENCH_QUERY_ID")
    done
  fi
fi
if [[ "$WORKLOAD_MODE" == scaled_adaptive || "$WORKLOAD_MODE" == scaled_method_matrix || "$WORKLOAD_MODE" == scaled_campaign_session || "$WORKLOAD_MODE" == scaled_query_bound_session ]]; then
  WORKLOAD_BUNDLE="$RUN_ROOT/workload-bundle"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_workload \
    --spec "$REPO_ROOT/$WORKLOAD_CONFIG" \
    --output "$WORKLOAD_BUNDLE" \
    | tee "$RUN_ROOT/workload_generation.json"
  WORKLOAD_ARGS=(--workload-bundle "$WORKLOAD_BUNDLE")
fi
if [[ "$WORKLOAD_MODE" == parameterized_stream || "$WORKLOAD_MODE" == parameterized_family_transfer ]]; then
  WORKLOAD_BUNDLE="$RUN_ROOT/parameterized-workload-bundle"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_parameterized_workload \
    --workload-spec "$REPO_ROOT/experiments/configs/m15_f2c_parameterized_workload_dev.json" \
    --query-template-spec "$REPO_ROOT/experiments/configs/m15_f2c_parameterized_financial_risk_v2.json" \
    --backend-template-root "$REPO_ROOT/experiments/templates/m15_f2c_financial_risk" \
    --output "$WORKLOAD_BUNDLE" \
    | tee "$RUN_ROOT/workload_generation.json"
  WORKLOAD_ARGS=(--parameterized-workload-bundle "$WORKLOAD_BUNDLE")
fi
if [[ "$WORKLOAD_MODE" == semantic_risk_relaxation ]]; then
  SEMANTIC_BASE_BUNDLE="$RUN_ROOT/semantic-base-workload-bundle"
  SEMANTIC_OVERLAY="$RUN_ROOT/semantic-overlay"
  SEMANTIC_CATALOG="$RUN_ROOT/semantic_catalog.json"
  cp -- "$REPO_ROOT/experiments/configs/m15_f2c6_semantic_relaxation_dev.json" \
    "$SEMANTIC_CATALOG"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_parameterized_workload \
    --workload-spec "$REPO_ROOT/experiments/configs/m15_f2c_parameterized_workload_dev.json" \
    --query-template-spec "$REPO_ROOT/experiments/configs/m15_f2c_parameterized_financial_risk_v2.json" \
    --backend-template-root "$REPO_ROOT/experiments/templates/m15_f2c_financial_risk" \
    --output "$SEMANTIC_BASE_BUNDLE" \
    | tee "$RUN_ROOT/semantic_base_generation.json"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_semantic_overlay \
    --base-bundle-root "$SEMANTIC_BASE_BUNDLE" \
    --base-query-id financial-risk-alice-aug-high-v2 \
    --catalog "$SEMANTIC_CATALOG" \
    --output "$SEMANTIC_OVERLAY" \
    | tee "$RUN_ROOT/semantic_overlay_generation.json"
  WORKLOAD_ARGS=(
    --semantic-overlay "$SEMANTIC_OVERLAY"
    --semantic-base-bundle "$SEMANTIC_BASE_BUNDLE"
    --semantic-catalog "$SEMANTIC_CATALOG"
  )
fi
if [[ "$WORKLOAD_MODE" == semantic_predicate_relaxation || "$WORKLOAD_MODE" == semantic_direct_frontier ]]; then
  SEMANTIC_BASE_BUNDLE="$RUN_ROOT/semantic-base-workload-bundle"
  PREDICATE_OVERLAY="$RUN_ROOT/predicate-overlay"
  SEMANTIC_CATALOG="$RUN_ROOT/semantic_catalog.json"
  PREDICATE_MAPPING="$RUN_ROOT/predicate_mapping.json"
  cp -- "$REPO_ROOT/experiments/configs/m15_f2c6_semantic_relaxation_dev.json" \
    "$SEMANTIC_CATALOG"
  cp -- "$REPO_ROOT/experiments/configs/m15_f2c8_predicate_mapping_dev.json" \
    "$PREDICATE_MAPPING"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_parameterized_workload \
    --workload-spec "$REPO_ROOT/experiments/configs/m15_f2c_parameterized_workload_dev.json" \
    --query-template-spec "$REPO_ROOT/experiments/configs/m15_f2c_parameterized_financial_risk_v2.json" \
    --backend-template-root "$REPO_ROOT/experiments/templates/m15_f2c_financial_risk" \
    --output "$SEMANTIC_BASE_BUNDLE" \
    | tee "$RUN_ROOT/semantic_base_generation.json"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_predicate_overlay \
    --base-bundle-root "$SEMANTIC_BASE_BUNDLE" \
    --base-query-id financial-risk-alice-aug-high-v2 \
    --catalog "$SEMANTIC_CATALOG" \
    --mapping "$PREDICATE_MAPPING" \
    --output "$PREDICATE_OVERLAY" \
    | tee "$RUN_ROOT/predicate_overlay_generation.json"
  WORKLOAD_ARGS=(
    --predicate-overlay "$PREDICATE_OVERLAY"
    --semantic-base-bundle "$SEMANTIC_BASE_BUNDLE"
    --semantic-catalog "$SEMANTIC_CATALOG"
    --predicate-mapping "$PREDICATE_MAPPING"
  )
  if [[ "$WORKLOAD_MODE" == semantic_direct_frontier ]]; then
    DIRECT_FRONTIER_ESTIMATES="$RUN_ROOT/direct_frontier_estimates.json"
    cp -- "$REPO_ROOT/experiments/configs/m15_f2c9_direct_frontier_estimates_dev.json" \
      "$DIRECT_FRONTIER_ESTIMATES"
    WORKLOAD_ARGS+=(--direct-frontier-estimates "$DIRECT_FRONTIER_ESTIMATES")
  fi
fi
if [[ "$WORKLOAD_MODE" == direct_family_pilot || "$WORKLOAD_MODE" == current_query_profile_baseline || "$WORKLOAD_MODE" == paired_physical_comparison ]]; then
  SEMANTIC_BASE_BUNDLE="$RUN_ROOT/direct-family-base-workload-bundle"
  DIRECT_SEMANTIC_WORKLOAD="$RUN_ROOT/direct-semantic-workload-bundle"
  SEMANTIC_CATALOG="$RUN_ROOT/semantic_catalog.json"
  PREDICATE_MAPPING="$RUN_ROOT/predicate_mapping.json"
  cp -- "$REPO_ROOT/experiments/configs/m15_f2c6_semantic_relaxation_dev.json" \
    "$SEMANTIC_CATALOG"
  cp -- "$REPO_ROOT/experiments/configs/m15_f2c8_predicate_mapping_dev.json" \
    "$PREDICATE_MAPPING"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_parameterized_workload \
    --workload-spec "$REPO_ROOT/experiments/configs/m15_f2c_parameterized_workload_dev.json" \
    --query-template-spec "$REPO_ROOT/experiments/configs/m15_f2c_parameterized_financial_risk_v2.json" \
    --backend-template-root "$REPO_ROOT/experiments/templates/m15_f2c_financial_risk" \
    --output "$SEMANTIC_BASE_BUNDLE" \
    | tee "$RUN_ROOT/direct_family_base_generation.json"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_direct_semantic_workload \
    --base-bundle-root "$SEMANTIC_BASE_BUNDLE" \
    --catalog "$SEMANTIC_CATALOG" \
    --mapping "$PREDICATE_MAPPING" \
    --policy "$REPO_ROOT/experiments/configs/m15_f2c10_direct_semantic_workload_dev.json" \
    --output "$DIRECT_SEMANTIC_WORKLOAD" \
    | tee "$RUN_ROOT/direct_semantic_workload_generation.json"
  WORKLOAD_ARGS=(
    --direct-semantic-workload "$DIRECT_SEMANTIC_WORKLOAD"
    --semantic-base-bundle "$SEMANTIC_BASE_BUNDLE"
    --semantic-catalog "$SEMANTIC_CATALOG"
    --predicate-mapping "$PREDICATE_MAPPING"
  )
  if [[ "$WORKLOAD_MODE" == direct_family_pilot || "$WORKLOAD_MODE" == paired_physical_comparison ]]; then
    DIRECT_FAMILY_PILOT_PROTOCOL="$RUN_ROOT/direct_family_pilot_protocol.json"
    DIRECT_FAMILY_PREDICTOR_POLICY="$RUN_ROOT/direct_family_predictor_policy.json"
    cp -- "$REPO_ROOT/experiments/configs/m15_f2c10d_family_memory_pilot_dev.json" \
      "$DIRECT_FAMILY_PILOT_PROTOCOL"
    cp -- "$REPO_ROOT/experiments/configs/m15_f2c10_family_memory_predictor_dev.json" \
      "$DIRECT_FAMILY_PREDICTOR_POLICY"
    WORKLOAD_ARGS+=(
      --direct-family-pilot-protocol "$DIRECT_FAMILY_PILOT_PROTOCOL"
      --direct-family-predictor-policy "$DIRECT_FAMILY_PREDICTOR_POLICY"
    )
  fi
  if [[ "$WORKLOAD_MODE" == current_query_profile_baseline || "$WORKLOAD_MODE" == paired_physical_comparison ]]; then
    CURRENT_QUERY_PROFILE_PROTOCOL="$RUN_ROOT/current_query_profile_protocol.json"
    cp -- "$REPO_ROOT/experiments/configs/m15_f2c12_current_query_profile_baseline_dev.json" \
      "$CURRENT_QUERY_PROFILE_PROTOCOL"
    WORKLOAD_ARGS+=(
      --current-query-profile-protocol "$CURRENT_QUERY_PROFILE_PROTOCOL"
    )
  fi
  if [[ "$WORKLOAD_MODE" == paired_physical_comparison ]]; then
    PAIRED_PHYSICAL_PROTOCOL="$RUN_ROOT/paired_physical_protocol.json"
    cp -- "$REPO_ROOT/experiments/configs/m15_f2c13_paired_physical_comparison_dev.json" \
      "$PAIRED_PHYSICAL_PROTOCOL"
    WORKLOAD_ARGS+=(
      --paired-physical-protocol "$PAIRED_PHYSICAL_PROTOCOL"
    )
  fi
fi
if [[ "$WORKLOAD_MODE" == resolution_execution_bridge || "$WORKLOAD_MODE" == selected_interpretation_session ]]; then
  RESOLUTION_RUN="$RUN_ROOT/resolution_run.json"
  RESOLUTION_BRIDGE_SPEC="$RUN_ROOT/resolution_bridge_spec.json"
  cp -- "$REPO_ROOT/experiments/configs/m15_e4_resolution_execution_bridge_dev.json" \
    "$RESOLUTION_BRIDGE_SPEC"
  PYTHONPATH="$REPO_ROOT/src" \
  "$PYTHON_BIN" -m xgap.experiments.m15_semantic_intake \
    --question '查找过去一个月与 Alice 有密切资金往来的高风险公司。' \
    --intake "$REPO_ROOT/experiments/configs/m15_e3_financial_risk_intake_dev.json" \
    --catalog "$REPO_ROOT/experiments/specs/m15_e3_financial_risk_catalog_dev.json" \
    --ontology "$REPO_ROOT/experiments/specs/m15_e3_financial_risk_ontology_dev.json" \
    --selection person-identity=person:alice-smith \
    > "$RESOLUTION_RUN"
  WORKLOAD_ARGS=(
    --resolution-run "$RESOLUTION_RUN"
    --resolution-bridge-spec "$RESOLUTION_BRIDGE_SPEC"
  )
  if [[ "$WORKLOAD_MODE" == selected_interpretation_session ]]; then
    if [[ "$XGAP_M15_SELECTED_TRAINING_MEMORY" != /* ]]; then
      echo "XGAP_M15_SELECTED_TRAINING_MEMORY must be absolute." >&2
      exit 2
    fi
    if [[ -L "$XGAP_M15_SELECTED_TRAINING_MEMORY" || ! -f "$XGAP_M15_SELECTED_TRAINING_MEMORY" ]]; then
      echo "XGAP_M15_SELECTED_TRAINING_MEMORY must be a regular non-symbolic-link file." >&2
      exit 2
    fi
    SELECTED_INPUT_ROOT="$RUN_ROOT/selected-session-inputs"
    mkdir -p "$SELECTED_INPUT_ROOT"
    SELECTED_TRAINING_MEMORY="$SELECTED_INPUT_ROOT/training_memory_view.json"
    SELECTED_PREDICTOR_POLICY="$SELECTED_INPUT_ROOT/predictor_policy.json"
    SELECTED_INTERPRETATION_POLICY="$SELECTED_INPUT_ROOT/interpretation_policy.json"
    SELECTED_ONTOLOGY="$SELECTED_INPUT_ROOT/ontology.json"
    SELECTED_RELAXATION_POLICY="$SELECTED_INPUT_ROOT/relaxation_policy.json"
    SELECTED_TRANSPORT_POLICY="$SELECTED_INPUT_ROOT/transport_policy.json"
    SELECTED_LIVE_POLICY="$SELECTED_INPUT_ROOT/live_policy.json"
    cp -- "$XGAP_M15_SELECTED_TRAINING_MEMORY" "$SELECTED_TRAINING_MEMORY"
    cp -- "$REPO_ROOT/experiments/configs/m15_f2c10_family_memory_predictor_dev.json" \
      "$SELECTED_PREDICTOR_POLICY"
    cp -- "$REPO_ROOT/experiments/configs/m15_e5_hierarchical_interpretation_policy_dev.json" \
      "$SELECTED_INTERPRETATION_POLICY"
    cp -- "$REPO_ROOT/experiments/specs/m15_e3_financial_risk_ontology_dev.json" \
      "$SELECTED_ONTOLOGY"
    cp -- "$REPO_ROOT/experiments/configs/m15_e5b_anchored_predicate_relaxation_dev.json" \
      "$SELECTED_RELAXATION_POLICY"
    cp -- "$REPO_ROOT/experiments/configs/m15_e5c_clarification_transport_dev.json" \
      "$SELECTED_TRANSPORT_POLICY"
    cp -- "$REPO_ROOT/experiments/configs/m15_e5d_live_selected_session_dev.json" \
      "$SELECTED_LIVE_POLICY"
    WORKLOAD_ARGS+=(
      --selected-session-training-memory "$SELECTED_TRAINING_MEMORY"
      --selected-session-expected-memory-sha256 "$XGAP_M15_SELECTED_MEMORY_SHA256"
      --selected-session-predictor-policy "$SELECTED_PREDICTOR_POLICY"
      --selected-session-interpretation-policy "$SELECTED_INTERPRETATION_POLICY"
      --selected-session-ontology "$SELECTED_ONTOLOGY"
      --selected-session-relaxation-policy "$SELECTED_RELAXATION_POLICY"
      --selected-session-transport-policy "$SELECTED_TRANSPORT_POLICY"
      --selected-session-live-policy "$SELECTED_LIVE_POLICY"
      --selected-session-id "$XGAP_M15_SELECTED_SESSION_ID"
      --selected-session-structural-candidate-id "$XGAP_M15_SELECTED_STRUCTURAL_CANDIDATE"
      --selected-session-predicate-candidate-id "$XGAP_M15_SELECTED_PREDICATE_CANDIDATE"
      --selected-session-authority-source-id "$XGAP_M15_SELECTED_AUTHORITY_SOURCE_ID"
    )
  fi
fi

QUERY_BOUND_ARGS=()
if [[ "$WORKLOAD_MODE" == scaled_query_bound_session ]]; then
  QUERY_BOUND_ARGS=(
    --query-bound-registry "$REPO_ROOT/$QUERY_BOUND_REGISTRY"
    --query-bound-session-id "$XGAP_M15_QUERY_BOUND_SESSION_ID"
    --expected-registry-spec-sha256 "$XGAP_M15_QUERY_BOUND_REGISTRY_SPEC_SHA256"
    --expected-query-bound-schedule-sha256 "$XGAP_M15_QUERY_BOUND_SCHEDULE_SHA256"
  )
fi

CAMPAIGN_ARGS=()
if [[ "$WORKLOAD_MODE" == scaled_campaign_session ]]; then
  CAMPAIGN_ARGS=(
    --campaign-config "$REPO_ROOT/$CAMPAIGN_CONFIG"
    --campaign-session-id "$XGAP_M15_CAMPAIGN_SESSION_ID"
    --expected-campaign-spec-sha256 "$XGAP_M15_CAMPAIGN_SPEC_SHA256"
    --expected-schedule-sha256 "$XGAP_M15_CAMPAIGN_SCHEDULE_SHA256"
  )
fi

XGAP_RUN_M15_NATIVE_SERVICES=1 \
PYTHONPATH="$REPO_ROOT/src" \
"$PYTHON_BIN" -m xgap.experiments.m15_native_services \
  --runtime-root "$RUNTIME_ROOT" \
  --staging-manifest "$STAGING_MANIFEST" \
  --output-root "$RUN_ROOT" \
  --run-id native-service-run \
  --filesystem-type "$FILESYSTEM_TYPE" \
  --allocation-id "$SLURM_JOB_ID" \
  --java-command "$JAVA_BIN" \
  --repo-root "$REPO_ROOT" \
  --workload-mode "$WORKLOAD_MODE" \
  "${WORKLOAD_ARGS[@]}" \
  "${CAMPAIGN_ARGS[@]}" \
  "${QUERY_BOUND_ARGS[@]}" \
  | tee "$RUN_ROOT/native_service_result.json"

echo "M15 native services workload '$WORKLOAD_MODE' passed."
