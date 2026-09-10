# M15 Agentic Federated Core

Current checkout, active observations and next engineering actions are in
[engineering_state.md](engineering_state.md). The sections below retain
milestone-specific acceptance and historical intermediate gates. Later
accepted measurements supersede earlier “pending” statements only for the
same declared scope; local tests do not supersede an unmeasured live gate.

## Goal

Build an executable, experiment-first agentic federation layer on top of the
existing deterministic graph-query stack. M15 does not replace the audited path
algebra and does not claim access to backend-internal physical operators.

## M15-A — Contracts, tools, memory, and bounded goal loop

Status: **DONE locally**

Implemented:

- typed, backend-independent semantic DAGs with explicit value kinds,
  constraints, capabilities, and unresolved holes;
- typed tool specifications and success/error/unavailable observations;
- a plugin registry for black-box graph backends;
- an adapter that exposes existing `BackendClient` healthcheck and execution
  behavior without changing those clients;
- typed session/schema/execution/cache memory with provenance, version,
  confidence, and expiry;
- a finite goal loop with explicit success criteria, tool allowlist, step
  budget, tool-call budget, trace, and no automatic retry;
- a deterministic sequential policy used as the first baseline;
- offline tests and a two-backend adapter demonstration.

M15-A does not implement cross-source data movement, coordinator joins, plan
search, LLM policy decisions, live services, or a UI.

## M15-B — Executable two-engine vertical slice

Status: **REAL NEO4J+FUSEKI VERTICAL SLICE VERIFIED ON CWRU; STREAMING/CANCELLATION PENDING**

Goal: execute one hand-authored semantic program across Neo4j and Fuseki and
join the normalized results at the coordinator.

Required work:

- live Neo4j and Fuseki execution of the split-data fixture;
- streaming/batched rows beyond the current bounded in-memory row contract;
- cancellation for live remote work;
- one synthetic dataset whose facts are deliberately split across engines;
- exact end-to-end correctness, latency, bytes, row-count, and remote-call
  metrics.

Implemented locally:

- semantic-DAG compilation for Match, Traverse, Filter, Project, Join, Union,
  Aggregate, OrderLimit and Align with explicit source placements. Real tiny
  execution verifies all eighteen path programs on each engine plus eight
  compositions (six actually federated). The compiler constructs the DAG but
  does not yet connect automatic candidate generation/source selection or all
  semantic admission/control requirements; see
  [the T1 semantic gate](report/toy_backbone_t1_semantic_dag.md);
- per-backend `SemanticFragment` compilation through the existing M9 Cypher
  and SPARQL compilers;
- a bounded typed-path planner using native Rel/Seq/Alt and root finite
  recursive expansion plus coordinator selector execution. All eighteen toy
  queries have real two-engine evidence (one complete plan per engine), with
  an additional actual federated slice. This does not yet integrate every
  semantic DAG into general federated partitioning; see
  [T1 coverage](report/toy_backbone_t1_bounded_paths.md);
- an additional explicitly selected directed-row fragment compiler for fixed
  OUT/IN Rel/Seq paths, preserving positional conditions and producing ordinary
  runtime RemoteQuery artifacts; its independent RDFLib checks are not live
  Neo4j/Fuseki admission or general semantic-DAG compiler coverage (see
  [D195](report/directed_native_rows_v1.md));
- typed `RemoteQuery`, `Align`, `Exchange`, `CoordinatorJoin`, `Merge`, and
  coordinator `Project` runtime nodes;
- validated finite execution DAGs with remote-call and parallelism budgets;
- parallel execution of independent remote nodes;
- deterministic coordinator alignment, exchange accounting, hash join, merge,
  failure propagation, and skipped descendants;
- a `runtime.execute_plan` agent tool that returns rows and measured runtime,
  remote-call, and transfer metrics;
- a typed `remote.executor` boundary for exact-commit staging, allowlisted
  Slurm submission, status, bounded logs, artifact retrieval, and guarded
  cancellation;
- a non-secret environment-configured CLI for the same remote-executor
  contract;
- an offline split-fact fixture where the complete answer requires both
  backend plugins;
- a deterministic vertically partitioned Neo4j/Fuseki dataset, native query
  artifacts, and exact expected result;
- a deployment-neutral, explicitly gated fixture loader that uses only the
  backend/Graph Store HTTP boundaries, performs namespaced idempotent appends,
  verifies both source results exactly, stores no credentials, and persists
  partial failures without retry. It is experiment bootstrap infrastructure,
  not an agent-visible query tool;
- a frozen native-service supply lock and fail-closed preparation runner for
  exact Neo4j/Fuseki archives. The cache path is separate from runtime state,
  verified entries require exact length and digest, conflicting entries are
  never overwritten, downloads are never retried, and preparation cannot
  extract archives or start services;
- a fail-closed live runner that invokes the existing real Neo4j and Fuseki
  clients through backend plugins and persists semantic, plan, health, result,
  validation, status, source-hash, and manifest evidence without retrying.

Current full local acceptance passes 762 tests with 36 explicitly gated or
external-artifact tests skipped.

Remote execution is decomposed into explicit B0/B1 environment and CPU-smoke
gates before live services are started. Both gates are now verified. See
[`docs/m15_remote_execution_loop.md`](m15_remote_execution_loop.md). These
gates distinguish the previously exercised legacy M13 CWRU/vLLM path from the
M15 service path, which subsequently passed the B2D/B3 live gate. The newer
M15-C2/D2 adaptive-service mode subsequently passed its independent CWRU gate
in job `3787152`.

B0 artifacts established an exact checkout, working Slurm, visible
`gpu2h100`, an existing vLLM environment, Miniconda Python 3.11.5, and the
dedicated pytest-capable `xgap-core` environment. B1 job `3784974` then passed
the M15 CPU smoke at exact commit `4c45931` on `compt365`: 40 tests passed, one
live gate skipped, and the deterministic two-source coordinator result used
two calls and 206 transferred bytes. The compute node exposed no supported
container runtime, so login-node Podman is not the B2 strategy. B2 prerequisite
job `3784980` on `compt386` then verified loopback and archive tools, exposed
OpenJDK 8 as the incompatible default, advertised `Java/17.0.6` as the highest
available module, and identified `/home` as NFS-backed. The original probe's
presence-only readiness flag is invalidated; probe v2 now validates the Java
major. B2B consequently pins Neo4j 5.26.30 LTS plus the final Java-17 Fuseki
line, 5.6.0, caches only verified archives on shared storage, and reserves
allocation-local storage for extracted runtime state.

B2B job `3787101` then ran commit `2ce4b53` on `compt398` and admitted exactly
the two locked archives to the shared cache: Neo4j 5.26.30 passed its frozen
162,360,826-byte SHA-256 and Fuseki 5.6.0 passed its frozen 50,290,245-byte
SHA-512. Each artifact used one download attempt, `automatic_retries` was zero,
and the job neither extracted an archive nor started a service. This admitted
the allocation-scoped B2D service run at a clean commit containing the
read-only evidence auditor.

