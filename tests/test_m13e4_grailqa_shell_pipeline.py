"""Execute the real shell handoffs without Slurm, GPUs, or scientific outcomes.

The fake commands test orchestration only. Existing Python contract tests cover
the request, inference, and audit bodies replaced at the process boundary here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40
SUBMIT = "scripts/server/submit_grailqa_semantic_paper_pipeline.sh"
RUN = "scripts/slurm/run_grailqa_semantic_paper.sbatch"
FINALIZE = "scripts/slurm/finalize_grailqa_semantic_paper.sbatch"


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def pipeline(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo with spaces"
    for relative in (SUBMIT, RUN, FINALIZE, "scripts/slurm/cwru_xgap_vllm.sbatch",
                     "scripts/cwru/common.sh"):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    (repo / "pyproject.toml").touch()
    bins = repo / "fake-bin"
    bins.mkdir()
    python_header = f"#!{sys.executable}\n"
    _executable(bins / "git", python_header + "import sys\nif 'rev-parse' in sys.argv: print('" + COMMIT + "')\n")
    _executable(bins / "module", "#!/bin/sh\nexit 0\n")
    _executable(bins / "core-python", python_header + '''import json, os, sys
if sys.argv[1:2] != ["-m"]:
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
with open(os.environ["FAKE_PYTHON_LOG"], "a") as handle:
    handle.write(json.dumps({"args": sys.argv[1:],
                            "vllm_active": os.environ.get("FAKE_VLLM_ACTIVE") == "1"}) + "\\n")
if sys.argv[2:4] == ["xgap.experiments.grailqa_semantic_paper_run", "check"]:
    if os.environ.get("FAKE_READINESS_FAILURE") == "1":
        sys.exit(2)
if sys.argv[2:4] == ["xgap.experiments.cwru_vllm", "verify-token-budget"]:
    if os.environ.get("FAKE_TOKEN_BUDGET_FAILURE") == "1":
        sys.exit(2)
print(json.dumps({"status": "success", "test_double": True}))
''')
    # Bare python is intentionally unavailable until the model environment starts.
    _executable(bins / "python", python_header + '''import os, sys
if os.environ.get("FAKE_VLLM_ACTIVE") != "1":
    print("python is unavailable before vLLM activation", file=sys.stderr)
    sys.exit(127)
os.execv(os.environ["XGAP_PYTHON"], [os.environ["XGAP_PYTHON"], *sys.argv[1:]])
''')
    _executable(bins / "sbatch", python_header + '''import json, os, sys
from pathlib import Path
finalizer = Path(sys.argv[-1]).name == "finalize_grailqa_semantic_paper.sbatch"
with open(os.environ["FAKE_SLURM_LOG"], "a") as handle:
    handle.write(json.dumps({"args": sys.argv[1:], "env": {
        key: value for key, value in os.environ.items() if key.startswith("XGAP_")
    }}) + "\\n")
if finalizer and os.environ.get("FAKE_FINALIZER_FAILURE") == "reject":
    sys.exit(1)
if finalizer and os.environ.get("FAKE_FINALIZER_FAILURE") == "malformed":
    print("invalid-reply")
else:
    print("502" if finalizer else "501")
''')
    _executable(repo / "scripts/cwru/launch_vllm_qwen3_32b.sh",
                "#!/bin/bash\nexport FAKE_VLLM_ACTIVE=1\n")
    _executable(repo / "scripts/cwru/check_vllm_ready.sh",
                '#!/bin/bash\ntest "$FAKE_VLLM_ACTIVE" = 1\n')

    controls = repo / "controls"
    request = {
        "run_id": "shell-test",
        "runner_commit": COMMIT,
        "protocol_sha256": "b" * 64,
        "author_selection_sha256": "c" * 64,
        "preexecution_admission_sha256": "d" * 64,
        "execution_request_sha256": "e" * 64,
    }
    authority = {
        "execution_authority_sha256": "f" * 64,
        "execution_request_sha256": request["execution_request_sha256"],
        "preexecution_admission_sha256": request["preexecution_admission_sha256"],
        "decision": "authorize_exact_150_query_semantic_execution",
        "full_150_execution_authorized": True,
    }
    _json(controls / "request.json", request)
    _json(controls / "authority.json", authority)
    _json(controls / "admission.json", {"preexecution_admission_sha256": "d" * 64})
    _json(controls / "selection.json", {})
    _json(controls / "custom-protocol.json", {})
    catalog = repo / "catalog"
    _json(catalog / "audit_summary.json", {})
    (catalog / "reachability.jsonl").touch()
    custom_outer = repo / "custom outer"
    _json(custom_outer / "results/shell-test/run_manifest.json", {
        **request,
        "execution_authority_sha256": authority["execution_authority_sha256"],
        "source_run_sha256": "0" * 64,
    })
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("XGAP_", "SLURM_", "FAKE_"))
    }
    env.update({
        "PATH": str(bins) + os.pathsep + env.get("PATH", ""),
        "XGAP_REPO_ROOT": str(repo),
        "XGAP_PYTHON": str(bins / "core-python"),
        "XGAP_GRAILQA_SEMANTIC_AUTHOR_SELECTION": str(controls / "selection.json"),
        "XGAP_GRAILQA_SEMANTIC_PREEXECUTION_ADMISSION": str(controls / "admission.json"),
        "XGAP_GRAILQA_SEMANTIC_EXECUTION_REQUEST": str(controls / "request.json"),
        "XGAP_GRAILQA_SEMANTIC_EXECUTION_AUTHORITY": str(controls / "authority.json"),
        "XGAP_GRAILQA_SEMANTIC_PROTOCOL": str(controls / "custom-protocol.json"),
        "XGAP_GRAILQA_PILOT150_CATALOG": str(catalog),
        "XGAP_GRAILQA_SEMANTIC_RUNNER_COMMIT": COMMIT,
        "XGAP_GRAILQA_SEMANTIC_PAPER_JOB_ID": "501",
        "XGAP_CWRU_RUN_ROOT": str(custom_outer),
        "FAKE_PYTHON_LOG": str(repo / "python-calls.jsonl"),
        "FAKE_SLURM_LOG": str(repo / "slurm-calls.jsonl"),
    })
    return repo, env


def _run(pipeline: tuple[Path, dict[str, str]], script: str) -> subprocess.CompletedProcess[str]:
    repo, env = pipeline
    return subprocess.run(["bash", str(repo / script)], cwd=repo, env=env,
                          text=True, capture_output=True, timeout=20)


def _calls(path: str) -> list[list[str]]:
    return [json.loads(line)["args"] for line in Path(path).read_text().splitlines()]


def test_submission_is_once_and_dependency_uses_accepted_gpu_id(pipeline) -> None:
    repo, env = pipeline
    result = _run(pipeline, SUBMIT)
    assert result.returncode == 0, result.stderr
    calls = _calls(env["FAKE_SLURM_LOG"])
    assert len(calls) == 2
    assert "--dependency=afterok:501" in calls[1]
    assert "--export=ALL,XGAP_GRAILQA_SEMANTIC_PAPER_JOB_ID=501" in calls[1]
    record = json.loads((repo / "runs/grailqa-semantic-paper-submissions/shell-test.json").read_text())
    assert (record["paper_job_id"], record["finalize_job_id"]) == ("501", "502")
    assert _run(pipeline, SUBMIT).returncode != 0
    assert _calls(env["FAKE_SLURM_LOG"]) == calls


@pytest.mark.parametrize("failure", ["reject", "malformed"])
def test_partial_submission_retains_gpu_job_without_retry(pipeline, failure) -> None:
    repo, env = pipeline
    env["FAKE_FINALIZER_FAILURE"] = failure
    result = _run(pipeline, SUBMIT)
    assert result.returncode != 0
    assert "paper_job_id=501" in result.stdout
    lease = repo / "runs/grailqa-semantic-paper-submissions/shell-test.submission-lease"
    assert (lease / "paper-job-id").read_text().strip() == "501"
    assert not (lease.parent / "shell-test.json").exists()
    assert len(_calls(env["FAKE_SLURM_LOG"])) == 2
    assert _run(pipeline, SUBMIT).returncode != 0
    assert len(_calls(env["FAKE_SLURM_LOG"])) == 2


def test_failed_readiness_never_submits_gpu(pipeline) -> None:
    _, env = pipeline
    env["FAKE_READINESS_FAILURE"] = "1"
    assert _run(pipeline, SUBMIT).returncode != 0
    assert not Path(env["FAKE_SLURM_LOG"]).exists()


def test_custom_protocol_and_outer_directory_reach_all_phases(pipeline) -> None:
    _, env = pipeline
    for script in (SUBMIT, RUN, FINALIZE):
        result = _run(pipeline, script)
        assert result.returncode == 0, result.stderr
    calls = _calls(env["FAKE_PYTHON_LOG"])
    for args in calls:
        if "--protocol" in args:
            assert args[args.index("--protocol") + 1] == env["XGAP_GRAILQA_SEMANTIC_PROTOCOL"]
    run_args = next(args for args in calls if args[1:3] == ["xgap.experiments.grailqa_semantic_paper_run", "run"])
    audit_args = next(args for args in calls if args[1] == "xgap.experiments.grailqa_semantic_paper_run_evidence")
    assert run_args[run_args.index("--output") + 1] == audit_args[audit_args.index("--run-root") + 1]
    assert [args[1] for args in calls[-4:]] == [
        "xgap.experiments.grailqa_semantic_paper_run_evidence",
        "xgap.experiments.grailqa_semantic_analysis",
        "xgap.experiments.grailqa_semantic_analysis_evidence",
        "xgap.experiments.grailqa_semantic_paper_result",
    ]


def test_real_generic_wrapper_uses_core_python_before_activation(pipeline) -> None:
    _, env = pipeline
    result = _run(pipeline, RUN)
    assert result.returncode == 0, result.stdout + result.stderr
    records = [json.loads(line) for line in Path(env["FAKE_PYTHON_LOG"]).read_text().splitlines()]
    lifecycle = [record for record in records
                 if record["args"][1] == "xgap.experiments.cwru_vllm"]
    assert [(record["args"][2], record["vllm_active"]) for record in lifecycle] == [
        ("verify-token-budget", False), ("capture-environment", True), ("finalize-run", True),
    ]


def test_relative_paths_survive_job_directory_changes(pipeline) -> None:
    repo, env = pipeline
    outside = repo.parent
    path_keys = [key for key, value in env.items()
                 if key.startswith("XGAP_") and value.startswith(str(repo))]
    for key in path_keys:
        env[key] = os.path.relpath(env[key], outside)
    submitted = subprocess.run(["bash", str(repo / SUBMIT)], cwd=outside, env=env,
                               text=True, capture_output=True, timeout=20)
    assert submitted.returncode == 0, submitted.stderr
    submissions = [json.loads(line) for line in Path(env["FAKE_SLURM_LOG"]).read_text().splitlines()]
    for script, submission in zip((RUN, FINALIZE), submissions):
        job_env = {**env, **submission["env"]}
        assert all(Path(job_env[key]).is_absolute() for key in path_keys)
        result = _run((repo, job_env), script)
        assert result.returncode == 0, result.stdout + result.stderr


def test_prelaunch_failure_preserves_cleanup_without_bare_python(pipeline) -> None:
    _, env = pipeline
    env["FAKE_TOKEN_BUDGET_FAILURE"] = "1"
    result = _run(pipeline, RUN)
    assert result.returncode == 2, result.stdout + result.stderr
    calls = _calls(env["FAKE_PYTHON_LOG"])
    assert [args[2] for args in calls] == ["check", "verify-token-budget", "finalize-run"]
    assert calls[-1][calls[-1].index("--exit-code") + 1] == "2"


@pytest.mark.parametrize("field", ["run_id", "execution_request_sha256", "execution_authority_sha256"])
def test_unrelated_source_run_is_rejected_before_finalization(pipeline, field) -> None:
    repo, env = pipeline
    original = Path(env["XGAP_CWRU_RUN_ROOT"]) / "results/shell-test/run_manifest.json"
    manifest = json.loads(original.read_text())
    manifest[field] = "different"
    other = repo / "other source"
    _json(other / "run_manifest.json", manifest)
    env["XGAP_GRAILQA_SEMANTIC_SOURCE_RUN_ROOT"] = str(other)
    result = _run(pipeline, FINALIZE)
    assert result.returncode != 0
    assert "Source run differs from submitted" in result.stderr
    assert not Path(env["FAKE_PYTHON_LOG"]).exists()
    assert not (repo / "runs/grailqa-semantic-paper-finalizations").exists()
