# M15 Remote Execution Loop

## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: plan
- Origin Date: 2026-09-04
- Verification Status: CWRU B2D/D2/F0/F1L/F2A/F2B4/F2C10D/F2C12B VERIFIED; F2C13B PAIRED LIVE GATE LOCAL; F2C13C SUMMARY LOCAL
- Version Label: m15_remote_loop_v31

## Current claim boundary

The legacy M13 Qwen/vLLM path has run on CWRU Pioneer. The M15 agentic
federated core has now also passed a real Neo4j-plus-Fuseki service gate. XGAP
can claim one audited live two-engine vertical slice through public backend
interfaces. It cannot yet claim paper-scale performance, streaming transport,
or live cancellation. A controlled local M15-D1 loop now persists observation
snapshots across processes, runs a declared common probe prefix, and permits
one evidence-triggered plan change without repeating the probe. This is an
orchestration sanity check, not a live adaptive-backend or paper result. A
separate live-service adaptive mode is now implemented locally: it collects a
finite three-observation planning tuple, persists and reopens the complete
snapshot, executes the two-engine query with at most one replan, and emits a
mode-aware immutable evidence bundle. CWRU job `3787152` verified that path on
real Neo4j and Fuseki. Its fixed cost model is not calibrated, the tiny fixture
did not warrant a plan change, and its manifest therefore declares
`paper_result=false`.

The F1L runner is also verified on CWRU. A separate
`scaled_method_matrix` mode reuses one verified workload and native-service
allocation, accounts one common calibration outside method metrics, and then
executes six frozen policies in explicit phases. The read-only auditor checks
their 18-call budget, exact answers, isolated memory histories, lifecycle, and
cleanup. Because order is fixed and backend cache state is shared and unknown,
this is a live mechanism gate, not a performance comparison. Job `3787267`
completed at exact clean commit `6aafafd`; all six methods returned the exact
answer and its independent read-only audit passed 326/326 checks without
mutating the run tree.

The F2A runner is verified on CWRU. It recompiles
the committed development campaign, requires the expected campaign and
schedule hashes, binds the selected workload to both source and normalized
bundle-spec hashes, and lets that session's Williams order drive the existing
six-method runner. The native lifecycle performs the preflight before service
startup, and the auditor reconstructs the same selection independently. This
gate still executes one query and one sequence, so it does not establish
cross-task memory benefit or a counterbalanced comparison. Job `3787291` ran
the selective `b01.s01` sequence at exact clean commit `c9a7afe` on
`compt336`, returned exact answers for all six methods with an 18-call,
zero-retry trace, and cleaned up its runtime. The independent read-only audit
passed 374/374 checks and did not mutate the run tree.

Refreshed D1 CPU job `3787126` ran exact clean commit `4c26eea` on `compt331`
and completed in 28 seconds with exit `0:0`. Its immutable run tree contains
all seven declared artifacts, 128 focused tests passed with two gated skips,
and the vertical-slice, alternative-selection, and bounded-replanning
assertions all passed. This verifies the published offline control substrate;
it is not a live-service or paper-performance result.

The first D2 submission, job `3787144` at exact clean commit `ee52c86`, failed
on `compt336` after two seconds and made no service or query attempt. Slurm ran
the copied wrapper as `/var/spool/slurm/job3787144/slurm_script`; deriving a
sibling path from `BASH_SOURCE[0]` therefore looked for the service script in
the spool directory. The wrapper now resolves the checkout from the explicit
`XGAP_REPO_ROOT` or Slurm's `SLURM_SUBMIT_DIR`, validates both repository
markers before sourcing, and exports the same root to the main lifecycle. The
failed job is preserved as evidence, not retried in place.

The explicitly new D2 job `3787152` then ran exact clean commit `247e714` on
`compt336` and completed in 96 seconds with exit `0:0`. It used Neo4j 5.26.30,
Fuseki 5.6.0, Java 17, loopback-only services, and allocation-local XFS. The
read-only audit passed all 173 checks without mutating the run tree. The exact
tool trace contained three planning-profile calls followed by two query calls,
and the two append-only memory versions were reopened successfully. Both the
initial and post-probe selector chose `m15-parallel-hash`, so zero replans was
the correct observed control outcome. The exact one-row answer used two query
calls and moved 530 bytes. This closes the live adaptive engineering gate, not
the calibration, scale, or comparative-performance gates; the compact record
is `experiments/artifacts/m15_d2_cwru_native_adaptive_20260905.json`.

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

