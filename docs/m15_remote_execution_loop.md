# M15 Remote Execution Loop

## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: plan
- Origin Date: 2026-09-04
- Verification Status: LOCALLY VERIFIED; CWRU B0 PARTIALLY PASSED
- Version Label: m15_remote_loop_v2

## Current claim boundary

The legacy M13 Qwen/vLLM path has run on CWRU Pioneer. The M15 agentic
federated core has passed local acceptance but has not yet run on Pioneer, and
its Neo4j-plus-Fuseki path has not yet passed a live two-engine gate. Therefore
XGAP is not yet ready to claim CWRU execution of the new system.

Two B0 probes on 2026-09-04 established a clean checkout at commit
`465e2e2454b74aaf7a1c055797740bde8ca5ace0`, working Slurm commands,
`gpu2h100`, `/home/hxc859/venvs/xgap-vllm`, and Podman. The login environment
has no default `python`; `module load Miniconda3` exposes Python 3.11.5, but
neither that base interpreter nor the vLLM interpreter contains pytest. The
next gate is a separate user-owned `xgap-core` environment; the model-serving
environment remains unchanged.

## Codex-owned development loop

The active project goal is advanced through this repeated state machine:

```text
freeze one milestone and its evidence gate
  -> inspect the current implementation and prior artifacts
  -> implement the smallest end-to-end increment
  -> run focused and regression validation
  -> package immutable experiment commands and outputs
  -> evaluate the evidence against the gate
  -> continue, or ask the user only for an external action/decision
```

Codex owns repository analysis, design proposals, implementation, local tests,
artifact schemas, experiment wrappers, result analysis, and documentation.
The user is involved only for:

- CWRU VPN, Duo, SSH, OnDemand, or account actions;
- server-side commands that Codex cannot execute from the local host;
- supplying external datasets, credentials, or generated artifacts;
- choosing between research alternatives that change the claim, workload,
  baseline, or experimental budget.

A failed external run is evidence. It is diagnosed before any resubmission;
jobs are not silently retried, and old run directories are never overwritten.

## Execution plan

### M15-B0 — CWRU environment gate

- Objective: determine the exact server-side Git, Python, Slurm, H100, vLLM,
  and container/runtime capabilities without running work on a login node.
- Entry command: `bash scripts/cwru/probe_m15_environment.sh`
- Expected output: `runs/cwru-m15-probe-*/environment_probe.txt`.
- Success threshold: `core_smoke_ready=true`.
- Decision output: choose Docker, Apptainer/Singularity, Podman, native Java,
  or externally hosted backends from observed capabilities; do not assume
  Docker is available on Pioneer.
- Observed decision: use Podman for B2 packaging; B1 must explicitly load
  `Miniconda3` and select the dedicated pytest-capable interpreter.

### M15-B1 — CWRU CPU smoke

- Objective: reproduce the M15 contracts, coordinator, and split-source
  fixture on a Pioneer compute node without a GPU or live graph service.
- Entry command:
  `sbatch --parsable scripts/slurm/run_m15_core_smoke.sbatch`.
- Environment: the job loads `${XGAP_PYTHON_MODULE:-Miniconda3}` and uses
  `${XGAP_PYTHON:-python}`. A dedicated user-owned environment may be selected
  without changing the script.
- Timeout: 15 minutes.
- Expected outputs: `run_status.json`, `environment.txt`, `pytest.txt`,
  `vertical_slice.json`, and `job.log` below the job-owned run directory.
- Success threshold: the status is `success`, all 34 M15 tests pass, the
  vertical slice returns exactly one row, uses two remote calls, and records
  positive transferred bytes.

## Typed remote-control entry

`python -m xgap.experiments.remote_control` exposes the same batch lifecycle
as an agent tool. It reads only non-secret configuration:

- `XGAP_REMOTE_HOST_ALIAS` and `XGAP_REMOTE_REPO_ROOT` are required;
- `XGAP_REMOTE_PYTHON` may point to the selected remote interpreter;
- `XGAP_REMOTE_JOB_PYTHON` and `XGAP_REMOTE_JOB_MODULE` are the only
  submission-environment values the executor may export;
- artifact roots, timeout, executor ID, and sbatch allowlist are optional;
- `XGAP_REMOTE_ALLOW_CANCEL=1` is the only value that enables cancellation.

SSH keys, Duo, VPN state, and passwords are never read from repository files.
Each invocation performs one requested operation with no implicit retry. The
server-side OnDemand handoff remains authoritative until the local machine has
VPN reachability and a working user-owned SSH alias.

### M15-B2 — Live backend packaging

- Objective: run isolated Neo4j and Fuseki services inside one scheduled
  allocation, or bind to approved persistent services, using the runtime
  selected by B0.
- Inputs: observed B0 runtime, pinned service versions, split-data fixture.
- Gate: both health checks, both native smoke queries, clean shutdown, and
  immutable service/version artifacts pass without exposing a public port.

### M15-B3 — Live federated vertical slice

- Objective: replace fixture clients with live backend plugins and execute one
  semantic program whose answer requires facts from both systems.
- Gate: neither backend alone produces the answer; the coordinator produces
  the hand-verified row; result equivalence, latency, rows, bytes, remote calls,
  and failure behavior are persisted.

### M15-C/D — Alternative plans, observations, memory, and replanning

- Add `inspect_schema`, `explain`, `profile`, and `sample` observations.
- Add at least two correct federated plans and controlled latency/cardinality
  changes that reverse the preferred plan.
- Compare static federation, no memory, no probe/profile, no replan, and the
  full agent under the same workload.

### M15-E — Selective semantic resolution and Qwen

- Integrate deterministic resolution first, clarification for identity
  ambiguity, catalog/ontology tools where informative, and bounded Qwen/vLLM
  fallback only when cheaper evidence cannot close a semantic hole.
- Measure LLM calls, GPU-seconds, planning latency, semantic deviation, and
  execution cost. The easy path must retain a zero-LLM condition.

### M15-F — Workload, baselines, ablations, and UI gate

- Freeze the synthetic federation workload before importing larger datasets.
- Add external datasets, catalog, and ontology through versioned adapters.
- Run correctness, cost, scaling, failure, and ambiguity experiments.
- Build the thin UI only after the CLI trace schema, remote executor, and one
  user-clarification action are stable. The UI is not an experiment runner.

## First user handoff

Open a CWRU OnDemand Terminal, synchronize the feature branch, run B0, and
return only `environment_probe.txt`. If `core_smoke_ready=true`, submit B1 and
return its `run_status.json`, `environment.txt`, `pytest.txt`, and
`vertical_slice.json`. No GPU job or live backend is started in this handoff.