B2D job `3787110` ran exact clean commit `cd564de8` on `compt331`. It staged
the locked products on allocation-local XFS, loaded the split fixture, and
executed the live coordinator path through the Neo4j and Fuseki HTTP plugins.
The exact one-row answer used two remote calls. Both loopback-only services
shut down without `SIGKILL`, the job-owned runtime was removed, and the
separate read-only audit passed all 102 checks with no mutation. This closes
the real two-engine vertical-slice gate, but it is engineering acceptance—not
a paper performance result—and does not close streaming/batching or live
cancellation.

Acceptance gate:

1. neither backend alone can answer the complete question;
2. the coordinator returns the hand-verified answer from both backends;
3. all remote calls, transferred bytes, intermediate cardinalities, and local
   join time are persisted;
4. no LLM or ontology is required;
5. offline tests remain independent of live services, and live tests are
   explicitly gated.

## M15-C — Nontrivial plan space and observation tools

Status: **LIVE OBSERVATION PATH VERIFIED ON CWRU; CALIBRATION AND SCALE PENDING**

Implemented in the first closed slice:

- a versioned, coordinator-owned observation catalog that exposes only
  registered read-only schema, query, and bounded-sample artifacts;
- black-box `inspect_schema`, `explain`, `profile`, and `sample` operations,
  with explicit `unavailable` outcomes when an engine lacks a capability;
- Neo4j HTTP `EXPLAIN` and `PROFILE` observations whose native plans remain
  evidence rather than XGAP physical operators;
- executable `RemoteBindQuery` and coordinator `SemiJoin` runtime nodes,
  including binding limits, an empty-binding short circuit, deterministic
  deduplication, call accounting, and transitive failure skipping;
- exact-semantic M15 `parallel-hash` and `risk-first-bind` plans;
- a frozen-snapshot selector using critical-path latency and explicit exchange
  bytes, with deterministic tie breaking and complete observation provenance.

The controlled M15 sanity check executes both plans to the same exact answer,
moves 530 versus 363 fixture bytes, selects bind under transfer pressure, and
flips to parallel when bound-query latency is increased. It is explicitly
marked `paper_result=false`; live profile-derived calibration is still pending.

The next slice adds a finite observation collector over the registered
catalogs. It validates the full request and cost-model contract before any
backend call, invokes each profile/sample once in declared order, retains
partial evidence on failure, and publishes a snapshot only after the complete
request tuple succeeds. The M15 live contract uses native Neo4j `PROFILE` for
the full and bound transfer artifacts and an explicit wall-clock execution
fallback for Fuseki's registered high-risk artifact. This path is implemented
and offline-tested, and CWRU job `3787152` verified all three observations
against the real services.

Alternative fragmentation, generalized pushdown/join-order enumeration,
fragment fusion, and paper-scale observations remain future M15-C work.

Acceptance gate: at least one workload has multiple correct executable plans,
and the selected plan changes under controlled cardinality or latency changes.

## M15-D — Memory-guided adaptation and replanning

Status: **LIVE ADAPTIVE RUNNER AND F1 LIVE METHOD MATRIX VERIFIED ON CWRU; PAPER CAMPAIGN PENDING**

Use versioned capability and execution memory across tasks, and permit explicit
within-query replanning after observations invalidate the current estimate.

The first slice adds an append-only JSONL memory backend, immutable snapshot
versions, an ancestor-closed scheduler continuation boundary, and a one-replan
adaptive executor. A probe must be an exact common prefix of every candidate
before any remote call. Its successful rows and accounting are reused by the
selected continuation; a failed probe is retained as evidence and does not
trigger a fallback query. The controlled demo starts from stale task memory,
changes selection from parallel hash to risk-first bind after a measured
latency deviation, returns the exact answer with two total remote calls, and
reloads the updated snapshot from disk. It is not a live or paper result.

Required baselines: static federation, no memory, no profile/probe, no replan,
and full agent. F1 now implements two fixed-plan static controls plus explicit
`no_memory`, `no_profile_probe`, `no_replan`, and `full_agent` policies. Plan
memory is reusable only under an exact context fingerprint over semantics,
candidate DAGs/artifacts, observations, cost model, workload, and catalogs.
Cold full-agent tasks profile and persist; warm tasks skip the three profiles,
probe one common prefix, and may change plan once. The controlled paired
matrix proves that the six methods have different action traces and preserve
one exact answer. It remains `paper_result=false`; a live repeated matrix is
pending. CWRU job `3787152` verified the earlier real-backend adaptive path,
including its legitimate zero-replan branch on the tiny fixture.

F1L composes those policies with the allocation-scoped native-service
lifecycle. It loads one verified workload, performs one separately accounted
three-observation calibration, seeds isolated memory histories for the three
warm methods, and executes all six policies with independent tool-event and
answer artifacts. The fail-closed auditor binds the workload hashes, policies,
18-call trace, snapshot identities, exact rows, service lifecycle, and guarded
cleanup. CWRU job `3787267` executed this path at exact clean commit
`6aafafd` on `compt336`; all six methods returned the exact answer, the
declared phase counts summed to 18 calls, runtime cleanup succeeded, and the
independent read-only audit passed 326/326 checks without mutating the run
tree. Fixed order, one selective workload, an uncalibrated cost model, and
shared unknown backend cache state remain explicit, so this is an engineering
mechanism gate rather than a latency comparison.

M15-D2 now has a separate fail-closed live runner. Within one query attempt it
accounts for exactly three planning-profile calls and two query calls, stores
the profile and runtime-updated snapshots in append-only memory, and persists
candidate plans, probe plan, tool invocations, exact answer, plan selections,
and replan decision. The allocation-scoped service lifecycle exposes this only
through an explicit `adaptive` workload mode; the previously audited vertical
slice remains the default. A mode-aware read-only auditor checks the full
service, fixture, observation, memory, query, and cleanup chain. All current
cost constants are explicitly uncalibrated development parameters and the run
is labeled `paper_result=false`.

Job `3787152` ran this mode at exact clean commit `247e714` on `compt336`.
The read-only audit passed 173 checks with no mutation, the exact
three-profile/two-execute trace and two memory versions were present, and the
federated answer was exact. Both selectors chose `m15-parallel-hash`, so the
run establishes the live no-replan outcome rather than a plan-flip result.
Scaled/skewed workloads and calibration are required before performance claims.

## M15-E — Selective semantic resolution

Status: **E1/E2A/E3/E4/E5/E5B/E5C VERIFIED LOCALLY; E2B, E4B, AND E5D LIVE GATES VERIFIED ON CWRU; E6C LOCAL CLARIFICATION WORKING SURFACE VERIFIED; REMOTE UI SUBMISSION AND MODEL-CONTEXT RUNTIME VALIDATION PENDING**

Integrate deterministic parsing, the preserved interpretation prototype,
catalog/ontology lookup, clarification, and the existing bounded LLM provider.
Easy cases use zero LLM calls; unresolved identity ambiguity asks the user;
hard constraints remain immutable.