B2 prerequisite job `3784980` ran exact commit `1d7af1d` on `compt386` and
completed in 36 seconds with exit `0:0`. It verified loopback binding, curl,
wget, tar, SHA-256/SHA-512 tools, `setsid`, and `timeout`. It also exposed an
important v1 probe defect: the inherited `java` executable was OpenJDK 8, but
the v1 readiness flag checked only command presence and incorrectly reported
`native_service_prerequisites_ready=true`. The module inventory advertises
`Java/17.0.6`, while no Java 21 module is available. Probe v2 now parses both
legacy and modern Java version output, attempts the pinned Java 17 module when
needed, and requires a compatible major version before reporting readiness.
The successful v1 job remains evidence; its invalid derived readiness flag is
not used.

The same job showed that both the checkout and home directory are on
`vstorvip.lb.cwru.edu:/home`. Verified archives may be cached there, but live
database state will be extracted and run only on allocation-local storage
after an explicit filesystem preflight. No service data directory will be
placed on that network filesystem.

B2B artifact-supply job `3787101` ran commit `2ce4b53` on `compt398` and
completed in 16 seconds with exit `0:0`. The manifest records two total download
attempts, one for each product, and zero automatic retries. Neo4j Community
5.26.30 matched the locked 162,360,826-byte SHA-256; Fuseki 5.6.0 matched the
locked 50,290,245-byte SHA-512. No archive was extracted, no service was
started, and no credentials were persisted. The shared cache can be reused by
the allocation-scoped service job without another network request.

B2D/B3 job `3787110` then ran exact clean commit `cd564de8` on `compt331` in
62 seconds. It used Java 17 and allocation-local XFS, started Neo4j 5.26.30 and
Fuseki 5.6.0 on loopback-only ports, loaded and verified the vertically split
fixture, and returned the exact federated answer with two remote calls. Both
services stopped in reverse order without kill escalation and the wrapper
removed the validated runtime root. The separate read-only audit returned exit
0 with all 102 checks passing, no failed IDs, and no mutation of the completed
run tree.

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

Status: **VERIFIED**, most recently by job `3787126` on `compt331`.

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
  The published `4c26eea` wrapper used by job `3787126` includes the B2A
  loader, B2B artifact-supply, B2C allocation-staging, B2D service-lifecycle,
  observation, alternative-plan, persistent-memory, continuation, and bounded
  replanning suites and therefore expects 128 passes and two gated skips. The
  subsequent C2/D2 wrapper adds the live adaptive and mode-aware audit
  regressions and passes 140 tests with the same two skips. Job `3787152`
  verified that live path independently against the real services. The current
  F0 wrapper also covers deterministic workload generation, scaled plans, and
  profile-to-spec audit binding and expects 159 passes with two gated skips;
  that refreshed CPU wrapper has not yet run on CWRU.
- Refreshed gate: job `3787126` completed at exact clean commit
  `4c26eea06c94c4ac0d650c56cf50b8da051a91bb` in 28 seconds on `compt331`.
  The scheduler exit was `0:0`; all seven expected artifacts were present;
  128 tests passed with two gated skips; and the three demonstration oracles
  passed. The compact evidence record is
  `experiments/artifacts/m15_d1_cwru_core_smoke_20260905.json`.

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
  B1 node. `probe_m15_native_services.sbatch` records Java/module availability,
  download, archive and hash tools, loopback binding, and filesystem evidence
  without downloading or starting a service.
- Observed prerequisite evidence: job `3784980` found OpenJDK 8 as the default,
  advertised Java modules through 17, no Java 21 module, all required archive
  tools, loopback binding, and an NFS-backed home directory. The v1
  command-presence readiness result is invalidated by its recorded Java 8
  version; probe v2 corrects this rather than rewriting the old artifact.
- Frozen native supply: `services/m15-native-runtime.lock.json` selects Neo4j
  Community `5.26.30` LTS and Apache Jena Fuseki `5.6.0`, which share the
  CWRU-provided Java 17 runtime. It records official HTTPS sources, exact byte
  lengths, SHA-256/SHA-512 digests, archive roots, and the runtime/storage
  policy. Jena 6 requires Java 21 and is therefore not made an undeclared
  cluster dependency.
