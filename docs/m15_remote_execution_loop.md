# M15 Remote Execution Loop

## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: plan
- Origin Date: 2026-09-04
- Verification Status: LOCALLY VERIFIED; CWRU B1 VERIFIED
- Version Label: m15_remote_loop_v5

## Current claim boundary

The legacy M13 Qwen/vLLM path has run on CWRU Pioneer. The M15 agentic
federated core has now passed its CPU smoke on Pioneer, but its live
Neo4j-plus-Fuseki path has not yet passed a two-engine service gate. Therefore
XGAP can claim server execution of the deterministic coordinator core, but not
live federated backend execution.

B0 observations on 2026-09-04 established an exact checkout at commit
`465e2e2454b74aaf7a1c055797740bde8ca5ace0`, working Slurm commands,
`gpu2h100`, and `/home/hxc859/venvs/xgap-vllm`. The login environment has no
default `python`; `module load Miniconda3` exposes Python 3.11.5. A separate
user-owned `/home/hxc859/venvs/xgap-core` environment now contains the editable
XGAP package and pytest, while the model-serving environment remains unchanged.
The generated untracked `src/xgap.egg-info/` metadata was removed and the
server checkout is clean again.

The final B0-v2 rerun on `hpc6` used commit
`4c45931a2a66a71154f4f48346e8fcc2eb9e6fbc` and the dedicated interpreter.
It reported `git_clean=true`, `pytest_available=true`,
`slurm_ready=true`, and `core_smoke_ready=true`; its artifact is
`runs/cwru-m15-probe-20260904T105823Z/environment_probe.txt`.

Container availability is node-dependent in the current evidence: Podman was
visible on `hpc5`, while none of Podman, Docker, Apptainer, or Singularity was
visible on `hpc7`. The authoritative B1 allocation on `compt365` also reported
`backend_runtime=none`, so login-node Podman is rejected as the Slurm service
strategy. B2 will probe user-space Java services inside an allocation.

B1 job `3784974` ran commit
`4c45931a2a66a71154f4f48346e8fcc2eb9e6fbc` on `compt365` and completed in
13 seconds with exit `0:0`. Its immutable artifacts report 40 tests passed,
one gated live test skipped, a successful one-row coordinator answer, two
remote calls, and 206 measured transfer bytes.

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
- Observed decision: B1 explicitly loads `Miniconda3` and selects the dedicated
  pytest-capable interpreter. Its allocated node exposed no container runtime,
  so B2 proceeds through a user-space Java prerequisite probe.

### M15-B1 — CWRU CPU smoke

Status: **VERIFIED** by job `3784974` on `compt365`.

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
- Verified threshold at commit `4c45931`: status `success`, 40 offline M15
  tests passed, one explicitly gated live test skipped, the vertical slice
  returned exactly one row with two remote calls and 206 transferred bytes.
  The next wrapper revision adds the B2A loader suite and therefore expects
  50 passes and two gated skips.

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
  allocation, or bind to approved persistent services, using the deployment
  path justified by compute-node evidence.
- Inputs: B1 compute-node runtime observation, pinned service versions, and
  the split-data fixture. A login-node-only runtime observation is
  insufficient.
- Portable load contract: `xgap.experiments.m15_fixture_loader` is independent
  of the service launcher. It applies namespaced idempotent Cypher statements,
  appends RDF through the Fuseki Graph Store HTTP endpoint, verifies both
  native source results exactly, omits credentials from artifacts, writes an
  immutable load manifest, and never retries. Its CLI is fail-closed unless
  `XGAP_LOAD_M15_FIXTURE=1` is explicitly set for dedicated M15 services.
  This loader is experiment bootstrap infrastructure, not a query-time agent
  tool, so a user query cannot mutate backend data.
- Compute-node decision: no supported container runtime exists on the verified
  B1 node. `probe_m15_native_services.sbatch` is the next read-only gate for a
  user-space Java deployment; it records Java/module availability, download,
  archive and hash tools, loopback binding, and filesystem evidence without
  downloading or starting a service.
- Gate: both health checks, both native smoke queries, clean shutdown, and
  immutable service/version artifacts pass without exposing a public port.

### M15-B3 — Live federated vertical slice

- Objective: replace fixture clients with live backend plugins and execute one
  semantic program whose answer requires facts from both systems.
- Local contract: `xgap.experiments.m15_live_federated` builds the typed
  semantic program and execution DAG, invokes the existing Neo4j and Fuseki
  clients through real backend plugins, and writes an immutable run directory.
  The fixture is vertically partitioned: Neo4j has identity/transfer facts but
  no company risk/name, while Fuseki has risk/name but no person/transfer facts.
- Gate: neither backend alone produces the answer; the coordinator produces
  the hand-verified row; result equivalence, latency, rows, bytes, remote calls,
  source hashes, health, status, and failure behavior are persisted. The live
  path is fail-closed behind `XGAP_RUN_M15_LIVE=1` and never retries
  automatically.

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

B0 and B1 are complete. After Codex publishes the B2A commit, synchronize the
clean CWRU checkout and submit exactly one
`probe_m15_native_services.sbatch` job. Return its `run_status.json`,
`environment.txt`, `java_modules.txt`, `java_version.txt`, and
`filesystem.txt`. No GPU job, download, or live backend is started by that
probe.