M15-E1 implements the finite routing and tool contracts. A fully bound program
succeeds with zero tool calls. Empty candidate sets may invoke a bounded catalog;
predicate/type ambiguity may next invoke ontology lookup and, only when enabled,
one bounded LLM proposal. Entity ambiguity cannot enter either ontology or LLM
and requires one authoritative clarification chosen from the bounded identity
candidates. The LLM tool rejects new candidate IDs, authoritative claims,
native-query metadata, and more than one external call. Every result appears in
the normal goal trace and execution memory; failed calls are not retried, while
unavailable optional semantic tools remain explicit observations.

M15-E2A adds a dedicated OpenAI-compatible candidate provider and a frozen
Qwen3-32B CWRU model bundle. It does not reuse the M12 `PathPatternQuery`
response shape: every request derives a strict candidate-ID schema from the
current bounded set, caps the response at eight IDs and 256 tokens, permits one
request with a 60-second deadline, and disables repair calls. Entity requests,
missing credentials, or prompt/schema drift fail before the network. A timeout,
transport failure, malformed response, or out-of-set response becomes one
costed tool error with no retry; successes and failures both retain call,
latency, and token evidence. The provider remains non-authoritative and emits no
backend-native query text.

E2A was verified with an offline transport before the separate E2B live gate.
Real catalog/ontology wiring, UI clarification transport, deterministic
parser-to-hole construction, and execution remain separate stages. Focused
E1/E2 acceptance passes 42 tests; E2B is accounted independently below.

M15-E2B supplies that fail-closed lifecycle and auditor. One frozen
predicate request is sealed before Qwen3-32B startup, executes through the
ordinary goal loop and execution memory, and permits one inference request with
zero repair or retry. Readiness uses `/v1/models`; the generic structured-output
smoke is omitted because it would add another inference request. The independent
auditor reconstructs the preflight, CWRU runtime/model identity, bounded output,
tool/invocation/memory links, shutdown, and every inventory hash without
modifying the run tree. The first CWRU job, `3792284`, reached the model but
vLLM 0.11.1 rejected `uniqueItems` before generation. That spent one-request,
zero-token failure is preserved. The provider-facing schema now omits only the
unsupported keyword while deterministic validation still rejects duplicates.
Replacement job `3792307` at exact clean commit `a2ed618` completed on
`gput073`: one Qwen3-32B call returned the in-set
`predicate:transferred_to` candidate in 1.877 seconds with 452 input and 21
output tokens, zero repairs/retries, and preserved hard constraints. Its
read-only audit passed 127/127 checks without mutation. This is mechanism
evidence only and remains `paper_result=false`.

M15-E3 adds the deterministic parser-to-hole and real artifact-provider path
without invoking the model. A versioned intake template performs only declared
exact-phrase matching and constructs four existing semantic operators, four
typed holes, and explicit hard/relaxable constraints. The `密切` phrase retains
single-transfer, window-total, and window-frequency meanings rather than being
collapsed into the transfer predicate. Versioned local catalog
and ontology providers expose bounded IDs, content hashes, and evidence through
the same E1 tool contract. The ontology permits one hop for predicate/type
candidates and rejects entities. The controlled `Alice` alias remains
ambiguous until an explicit in-set user choice is supplied; without that tool
the goal blocks after one catalog read and makes zero ontology/model calls.
The successful development route uses four catalog reads, one ontology read,
one clarification, zero LLM calls, and zero backend calls. These controlled
fixtures are interface evidence rather than ontology truth or parsing quality.
The E3/E4 bridge and registry-focused gate passes 32 tests. Full local
acceptance passes 1,003 tests with 36 explicit skips.
See [`docs/m15_e3_semantic_intake.md`](m15_e3_semantic_intake.md).

M15-E4 now binds the sealed E3 result to the executable-family registry through
a capability-checked bridge. Three relationship-strength meanings and two
predicate meanings create six deterministic classes. The single-transfer
threshold has a valid parent-family binding, and two hash-bound Neo4j extension
templates preserve the hard exclusive month upper bound; its two predicate
classes therefore receive both registered physical strategies. Window-total
and window-frequency meanings need aggregate capabilities absent from the
family and remain four explicit unavailable classes. The bridge emits no native
query text and uses zero backend, model, or ontology-service calls. Offline
fixture execution validates the four constructed plans only after selection.
See
[`docs/m15_e4_resolution_execution_bridge.md`](m15_e4_resolution_execution_bridge.md).

M15-E4B binds that deterministic bridge to one native Neo4j-plus-Fuseki
lifecycle. The run-local resolution, bridge spec, six semantic classes, two
executable tasks, and four physical candidates are reconstructed and sealed
before either service starts. Each physical plan makes exactly one Neo4j and
one Fuseki execute call; the successful gate therefore contains eight backend
calls and no profile, model, ontology-service, retry, or native-query-emission
action. The four unavailable aggregate classes are retained as explicit
capability gaps and never reach a backend. Exact answer oracles are opened only
after all four selected executions. A separate read-only auditor recompiles the
bridge and workload, reconstructs every result and invocation edge, validates
service cleanup, detects tampering, and checks that the run tree is unchanged.
Focused cross-layer acceptance passes 81 tests and full local acceptance passes
1,010 tests with 36 explicit skips. CWRU job `3792349` at exact clean commit
`8056ee4` completed the four-plan/eight-call contract on `compt292` in 94
seconds and removed its allocation runtime. An initial independent audit
correctly left the run untouched but falsely expected a synthetic
`loopback_only` service-plan field. Audit fix `aed12e3` reconstructs that
invariant from the actual endpoints and persisted Neo4j/Fuseki configuration;
its v2 audit of the same run passed 152/152 checks with no mutation or
experiment rerun. All outputs remain `paper_result=false`. See
[`docs/m15_e4b_live_resolution_execution.md`](m15_e4b_live_resolution_execution.md).

M15-E5/E5B/E5C separate unresolved interpretations, anchored relaxations, and
interactive authority transport. R1 first asks about operator-level meaning
when aggregation, quantification, answer meaning, output contract, or
capability differs. Family memory reduces physical plans only inside each
interpretation and cannot select user intent. Once the single-transfer meaning
is explicitly chosen, a second explicit event selects the predicate base for a
one-hop, provenance-bound ontology sibling relaxation. Pareto/epsilon/K applies
only inside that anchored set.