- Artifact preparation: `xgap.experiments.m15_native_artifacts` performs at
  most one download attempt per archive, verifies size and digest before an
  atomic no-overwrite publication, rejects symbolic links and conflicting
  cache entries, and persists every partial failure. A verified cache is
  reused without a network call. The separately allowlisted
  `prepare_m15_native_artifacts.sbatch` downloads only these two archives to
  shared storage; it does not extract them or start a service.
- Allocation-local staging: `xgap.experiments.m15_native_runtime` re-verifies
  each cached archive, rejects unsafe or ambiguous tar layouts, extracts only
  regular files and directories through private temporary roots, and atomically
  publishes the two exact product directories into a new empty job-owned
  runtime root. Its durable manifest is outside the ephemeral root and records
  the first failure with zero retries. Staging does not start either service;
  the launcher must still verify the actual filesystem type, Java 17, loopback
  ports, health, and cleanup.
- Allocation lifecycle: `xgap.experiments.m15_native_services` and the
  allowlisted `run_m15_native_services.sbatch` require exact Java 17, stage on
  an allowlisted `SLURM_TMPDIR` or `/tmp` filesystem, use three dynamically
  reserved `127.0.0.1` ports, and keep all mutable backend state local to the
  allocation. The runner waits on the same processes without restart, loads
  the fixture once, executes the federated slice once, stops process groups in
  reverse order, archives logs and lifecycle evidence, and removes only the
  validated job-owned runtime path.
- Gate: both health checks, both native smoke queries, clean shutdown, and
  immutable service/version artifacts pass without exposing a public port.
- Evidence acceptance: `python -m xgap.experiments.m15_native_evidence`
  performs a read-only audit after the job finishes. It requires the exact full
  Git commit and cross-checks the frozen lock snapshot, archive digests,
  allocation-local staging, Java 17 record, loopback-only command and
  configuration, health, fixture load, final answer, shutdown, and guarded
  cleanup. Its report must be written outside the completed run tree, and it
  never retries or repairs a failed run.

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

- Implemented locally: registered `inspect_schema`, `explain`, `profile`, and
  `sample` observations; two correct federated plans; controlled cost changes
  that reverse selection; append-only versioned snapshot memory; and one
  bounded exact-prefix replan without duplicate remote work.
- The live adaptive runner declares exactly three planning observations,
  invokes each at most once, and publishes a snapshot only after the complete
  tuple succeeds. Neo4j contributes two native PROFILE results; Fuseki
  contributes one explicitly labeled wall-clock execution fallback. The
  persisted snapshot is reopened before the two-backend query, and the complete
  run records three profile plus two execute events, memory versions, plan
  snapshots, validation, and provenance.
- The adaptive workload is a separate native-service mode and Slurm entry
  point. The historical vertical-slice mode and job `3787110` remain unchanged.
  The same read-only auditor accepts a declared mode and enforces its exact
  schema and artifact contract.
- Verified external gate: job `3787152` ran the repaired wrapper at exact clean
  commit `247e714`; its read-only audit accepted 173/173 checks. Job `3787144`
  remains immutable and is not represented as a service-level failure.
- Remaining research gate: calibrate the cost model and exercise plan changes
  on scaled/skewed workloads. The tiny fixture may legitimately select zero or
  one replan and is only a live control-path gate, not performance evidence.
- Compare static federation, no memory, no probe/profile, no replan, and the
  full agent under the same workload. The local `scaled_method_matrix` runner
  and auditor implement this mechanism gate. CWRU job `3787267` completed it
  with all exact answers and an independently accepted 18-call trace.

### M15-E — Selective semantic resolution and Qwen

- Integrate deterministic resolution first, clarification for identity
  ambiguity, catalog/ontology tools where informative, and bounded Qwen/vLLM
  fallback only when cheaper evidence cannot close a semantic hole.
- Measure LLM calls, GPU-seconds, planning latency, semantic deviation, and
  execution cost. The easy path must retain a zero-LLM condition.

### M15-F — Workload, baselines, ablations, and UI gate

- F0 locally freezes two bounded specifications over 200 companies and 5,000
  transfers. The selective profile has 20 high-risk cold companies and 120
  exact answer rows; the broad-hot profile has 160 high-risk companies and
  4,800 exact answer rows.
- Generated Neo4j/Fuseki loads, native queries, source oracles, and the final
  oracle exist only in the no-overwrite run tree and are SHA-256 bound. The
  read-only audit binds the requested profile to its committed spec.
