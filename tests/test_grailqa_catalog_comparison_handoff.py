"""Actual CPU handoff with offline process doubles, not a source-scan claim."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = "scripts/server/run_grailqa_catalog_comparison.sh"
SBATCH = "scripts/slurm/run_grailqa_catalog_comparison.sbatch"
COMMIT = "c" * 40
SCHEMA = "m13e3b-grailqa-local-catalog-v1"


def _write(path: Path, value: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _json(path: Path, value: object) -> None:
    _write(path, json.dumps(value) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


@pytest.fixture
def shell(tmp_path):
    tmp_path = tmp_path.resolve()
    repo = tmp_path / "repo with spaces"
    for name in (HELPER, SBATCH):
        _write(repo / name, (ROOT / name).read_text(), executable=True)
    (repo / "src/xgap").mkdir(parents=True)
    config = repo / "experiments/specs/grailqa_local_catalog_v1.json"
    # The real repository configuration supplies the frozen IDs, never an
    # invented population that happens to have cardinality eighteen.
    cfg = json.loads((ROOT / "experiments/specs/grailqa_local_catalog_v1.json").read_text())
    _json(config, cfg)
    ids = cfg["workloads"]["preflight18"]["question_ids"]
    pilot = repo / "datasets/grailqa_pilot_v1"
    questions = [{"question_id": qid, "text": f"Question {i}?"} for i, qid in enumerate(ids)]
    _write(pilot / "inference_questions.jsonl", "".join(json.dumps(q) + "\n" for q in questions))
    _write(pilot / "reference_interpretations.jsonl", "REFERENCE MUST NOT BE OPENED DURING PRECHECK\n")
    _write(pilot / "ontology.yaml", "ontology: frozen-fixture\n")
    reverse = repo / "datasets/grailqa_inference_catalog_v1/reverse_properties.json"
    _json(reverse, {})
    source = tmp_path / "source manifest.json"
    _json(source, {"revision": "frozen-fixture"})
    parquet = tmp_path / "parquet source"
    parquet.mkdir()
    _write(parquet / "preserved.parquet", "not-real-parquet\n")
    scratch = tmp_path / "node local staging"
    scratch.mkdir()
    baseline = tmp_path / "baseline preflight18"
    manifest = {
        "local_catalog_schema_version": SCHEMA,
        "question_ids": ids,
        "anchor_extraction": cfg["anchor_extraction"],
        "sources": {
            "freebase_archival_parquet": {"source_manifest_sha256": _sha(source)},
            "ontology": {"sha256": _sha(pilot / "ontology.yaml"),
                         "reverse_properties_sha256": _sha(reverse)},
            "inference_questions": {"sha256": _sha(pilot / "inference_questions.jsonl"),
                                    "question_only": True},
        },
    }
    _json(baseline / "manifest.json", manifest)
    # Real builder exports local_queries.jsonl with `text`; question_text is
    # the SQLite column, not the portable JSONL field. No queries.jsonl exists.
    _write(baseline / "local_queries.jsonl", "".join(json.dumps({
        **q, "question_hash": hashlib.sha256(q["text"].encode()).hexdigest(),
    }) + "\n" for q in questions))
    bins = tmp_path / "fake commands"
    control = bins / "explicit control python"
    body = r'''import hashlib, json, os, sys, types
from pathlib import Path
def record(stage, **fields):
    with open(os.environ["TEST_LOG"], "a") as handle:
        handle.write(json.dumps({"stage":stage, **fields})+"\n")
def flag(stage):
    if os.environ.get("TEST_DRIFT_STAGE") == stage:
        Path(os.environ["TEST_DRIFT_FILE"]).touch()
def arg(name):
    return sys.argv[sys.argv.index(name)+1]
record("python", args=sys.argv[1:], executable=sys.argv[0],
       offline={key:os.environ.get(key) for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE")})
if sys.argv[1:3] == ["-m", "xgap.experiments.grailqa_local_catalog"]:
    record("full_source_scan", args=sys.argv[1:])
    assert sys.argv[3] == "build"
    assert arg("--workload") == "preflight18"
    assert arg("--candidate-selection") == "canonical_eligible_topk_v2"
    assert not any(x in sys.argv for x in ("--force", "--resume", "--retry"))
    root=Path(arg("--local-root"))/"preflight18-eligible-v2"
    root.mkdir(parents=True, exist_ok=False)
    (root/"fixture.json").write_text("{}\n")
    flag("build")
    sys.exit(int(os.environ.get("TEST_BUILD_EXIT", "0")))
if sys.argv[1:3] == ["-m", "xgap.experiments.grailqa_catalog_comparison"]:
    record("comparison", args=sys.argv[1:])
    assert Path(arg("--eligible-catalog-root"), "fixture.json").is_file()
    assert len(arg("--question-ids").split(",")) == 18
    root=Path(arg("--output-root"))
    root.mkdir(parents=True, exist_ok=False)
    (root/"fixture-result.json").write_text("{}\n")
    sys.exit(int(os.environ.get("TEST_COMPARE_EXIT", "0")))
assert sys.argv[1:] == ["-"]
record("small_input_precheck")
original_read_text=Path.read_text
def guarded_read_text(path, *args, **kwargs):
    if path.name == "reference_interpretations.jsonl":
        raise AssertionError("Reference content must remain closed during precheck")
    return original_read_text(path, *args, **kwargs)
Path.read_text=guarded_read_text
catalog=types.ModuleType("xgap.experiments.grailqa_catalog")
def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
catalog.sha256_file=sha256_file
local=types.ModuleType("xgap.experiments.grailqa_local_catalog")
local.LOCAL_CATALOG_SCHEMA_VERSION="m13e3b-grailqa-local-catalog-v1"
def load_questions(path, *, question_ids):
    record("inference_inputs", path=str(path), ids=list(question_ids))
    rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    selected=[q for q in rows if q["question_id"] in question_ids]
    assert len(selected) == len(question_ids)
    return tuple(types.SimpleNamespace(question_id=q["question_id"], text=q["text"]) for q in selected)
def validate(path):
    record("baseline_validation", path=str(path))
    if os.environ.get("TEST_BASELINE_INVALID") == "1":
        raise ValueError("Synthetic baseline rejection")
    assert (path/"manifest.json").is_file()
    assert (path/"local_queries.jsonl").is_file()
    flag("precheck")
    return {"valid":True}
local.load_inference_questions=load_questions
local.validate_local_catalog=validate
sys.modules[catalog.__name__]=catalog
sys.modules[local.__name__]=local
exec(compile(sys.stdin.read(), "<actual-comparison-precheck>", "exec"), {"__name__":"__main__"})
'''
    _write(control, f"#!{sys.executable}\n" + body, executable=True)
    _write(bins / "git", '''#!/bin/bash
if [[ "$1" == rev-parse ]]; then
  if [[ -f "$TEST_DRIFT_FILE" ]]; then printf '%040d\n' 0; else printf '%s\n' "$TEST_HEAD"; fi
elif [[ "$1" == status ]]; then printf '%s' "${TEST_DIRTY:-}"
else exit 98
fi
''', executable=True)
    _write(bins / "module", '#!/bin/sh\n[ "$*" = "load Miniconda3" ]\n', executable=True)
    for name in ("sbatch", "srun", "curl", "wget", "pip", "uv", "python", "python3", "vllm"):
        _write(bins / name, '#!/bin/sh\nprintf "%s\\n" "$0" >> "$TEST_FORBIDDEN"\nexit 99\n', executable=True)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("XGAP_", "SLURM_", "TEST_", "GIT_", "HF_", "TRANSFORMERS_"))}
    env.update({
        "PATH": str(bins) + os.pathsep + env.get("PATH", ""),
        "XGAP_REPO_ROOT": str(repo), "XGAP_PYTHON": str(control),
        "XGAP_GRAILQA_REPAIR_RUNNER_COMMIT": COMMIT, "SLURM_JOB_ID": "1234",
        "XGAP_FREEBASE_PARQUET_ROOT": str(parquet),
        "XGAP_FREEBASE_SOURCE_MANIFEST": str(source),
        "XGAP_GRAILQA_LEGACY_CATALOG": str(baseline),
        "XGAP_LOCAL_CATALOG_STAGING_ROOT": str(scratch),
        "TEST_HEAD": COMMIT, "TEST_LOG": str(tmp_path / "calls.jsonl"),
        "TEST_FORBIDDEN": str(tmp_path / "forbidden"),
        "TEST_DRIFT_FILE": str(tmp_path / "drift"),
    })
    return SimpleNamespace(tmp=tmp_path, repo=repo, config=config, pilot=pilot,
                           source=source, parquet=parquet, scratch=scratch, baseline=baseline,
                           reverse=reverse, control=control, ids=ids, env=env,
                           output=repo / "runs/cwru-grailqa-catalog-comparison-1234")


def _run(shell, *, args=(), entry=SBATCH):
    return subprocess.run(["bash", str(shell.repo / entry), *args], cwd=shell.tmp,
                          env=shell.env, capture_output=True, text=True, timeout=15)


def _records(shell, stage=None):
    path = Path(shell.env["TEST_LOG"])
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [row for row in rows if stage is None or row["stage"] == stage]


def _no_scan(shell):
    assert not _records(shell, "full_source_scan")
    assert not _records(shell, "comparison")
    assert not Path(shell.env["TEST_FORBIDDEN"]).exists()


@pytest.mark.parametrize("entry", [HELPER, SBATCH])
def test_actual_handoff_preserves_baseline_and_orders_work(shell, entry):
    preserved = {p: _tree(p) for p in (shell.baseline, shell.pilot, shell.parquet)}
    shell.env.update(XGAP_LOCAL_CATALOG_WORKLOAD="pilot150", HF_HUB_OFFLINE="0",
                     XGAP_GRAILQA_COMPARISON_RUN=str(shell.baseline))
    result = _run(shell, entry=entry)
    assert result.returncode == 0, result.stderr
    stages = [row["stage"] for row in _records(shell)]
    assert stages.index("small_input_precheck") < stages.index("baseline_validation") < stages.index("full_source_scan") < stages.index("comparison")
    scan, = _records(shell, "full_source_scan")
    assert "--workload" in scan["args"]
    assert scan["args"][scan["args"].index("--local-root") + 1] == str(shell.output / "catalog")
    compare, = _records(shell, "comparison")
    assert compare["args"][compare["args"].index("--legacy-catalog-root") + 1] == str(shell.baseline)
    assert compare["args"][compare["args"].index("--question-ids") + 1] == ",".join(shell.ids)
    for row in _records(shell, "python"):
        assert row["executable"] == str(shell.control)
        assert set(row["offline"].values()) == {"1"}
    inputs = json.loads((shell.output / "run_inputs.json").read_text())
    assert inputs["runner_commit"] == COMMIT
    assert inputs["question_ids"] == shell.ids
    assert inputs["paper_result"] is False
    assert inputs["automatic_retries"] == inputs["llm_calls"] == inputs["backend_calls"] == 0
    assert all(_tree(path) == before for path, before in preserved.items())
    assert not Path(shell.env["TEST_FORBIDDEN"]).exists()


@pytest.mark.parametrize("key", ["XGAP_REPO_ROOT", "XGAP_PYTHON", "XGAP_GRAILQA_REPAIR_RUNNER_COMMIT"])
def test_missing_explicit_input_refuses_without_scan(shell, key):
    del shell.env[key]
    assert _run(shell).returncode != 0
    _no_scan(shell)


@pytest.mark.parametrize("key,value", [("TEST_DIRTY", "?? user-work"), ("TEST_HEAD", "b" * 40),
    ("SLURM_JOB_ID", ""), ("SLURM_JOB_ID", "1234_1"),
    ("XGAP_GRAILQA_REPAIR_RUNNER_COMMIT", "main"),
    ("XGAP_REPO_ROOT", "relative-repository"), ("XGAP_PYTHON", "relative-python")])
def test_invalid_launch_binding_refuses_without_scan(shell, key, value):
    shell.env[key] = value
    assert _run(shell).returncode != 0
    _no_scan(shell)


def test_arguments_are_not_silently_accepted(shell):
    assert _run(shell, args=("--force",)).returncode != 0
    _no_scan(shell)


@pytest.mark.parametrize("name", ["source", "parquet", "scratch", "baseline", "config", "reverse",
                                    "inference_questions.jsonl", "reference_interpretations.jsonl", "ontology.yaml"])
def test_missing_prerequisite_refuses_before_full_source_scan(shell, name):
    path = getattr(shell, name, None) or shell.pilot / name
    path.rename(path.with_name(path.name + ".preserved"))
    assert _run(shell).returncode != 0
    _no_scan(shell)
    assert not shell.output.exists()


@pytest.mark.parametrize("kind", ["existing", "symlink", "dangling_symlink", "symlink_parent"])
def test_existing_or_redirected_run_is_not_overwritten(shell, kind):
    shell.output.parent.mkdir(parents=True)
    unrelated = shell.tmp / "unrelated"
    unrelated.mkdir()
    _write(unrelated / "keep", "user-data")
    if kind == "existing":
        shell.output.mkdir()
        _write(shell.output / "keep", "previous-evidence")
    elif kind == "symlink_parent":
        shell.output.parent.rmdir()
        shell.output.parent.symlink_to(unrelated, target_is_directory=True)
    else:
        shell.output.symlink_to(unrelated if kind == "symlink" else shell.tmp / "missing", target_is_directory=True)
    assert _run(shell).returncode != 0
    _no_scan(shell)
    assert (unrelated / "keep").read_text() == "user-data"
    if kind == "existing":
        assert (shell.output / "keep").read_text() == "previous-evidence"


@pytest.mark.parametrize("name", ["baseline", "source", "parquet", "scratch", "config", "reverse"])
def test_symlinked_prerequisite_refuses_before_scan(shell, name):
    path = getattr(shell, name)
    original = path.with_name(path.name + ".real")
    path.rename(original)
    path.symlink_to(original, target_is_directory=original.is_dir())
    assert _run(shell).returncode != 0
    _no_scan(shell)


@pytest.mark.parametrize("name", ["baseline", "parquet", "pilot"])
def test_scratch_inside_protected_input_refuses(shell, name):
    scratch = getattr(shell, name) / "scratch"
    scratch.mkdir()
    shell.env["XGAP_LOCAL_CATALOG_STAGING_ROOT"] = str(scratch)
    assert _run(shell).returncode != 0
    _no_scan(shell)


@pytest.mark.parametrize("name", ["source", "reverse", "ontology.yaml"])
def test_frozen_input_content_mismatch_refuses_before_scan(shell, name):
    path = getattr(shell, name, None) or shell.pilot / name
    _write(path, "changed source content\n")
    assert _run(shell).returncode != 0
    _no_scan(shell)
    assert not shell.output.exists()


@pytest.mark.parametrize("defect", ["v2_schema", "question_text", "missing_question", "duplicate_question", "baseline_invalid"])
def test_bad_baseline_refuses_without_full_scan(shell, defect):
    if defect == "v2_schema":
        path = shell.baseline / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["local_catalog_schema_version"] = "m13e3b-grailqa-local-catalog-v2"
        _json(path, manifest)
    elif defect == "baseline_invalid":
        shell.env["TEST_BASELINE_INVALID"] = "1"
    else:
        path = shell.baseline / "local_queries.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if defect == "question_text":
            rows[0]["text"] = "Changed question"
        elif defect == "missing_question":
            rows.pop()
        else:
            rows.append(rows[0])
        _write(path, "".join(json.dumps(row) + "\n" for row in rows))
    assert _run(shell).returncode != 0
    _no_scan(shell)


@pytest.mark.parametrize("defect", ["question_order", "anchor_policy", "inference_source_hash"])
def test_baseline_construction_binding_drift_refuses_before_scan(shell, defect):
    path = shell.baseline / "manifest.json"
    manifest = json.loads(path.read_text())
    if defect == "question_order":
        manifest["question_ids"].reverse()
    elif defect == "anchor_policy":
        manifest["anchor_extraction"]["max_candidates_per_query"] += 1
    else:
        manifest["sources"]["inference_questions"]["sha256"] = "0" * 64
    _json(path, manifest)
    before = _tree(shell.baseline)
    result = _run(shell)
    assert result.returncode != 0
    _no_scan(shell)
    assert not shell.output.exists()
    assert _tree(shell.baseline) == before


def test_inference_file_byte_drift_refuses_even_when_question_text_is_unchanged(shell):
    path = shell.pilot / "inference_questions.jsonl"
    # Changing whitespace leaves parsed IDs/text intact, but changes the frozen
    # complete inference source identity required by the paired construction.
    _write(path, path.read_text() + "\n")
    result = _run(shell)
    assert result.returncode != 0
    assert "inference-question source file differs" in result.stderr
    _no_scan(shell)
    assert not shell.output.exists()


@pytest.mark.parametrize("kind", ["17", "duplicate", "unknown_question"])
def test_invalid_frozen_development_population_refuses(shell, kind):
    cfg = json.loads(shell.config.read_text())
    ids = cfg["workloads"]["preflight18"]["question_ids"]
    if kind == "17":
        ids.pop()
    elif kind == "duplicate":
        ids[0] = ids[1]
    else:
        ids[0] = "not-in-inference-input"
    _json(shell.config, cfg)
    assert _run(shell).returncode != 0
    _no_scan(shell)


@pytest.mark.parametrize("stage", ["precheck", "build"])
def test_runner_drift_stops_before_next_phase(shell, stage):
    shell.env["TEST_DRIFT_STAGE"] = stage
    assert _run(shell).returncode != 0
    assert not _records(shell, "comparison")
    assert len(_records(shell, "full_source_scan")) == (stage == "build")


@pytest.mark.parametrize("stage,code", [("BUILD", 7), ("COMPARE", 8)])
def test_failed_phase_is_preserved_without_retry(shell, stage, code):
    before = _tree(shell.baseline)
    shell.env[f"TEST_{stage}_EXIT"] = str(code)
    first = _run(shell)
    assert first.returncode == code, first.stderr
    assert len(_records(shell, "full_source_scan")) == 1
    assert len(_records(shell, "comparison")) == (stage == "COMPARE")
    assert (shell.output / "run_inputs.json").is_file()
    assert (shell.output / "catalog/preflight18-eligible-v2/fixture.json").is_file()
    prior = len(_records(shell, "full_source_scan"))
    assert _run(shell).returncode != 0
    assert len(_records(shell, "full_source_scan")) == prior
    assert _tree(shell.baseline) == before
    assert not Path(shell.env["TEST_FORBIDDEN"]).exists()