E5C persists those choices as a deterministic two-stage session. Every event
is restricted to the pending bounded set and binds the session ID, sequence,
hole, question hash, authority source, and its own content hash. Recompiling
the session from the same sealed E4 bridge, workload, family memory, policies,
ontology, and event log yields an exact byte-equivalent portable state. An
unsupported structural choice ends without execution. A ready state produces
an E4 runtime handoff containing exactly the E5B returned plans and only the
existing `runtime.execute_plan` capability; portable artifacts expose no native
query text. The mechanism and its independent auditor make zero current-query
profile, backend, LLM, ontology-service, oracle, repair, or retry calls. Full
local acceptance passes 1,044 tests with 36 explicit skips. This is local
control-plane evidence only. E5D now binds that handoff to the E4B native
Neo4j/Fuseki lifecycle. It imports the exact accepted F2C10D historical-memory
view, requires explicit structural and predicate authority at submission, and
seals the reconstructed session and selected plans before service startup.
One finite goal can invoke only `runtime.execute_plan`, executes all and only
the ranked handoff plans, stops on first failure, and uses zero profile, LLM,
ontology-service, oracle-for-selection, repair, or retry calls. Its independent
auditor reconstructs the full control/data-plane chain and real loopback
configuration without mutating the run. Full repository acceptance passes
1,054 tests with 36 explicit skips. CWRU job `3793365` completed the selected
two-plan handoff through four backend calls and passed its 127-check read-only
audit with no run-tree mutation. It remains mechanism evidence only. The compact
readiness record is
`experiments/artifacts/m15_e5d_local_live_selected_session_readiness_20260907.json`.
See
[`docs/m15_e5_interpretation_relaxation_gate.md`](m15_e5_interpretation_relaxation_gate.md).

M15-E6A/E6B/E6C add only the local presentation and typed remote-control
boundary. The loopback service reconstructs the existing E5C session from
sealed inputs, persists only content-hashed authority events, and accepts
hash-bound, explicitly confirmed candidate choices. The browser cannot supply
the authority-source ID or remote environment. A terminal session exposes a
sanitized E5D handoff preview; remote submission is disabled unless the local
operator explicitly enables it, and then one attempt can reach only the fixed
selected-session wrapper through `remote.executor`. The companion page uses
the same actions for visible controls and model-context tools and contains no
direct Neo4j, Fuseki, vLLM, SSH, or generic command path. Focused E6C tests pass
34 cases, full repository acceptance passes 1,075 tests with 36 explicit skips,
and the frontend production build succeeds. This is local engineering
readiness, not experiment or user-utility evidence. Model-context runtime
registration and one real local-to-CWRU submission remain unverified.

## M15-F — Paper experiment surface and optional UI

Status: **F0/F1/F2A/F2B4/F2C4/F2C5/F2C7B2/F2C8B/F2C9B/F2C10D/F2C12B/F2C13B LIVE GATES VERIFIED; F2C6/F2C7B1/F2C8A/F2C10A/F2C10B/F2C10C/F2C11/F2C12A/F2C14A LOCAL MECHANISMS VERIFIED; F2C11/F2C12B/F2C13C AUDITED DEVELOPMENT RESULTS ACCEPTED**

The first F0 slice commits two bounded workload specifications and generates
large artifacts only inside a new immutable run tree. The generator produces
namespaced Neo4j/Fuseki loads, full and bound queries, per-source oracles, and
the exact cross-source answer; every file is SHA-256 bound and the bundle is
revalidated at each trust boundary. `selective-dev-v1` has 200 companies,
5,000 transfers, 20 high-risk companies placed outside the hot set, and 120
answer rows. `broad-hot-dev-v1` keeps the same graph size but places 160
high-risk companies across the hot region and has 4,800 answer rows.

Both profiles run the same exact semantic program and the same parallel-hash
and risk-first-bind candidates through an explicit `scaled_adaptive` service
mode. The mode has its own Slurm wrapper and audit contract; the auditor binds
the profile label back to the committed spec and checks the generated bundle,
fixture, observations, memory, plan, answer, service lifecycle, and cleanup.
Local execution is development validation with `paper_result=false`. CWRU job
`3787167` exercised the first selective bundle at exact commit `36281aa`.
Archive staging, workload generation, service startup, and guarded cleanup
reached their declared boundaries, but Neo4j rejected the first load statement
before profiling because generator v1 embedded JSON objects as Cypher map
literals. The failed run made zero query calls and is not a performance result.
Generator v2 emits validated Cypher literals. New job `3787173` at clean
commit `3a2bce9` passed that syntax boundary and started both services, but
statement 6/6 still carried all 5,000 transfers and exceeded the fixed Neo4j
request deadline after five successful statements. No profile or query ran.
Generator v3 and bundle schema v2 now bind a fixed 100-row batch protocol,
producing 56 selective load statements without a timeout increase or retry.
Job `3787213` at clean commit `32c157f` then completed: all 56 Neo4j statements
loaded, the exact 120-row result used risk-first bind with two calls and 28,702
bytes moved, and a separate read-only audit passed 188/188 checks without run
mutation. This is a single-run engineering gate. Broad-hot execution,
calibrated repetitions, and the paper-scale counterbalanced campaign remain
pending. F1's
deterministic paired sanity check already executes all six
declared methods. Under one controlled stale-to-current latency transition,
all return the exact answer; full agent changes from parallel hash to
risk-first bind while no-replan observes the same preferred change but retains
the initial plan. Calibration and live timings are deliberately excluded from
this mechanism-only result. The compact clean-commit record is
`experiments/artifacts/m15_f1_local_controlled_method_matrix_20260905.json`.

The separate `scaled_method_matrix` mode now carries the same six methods into
one real Neo4j/Fuseki allocation. It preserves common calibration outside the
per-method totals, requires an exact 18-invocation trace, writes distinct
method and memory artifacts, and is covered by the read-only native evidence
auditor. Job `3787267` passed this contract and its independent 326-check audit.
The fixed-order shared-cache design remains intentionally a mechanism gate;
randomized/counterbalanced repetitions and calibrated cost parameters are
still required for paper comparisons.

F2 begins with a side-effect-free campaign compiler. Its development protocol
uses a deterministic six-sequence Williams design per workload and block, so
every method occurs once in every position and every directed first-order
method transition occurs once. Each sequence declares a fresh service pair,
separate method memory namespaces, excluded common calibration, raw
repetition preservation, exact-answer gating, and zero retry. The compiler
makes no backend, LLM, or ontology call and never labels its output as a
result. The current two-workload, one-query development configuration cannot
measure cross-task memory reuse and remains blocked from paper comparison
until query artifacts, 30--50 query contexts, cost calibration, repetitions,
live isolation validation, and an author-approved inferential analysis are
frozen.

F2A connects one compiled sequence to the existing live six-method runner.
Before a service or backend call, it recompiles the campaign, verifies the
author-supplied campaign and schedule hashes, matches both the source workload
configuration hash and normalized bundle-spec hash, and checks the exact
session, query stream, measured task IDs, logical memory namespaces, and
method order. A custom order is rejected unless the
matrix receives this complete campaign binding. The native lifecycle and
allowlisted Slurm wrapper now carry one such session through fresh
Neo4j/Fuseki services, fixture load, the 18-call sequence, cleanup, and the
read-only cross-artifact auditor. The v1 executor deliberately accepts only
the existing single financial-risk query, so the CWRU run is a mechanism gate
and cannot establish cross-task memory or counterbalanced performance.

