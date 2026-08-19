#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RAW_DIR="${XGAP_FREEBASE_RAW_DIR:-${XGAP_FREEBASE_SOURCE_ROOT:-$HOME/xgap-data/freebase/raw}}"
PARQUET_ROOT="${XGAP_FREEBASE_PARQUET_ROOT:-$RAW_DIR/hf-archival-parquet}"
SOURCE_MANIFEST="${XGAP_FREEBASE_SOURCE_MANIFEST:-$RAW_DIR/source_manifest.json}"
FROZEN_SPEC="${XGAP_FREEBASE_PARQUET_SPEC:-$REPO_ROOT/experiments/artifacts/freebase_hf_archival_parquet_v1.json}"
SOURCE_MODE="${XGAP_FREEBASE_SOURCE_MODE:-hf_archival_parquet}"
PYTHON="${PYTHON:-python}"
SMOKE_ONLY=false

# shellcheck source=scripts/server/curl_compat.sh
source "$SCRIPT_DIR/curl_compat.sh"

if [[ "${1:-}" == "--smoke-only" ]]; then
  SMOKE_ONLY=true
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--smoke-only]" >&2
  exit 2
fi
if [[ "$SOURCE_MODE" != "hf_archival_parquet" ]]; then
  echo "This script requires XGAP_FREEBASE_SOURCE_MODE=hf_archival_parquet." >&2
  exit 2
fi
xgap_configure_curl_retry_options
command -v sha256sum >/dev/null || { echo "sha256sum is required." >&2; exit 1; }

mkdir -p "$PARQUET_ROOT"
cd "$REPO_ROOT"

download_shard() {
  local relative_path="$1"
  local expected_size="$2"
  local expected_sha="$3"
  local url="$4"
  local target="$PARQUET_ROOT/$relative_path"
  local partial="$target.part"
  local actual_size actual_sha

  mkdir -p "$(dirname "$target")"
  if [[ -f "$target" ]]; then
    actual_size="$(wc -c < "$target" | tr -d ' ')"
    actual_sha="$(sha256sum "$target" | awk '{print $1}')"
    if [[ "$actual_size" == "$expected_size" && "$actual_sha" == "$expected_sha" ]]; then
      echo "Using verified shard: $relative_path"
      return
    fi
    echo "Existing final shard does not match the frozen inventory: $target" >&2
    exit 1
  fi
  if [[ -f "$partial" && "$(wc -c < "$partial" | tr -d ' ')" -gt "$expected_size" ]]; then
    rm -f "$partial"
  fi

  echo "Downloading immutable shard: $relative_path"
  xgap_curl_with_retries --fail --location --continue-at - \
    --output "$partial" "$url"
  actual_size="$(wc -c < "$partial" | tr -d ' ')"
  actual_sha="$(sha256sum "$partial" | awk '{print $1}')"
  if [[ "$actual_size" != "$expected_size" || "$actual_sha" != "$expected_sha" ]]; then
    echo "Resumed shard failed integrity; retrying it once from byte zero: $relative_path" >&2
    rm -f "$partial"
    xgap_curl_with_retries --fail --location \
      --output "$partial" "$url"
    actual_size="$(wc -c < "$partial" | tr -d ' ')"
    actual_sha="$(sha256sum "$partial" | awk '{print $1}')"
  fi
  if [[ "$actual_size" != "$expected_size" || "$actual_sha" != "$expected_sha" ]]; then
    echo "Downloaded shard failed frozen size/SHA-256 validation: $relative_path" >&2
    exit 1
  fi
  mv "$partial" "$target"
}

inventory_output="$(PYTHONPATH=src "$PYTHON" -m xgap.experiments.freebase_sources inventory \
  --frozen-spec "$FROZEN_SPEC")"
inventory_count="$(printf '%s\n' "$inventory_output" | wc -l | tr -d ' ')"
if [[ "$inventory_count" != "964" ]]; then
  echo "Frozen inventory must contain exactly 964 shards; found $inventory_count." >&2
  exit 1
fi

downloaded=0
while IFS=$'\t' read -r relative_path expected_size expected_sha url; do
  download_shard "$relative_path" "$expected_size" "$expected_sha" "$url"
  downloaded=$((downloaded + 1))
  if [[ "$SMOKE_ONLY" == true ]]; then
    break
  fi
done <<< "$inventory_output"

if [[ "$SMOKE_ONLY" == true ]]; then
  echo "Downloaded and verified the frozen smoke shard under: $PARQUET_ROOT"
  exit 0
fi

if [[ "$downloaded" != "964" ]]; then
  echo "Download loop did not process the complete 964-shard inventory." >&2
  exit 1
fi

export XGAP_GIT_COMMIT="$(git rev-parse HEAD)"
PYTHONPATH=src "$PYTHON" -m xgap.experiments.freebase_sources write-manifest \
  --parquet-root "$PARQUET_ROOT" \
  --frozen-spec "$FROZEN_SPEC" \
  --output "$SOURCE_MANIFEST"
echo "Downloaded $downloaded frozen Freebase Parquet shards."
echo "parquet_root=$PARQUET_ROOT"
echo "source_manifest=$SOURCE_MANIFEST"