- `run_m15_native_scaled_adaptive.sbatch` exposes only `selective` and
  `broad_hot` through a separate `scaled_adaptive` mode. The first CWRU gate is
  one selective run; it is not a paper result.
- First selective job `3787167` at commit `36281aa` failed at the first Neo4j
  load `UNWIND` before all planning and query calls. Its v1 bundle used JSON
  object syntax where Cypher requires identifier map keys. The allocation
  cleaned up successfully. Generator v2 is the only admitted repaired format;
  the failed run is recorded in
  `experiments/artifacts/m15_f0_cwru_scaled_selective_failure_20260905.json`.
- Second selective job `3787173` at clean commit `3a2bce9` passed the syntax
  boundary and made both services healthy, but the sixth and final Neo4j load
  statement embedded all 5,000 transfers and timed out after five statements
  succeeded. It made zero profile and query calls. Generator v3 and bundle
  schema v2 now fix batches at 100 rows and declare all 56 selective statements
  in the manifest, without changing the timeout or zero-retry policy. The run
  is preserved in
  `experiments/artifacts/m15_f0_cwru_scaled_selective_timeout_20260905.json`.
- Third selective job `3787213` at clean commit `32c157f` completed on
  `compt336`: Neo4j loaded all 56 fixed batches, the exact 120-row answer used
  risk-first bind with two remote calls and 28,702 bytes moved, and the
  independent read-only audit passed 188/188 checks with no run-tree mutation.
  Its compact engineering record is
  `experiments/artifacts/m15_f0_cwru_scaled_selective_success_20260905.json`;
  one run with an uncalibrated model remains `paper_result=false`.
- F1 defines six executable task policies with exact memory-context
  compatibility and a controlled paired matrix. The separate
  `run_m15_native_method_matrix.sbatch` entry point now executes the six-policy
  real-service mechanism gate without mixing its artifacts into F0. It uses a
  fixed order and shared unknown cache, so verified CWRU job `3787267` remains
  non-comparative despite passing all 326 independent audit checks.
- F2 locally compiles a seeded six-sequence Williams schedule per workload and
  block and proves exact position and directed first-order carryover balance
  without starting services or calling a backend. Its development input has
  only one query per workload, so it cannot measure cross-task memory and is
  not ready for paper comparison.
- F2A now admits exactly one compiled development session to a new native
  service mode. It validates campaign/spec/schedule/bundle/session/order
  binding before service startup, executes the declared six-method order, and
  exposes a read-only audit over the complete nested evidence tree. The CWRU
  gate is one selective sequence only; full campaign dispatch is not enabled.
  That gate passed as CWRU job `3787291` with a 374-check read-only audit.
- Add external datasets, catalog, and ontology through versioned adapters.
- Run correctness, cost, scaling, failure, and ambiguity experiments.
- Build the thin UI only after the CLI trace schema, remote executor, and one
  user-clarification action are stable. The UI is not an experiment runner.

## Next user handoff

B0, both B1 CPU gates, B2 prerequisite, B2B supply, B2D service lifecycle, B3
federated execution, D2 live adaptation, F0 selective execution, F1L live
method execution, and their independent evidence audits are complete. Keep
jobs `3787110`, `3787126`, `3787152`, `3787213`, and `3787267` and their run
trees immutable. D2 job `3787144` remains a separate pre-service wrapper
failure; preserve its top-level output. F2A job `3787291` and its run tree are
now immutable evidence. F2B1--F2B3 compile the resolved query contract, bind
it into the development campaign, and recompute it from the selected live
bundle before output or backend observation. F2B4 carries that v2 identity
through a fresh native lifecycle, a dedicated allowlisted Slurm wrapper, and
an independent auditor that recompiles the contract from the run bundle.
F2C4 job `3787592`, F2C5 job `3787610`, and F2C7B2 job `3787648` are now
immutable accepted mechanism evidence. F2C5 completed at commit `30214cb` and
passed all 278 dedicated checks; F2C7B2 completed at exact clean commit
`2197aef` and passed all 133 dedicated checks. Neither audit changed its run
tree. Do not resubmit these jobs or dispatch the remaining development
campaign sessions. F2C6/F2C7B1 remain local planning and artifact gates. The
F2C8A provides versioned payment-predicate data, compiler, oracle, and
coordinator plumbing. F2C8B job `3790680` has completed at exact commit
`2d39c3c`; its two exact answers and 150/150 audit are immutable accepted
mechanism evidence and must not be rerun. F2C9A builds the capability-aware
direct frontier, and F2C9B now adds its native lifecycle, versioned controlled
estimate source, selected-only executor, allowlisted Slurm wrapper, and
independent auditor. The one authorized `semantic_direct_frontier` CWRU job,
`3791375`, completed at exact commit `2c0ee7f` on `compt298` in 94 seconds with
exit `0:0`. Do not rerun it. Its first audit used the wrong outer directory
for the service-owned preflight seal and emitted 20 false missing-artifact
failures. The corrected auditor was then run read-only against the unchanged
tree and passed 211/211 checks with no mutation. F2C9B is accepted mechanism
evidence; do not interpret its controlled selection as a performance
comparison.

