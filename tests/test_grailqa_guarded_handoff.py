"""Exercise actual shell handoff with offline process-boundary doubles only."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = "scripts/server/run_grailqa_guarded_preflight.sh"
SBATCH = "scripts/slurm/run_grailqa_guarded_preflight.sbatch"
COMMIT = "c" * 40
REVISION = "d" * 40
REQUIRED = (
    "XGAP_REPO_ROOT", "XGAP_PYTHON", "XGAP_GRAILQA_GUARDED_SPEC",
    "XGAP_GRAILQA_GUARDED_SPEC_SHA256", "XGAP_GRAILQA_GUARDED_RUNNER_COMMIT", "VLLM_ENV",
)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o755)


def _freeze(shell, **changes):
    data = json.loads(shell.spec.read_text())
    data.pop("freeze_hash", None)
    data.update(changes)
    data["freeze_hash"] = _hash(data)
    shell.spec.write_text(json.dumps(data))
    shell.env["XGAP_GRAILQA_GUARDED_SPEC_SHA256"] = data["freeze_hash"]


@pytest.fixture
def shell(tmp_path):
    tmp_path = tmp_path.resolve()
    repo = tmp_path / "repo with spaces"
    (repo / "src/xgap").mkdir(parents=True)
    for name in (HELPER, SBATCH):
        _write(repo / name, (ROOT / name).read_text(), True)
    bins = tmp_path / "test bin"
    serving = tmp_path / "frozen serving"
    cache = tmp_path / "frozen cache"
    snapshot = cache / "hub/models--Qwen--Qwen3-32B/snapshots" / REVISION
    snapshot.mkdir(parents=True)
    _write(serving / "bin/activate", "# synthetic activation\n")
    _write(serving / "bin/vllm", "#!/bin/sh\nexit 97\n", True)
    interpreter_body = '''import hashlib, json, os, sys, types
from pathlib import Path
# Exercise the real policy validator, while retaining the explicit doubles
# below for heavyweight readiness/environment process boundaries.
sys.path.insert(0, os.environ["TEST_SOURCE_ROOT"])
from xgap.experiments import grailqa_candidate_grounding
def record(stage, **fields):
    with open(os.environ["TEST_LOG"], "a") as h:
        h.write(json.dumps({"stage": stage, **fields}) + "\\n")
def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
if sys.argv[1:3] == ["-m", "xgap.experiments.grailqa_guarded_preflight"]:
    record("inference", args=sys.argv[1:], executable=sys.argv[0], cwd=str(Path.cwd()))
    sys.exit(int(os.environ.get("TEST_INFERENCE_EXIT", "0")))
record("control", args=sys.argv[1:], executable=sys.argv[0], env={
    k: v for k,v in os.environ.items() if k.startswith(("XGAP_GRAILQA_", "HF_", "TRANSFORMERS_"))
})
assert sys.argv[1] == "-"
class Spec:
    @classmethod
    def load(cls, path):
        obj = cls(); obj.path = Path(path).resolve(); obj.data = json.loads(obj.path.read_text())
        assert obj.data["freeze_hash"] == identity({k:v for k,v in obj.data.items() if k != "freeze_hash"})
        obj.question_ids = tuple(obj.data["question_ids"])
        assert len(obj.question_ids) == len(set(obj.question_ids))
        return obj
class Contract:
    @classmethod
    def load(cls, path):
        obj=cls(); obj.path=Path(path).resolve(); obj.data=json.loads(obj.path.read_text())
        obj.model=obj.data["serving"]["model"]; obj.contract_hash=obj.data["contract_hash"]
        return obj
def readiness(spec, repo, *, require_credentials):
    record("readiness", require_credentials=require_credentials)
    return {"ready": os.environ.get("TEST_READY", "1") == "1", "checks": []}
def budget(**kwargs):
    record("budget", **{k:str(v) for k,v in kwargs.items()})
    if os.environ.get("TEST_BUDGET_FAIL") == "1": raise ValueError("Synthetic budget mismatch")
preflight=types.ModuleType("xgap.experiments.grailqa_preflight")
preflight.GrailQAPreflightSpec=Spec; preflight.preflight_readiness=readiness
cwru=types.ModuleType("xgap.experiments.cwru_vllm")
cwru.CWRUVLLMContract=Contract; cwru.verify_preflight_token_budget=budget
sys.modules[preflight.__name__]=preflight; sys.modules[cwru.__name__]=cwru
source=sys.stdin.read(); sys.argv=sys.argv[1:]
exec(compile(source, "<offline-handoff-check>", "exec"), {"__name__":"__main__"})
'''
    control = bins / "control python"
    for path in (control, serving / "bin/python"):
        _write(path, f"#!{sys.executable}\n" + interpreter_body, True)
    _write(bins / "git", '''#!/bin/bash
if [[ "$*" == "rev-parse HEAD" ]]; then
  if [[ -f "$TEST_DRIFT_FILE" ]]; then printf '%040d\n' 0; else printf '%s\n' "$TEST_HEAD"; fi
elif [[ "$1" == status ]]; then printf '%s' "${TEST_DIRTY:-}"
else exit 98
fi
''', True)
    for name in ("sbatch", "srun", "curl", "wget", "pip", "uv", "python", "python3", "vllm"):
        _write(bins / name, '#!/bin/sh\nprintf "%s\\n" "$0" >> "$TEST_FORBIDDEN"\nexit 99\n', True)
    wrapper = repo / "scripts/slurm/cwru_xgap_vllm.sbatch"
    _write(wrapper, f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
with open(os.environ["TEST_LOG"], "a") as h:
    h.write(json.dumps({"stage":"wrapper", "args":sys.argv[1:], "smoke":os.environ.get("XGAP_SKIP_VLLM_STRUCTURED_SMOKE"),
      "offline":os.environ.get("HF_HUB_OFFLINE"), "contract":os.environ.get("XGAP_CWRU_CONTRACT"),
      "log":os.environ.get("XGAP_VLLM_LOG"), "pid":os.environ.get("XGAP_VLLM_PID_FILE")})+"\\n")
root=Path(os.environ["XGAP_CWRU_RUN_ROOT"])
envpath=root/"cwru_environment.json"; envpath.write_text("{}")
os.environ["XGAP_RUN_ENVIRONMENT_FILE"]=str(envpath)
os.environ["XGAP_RESOLVED_MODEL_REVISION"]=os.environ.get("TEST_REVISION", "d"*40)
if os.environ.get("TEST_DRIFT") == "1": Path(os.environ["TEST_DRIFT_FILE"]).touch()
if os.environ.get("TEST_PREEXIST_RESULT") == "1": (root/"results/grailqa-guarded-preflight").mkdir(parents=True)
os.execvp(sys.argv[2], sys.argv[2:])
''', True)
    # The real handoff invokes the generic wrapper through bash. Keep the test
    # wrapper a shell script and delegate only to this explicit local double.
    wrapper_double = tmp_path / "wrapper_double"
    shutil.copyfile(wrapper, wrapper_double)
    wrapper_double.chmod(0o755)
    _write(wrapper, f'#!/bin/bash\nexec "{wrapper_double}" "$@"\n', True)
    contract = repo / "experiments/environments/explicit.json"
    _write(contract, json.dumps({
        "shared_paths": {"vllm_env": str(serving), "hf_home": str(cache)},
        "serving": {"model": "Qwen/Qwen3-32B"}, "contract_hash": "e" * 64,
    }))
    spec = repo / "experiments/specs/explicit spec.json"
    _write(spec, json.dumps({
        "question_ids": [str(i) for i in range(18)], "backend_execution": False,
        "gold_exposed_to_inference": False, "full_150_run_permitted": False,
        "deployment_contract": str(contract),
    }))
    env = {k: v for k,v in os.environ.items() if not k.startswith(("XGAP_", "SLURM_", "TEST_", "HF_", "TRANSFORMERS_", "GIT_"))}
    env.update({
        "PATH": str(bins)+os.pathsep+env.get("PATH", ""),
        "XGAP_REPO_ROOT": str(repo), "XGAP_PYTHON": str(control),
        "XGAP_GRAILQA_GUARDED_SPEC": str(spec),
        "XGAP_GRAILQA_GUARDED_RUNNER_COMMIT": COMMIT,
        "VLLM_ENV": str(serving), "SLURM_JOB_ID": "1234", "TEST_HEAD": COMMIT,
        "TEST_LOG": str(tmp_path / "calls.jsonl"), "TEST_FORBIDDEN": str(tmp_path / "forbidden"),
        "TEST_DRIFT_FILE": str(tmp_path / "drift"),
        "TEST_SOURCE_ROOT": str(ROOT / "src"),
    })
    result = SimpleNamespace(tmp=tmp_path, repo=repo, spec=spec, contract=contract, control=control,
                             serving=serving, snapshot=snapshot, env=env,
                             output=repo/"runs/cwru-grailqa-guarded-1234")
    _freeze(result)
    return result


def _run(shell, args=(), entry=SBATCH):
    return subprocess.run(["bash", str(shell.repo/entry), *args], cwd=shell.tmp, env=shell.env,
                          text=True, capture_output=True, timeout=15)


def _records(shell, stage=None):
    path = Path(shell.env["TEST_LOG"])
    rows = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
    return [x for x in rows if stage is None or x["stage"] == stage]


def _no_live_handoff(shell):
    assert not _records(shell, "wrapper")
    assert not _records(shell, "inference")
    assert not Path(shell.env["TEST_FORBIDDEN"]).exists()


def test_exact_guarded_handoff_and_interpreter_separation(shell):
    preserved = {p: p.read_bytes() for p in (shell.spec, shell.contract, shell.repo/"scripts/slurm/cwru_xgap_vllm.sbatch")}
    shell.env.update(HF_HUB_OFFLINE="0", XGAP_SKIP_VLLM_STRUCTURED_SMOKE="0", XGAP_VLLM_LOG="old.log", XGAP_VLLM_PID_FILE="old.pid")
    result = _run(shell)
    assert result.returncode == 0, result.stderr
    wrapper, = _records(shell, "wrapper")
    assert wrapper["args"] == [str(shell.spec), "bash", str(shell.repo/HELPER), "--after-model"]
    assert wrapper["smoke"] == wrapper["offline"] == "1"
    assert wrapper["log"] == str(shell.output/"vllm.log")
    assert wrapper["pid"] == str(shell.output/"vllm.pid")
    inference, = _records(shell, "inference")
    assert inference["executable"] == str(shell.serving/"bin/python")
    assert inference["args"] == [
        "-m", "xgap.experiments.grailqa_guarded_preflight",
        "--spec", str(shell.spec), "--repo-root", str(shell.repo),
        "--output-root", str(shell.output/"results/grailqa-guarded-preflight"),
        "--run-environment-path", str(shell.output/"cwru_environment.json"),
        "--tokenizer-snapshot", str(shell.snapshot), "--tokenizer-revision", REVISION,
        "--expected-runner-commit", COMMIT,
        "--execute-development-spec-sha256", shell.env["XGAP_GRAILQA_GUARDED_SPEC_SHA256"],
        "--verify-server-tokenization",
    ]
    assert [x["executable"] for x in _records(shell, "control")] == [str(shell.control)] * 2
    assert _records(shell, "readiness") == [{"stage": "readiness", "require_credentials": False}]
    assert _records(shell).index(wrapper) > next(i for i,x in enumerate(_records(shell)) if x["stage"] == "readiness")
    assert all(p.read_bytes() == data for p,data in preserved.items())
    assert not Path(shell.env["TEST_FORBIDDEN"]).exists()


@pytest.mark.parametrize("policy", ["grailqa_canonical_ast_grounding_v1", "grailqa_canonical_semantic_grounding_v2"])
def test_explicit_canonical_policy_is_bound_in_both_launch_phases(shell, policy):
    _freeze(shell, candidate_grounding_policy=policy)
    result = _run(shell)
    assert result.returncode == 0, result.stderr
    binding = json.loads((shell.output / "guarded_launch_binding.json").read_text())
    assert binding["candidate_grounding_policy"] == policy
    assert len(_records(shell, "wrapper")) == len(_records(shell, "inference")) == 1


def test_explicit_feedback_policy_is_bound_in_both_launch_phases(shell):
    _freeze(shell, candidate_grounding_policy="grailqa_canonical_semantic_grounding_v2",
            candidate_repair_policy="typed_grounding_one_repair_v1")
    result = _run(shell)
    assert result.returncode == 0, result.stderr
    binding = json.loads((shell.output / "guarded_launch_binding.json").read_text())
    assert binding["candidate_repair_policy"] == "typed_grounding_one_repair_v1"
    assert len(_records(shell, "wrapper")) == len(_records(shell, "inference")) == 1


@pytest.mark.parametrize("policy", [None, "typo", {}, True, "typed_grounding_one_repair_v1"])
def test_invalid_or_mixed_feedback_policy_never_starts_the_model(shell, policy):
    _freeze(shell, candidate_repair_policy=policy)  # Legacy grounding cannot opt in.
    result = _run(shell)
    assert result.returncode != 0
    assert "repair policy" in result.stderr or "semantic grounding" in result.stderr
    _no_live_handoff(shell)


@pytest.mark.parametrize("policy", [None, "typo", {}, True])
def test_invalid_grounding_policy_never_starts_the_model(shell, policy):
    _freeze(shell, candidate_grounding_policy=policy)
    result = _run(shell)
    assert result.returncode != 0
    assert "Unknown GrailQA candidate grounding policy" in result.stderr
    _no_live_handoff(shell)


def test_relative_explicit_inputs_anchor_before_cd(shell):
    for key in ("XGAP_REPO_ROOT", "XGAP_PYTHON", "XGAP_GRAILQA_GUARDED_SPEC", "VLLM_ENV"):
        shell.env[key] = os.path.relpath(shell.env[key], shell.tmp)
    shell.env["XGAP_CWRU_RUN_ROOT"] = os.path.relpath(shell.output, shell.tmp)
    assert _run(shell).returncode == 0
    assert _records(shell, "inference")[0]["args"][3] == str(shell.spec)


def test_explicit_catalog_overrides_preserved(shell):
    overrides = {"XGAP_GRAILQA_CATALOG_V2": "relative custom catalog", "XGAP_GRAILQA_REACHABILITY_V2": "relative reachability",
                 "XGAP_GRAILQA_REACHABILITY_ROWS": "relative rows.jsonl", "XGAP_GRAILQA_REACHABILITY_SUMMARY": "relative summary.json"}
    shell.env.update(overrides)
    assert _run(shell).returncode == 0
    for row in _records(shell, "control"):
        assert {k:row["env"][k] for k in overrides} == overrides


@pytest.mark.parametrize("key", REQUIRED)
def test_missing_explicit_input_never_hands_off(shell, key):
    del shell.env[key]
    assert _run(shell).returncode != 0
    _no_live_handoff(shell)


@pytest.mark.parametrize("key,value", [("TEST_HEAD", "b"*40), ("TEST_DIRTY", "?? unexpected"),
    ("XGAP_GRAILQA_GUARDED_RUNNER_COMMIT", "main"), ("XGAP_GRAILQA_GUARDED_SPEC_SHA256", "bad"),
    ("SLURM_JOB_ID", ""), ("XGAP_GRAILQA_GUARDED_SPEC_SHA256", "a"*64),
    ("TEST_READY", "0"), ("TEST_BUDGET_FAIL", "1"), ("HF_HOME", "/incorrect/cache"),
    ("XGAP_LLM_BASE_URL", "https://example.invalid/v1"), ("XGAP_LLM_MODEL", "other"),
])
def test_invalid_prelaunch_binding_never_starts_wrapper(shell, key, value):
    shell.env[key] = value
    assert _run(shell).returncode != 0
    _no_live_handoff(shell)


@pytest.mark.parametrize("change", [{"question_ids": [str(i) for i in range(17)]},
    {"backend_execution": True}, {"gold_exposed_to_inference": True}, {"full_150_run_permitted": True}])
def test_canonical_but_out_of_scope_spec_never_starts_wrapper(shell, change):
    _freeze(shell, **change)
    assert _run(shell).returncode != 0
    _no_live_handoff(shell)


@pytest.mark.parametrize("kind", ["external_spec", "external_contract", "aliased_spec", "aliased_contract"])
def test_environment_collector_inputs_must_be_repository_contained_and_unaliased(shell, kind):
    original_spec = shell.spec.read_bytes()
    original_contract = shell.contract.read_bytes()
    if kind == "external_spec":
        external = shell.tmp / "outside-spec.json"
        external.write_bytes(original_spec)
        shell.env["XGAP_GRAILQA_GUARDED_SPEC"] = str(external)
    elif kind == "external_contract":
        external = shell.tmp / "outside-contract.json"
        external.write_bytes(original_contract)
        _freeze(shell, deployment_contract=str(external))
    elif kind == "aliased_spec":
        alias = shell.repo / "spec-alias"
        alias.symlink_to(shell.spec.parent, target_is_directory=True)
        shell.env["XGAP_GRAILQA_GUARDED_SPEC"] = str(alias / shell.spec.name)
    else:
        alias = shell.repo / "contract-alias"
        alias.symlink_to(shell.contract.parent, target_is_directory=True)
        _freeze(shell, deployment_contract=str(alias / shell.contract.name))
    before = shell.spec.read_bytes()
    assert _run(shell).returncode != 0
    _no_live_handoff(shell)
    assert not shell.output.exists()
    assert shell.spec.read_bytes() == before
    assert shell.contract.read_bytes() == original_contract


@pytest.mark.parametrize("kind", ["existing", "symlink", "ancestor_symlink", "source", "old_run_child", "dotdot"])
def test_unsafe_or_nonexclusive_run_root_rejected(shell, kind):
    if kind == "existing":
        shell.output.mkdir(parents=True)
        (shell.output/"preserve").write_text("old")
    elif kind == "symlink":
        shell.output.parent.mkdir(); shell.output.symlink_to(shell.tmp/"missing")
    elif kind == "ancestor_symlink":
        target=shell.tmp/"target"; target.mkdir(); shell.output.parent.symlink_to(target)
    elif kind == "source":
        shell.env["XGAP_CWRU_RUN_ROOT"] = str(shell.repo/"src/cwru-grailqa-guarded-new")
    elif kind == "old_run_child":
        shell.env["XGAP_CWRU_RUN_ROOT"] = str(shell.repo/"runs/old-run/cwru-grailqa-guarded-new")
    else:
        shell.env["XGAP_CWRU_RUN_ROOT"] = str(shell.repo/"runs/../src/cwru-grailqa-guarded-new")
    assert _run(shell).returncode != 0
    _no_live_handoff(shell)
    if kind == "existing": assert (shell.output/"preserve").read_text() == "old"


@pytest.mark.parametrize("key,value", [("TEST_DRIFT", "1"), ("TEST_REVISION", "main"), ("TEST_PREEXIST_RESULT", "1")])
def test_postlaunch_drift_or_unsafe_result_prevents_inference(shell, key, value):
    shell.env[key] = value
    assert _run(shell).returncode != 0
    assert len(_records(shell, "wrapper")) == 1
    assert not _records(shell, "inference")


@pytest.mark.parametrize("status", [1, 2, 17, 143])
def test_inference_exit_status_preserved_no_retry(shell, status):
    shell.env["TEST_INFERENCE_EXIT"] = str(status)
    assert _run(shell).returncode == status
    assert len(_records(shell, "inference")) == 1


def test_slurm_resource_boundary_is_explicit_and_unchanged():
    text = (ROOT/SBATCH).read_text()
    for directive in ("--partition=gpu", "-C gpu2h100", "--gres=gpu:1", "--cpus-per-task=8", "--mem=64G", "--time=04:00:00"):
        assert "#SBATCH " + directive in text
    helper = (ROOT/HELPER).read_text()
    assert "--allow-unverified-serving-tokenizer" not in helper
    assert "--verify-server-tokenization" in helper