CWRU job `3787291` executed the first selective session at exact clean commit
`c9a7afe` on `compt336`. The compiled Williams order drove all six methods,
all answers were exact, the trace contained exactly 18 tool invocations and no
automatic retry, and runtime cleanup succeeded. The independent read-only
audit passed 374/374 checks without mutating the run tree. This closes the
compiler-to-live-runner engineering gate only; the other 11 development
sessions were not dispatched and no comparative claim is supported.

F2B begins by replacing an unstructured query label with a resolved-query
contract. The committed development specification declares the immutable
person, time, amount, and risk constraints; semantic operators and answer
fields; exact Neo4j full/bound and Fuseki risk query roles; the bind parameter
contract; and source/final oracles. The compiler accepts only a verified
workload bundle, binds every query and oracle file by SHA-256, rejects role,
parameter, schema, symlink, or hard-constraint-relaxability drift, and produces
a location-independent contract hash without making an external call. This is
currently a local primitive: the v1 campaign/session still carries its old
query label, so the remaining sessions stay disabled until F2B binding is
wired through the scheduler, live runner, and read-only auditor.

F2B2 adds a separately versioned registry over the immutable F2A campaign.
It requires exact base campaign/spec hashes and complete coverage of every
workload/query key, verifies each query-spec source hash, freezes the expected
bundle-dependent contract hashes, injects contract references into every
method stream, and derives a portable query-bound schedule hash. Local file
paths remain provenance and do not affect that hash. This closes the
scheduler-side label gap, but the expected contracts have not yet been
recomputed against the live generated bundle and the existing session runner
does not consume this plan. F2B3 must perform both checks before enabling one
new remote engineering gate.

F2B3 now performs the missing live-bundle verification in a direct runner.
Before it creates an output directory or observes a backend, it recompiles the
query-bound plan, verifies the expected registry and bound-schedule hashes,
loads the deterministic bundle, and recomputes the selected resolved-query
contract. The matrix receives a v2 binding that includes the exact query-spec,
query-contract, workload, registry, and schedule identities; incomplete or
wrong contracts are rejected. The six methods then execute in the compiled
order with the existing exact-answer and 18-call gates. This path is locally
verified only: fresh Neo4j/Fuseki service lifecycle, Slurm entry, and an
independent cross-artifact audit remain F2B4.

F2B4 places that path inside a separately versioned native-service mode and
allowlisted Slurm wrapper. The native runner requires all four query-bound
inputs together and completes the F2B3 bundle-contract preflight before Java
inspection or Neo4j/Fuseki startup. The independent read-only auditor does not
trust the recorded contract identity: it recompiles the repository registry
and selected contract from the completed run's verified bundle, then checks
the wrapper, v2 matrix binding, contract artifact, exact result, 18-call
trace, service lifecycle, and cleanup as one cross-artifact chain. Local
acceptance now authorizes one selective CWRU engineering gate only. The other
eleven development sessions, multi-query execution, cross-task memory claims,
and all comparative paper claims remain disabled.

CWRU job `3787430` now verifies F2B4 at exact clean commit `d795fac`. It
completed on `compt348` with zero retry and restart, cleaned up both
loopback-only services and the allocation runtime, and passed all 377
independent read-only audit checks without run-tree mutation. It remains a
single-query identity-chain gate, not a method comparison or memory result.

F2C0 adds the route-independent task-stream boundary needed before those
multi-query runs exist. It validates the complete F2B query-bound plan and
recomputes its binding and schedule hashes, then expands one selected session
into a deterministic method/phase/repetition/query order. Each task has a
unique content-derived identity and an immutable query-spec/contract reference.
Its pre-task memory view is frozen, restricted to eligible successful exact
predecessors in the same method namespace, and cannot observe writes from the
current task; any post-task write is separately policy- and correctness-gated.
The present session has one task per method, so its machine-readable validation
rejects a cross-task-memory claim and also records that no transfer model is
bound. F2C0 is plan-only and does not authorize another remote run.

F2C1 follows the selected family-local transfer design. A query family fixes
the semantic/operator shape, hard-constraint schema, backend artifact roles,
candidate-plan space, and compatibility versions while instances vary explicit
hard bindings and selectivity. Memory remains isolated by method and family;
held-out instances of seen families may reuse compatible history, but a
held-out family must start cold. Cross-family transfer is not part of the first
paper method and cannot occur as a fallback heuristic.

The first F2C1 compiler and development registry now enforce that boundary.
Concrete query specs are source-hash verified; hard values receive distinct
instance identities while the structural family key excludes those values and
local paths. Duplicate bindings, structural drift, duplicate family keys,
runtime-version drift, cross-family reads, and evaluation writes fail closed.
The current registry contains only the existing Alice seed and therefore
reports every missing paper boundary, including typed DAG and backend-template
structure, workload/oracle binding, held-out coverage, and the 30--50 instance
target.

F2C2 defines the v2 typed parameterized contract that the next task-stream
version will consume. It preserves the audited v1 path while making entity,
time, and amount immutable and allowing only bounded risk, predicate, and path
relaxations. The compiler materializes the seven-node semantic DAG, validates
all slot uses, and type-checks backend parameters across compile-time template,
runtime value, and runtime-intermediate stages. Values change instance identity
but not family compatibility. Backend query files, multi-instance workload
data, and oracles remain intentionally unbound, so this local contract is not
an executable experiment and does not authorize another CWRU job.

F2C3 binds that type contract to literal-free Cypher/SPARQL templates and a
shared deterministic data snapshot with four people, 30 companies, and 720
transfers. Six distinct binding contexts—four seed and two held-out—share the
same family compatibility hash and own exact compiled artifacts, binding-stage
records, source oracles, and final oracles. Recursive hashes and full
regeneration protect the bundle from artifact or manifest tampering. This is
still a zero-call, one-family development artifact: it neither executes the
queries nor implements relaxation/Pareto enumeration.

F2C4 adds the executable bridge. The coordinator receives two exact physical
plans per query instance, with runtime hard values bound to native artifacts
and the Fuseki result aligned before it can become Neo4j's `company_ids`
runtime intermediate. The alignment catalog is generated from the declared
company-ID domain, not from answer oracles. A fixed task stream orders four
seed and two held-out instances and executes both strategies, while a distinct
fixture phase verifies the twelve source fragments. The additive native mode,
Slurm entry point, zero-retry trace, and independent read-only auditor are
complete. CWRU job `3787592` closed this gate at exact clean commit `66327a47`:
all twelve exact-strategy runs completed in 24 backend calls and its read-only
audit passed 172/172 checks without modifying the evidence tree. Memory, plan
selection, semantic relaxation, and paper comparisons are intentionally
outside this gate.