F2C10A--F2C10C are locally accepted and require no CWRU dispatch. The first
F2C10D submission, job `3791589` at clean commit `d4db59a`, failed before any
fixture mutation or pilot plan call. The pre-service schedule seal exists, but
fixture handoff tried to reopen the nested predicate-extended workload with the
base parameterized-bundle loader and correctly rejected its schema. Guarded
cleanup succeeded and no automatic retry occurred. The producer now
revalidates the enclosing direct-semantic workload at fixture time; the base
schema allowlist is unchanged. Preserve the failed run and do not audit or
rerun it. The repair passes the 899-test full local suite with 36 gated skips.

The one explicitly new F2C10D repair job was submitted as job `3791600` at
exact clean commit `08f1911dfab2617e2598df91578fa0997f90eb11`. Do not submit
another job while it is pending or after it succeeds. Its frozen development
protocol measures 144 counterbalanced training
plan runs, seals family memory and two independent held-out query frontiers
with zero current-query profiling, executes 2--8 returned online plans, and
then executes 80 shadow plan runs. The valid total is 226--232 plan runs and
452--464 plan backend calls. Each request has a 60-second timeout, the Slurm
wrapper reserves 45 minutes, failure stops on the first error, and no retry is
allowed. The submitted command was:

```bash
cd "$HOME/XGAP-m15-465e2e2"

test -z "$(git status --porcelain)" || {
  echo "checkout is dirty; stop"
  exit 1
}

git fetch --prune origin
git switch codex/m15-f2c10-family-memory-prediction
git pull --ff-only origin codex/m15-f2c10-family-memory-prediction

git rev-parse HEAD
git status --short

sbatch --parsable \
  --export=ALL,XGAP_PYTHON="$HOME/venvs/xgap-core/bin/python",XGAP_PYTHON_MODULE=Miniconda3,XGAP_JAVA_MODULE=Java/17.0.6 \
  scripts/slurm/run_m15_native_direct_family_pilot.sbatch
```

After the job finishes, inspect `sacct` and the outer `run_status.json`. If and only if both
report success, run the independent auditor once with a new output path:

```bash
cd "$HOME/XGAP-m15-465e2e2"
XGAP_F2C10D_JOB=<successful-job-id>
XGAP_F2C10D_COMMIT=<exact-40-character-job-commit>
XGAP_F2C10D_RUN="$PWD/runs/cwru-m15-native-direct-family-pilot-$XGAP_F2C10D_JOB"
XGAP_F2C10D_AUDIT="$PWD/runs/audits/cwru-m15-f2c10d-direct-family-pilot-$XGAP_F2C10D_JOB-audit.json"

mkdir -p "$PWD/runs/audits"
test ! -e "$XGAP_F2C10D_AUDIT" || {
  echo "audit output already exists; stop"
  exit 1
}

PYTHONPATH="$PWD/src" \
"$HOME/venvs/xgap-core/bin/python" \
  -m xgap.experiments.m15_direct_family_pilot_evidence \
  --run-root "$XGAP_F2C10D_RUN" \
  --expected-commit "$XGAP_F2C10D_COMMIT" \
  --output "$XGAP_F2C10D_AUDIT" \
  > "$XGAP_F2C10D_AUDIT.stdout"

echo "audit_exit=$?"
```

When `audit_exit=0`, pull the current branch (the completed run still remains
bound to its original commit) and produce one compact, claim-bounded result
outside the immutable run tree:

```bash
cd "$HOME/XGAP-m15-465e2e2"
git pull --ff-only origin codex/m15-f2c10-family-memory-prediction

XGAP_F2C10D_SUMMARY="$PWD/runs/audits/cwru-m15-f2c10d-direct-family-pilot-$XGAP_F2C10D_JOB-summary.json"
test ! -e "$XGAP_F2C10D_SUMMARY" || {
  echo "summary output already exists; stop"
  exit 1
}

PYTHONPATH="$PWD/src" \
"$HOME/venvs/xgap-core/bin/python" \
  -m xgap.experiments.m15_direct_family_pilot_summary \
  --run-root "$XGAP_F2C10D_RUN" \
  --audit "$XGAP_F2C10D_AUDIT" \
  --output "$XGAP_F2C10D_SUMMARY" \
  > "$XGAP_F2C10D_SUMMARY.stdout"

cat "$XGAP_F2C10D_SUMMARY"
```

F2C11 was frozen on a separate branch before job `3791600` completed. After
the F2C10D audit and compact summary both succeed, switch to that branch and
produce the result-blind physical comparison outside the source run tree. The
analyzer reruns the F2C10D audit read-only, so any post-audit mutation fails:

```bash
cd "$HOME/XGAP-m15-465e2e2"

git fetch --prune origin
git switch codex/m15-f2c11-physical-baselines
git pull --ff-only origin codex/m15-f2c11-physical-baselines

XGAP_F2C11_ANALYSIS="$PWD/runs/audits/cwru-m15-f2c11-physical-baselines-$XGAP_F2C10D_JOB.json"
test ! -e "$XGAP_F2C11_ANALYSIS" || {
  echo "baseline output already exists; stop"
  exit 1
}

PYTHONPATH="$PWD/src" \
"$HOME/venvs/xgap-core/bin/python" \
  -m xgap.experiments.m15_direct_family_baselines \
  --run-root "$XGAP_F2C10D_RUN" \
  --audit "$XGAP_F2C10D_AUDIT" \
  --policy experiments/configs/m15_f2c11_physical_baselines_dev.json \
  --output "$XGAP_F2C11_ANALYSIS" \
  > "$XGAP_F2C11_ANALYSIS.stdout"

echo "baseline_exit=$?"
cat "$XGAP_F2C11_ANALYSIS"
```

Only after the analyzer exits zero, run its independent reconstruction audit.
The output name is unique and neither artifact may be placed below the F2C10D
source run:

```bash
XGAP_F2C11_AUDIT="${PWD}/runs/audits/\
cwru-m15-f2c11-physical-baselines-${XGAP_F2C10D_JOB}-audit.json"
test ! -e "$XGAP_F2C11_AUDIT" || {
  echo "baseline audit output already exists; stop"
  exit 1
}

PYTHONPATH="$PWD/src" \
"$HOME/venvs/xgap-core/bin/python" \
  -m xgap.experiments.m15_direct_family_baselines_evidence \
  --run-root "$XGAP_F2C10D_RUN" \
  --source-audit "$XGAP_F2C10D_AUDIT" \
  --policy experiments/configs/m15_f2c11_physical_baselines_dev.json \
  --analysis "$XGAP_F2C11_ANALYSIS" \
  --output "$XGAP_F2C11_AUDIT" \
  > "$XGAP_F2C11_AUDIT.stdout"

echo "baseline_audit_exit=$?"
cat "$XGAP_F2C11_AUDIT"
```

This comparison makes no backend, profile, sample, explain, LLM, or ontology
call. It is an exploratory physical-choice analysis over ten held-out semantic
tasks, not a semantic-frontier comparison or a substitute for a later live
current-query-profiling baseline. The independent audit must report success,
no failed checks, and no source-run mutation before the comparison is admitted.
Do not add path execution until its hard-constraint semantics are frozen.
Hash-bound multi-family execution and all paper campaign dispatch remain
disabled.
No paper-performance claim is currently made.

## F2C12B current-query profile baseline

F2C12B is the cost-inclusive comparator frozen before the accepted F2C10D and
F2C11 metrics were read. Its dedicated native entry runs 20 full-plan profile
acquisitions, seals ten latency/bytes/plan-ID choices, executes those ten
choices, and then runs 80 evaluation-only shadows. The valid completed tree
has 110 plan runs and 220 backend calls, zero retry, zero memory/LLM/ontology
input, and `paper_result=false`.

CWRU job `3791649` completed this exact protocol at clean commit `64f750b` on
`compt268`. The outer, service, and live status chain succeeded, and the
independent outer-root audit passed 1,185/1,185 checks with no mutation.
Preserve this run and do not resubmit it. The allocation-local development
result selected 10/10 observed latency winners, but raw timing must not be
compared with F2C10D job `3791600` because the allocations differ.

