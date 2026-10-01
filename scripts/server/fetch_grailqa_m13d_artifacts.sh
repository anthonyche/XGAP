#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python}"
SOURCE_MANIFEST="$REPO_ROOT/experiments/sources/grailqa_m13d_sources.json"
SPEC="$REPO_ROOT/experiments/specs/grailqa_semantic_pilot_v1.json"
if [ -n "${XGAP_ARTIFACT_CACHE:-}" ]; then
  CACHE_ROOT="$XGAP_ARTIFACT_CACHE"
elif [ -d /data ]; then
  CACHE_ROOT="${XGAP_DATA_LINK:-$HOME/xgap-data}/grailqa-m13d-v1"
else
  CACHE_ROOT="$HOME/.cache/xgap/grailqa-m13d-v1"
fi
DOWNLOAD_ROOT="$CACHE_ROOT/downloads"
BUILD_ROOT="$CACHE_ROOT/build-$$"
DATASET_ARCHIVE="$DOWNLOAD_ROOT/GrailQA_v1.0.zip"
DATASET_ROOT="$CACHE_ROOT/GrailQA_v1.0"
ONTOLOGY_ROOT="$DOWNLOAD_ROOT/ontology"
ENTITY_NAMES="$DOWNLOAD_ROOT/FB15k_mid2name.txt"
CATALOG_TARGET="$REPO_ROOT/datasets/grailqa_inference_catalog_v1"
PILOT_TARGET="$REPO_ROOT/datasets/grailqa_pilot_v1"
FORCE=0
VERIFY_ONLY=0

usage() {
  echo "Usage: $0 [--force|--verify-only]" >&2
}

case "${1:-}" in
  "") ;;
  --force) FORCE=1 ;;
  --verify-only) VERIFY_ONLY=1 ;;
  *) usage; exit 2 ;;
esac

for command in "$PYTHON" curl unzip; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command is unavailable: $command" >&2
    exit 1
  fi
done

if [ ! -f "$SOURCE_MANIFEST" ] || [ ! -f "$SPEC" ]; then
  echo "M13-D source manifest or frozen spec is missing. Run git pull first." >&2
  exit 1
fi

json_get() {
  "$PYTHON" -c '
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
for key in sys.argv[2:]:
    value = value[key]
print(value)
' "$SOURCE_MANIFEST" "$@"
}

sha256_file() {
  "$PYTHON" -c '
import hashlib, pathlib, sys
digest = hashlib.sha256()
with pathlib.Path(sys.argv[1]).open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
' "$1"
}

verify_hash() {
  local path="$1"
  local expected="$2"
  if [ ! -f "$path" ]; then
    return 1
  fi
  local actual
  actual="$(sha256_file "$path")"
  if [ "$actual" != "$expected" ]; then
    echo "SHA-256 mismatch: $path" >&2
    echo "expected=$expected" >&2
    echo "actual=$actual" >&2
    return 1
  fi
}

download_verified() {
  local url="$1"
  local destination="$2"
  local expected="$3"
  if verify_hash "$destination" "$expected" 2>/dev/null; then
    echo "Using verified cache: $destination"
    return
  fi
  mkdir -p "$(dirname "$destination")"
  local temporary="${destination}.part"
  rm -f "$temporary"
  echo "Downloading: $url"
  curl --http1.1 -fL --retry 5 --retry-delay 2 \
    --connect-timeout 30 --max-time 1800 \
    "$url" -o "$temporary"
  verify_hash "$temporary" "$expected"
  mv "$temporary" "$destination"
}

verify_installed() {
  PYTHONPATH=src "$PYTHON" -c '
from pathlib import Path
import sys
from xgap.experiments.grailqa_semantic_pilot import (
    GrailQASemanticPilotSpec,
    validate_frozen_artifacts,
)
repo = Path(sys.argv[1]).resolve()
spec = GrailQASemanticPilotSpec.load(sys.argv[2])
validate_frozen_artifacts(spec, repo)
print("catalog_hash=" + str(spec.data["catalog_hash"]))
print("pilot_bundle_hash=" + str(spec.data["pilot_bundle_hash"]))
print("question_count=" + str(len(spec.question_ids)))
' "$REPO_ROOT" "$SPEC"
}

if [ "$FORCE" -eq 0 ] && verify_installed >/dev/null 2>&1; then
  echo "M13-D GrailQA artifacts are already installed and match the frozen spec."
  verify_installed
  exit 0
fi

if [ "$VERIFY_ONLY" -eq 1 ]; then
  echo "M13-D GrailQA artifacts are missing or do not match the frozen spec." >&2
  exit 1
fi

if [ -z "${XGAP_ARTIFACT_CACHE:-}" ] && [ -d /data ]; then
  bash "$SCRIPT_DIR/prepare_xgap_data_storage.sh"
fi

echo "Artifact cache: $CACHE_ROOT"
mkdir -p "$DOWNLOAD_ROOT" "$ONTOLOGY_ROOT"
rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT"
trap 'rm -rf "$BUILD_ROOT"' EXIT

