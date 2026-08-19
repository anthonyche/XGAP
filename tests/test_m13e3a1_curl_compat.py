from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER = REPO_ROOT / "scripts/server/curl_compat.sh"


@pytest.mark.parametrize("supports_retry_all_errors", (True, False))
def test_curl_retry_options_are_capability_aware(
    tmp_path: Path, supports_retry_all_errors: bool
) -> None:
    fake_curl = _write_fake_curl(tmp_path, supports_retry_all_errors)
    log = tmp_path / "curl-arguments.txt"
    command = r'''
source "$1"
export XGAP_CURL_BIN="$2"
export XGAP_FAKE_CURL_LOG="$3"
xgap_configure_curl_retry_options
printf 'OPTION=%s\n' "${XGAP_CURL_RETRY_OPTIONS[@]}"
xgap_curl_with_retries --fail --location https://example.invalid/shard.parquet
'''

    result = subprocess.run(
        ["bash", "-c", command, "xgap-curl-test", str(HELPER), str(fake_curl), str(log)],
        check=True,
        capture_output=True,
        text=True,
    )

    options = [line.removeprefix("OPTION=") for line in result.stdout.splitlines()]
    arguments = log.read_text(encoding="utf-8").splitlines()
    assert options[:4] == ["--retry", "5", "--retry-delay", "2"]
    assert arguments[:4] == ["--retry", "5", "--retry-delay", "2"]
    assert ("--retry-all-errors" in options) is supports_retry_all_errors
    assert ("--retry-all-errors" in arguments) is supports_retry_all_errors
    assert "--fail" in arguments
    assert "--location" in arguments


def test_archival_scripts_use_shared_curl_compatibility_helper() -> None:
    download = (
        REPO_ROOT / "scripts/server/download_freebase_archival_parquet.sh"
    ).read_text(encoding="utf-8")
    smoke = (
        REPO_ROOT / "scripts/server/smoke_freebase_archival_parquet.sh"
    ).read_text(encoding="utf-8")

    assert 'source "$SCRIPT_DIR/curl_compat.sh"' in download
    assert download.count("xgap_curl_with_retries") == 2
    assert "--retry-all-errors" not in download
    assert "download_freebase_archival_parquet.sh --smoke-only" in smoke


def _write_fake_curl(root: Path, supports_retry_all_errors: bool) -> Path:
    help_line = (
        "  --retry-all-errors  Retry all errors" if supports_retry_all_errors else ""
    )
    path = root / "curl"
    path.write_text(
        f"""#!/usr/bin/env bash
if [[ "${{1:-}}" == "--help" && "${{2:-}}" == "all" ]]; then
  printf '%s\\n' '  --retry <num>  Retry request' '{help_line}'
  exit 0
fi
printf '%s\\n' "$@" > "$XGAP_FAKE_CURL_LOG"
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path