F2C13B implements the frozen F2C13A schedule as one fail-closed native job.
It seals the schedule before service startup, executes 144 training, 20
profile-acquisition, 20 method-specific selected, and 80 shared-shadow runs,
and stops at the first failure with zero retry. Family selection is sealed
before profiling, and profile selection is sealed before either selected or
shadow execution. Its independent auditor recompiles the schedule from the
copied source inputs, rebuilds family memory and both choices, recomputes the
paired analysis, and verifies the exact 528-call phase/run order without
mutating the run tree. Full local acceptance passes 939 tests with 36 explicit
environment or external-artifact skips. One clean CWRU run and its successful
outer-root audit are now the next gate; no result is claimed yet.

After that one F2C13B job succeeds, run its independent auditor once from the
same exact experiment commit. Do not retry a failed job or overwrite an audit:

```bash
cd "$HOME/XGAP-m15-465e2e2"
XGAP_F2C13B_JOB=<successful-job-id>
XGAP_F2C13B_COMMIT=cf3d430dfe952e7fdbdcf8cc65c1d02cb4e7c660
XGAP_F2C13B_RUN="$PWD/runs/cwru-m15-native-paired-physical-comparison-$XGAP_F2C13B_JOB"
XGAP_F2C13B_AUDIT="$PWD/runs/audits/cwru-m15-f2c13b-paired-$XGAP_F2C13B_JOB-audit.json"

mkdir -p "$PWD/runs/audits"
test ! -e "$XGAP_F2C13B_AUDIT" || {
  echo "audit output already exists; stop"
  exit 1
}

PYTHONPATH="$PWD/src" \
"$HOME/venvs/xgap-core/bin/python" \
  -m xgap.experiments.m15_paired_physical_comparison_evidence \
  --run-root "$XGAP_F2C13B_RUN" \
  --expected-commit "$XGAP_F2C13B_COMMIT" \
  --output "$XGAP_F2C13B_AUDIT" \
  > "$XGAP_F2C13B_AUDIT.stdout"

echo "audit_exit=$?"
```

Only when that exit is zero, switch to F2C13C and create one compact summary
outside the immutable run tree:

```bash
git fetch --prune origin
git switch codex/m15-f2c13c-paired-summary
git pull --ff-only origin codex/m15-f2c13c-paired-summary

XGAP_F2C13C_SUMMARY="$PWD/runs/audits/cwru-m15-f2c13c-paired-$XGAP_F2C13B_JOB-summary.json"
test ! -e "$XGAP_F2C13C_SUMMARY" || {
  echo "summary output already exists; stop"
  exit 1
}

PYTHONPATH="$PWD/src" \
"$HOME/venvs/xgap-core/bin/python" \
  -m xgap.experiments.m15_paired_physical_comparison_summary \
  --run-root "$XGAP_F2C13B_RUN" \
  --audit "$XGAP_F2C13B_AUDIT" \
  --output "$XGAP_F2C13C_SUMMARY" \
  > "$XGAP_F2C13C_SUMMARY.stdout"

echo "summary_exit=$?"
cat "$XGAP_F2C13C_SUMMARY"
```

F2C13C does not rerun a backend or reinterpret an unaudited result. It keeps
historical training cost separate, reports the current-query profile cost, and
retains the frozen single-allocation descriptive boundary. Do not select the
paper-scale multi-family domains from this ten-task result alone.

## E2B live resolution compatibility rerun

CWRU job `3792284` at exact commit `953f15f` reached a healthy Qwen3-32B
service but failed before generation because vLLM 0.11.1 rejected
`uniqueItems` in the guided-decoding schema. Preserve that failed run. Do not
audit it and do not resubmit the old commit. It spent exactly one provider
request, with zero repair calls, zero retries, and zero generated tokens.

The compatibility branch removes only the unsupported provider-facing schema
keyword. XGAP's deterministic validator still rejects duplicate, out-of-set,
empty, and oversized candidate selections. After the replacement commit is
published, submit exactly one fresh `run_m15_live_resolution.sbatch` job at
that exact clean commit. Keep the same frozen model, runtime, token budget,
timeout, and zero-retry contract. A successful replacement run may be audited
once with the existing E2B evidence command; a failed replacement run must be
returned without audit or retry.
