#!/usr/bin/env bash
# Explicit, offline token-fit inventory only; this does not authorize a run.
set -euo pipefail

fail() {
  printf '%s\n' "$1" >&2
  exit 2
}

if [[ $# -ne 0 ]]; then
  fail "This helper accepts explicit XGAP_* environment inputs, not arguments."
fi

for token_variable in \
  XGAP_REPO_ROOT \
  XGAP_PYTHON \
  XGAP_GRAILQA_TOKEN_SPEC \
  XGAP_GRAILQA_TOKENIZER_SNAPSHOT \
  XGAP_GRAILQA_TOKENIZER_REVISION \
  XGAP_GRAILQA_TOKEN_OUTPUT
do
  [[ -n "${!token_variable:-}" ]] || fail "Required input is missing: $token_variable"
done

# Anchor caller-relative inputs before changing directory. Catalog/reachability
# overrides are deliberately untouched; their existing loader owns resolution.
TOKEN_ENTRY_DIRECTORY="$(pwd -P)"
anchor_input() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s/%s\n' "$TOKEN_ENTRY_DIRECTORY" "$1" ;;
  esac
}

TOKEN_REPO_ROOT="$(anchor_input "$XGAP_REPO_ROOT")"
TOKEN_PYTHON="$(anchor_input "$XGAP_PYTHON")"
TOKEN_SPEC="$(anchor_input "$XGAP_GRAILQA_TOKEN_SPEC")"
TOKEN_SNAPSHOT="$(anchor_input "$XGAP_GRAILQA_TOKENIZER_SNAPSHOT")"
TOKEN_OUTPUT="$(anchor_input "$XGAP_GRAILQA_TOKEN_OUTPUT")"

[[ -d "$TOKEN_REPO_ROOT/src/xgap" ]] || fail "Explicit XGAP repository source is unavailable."
[[ -f "$TOKEN_PYTHON" && -x "$TOKEN_PYTHON" ]] || fail "Explicit XGAP_PYTHON executable is unavailable."
[[ -f "$TOKEN_SPEC" && -r "$TOKEN_SPEC" ]] || fail "Explicit token-inventory spec is unavailable."
[[ ! -e "$TOKEN_OUTPUT" && ! -L "$TOKEN_OUTPUT" ]] || fail "Token-inventory output already exists or is a symlink."

# Refuse redirecting the new report through any symlinked output ancestor,
# including a broken link. No parent directories or report are created here.
TOKEN_OUTPUT_ANCESTOR="$TOKEN_OUTPUT"
while [[ "$TOKEN_OUTPUT_ANCESTOR" != / && -n "$TOKEN_OUTPUT_ANCESTOR" ]]; do
  [[ ! -L "$TOKEN_OUTPUT_ANCESTOR" ]] || fail "Token-inventory output has a symlinked ancestor."
  TOKEN_OUTPUT_ANCESTOR="${TOKEN_OUTPUT_ANCESTOR%/*}"
done

cd -- "$TOKEN_REPO_ROOT"
export XGAP_REPO_ROOT="$TOKEN_REPO_ROOT"
export PYTHONPATH="$TOKEN_REPO_ROOT/src"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1

# One CLI invocation, no credential requirement, service startup, download, or
# scheduler submission. exec preserves its status without retries or masking.
# The CLI validates the supplied snapshot/revision and writes exclusively.
exec "$TOKEN_PYTHON" -m xgap.experiments.grailqa_request_tokens \
  --spec "$TOKEN_SPEC" \
  --repo-root "$TOKEN_REPO_ROOT" \
  --tokenizer-snapshot "$TOKEN_SNAPSHOT" \
  --tokenizer-revision "$XGAP_GRAILQA_TOKENIZER_REVISION" \
  --output "$TOKEN_OUTPUT"