F2C5 now separates actual family-level transfer from the old exact-context
snapshot cache. A method/family/workload/runtime compatibility key guards an
append-only observation store containing typed bindings and per-strategy
execution costs but no answer rows. Four seed tasks may commit only after both
exact strategies succeed and pass post-execution answer validation. The store
is then reopened and frozen once; both held-out instances select from that
same predecessor-only view and cannot write. The development KNN policy is
oracle-free and replaceable. Its optional alternate-plan run is explicitly a
post-selection evaluation shadow. The native mode binds that context to one
Slurm allocation and its filesystem, Java, runtime-lock, staging, and
backend-version identity. A dedicated wrapper and independent auditor now
verify seed costs against append-only memory, one frozen predecessor view,
oracle-free held-out selections, selected-before-shadow execution roles,
exact answers, and clean zero-retry lifecycle. The local gate is ready for one
CWRU run. Job `3787610` completed at exact clean commit `30214cb` and its
independent read-only audit passed all 278 checks without mutating the run
tree. This accepts the native mechanism but makes no transfer or performance
claim. Both selected answers were exact, but the development KNN selected zero
of two post hoc observed latency winners. The fixed selected-then-shadow order
makes this a diagnostic; it is preserved without tuning and cannot support a
regret estimate.

F2C6 introduces a separate bounded semantic frontier rather than mixing
relaxation into family-memory selection. The exact interpretation is always
present; hard person, time, and amount bindings cannot change. Risk,
predicate, and path alternatives require explicit evidence-backed transitions
that satisfy the typed constraint's transformation and step bound, and each
derived instance is recompiled against the unchanged family key. Semantic
equivalence is resolved before physical-plan reduction, after which
semantic-deviation, latency, and resource cost feed Pareto, minimum-gain
epsilon, and K-bounded representative selection. The development HIGH-risk
query has 12 interpretations and a maximum of four returned representatives.
Enumeration is deterministic and zero-call; relaxed execution, answer-quality
validation, and paper parameter freezing remain F2C7 and later work.

F2C7A binds that abstract frontier to current executor capabilities. It finds
one bound exact class, one risk-only class that can be generated safely, and
ten blocked classes requiring predicate or path extensions. F2C7B1
materializes only the supported HIGH-to-MEDIUM risk class in a separate
regenerable overlay: typed artifacts and source/final oracles are bound, the
base bundle is untouched, and both backend load files remain byte-identical.
The 11-row relaxed oracle is still a deterministic development oracle, not a
human semantic-quality judgment. Live relaxed execution, payment-predicate
data, and the author-selected multihop hard-constraint semantics remain open.

F2C7B2 adds the first live semantic-plan bridge while keeping the mechanism
isolated from memory and plan learning. One fixed risk-first physical plan is
decorated with the approved class identity and positive semantic deviation,
then sent through the existing backend tool and coordinator scheduler. The
native wrapper copies the semantic catalog into the run tree, regenerates and
verifies the overlay, starts fresh loopback-only services, and admits exactly
one two-call semantic execution. The oracle is post-execution only. A dedicated
read-only auditor verifies the full chain. CWRU job `3787648` at exact clean
commit `2197aef` returned the exact 11-row answer in two calls and moved 3,963
bytes; its audit passed 133/133 checks without mutation. This is now live
mechanism evidence, not a semantic-utility or performance result.

F2C8A extends that bridge at the artifact boundary. A versioned development
mapping adds an independently generated `payment_to_company` edge family and
closed Cypher compilation while keeping the base bundle immutable. The
cumulative overlay binds exact, risk-only, predicate-only, and combined direct
classes and reuses the same coordinator plans and fixture tool boundary. Local
execution against deterministic backend doubles returns every added oracle;
live backends, ontology calls, semantic-utility claims, and multihop execution
remain outside this gate.

F2C8B adds the native execution boundary for the two predicate-changing direct
classes. Both plans are constructed before oracle access and use one fixed
risk-first strategy, so the gate has exactly two plan runs and four expected
backend calls. The versioned mapping remains a development fixture carried in
the execution contract; no ontology service is required. A dedicated native
mode, allowlisted Slurm wrapper, and independent read-only auditor now cover
overlay revalidation, nine-instance fixture verification, exact post-execution
answers, zero retry, service shutdown, and allocation-local cleanup. CWRU job
`3790680` at exact clean commit `2d39c3c` returned exact 6- and 9-row answers
with four total backend calls and 6,262 moved bytes. Its independent audit
passed 150/150 checks without modifying the run tree. This is live mechanism
evidence, not a semantic-utility, ontology-truth, or performance result.

F2C9A now joins the four executable direct interpretations to physical plan
selection without pretending that the eight blocked multihop classes are
available. It builds two physical candidates per direct class, binds all eight
plans to a sealed pre-execution estimate snapshot, keeps one predicted-cost
representative per class, and applies the existing semantic-deviation/cost
Pareto, epsilon, and K policy. Snapshot and candidate hashes fail closed on
oracle fields, post-execution evidence, incomplete coverage, runtime-plan
drift, or post-seal mutation. A controlled readiness fixture exercises the
8-to-4-to-4-to-3 reduction and retains exact semantics first. These are
constructed estimates; no backend, oracle, LLM, or ontology call occurs and no
performance or semantic-quality claim is enabled. At the F2C9A boundary, the
native lifecycle and every multihop interpretation remained unavailable.

F2C9B now supplies that native boundary without changing the selection policy.
The exact controlled estimate source is versioned and copied into each run;
all eight estimates bind to the complete candidate hash before the selector
persists its snapshot and three-plan frontier. Only after that seal may the
runner open answer oracles and invoke Neo4j/Fuseki. It executes exactly the
returned exact, combined, and risk-only semantic plans in rank order, stops on
the first failure, and admits no retry, fallback, memory, LLM, or ontology
call. A dedicated native mode, allowlisted Slurm wrapper, and read-only
reconstruction auditor bind the overlay, fixture, selection artifacts, exact
answers, six-call trace, lifecycle, and cleanup. Controlled local doubles
returned 11, 9, and 11 rows and the synthetic native audit passed 211 checks;
full acceptance passes 853 tests with 36 gated skips. One CWRU mechanism run is
the next gate. Constructed cost estimates cannot support a performance claim,
and all eight multihop classes remain excluded pending author-owned semantics.

F2C10A introduces the separately versioned variable-cardinality successor to
that mechanism. It enumerates every catalog-adjacent direct interpretation
before bounding the result: four classes for HIGH/LOW and six for MEDIUM, each
with both physical strategies. The six development base queries become 28
semantic tasks and 56 candidates. Split ownership remains at the base-query
level, so every interpretation of one base query stays entirely in training or
held-out. Selection-safe views are hash-bound and exclude answer artifacts;
the evaluation registry is a separate post-selection input. The generalized
selector retains the same physical/Pareto/epsilon/K order, and the old F2C9 v1
hashes remain unchanged. This gate performs no external call or measurement
and does not turn the six-query development fixture into paper evidence.

F2C10B connects that variable semantic space to agent memory rather than to a
current-query profiling tool. Its immutable memory view contains only
successful/exact training-plan histories with raw counterbalanced repetition
metadata and no answer rows. A strategy-conditioned KNN reference predictor
uses typed query and semantic bindings to emit latency, transferred-byte, and
uncertainty estimates for every held-out physical plan. The complete training
observation order, model configuration, target plan identities, and zero-call
boundary are hash-bound before the existing frontier selector runs. Cold
start is an error, not a controlled-estimate or profiling fallback. The local
values validate architecture only; they are explicitly not measurements.

