"""Run the actual offline shell helper with a process-boundary test double."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/server/check_grailqa_request_tokens.sh"
REVISION = "b" * 40
REQUIRED = (
    "XGAP_REPO_ROOT", "XGAP_PYTHON", "XGAP_GRAILQA_TOKEN_SPEC",
    "XGAP_GRAILQA_TOKENIZER_SNAPSHOT", "XGAP_GRAILQA_TOKENIZER_REVISION",
    "XGAP_GRAILQA_TOKEN_OUTPUT",
)


def _executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def shell(tmp_path: Path) -> SimpleNamespace:
    repo = tmp_path / "repo with spaces"
    (repo / "src/xgap").mkdir(parents=True)
    spec = tmp_path / "explicit spec.json"
    spec.write_text("{}", encoding="utf-8")
    snapshot = tmp_path / "cached model" / "snapshots" / REVISION
    snapshot.mkdir(parents=True)
    bins = tmp_path / "fake bin"
    bins.mkdir()
    interpreter = bins / "explicit python"
    _executable(interpreter, f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
record = {
    "args": sys.argv[1:], "cwd": str(Path.cwd()),
    "env": {key: value for key, value in os.environ.items()
            if key.startswith(("XGAP_", "HF_", "TRANSFORMERS_")) or key == "PYTHONPATH"},
}
with open(os.environ["FAKE_CALL_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\\n")
print("offline-interpreter-stdout")
print("offline-interpreter-stderr", file=sys.stderr)
sys.exit(int(os.environ.get("FAKE_EXIT_STATUS", "0")))
''')
    # A prohibited command would leave evidence even if the helper swallowed
    # its failure. The actual helper uses none of these commands.
    for name in ("sbatch", "srun", "curl", "wget", "pip", "uv", "module", "python", "python3", "vllm"):
        _executable(bins / name, '#!/bin/sh\nprintf "%s\\n" "$0" >> "$FAKE_FORBIDDEN_LOG"\nexit 99\n')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("XGAP_", "SLURM_", "FAKE_", "HF_", "TRANSFORMERS_"))}
    env.update({
        "PATH": str(bins) + os.pathsep + env.get("PATH", ""),
        "XGAP_REPO_ROOT": str(repo), "XGAP_PYTHON": str(interpreter),
        "XGAP_GRAILQA_TOKEN_SPEC": str(spec),
        "XGAP_GRAILQA_TOKENIZER_SNAPSHOT": str(snapshot),
        "XGAP_GRAILQA_TOKENIZER_REVISION": REVISION,
        "XGAP_GRAILQA_TOKEN_OUTPUT": str(tmp_path / "new reports" / "tokens.json"),
        "FAKE_CALL_LOG": str(tmp_path / "calls.jsonl"),
        "FAKE_FORBIDDEN_LOG": str(tmp_path / "forbidden.jsonl"),
    })
    return SimpleNamespace(tmp=tmp_path, repo=repo, spec=spec, snapshot=snapshot,
                           interpreter=interpreter, env=env)


def _run(shell, args=()) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HELPER), *args], cwd=shell.tmp, env=shell.env,
                          text=True, capture_output=True, timeout=10)


def _calls(shell) -> list[dict]:
    path = Path(shell.env["FAKE_CALL_LOG"])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _assert_no_calls(shell) -> None:
    assert _calls(shell) == []
    assert not Path(shell.env["FAKE_FORBIDDEN_LOG"]).exists()


def test_exactly_one_explicit_offline_cli_invocation(shell) -> None:
    result = _run(shell)
    assert result.returncode == 0, result.stderr
    records = _calls(shell)
    assert len(records) == 1
    record = records[0]
    assert record["cwd"] == str(shell.repo)
    assert record["args"] == [
        "-m", "xgap.experiments.grailqa_request_tokens",
        "--spec", str(shell.spec), "--repo-root", str(shell.repo),
        "--tokenizer-snapshot", str(shell.snapshot), "--tokenizer-revision", REVISION,
        "--output", shell.env["XGAP_GRAILQA_TOKEN_OUTPUT"],
    ]
    assert record["env"]["PYTHONPATH"] == str(shell.repo / "src")
    for key in ("HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "TRANSFORMERS_OFFLINE"):
        assert record["env"][key] == "1"
    assert "XGAP_LLM_API_KEY" not in record["env"]
    assert not Path(shell.env["FAKE_FORBIDDEN_LOG"]).exists()
    # Only the CLI owns creation of output/parents; the test double did not.
    assert not Path(shell.env["XGAP_GRAILQA_TOKEN_OUTPUT"]).parent.exists()


def test_relative_inputs_are_anchored_before_repository_cd(shell) -> None:
    for key in ("XGAP_REPO_ROOT", "XGAP_PYTHON", "XGAP_GRAILQA_TOKEN_SPEC",
                "XGAP_GRAILQA_TOKENIZER_SNAPSHOT", "XGAP_GRAILQA_TOKEN_OUTPUT"):
        shell.env[key] = os.path.relpath(shell.env[key], shell.tmp)
    result = _run(shell)
    assert result.returncode == 0, result.stderr
    record = _calls(shell)[0]
    for option, expected in (("--spec", shell.spec), ("--repo-root", shell.repo),
                             ("--tokenizer-snapshot", shell.snapshot),
                             ("--output", shell.tmp / "new reports/tokens.json")):
        assert record["args"][record["args"].index(option) + 1] == str(expected)


def test_catalog_and_reachability_overrides_are_preserved_verbatim(shell) -> None:
    overrides = {
        "XGAP_GRAILQA_PREFLIGHT_ARTIFACT_PROFILE": "query_local_e3b4",
        "XGAP_GRAILQA_CATALOG_V2": "relative catalog",
        "XGAP_GRAILQA_REACHABILITY_V2": str(shell.tmp / "external reachability"),
        "XGAP_GRAILQA_REACHABILITY_SUMMARY": "relative summary.json",
        "XGAP_GRAILQA_REACHABILITY_ROWS": "relative rows.jsonl",
    }
    shell.env.update(overrides)
    assert _run(shell).returncode == 0
    assert {key: _calls(shell)[0]["env"][key] for key in overrides} == overrides


@pytest.mark.parametrize("status", [0, 1, 2, 17, 143])
def test_preserves_cli_status_and_streams_without_retry(shell, status) -> None:
    shell.env["FAKE_EXIT_STATUS"] = str(status)
    result = _run(shell)
    assert result.returncode == status
    assert result.stdout == "offline-interpreter-stdout\n"
    assert result.stderr == "offline-interpreter-stderr\n"
    assert len(_calls(shell)) == 1


@pytest.mark.parametrize("key", REQUIRED)
@pytest.mark.parametrize("empty", [False, True])
def test_missing_or_empty_input_never_invokes_interpreter(shell, key, empty) -> None:
    if empty:
        shell.env[key] = ""
    else:
        del shell.env[key]
    assert _run(shell).returncode == 2
    _assert_no_calls(shell)


@pytest.mark.parametrize("kind", ["regular", "directory", "symlink", "broken_symlink", "ancestor_symlink"])
def test_unsafe_output_is_refused_without_interpreter_or_mutation(shell, kind) -> None:
    output = shell.tmp / "output.json"
    kept = shell.tmp / "keep.txt"
    kept.write_text("preserve-me", encoding="utf-8")
    if kind == "regular":
        output.write_text("old-report", encoding="utf-8")
    elif kind == "directory":
        output.mkdir()
    elif kind == "symlink":
        output.symlink_to(kept)
    elif kind == "broken_symlink":
        output.symlink_to(shell.tmp / "missing")
    else:
        directory = shell.tmp / "real-dir"
        directory.mkdir()
        link = shell.tmp / "linked-dir"
        link.symlink_to(directory, target_is_directory=True)
        output = link / "output.json"
    shell.env["XGAP_GRAILQA_TOKEN_OUTPUT"] = str(output)
    assert _run(shell).returncode == 2
    _assert_no_calls(shell)
    assert kept.read_text() == "preserve-me"
    if kind == "regular":
        assert output.read_text() == "old-report"
    elif kind in ("symlink", "broken_symlink"):
        assert output.is_symlink()
    elif kind == "ancestor_symlink":
        assert not output.exists()


@pytest.mark.parametrize("invalid", ["repository", "spec", "interpreter", "interpreter_not_executable"])
def test_unavailable_required_path_fails_before_cli(shell, invalid) -> None:
    if invalid == "repository":
        shell.env["XGAP_REPO_ROOT"] = str(shell.tmp / "missing-repo")
    elif invalid == "spec":
        shell.env["XGAP_GRAILQA_TOKEN_SPEC"] = str(shell.tmp / "missing-spec")
    elif invalid == "interpreter":
        shell.env["XGAP_PYTHON"] = str(shell.tmp / "missing-python")
    else:
        shell.interpreter.chmod(0o644)
    assert _run(shell).returncode == 2
    _assert_no_calls(shell)


def test_explicit_unavailable_snapshot_reaches_cli_without_guessing(shell) -> None:
    # The CLI, not a cache-search fallback, emits the incomplete inventory.
    missing = shell.tmp / "nonexistent snapshot"
    shell.env["XGAP_GRAILQA_TOKENIZER_SNAPSHOT"] = str(missing)
    shell.env["FAKE_EXIT_STATUS"] = "1"
    result = _run(shell)
    assert result.returncode == 1
    args = _calls(shell)[0]["args"]
    assert args[args.index("--tokenizer-snapshot") + 1] == str(missing)
    assert args[args.index("--tokenizer-revision") + 1] == REVISION
    assert not missing.exists()


def test_positional_arguments_do_not_activate_a_different_command(shell) -> None:
    assert _run(shell, ["--run"]).returncode == 2
    _assert_no_calls(shell)