DATASET_URL="$(json_get dataset archive_url)"
DATASET_SHA="$(json_get dataset archive_sha256)"
ENTITY_URL="$(json_get entity_names url)"
ENTITY_SHA="$(json_get entity_names sha256)"
ONTOLOGY_URL="$(json_get ontology base_url)"
ONTOLOGY_REVISION="$(json_get ontology revision)"

download_verified "$DATASET_URL" "$DATASET_ARCHIVE" "$DATASET_SHA"
download_verified "$ENTITY_URL" "$ENTITY_NAMES" "$ENTITY_SHA"

for name in domain_dict domain_info fb_roles fb_types reverse_properties; do
  download_verified \
    "$ONTOLOGY_URL/$name" \
    "$ONTOLOGY_ROOT/$name" \
    "$(json_get ontology files "$name")"
done

if [ ! -d "$DATASET_ROOT" ] || [ "$FORCE" -eq 1 ]; then
  rm -rf "$DATASET_ROOT"
  unzip -oq "$DATASET_ARCHIVE" -d "$CACHE_ROOT"
fi
for name in grailqa_v1.0_train.json grailqa_v1.0_dev.json grailqa_v1.0_test_public.json; do
  verify_hash "$DATASET_ROOT/$name" "$(json_get dataset files "$name")"
done

echo "Building deterministic GrailQA v2 audit (temporary prerequisite)..."
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_v2 \
  --dataset-root "$DATASET_ROOT" \
  --ontology-root "$ONTOLOGY_ROOT" \
  --ontology-revision "$ONTOLOGY_REVISION" \
  --output "$BUILD_ROOT/grailqa_audit_v2"

echo "Building frozen 150-query GrailQA pilot..."
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_pilot \
  --dataset-root "$DATASET_ROOT" \
  --ontology-root "$ONTOLOGY_ROOT" \
  --audit-root "$BUILD_ROOT/grailqa_audit_v2" \
  --output "$BUILD_ROOT/grailqa_pilot_v1"

echo "Building query-independent GrailQA inference catalog..."
PYTHONPATH=src "$PYTHON" -m xgap.experiments.grailqa_catalog build \
  --entity-names "$ENTITY_NAMES" \
  --ontology-root "$ONTOLOGY_ROOT" \
  --normalized-ontology "$BUILD_ROOT/grailqa_pilot_v1/ontology.yaml" \
  --output "$BUILD_ROOT/grailqa_inference_catalog_v1"

PYTHONPATH=src "$PYTHON" -c '
import hashlib, json, pathlib, sys
from xgap.experiments.grailqa_catalog import GrailQAInferenceCatalog
spec = json.load(open(sys.argv[1], encoding="utf-8"))
pilot = pathlib.Path(sys.argv[2])
catalog = GrailQAInferenceCatalog.load(sys.argv[3])
if catalog.catalog_hash != spec["catalog_hash"]:
    raise SystemExit("Built catalog does not match frozen catalog hash.")
for name, expected in spec["pilot_artifact_hashes"].items():
    digest = hashlib.sha256((pilot / name).read_bytes()).hexdigest()
    if digest != expected:
        raise SystemExit(f"Built pilot artifact hash mismatch: {name}")
print("Built artifacts match the frozen experiment spec.")
' "$SPEC" "$BUILD_ROOT/grailqa_pilot_v1" "$BUILD_ROOT/grailqa_inference_catalog_v1"

CATALOG_BACKUP="${CATALOG_TARGET}.pre-m13d-$$"
PILOT_BACKUP="${PILOT_TARGET}.pre-m13d-$$"
rm -rf "$CATALOG_BACKUP" "$PILOT_BACKUP"
[ ! -e "$CATALOG_TARGET" ] || mv "$CATALOG_TARGET" "$CATALOG_BACKUP"
[ ! -e "$PILOT_TARGET" ] || mv "$PILOT_TARGET" "$PILOT_BACKUP"

restore_backups() {
  rm -rf "$CATALOG_TARGET" "$PILOT_TARGET"
  [ ! -e "$CATALOG_BACKUP" ] || mv "$CATALOG_BACKUP" "$CATALOG_TARGET"
  [ ! -e "$PILOT_BACKUP" ] || mv "$PILOT_BACKUP" "$PILOT_TARGET"
}

if ! mv "$BUILD_ROOT/grailqa_inference_catalog_v1" "$CATALOG_TARGET" || \
   ! mv "$BUILD_ROOT/grailqa_pilot_v1" "$PILOT_TARGET"; then
  restore_backups
  echo "Could not install built M13-D artifacts." >&2
  exit 1
fi

if ! verify_installed; then
  restore_backups
  echo "Installed artifacts failed final frozen-spec validation; previous files restored." >&2
  exit 1
fi

rm -rf "$CATALOG_BACKUP" "$PILOT_BACKUP"
echo "M13-D GrailQA artifacts downloaded, rebuilt, installed, and verified."
echo "Next: bash scripts/check_grailqa_semantic_pilot_ready.sh"
