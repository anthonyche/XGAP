#!/usr/bin/env bash

XGAP_CURL_RETRY_OPTIONS=()

# Populate the retry options supported by the curl installed on this host.
xgap_configure_curl_retry_options() {
  local curl_bin="${XGAP_CURL_BIN:-curl}"
  local help_output

  if ! command -v "$curl_bin" >/dev/null 2>&1; then
    echo "curl is required: $curl_bin" >&2
    return 1
  fi
  XGAP_CURL_BIN="$curl_bin"
  XGAP_CURL_RETRY_OPTIONS=(--retry 5 --retry-delay 2)
  help_output="$("$curl_bin" --help all 2>/dev/null || true)"
  if [[ "$help_output" == *"--retry-all-errors"* ]]; then
    XGAP_CURL_RETRY_OPTIONS+=(--retry-all-errors)
  fi
}

xgap_curl_with_retries() {
  if [[ ${#XGAP_CURL_RETRY_OPTIONS[@]} -eq 0 ]]; then
    echo "xgap_configure_curl_retry_options must be called first." >&2
    return 2
  fi
  "$XGAP_CURL_BIN" "${XGAP_CURL_RETRY_OPTIONS[@]}" "$@"
}