F2C10C closes the local execution and evidence boundary. It seals every
selection input and output before runtime oracle rows are read, then executes
only the Pareto/epsilon/K representatives through the same coordinator and
typed backend tool interface used by native services. Its independent auditor
regenerates the workload, memory, predictions, snapshots, frontiers, selected
plans, answers, and invocation set from copied inputs, verifies every seal
hash, and fingerprints the run tree before and after. The clean-commit local
gate passed 134 checks with zero current-query profiles and no mutation. This
does not replace the native measurement protocol: training values and backend
latencies remain controlled nonmeasurements until F2C10D.

F2C10D turns that mechanism into one bounded native development pilot without
changing the optimizer. It measures all 36 training physical plans four times
under deterministic counterbalancing, freezes strategy-conditioned family
memory, predicts all 20 held-out physical plans without a current-query tool
call, and seals the two per-query semantic frontiers. Because frontier
cardinality is a query-level result, each query retains one to K=4 plans:
online cardinality is 2--8, total plan runs are 226--232, and plan backend
calls are 452--464. Online execution precedes a post-selection 80-run shadow
matrix. The shadow matrix cannot affect selection or memory; it exists only to
compute prediction error, physical-winner accuracy, latency/byte regret, and
predicted/observed frontier overlap. The native boundary fixes 60-second
requests, a 45-minute Slurm allocation, stop-on-first-failure, and zero retry.
A pre-service schedule seal and a separate read-only reconstruction audit are
required. This remains six-query development evidence and cannot set
`paper_result=true` or support a generalization claim.

The first CWRU attempt, job `3791589` at clean commit `d4db59a`, stopped before
fixture mutation or pilot execution. The direct workload's nested bundle uses
the predicate-extended F2C8 schema, while fixture handoff accidentally invoked
the base F2C parameterized-bundle loader. The repair preserves fail-closed
validation by reconstructing the enclosing direct-semantic workload at the
fixture boundary and then using its verified nested bundle; it does not make
the generic loader accept a broader schema. The failed run remains engineering
diagnostic evidence and a new job is required.

F2C11 freezes the first physical baseline surface before the replacement
pilot outcome is available. The agent-memory primary is compared with a
family-wide strategy-median ablation that removes instance features, both
fixed coordinator strategies, and a post-selection observed oracle upper
bound. This is a physical choice within each semantic class; it does not
change or rerank the semantic frontier. The primary and ablation paths use
only training-time evidence. Shadow measurements supply independent
four-repetition evaluation medians and can select only the explicitly labeled
oracle upper bound. Online results and answer-row values are not baseline
inputs.

The analyzer accepts only a successful read-only F2C10D audit and reruns the
complete reconstruction immediately before analysis, then rebuilds the
training memory and prediction suite instead of trusting result metadata.
Latency-first and byte-first evaluation references are declared separately.
No current-query observation or external call is introduced, output stays
outside the immutable run tree, and all F2C11 artifacts remain exploratory and
`paper_result=false`.

An independent F2C11 evidence auditor then repeats that reconstruction and
requires exact equality with the persisted comparison, even when a tampered
artifact carries a recomputed self-hash. It verifies the five-method,
ten-semantic-task, zero-call, results-blind, and non-confirmatory boundaries
while comparing source-tree digests before and after. The audit artifact also
lives outside the F2C10D run tree and cannot promote `paper_result`.

F2C12A freezes the missing cost-inclusive current-query profiling comparator
without reading F2C10D results. Within each of the same ten held-out semantic
classes it seals both physical strategies, measures each complete federated
plan once, selects from latency/bytes/plan identity only, and then executes the
selected plan once. This deliberately uses the shared black-box coordinator
boundary rather than asymmetric backend-internal `PROFILE` features. Two
acquisition plan runs, one selected run, and eight four-repetition shadow runs
per task yield 110 plan runs and 220 backend calls overall. Acquisition cost is
part of the method's end-to-end latency and bytes; shadows are evaluation-only.
The schedule compiler makes zero calls, proves AB/BA balance, forbids memory,
LLM, ontology, fallback, retry, and pre-selection oracle access, and does not
authorize a remote run. F2C12B supplies the native producer and independent
read-only auditor. The producer freezes candidates before acquisition, seals
the cost-only choice before any oracle or later execution, and enforces the
exact 40/20/160 backend-call phase split. The auditor reconstructs schedule
identities, estimates, selection, shadow medians, regret, end-to-end
acquisition cost, and invocation order while proving the run tree unchanged.
It also recompiles the source-bound schedule and checks the outer native
service/preflight chain when given a Slurm run root. Full acceptance passes
919 tests with 36 environment-gated skips; real-backend evidence remains
pending one clean audited CWRU job.

The repaired F2C10D pilot and pre-frozen F2C11 analysis are now accepted as
development evidence. Job `3791600` ran 231 plans and 462 backend calls with
zero current-query profiles; its read-only audit passed 1,289 checks. Family
memory selected 6/10 observed physical winners, compared with 8/10 for the
no-instance family median and fixed parallel controls. Its mean latency regret
was 2.282 ms versus 1.276 ms for fixed parallel, while mean byte regret was
lower (4,658 versus 5,625.6). The independent F2C11 audit reconstructed the
exact five-method analysis and passed 17/17 checks. This negative development
result is preserved without predictor tuning and does not alter the already
frozen F2C12A protocol.

F2C12B job `3791649` subsequently completed at exact clean commit `64f750b`
on `compt268`. It executed the frozen 110-plan/220-call protocol and its
independent outer-root audit passed 1,185 checks without mutation. The method
selected 10/10 shadow-median latency winners with zero latency regret, while
incurring 5,625.6 mean byte regret against the separate byte winner and a
median two-plan acquisition cost of 61.816 ms/14,082 bytes. This accepts the
live comparator as development evidence, but the different allocation from
F2C10D forbids a causal timing comparison.

F2C13A freezes that missing paired boundary. It composes the exact 144-run
family training schedule with the exact 20-run profile acquisition and 80-run
shared shadow schedules. Family selection seals before current-query
profiling; both methods then execute one selected plan for each of ten tasks in
a counterbalanced order. The result is a fixed 264-plan/528-call future
allocation with separate training, acquisition, serving, and shadow ledgers.
The local compiler makes zero calls and authorizes no live execution. It tests
physical selection within semantic classes only and remains descriptive and
`paper_result=false`. Full local acceptance passes 931 tests with 36 explicit
environment or external-artifact skips.

F2C13B implements that protocol without changing its population, order, or
metrics. A pre-service seal binds all 264 runs. Within one native allocation,
the producer loads the fixture once, seals family-memory choices after the 144
training runs, executes and seals 20 cost-only profiles, runs both methods once
per held-out task in counterbalanced order, and opens the shared 80-run shadow
matrix only after both seals. The first failure stops execution and no retry or
fallback occurs. A separate read-only auditor reconstructs the source
schedule, all candidate identities, training memory, prediction suite, both
selection seals, analysis, and the complete 528-call phase/run sequence. It
also rejects tampered choices, costs, or analysis. CWRU job `3792343` completed
the exact 264-plan/528-call schedule at clean commit `cf3d430` on `compt292`;
its independent reconstruction audit passed 2,735 checks with no failed ID or
run-tree mutation.

F2C13C freezes how an accepted paired run is reduced before its measurements
are available. The summary builder requires the successful independent audit,
revalidates the exact commit, supported schemas, frozen 264-plan/528-call
ledger, ten-task selection seals, hashes, and shadow-use boundary, and refuses
overwrite. It reports both methods, paired profile-minus-memory regret,
selection agreement, profile acquisition, and historical training as separate
cost scopes. In the accepted summary, family memory made zero current-query
profile calls, selected 7/10 observed latency winners, and had 2.733 ms mean
latency regret. Dual profiling made 20 profile acquisitions, selected 5/10,
and had 2.808 ms mean latency regret; it lowered mean byte regret from 4,658 to
3,346.4 while adding 35.154 ms and 14,056 bytes of mean acquisition cost.
Fixed parallel remained the strongest evaluation-only latency control at 9/10
and 0.289 ms regret. This mixed ten-task result is retained without retuning and
remains a descriptive single-allocation record with zero LLM/ontology calls,
no semantic-frontier or generalization claim, and `paper_result=false`.

F2C14A defines the admission boundary for the larger multi-family population.
An executable family is not a name or a collection of prose examples: it is a
hash-bound package containing a typed semantic DAG, binding and constraint
schemas, registered literal-free backend templates, deterministic instances,
source/final oracles, direct semantic tasks, physical candidates, split-safe
selection views, and a family-memory policy. The compiler reconstructs those
layers from their source inputs in temporary storage and rejects any source,
generated hash, operator, or count drift.

The registry also makes the agent model explicit. Its environment contains the
coordinator plus black-box Neo4j and Fuseki services. Its tools are registered
backend execution, coordinator federation, bounded semantic enumeration and
selection, and family-local memory. It may compile, enumerate, predict, select,
invoke registered fragments, and coordinate results; it may not change hard
constraints, issue arbitrary native text, inspect backend internals, read an
answer oracle before execution, or retry automatically. Catalog, ontology, and
LLM facilities are optional inputs, not preconditions for package validity.

The existing financial-risk family now passes this executable admission gate:
seven typed operators, three native templates, six base instances with their
own oracles, 28 direct semantic tasks, and 56 physical candidates are bound to
one compatibility key. This removes the old implementation blockers for that
family only. Additional family domains, an entirely held-out family, the
30--50-query allocation, and inferential preregistration remain author-owned
paper blockers. F2C14A makes no external call, authorizes no remote run, and
remains `paper_result=false`. Full local acceptance passes 946 tests with 36
explicit environment or external-artifact skips.

The public FinBench family-memory comparison is now frozen as a distinct
development campaign rather than inferred from the earlier toy protocols. It
binds 128 training, 40 current-query acquisition, 40 paired serving, and 160
post-selection shadow plan runs in one result-blind schedule. The agent-memory
method receives no current-query profile for known-family queries; F3 uses an
explicitly different cold-start fallback. The dual-profile comparator pays for
both complete federated probes. Selection seals precede paired serving, and
all shadow observations remain evaluation-only. The compiler performs no tool
call. A native producer now enforces the exact 368-plan/736-call phase order,
requires an independently audited workload-matching correctness run, and opens
the oracle only after execution. A separate read-only auditor reconstructs the
schedule, candidate catalog, correctness admission, family memory, both
selection seals, all result sets, oracle comparisons, and analysis. Full local
acceptance passes 1,125 tests with 36 intentional skips. The repaired SF0.1
correctness job `3793698` and its 368-check independent audit have passed.
Exactly one development campaign was then submitted as job `3793702` at clean
commit `c00c389`; its repaired independent audit passed 92/92 checks without
mutating the run tree. It remains non-confirmatory with `paper_result=false`.

For the answer-independent Option-A population, the campaign coordinator and
final reconstruction auditor are now implemented as a staged, immutable
dependency graph. The producer cannot promote its own result: it always writes
`paper_result=false`, and only the independent final audit can admit a
successful, exact campaign. This closes the local execution-plumbing gap but
does not grant CWRU execution authority; the exact request, explicit author
authority, clean runner commit, and full regression remain mandatory.

A distinct paper-protocol readiness compiler now prevents development evidence
from being silently promoted. It fixes the primary physical contrast and
statistical/failure boundaries, binds author choices by a subject hash,
reconstructs external development audits read-only, and makes no backend,
model, or ontology call. It explicitly rejects the answer-filtered 36-query
development split as an automatic confirmatory population and records four
missing physical components: an answer-independent population compiler, an
out-of-sample family runner, a confirmatory analyzer, and its independent
auditor. Semantic GrailQA and external FedShop protocols remain separate
paper-completeness requirements.

Freeze a 30–50 query hand-verified federated workload before importing a large
external benchmark. Vary data skew, latency, schema overlap, source count, and
failure injection. Report answer correctness, P50/P95 end-to-end latency,
bytes, remote calls, coordinator CPU/memory, planning overhead, LLM calls and
GPU-seconds, replans, and recovery rate.

The UI is optional and must consume the same goal/trace/artifact API as the CLI.
It is not an acceptance dependency for M15-B through M15-E.

### Confirmatory execution authority and block isolation

The accepted FinBench Option-A freeze fixes 48 query instances, 22 measurement
blocks, and 1,888 plan runs. It intentionally leaves
`confirmatory_execution_authorized=false`. The execution design adds a second,
explicit author authority record after the freeze audit; an approved population
choice alone cannot activate backend work.

Every measurement allocation is one agent environment episode: the environment
contains a coordinator and fresh job-owned black-box Neo4j/Fuseki services; the
only data-plane tools are the two registered backend adapters and coordinator
federation. A hash-bound block envelope constrains the agent to the exact
schedule projection, physical strategy, order, timeout, and retry policy. The
worker cannot inspect backend internals, emit an unscheduled native query,
profile outside the profile block, read an oracle, or expand its authority.

Training-memory admission now makes the required semantic distinction. A
content-addressed record replays the accepted real SF0.1 correctness evidence,
binds the common source archive, and verifies unchanged F1/F2 hard constraints
and physical plan-family contracts. It admits only successful, block-paired
costs; it does not observe a current confirmatory answer. The current-query
oracle remains sealed until every scheduled block has completed and is
authoritative for the final correctness gate.

Block reconstruction is independent and read-only. The sole replacement is
available only after an audited infrastructure attempt produced zero
measurements; method timeouts, backend/plan failures, and partial blocks remain
their declared outcomes. Both native services enforce a 60-second query limit,
with a 65-second transport grace used only to preserve timeout attribution.
The next boundary is campaign orchestration plus one final independent audit,
not a change to the agent environment or tool authority.
