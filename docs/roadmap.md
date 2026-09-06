# XGAP Roadmap

## Current Mainline: M15 Agentic Federated Core

The M0-M14 milestones below record the original ambiguity-aware planning and
semantic-experiment track. They remain reproducible legacy baselines. The new
mainline is specified in
[`docs/m15_agentic_federated_core.md`](m15_agentic_federated_core.md).

### M15-A Contracts, Tools, Memory, and Bounded Goal Loop

Goal: define the agent environment and implement the first executable control
substrate without changing the audited path algebra.

Acceptance criteria: typed semantic DAGs and holes; typed tool outcomes;
pluggable backend adapters; provenance-bearing memory; explicit goals and
success criteria; tool allowlists; finite step/tool budgets; no automatic
retry; offline tests and example.

Current status: **DONE LOCALLY**

### M15-B Executable Two-Engine Vertical Slice

Goal: execute one hand-verified semantic program whose answer requires both
Neo4j and Fuseki, then join normalized results at the coordinator.

Acceptance criteria: fragment compilation, remote execution, exchange,
alignment, coordinator join/merge, correctness, latency, bytes, cardinality,
and remote-call artifacts; no LLM or ontology required.

Current status: **REAL NEO4J+FUSEKI VERTICAL SLICE VERIFIED ON CWRU; STREAMING/CANCELLATION PENDING**

Execution order:

1. **M15-B0 CWRU environment gate** — verified: clean Git checkout, Slurm,
   H100 feature, vLLM environment, Miniconda Python, and a dedicated
   pytest-capable `xgap-core` environment are present.
2. **M15-B1 CWRU CPU smoke** — initially verified by job `3784974` at commit
   `4c45931` on `compt365`: exit `0:0`, 40 passed/1 live skip, exact one-row
   result, two calls, and 206 transferred bytes. Refreshed job `3787126` at
   exact clean commit `4c26eea` then passed on `compt331` with exit `0:0`, 128
   passes/two gated skips, all seven declared artifacts, and the vertical,
   plan-selection, and bounded-replanning oracles accepted.
3. **M15-B2 live backend packaging** — the authoritative compute node has no
   supported container runtime, so login-node Podman is rejected for Slurm
   service execution. The runtime-neutral loader and exact per-source oracle
   are implemented. Prerequisite job `3784980` verified loopback/archive tools,
   found Java 8 as the incompatible default, advertised Java 17 as the highest
   module, and found NFS-backed home storage. The v1 presence-only Java
   readiness flag is explicitly invalidated and fixed in probe v2. B2B pins
   Neo4j 5.26.30 and Fuseki 5.6.0 to a common Java 17 runtime and provides a
   single-attempt, digest-verified, no-overwrite shared archive cache. One CWRU
   artifact-preparation job `3787101` passed at commit `2ce4b53`: both archives
   matched their locked lengths and digests in one attempt each, with no retry,
   extraction, or service startup. B2C is implemented locally as a second,
   allocation-only trust boundary: verified archives are inspected for safe
   members and staged atomically into a new empty runtime directory. Real
   service launch remains gated on both cached archives and an explicit
   allocation-local filesystem check. B2D now implements the allocation-scoped
   launcher, exact Java 17 check, dynamic loopback ports, local Neo4j/Fuseki
   state, bounded health waits, one fixture/load run, reverse shutdown, and
   guarded cleanup. Combined service job `3787110` passed on `compt331` at
   exact commit `cd564de8`; both engines were healthy and loopback-only, the
   fixture and exact federated answer passed, shutdown and cleanup passed, and
   the read-only cross-artifact audit accepted all 102 checks.
4. **M15-B3 live federated vertical slice** — the typed program, real-plugin
   runner, vertically split fixture, exact oracle, immutable evidence, and
   gated live test are implemented. Job `3787110` verified the same contract
   against real Neo4j 5.26.30 and Fuseki 5.6.0 on CWRU.

The typed remote-executor plugin and its CLI are implemented locally. They
stage exact commits, allowlist batch entry points, observe jobs, and retrieve
scoped artifacts without storing credentials or silently retrying.

The command and artifact contract is frozen in
[`docs/m15_remote_execution_loop.md`](m15_remote_execution_loop.md).

### M15-C Nontrivial Plan Space and Observation Tools

Goal: add schema/explain/profile/sample tools and alternative correct plans for
pushdown, join strategy/order, parallel scheduling, and fragment fusion.

Current status: **LIVE OBSERVATION PATH VERIFIED ON CWRU; CALIBRATION AND SCALE PENDING**

The first slice provides catalog-allowlisted observation tools, native Neo4j
plan/profile evidence, executable bind-query and semi-join nodes, two
exact-semantic M15 plans, and a deterministic critical-path/transfer selector.
Both plans return the same fixture answer and the selected plan reverses under
a controlled bound-query latency change. The controlled artifact is not a
paper result. A bounded collector now executes one declared, duplicate-free
observation tuple with no retry and publishes a plan snapshot only when every
observation succeeds. The live path obtains native Neo4j PROFILE evidence and
an explicitly labeled Fuseki wall-clock execution fallback. Its fixed cost
model is intentionally marked uncalibrated. General fragmentation,
pushdown/order enumeration, fusion, calibrated estimates, and paper-scale
observations remain open. CWRU job `3787152` verified the bounded
three-observation path against real Neo4j and Fuseki.

### M15-D Memory-Guided Adaptation and Replanning

Goal: use versioned observations across tasks and explicitly replan within a
query when runtime evidence invalidates the current estimate.

Current status: **LIVE ADAPTIVE PIPELINE AND F1 LIVE METHOD MATRIX VERIFIED ON CWRU; PAPER CAMPAIGN PENDING**

The current slice persists versioned plan snapshots to append-only JSONL,
validates a probe as an exact common plan prefix before invocation, reuses that
prefix during continuation, and permits at most one explicit replan. The
controlled fixture flips from parallel hash to risk-first bind after observed
latency invalidates stale memory without duplicating the probe call. Probe
failure and the no-replan control are covered. Calibration, scaled/skewed
workloads, and the complete baseline matrix remain open.
The new live-service mode
collects exactly three registered planning observations, reopens the persisted
snapshot, executes one two-backend federated query with at most one replan,
persists and reopens two memory versions, and records a five-event tool trace.
It has its own Slurm entry point and mode-aware read-only audit so the verified
M15-B vertical slice remains reproducible. Job `3787152` ran the full path at
exact clean commit `247e714`; the 173-check audit passed, the exact answer was
returned, and the small fixture correctly retained the initial plan with zero
replans. Until the cost model and scale experiments are complete, the artifact
remains a development gate with `paper_result=false`.

F1 adds an exact compatibility fingerprint for cross-task snapshots and six
executable method policies: two fixed-plan static controls, no memory, no
current profile/probe, no replan, and full agent. A cold full-agent task
profiles and persists; a warm task skips the profile tuple, executes one
common probe, and can replan once. The deterministic paired matrix verifies
distinct action counts, exact answers, cold/warm persistence, and a controlled
plan flip. It is mechanism evidence only; live repetitions and statistical
comparison remain open.

The F1L engineering runner now executes the six policies against one loaded
native Neo4j/Fuseki pair. It excludes one common three-profile calibration
from all per-method metrics, records 18 backend events in named phases, and
uses separate append-only memory files for warm policies. The independent
auditor checks the exact workload, results, budgets, memory identity, service
lifecycle, and cleanup. CWRU job `3787267` passed at exact clean commit
`6aafafd`: all six exact answers and the 18-call trace validated, cleanup
succeeded, and the independent read-only audit passed 326/326 checks without
run-tree mutation. Its fixed order and shared unknown backend cache remain
declared limitations; this cannot be a comparative paper result.

First CWRU attempt `3787144` failed before service startup because Slurm's
copied wrapper used its spool path to locate the repository-owned lifecycle
script. This failure provides no adaptive-query evidence and remains separate
from successful job `3787152`, which used the published path repair.

### M15-E Selective Semantic Resolution

Goal: integrate deterministic interpretation, clarification, optional
catalog/ontology lookup, and bounded LLM fallback without making any one of
them a prerequisite for federated execution.

Current status: **PLANNED**

### M15-F Paper Experiment Surface and Optional UI

Goal: freeze a cross-platform workload and baselines/ablations; add a thin UI
only after the CLI, goal trace, coordinator, and remote-executor contracts are
stable.

Current status: **F0/F1/F2A/F2B4/F2C4/F2C5/F2C7B2/F2C8B/F2C9B/F2C10D LIVE GATES VERIFIED; F2C6/F2C7B1/F2C8A/F2C10A/F2C10B/F2C10C/F2C11/F2C12A LOCAL MECHANISMS VERIFIED; F2C11 AUDITED DEVELOPMENT RESULT ACCEPTED**

F0 adds two committed, bounded specifications for the same exact federated
question: a selective cold-risk regime with 120 answer rows and a broad
hot-risk regime with 4,800 answer rows, each over 200 companies and 5,000
transfers. A deterministic no-overwrite generator materializes namespaced
Neo4j/Fuseki artifacts and exact oracles inside the run tree, binds every file
by SHA-256, and rejects empty-answer configurations. The fixture loader,
observation catalogs, two exact-semantic candidate plans, common probe,
adaptive runner, native lifecycle, and read-only auditor consume the verified
bundle through a separate `scaled_adaptive` mode. The auditor also proves that
the declared profile corresponds to its committed spec.

The local workload substrate and one real-backend selective engineering gate
are closed. The artifacts remain `paper_result=false`; broad-hot execution,
calibration, repetitions, baseline and ablation scheduling, additional
queries/sources, and UI work remain open.

A separate `scaled_method_matrix` native mode and Slurm entry point now run the
two static plans plus `no_memory`, `no_profile_probe`, `no_replan`, and
`full_agent` over the same verified service instance and workload. This first
live matrix validates action traces and correctness only. Job `3787267`
completed and passed the independent 326-check audit. Counterbalanced ordering,
cache controls, repetitions, and calibrated parameters remain the paper
experiment scheduler's responsibility.

F2 now starts that scheduler as a pure campaign-plan compiler. A seeded
Williams design emits six sequences per workload and block with exact position
and directed first-order carryover balance, deterministic dispatch order,
fresh-service and isolated-memory declarations, explicit warmup/measurement
phases, no retry, and a machine-checked balance proof. The current development
configuration expands the selective and broad-hot workloads into 12 sessions
and 72 measured method-query attempts without making any external call. It
remains unexecuted and `paper_result=false`; its one-query streams cannot test
cross-task memory reuse, the query label is not yet a hash-bound 30--50 query
paper workload, and the final repetition/statistical protocol remains
author-owned.

The F2A development executor now consumes one compiled session instead of an
ad hoc method list. It validates the expected campaign and schedule hashes,
the source and generated workload-spec hashes, the supported query ID,
measured task IDs, logical memory namespaces, and the six-method order before
any external call. The ordered sequence then runs
through the existing native lifecycle with a fresh backend pair and an exact
18-call budget. A new read-only audit binds the outer Slurm evidence, service
lifecycle, generated bundle, campaign plan/session/binding, nested matrix,
answers, memory, and call trace. Only one selective session was admitted to
the live gate; full campaign dispatch and multi-query memory streams remain
open.

The first F2A CWRU gate is complete. Job `3787291` ran the selective `b01.s01`
session at exact clean commit `c9a7afe`; the selected Williams order controlled
the real six-method sequence, all answers were exact, and the 18-call trace had
zero automatic retries. Its independent read-only audit passed 374 checks and
confirmed that the run tree was unchanged. F2B must next replace the remaining
query label with a portable contract over resolved hard constraints, exact
backend artifacts, parameter requirements, and answer oracles before any
additional campaign sessions are enabled.

F2B1 now provides that standalone contract primitive. It compiles the resolved
development query against a verified generated bundle, binds all three backend
queries plus both oracle files by SHA-256, preserves hard constraints as
non-relaxable, and emits a portable content hash independent of its local file
path. It makes zero backend, LLM, or ontology calls and remains
`paper_result=false`. This primitive alone was insufficient; F2B2 therefore
adds the contract reference and expected hash to a separately versioned
campaign path without rewriting the audited F2A v1 configuration.

F2B2 now layers a query-bound registry over that unchanged F2A plan. The new
compiler verifies both base campaign hashes, requires one binding for every
workload/query context, checks the resolved-query source hashes, freezes the
selective and broad-hot bundle-dependent contract hashes, and carries those
references through all twelve sessions under a new portable schedule hash.
The compiler records that live-bundle verification is still pending and makes
no external call. F2B3 is the next implementation gate: recompute the selected
contract from the generated bundle before service startup, bind it into the
matrix execution contract, and extend the independent auditor without changing
the preserved F2A path.

F2B3 now recompiles and verifies the selected bundle-dependent query contract
before any backend healthcheck or run-tree creation. A distinct v2 matrix
binding carries the registry, query-binding, bound-schedule, query-spec,
query-contract, and workload identities into the real six-method sequence.
Tests also cover the adversarial case where a registry and schedule are
internally consistent but freeze the wrong contract hash. The next F2B4 gate
must place this runner inside a fresh native Neo4j/Fuseki lifecycle and extend
the independent auditor before one CWRU query-bound session may run.

F2B4 now supplies that native boundary. The new mode preflights the exact
registry, bound schedule, session, workload, and recomputed query contract
before starting either service; its dedicated Slurm wrapper is separately
allowlisted. The read-only auditor independently regenerates the expected v2
binding and contract from the completed run bundle and detects contract-file
tampering. One selective CWRU query-bound gate is ready. Its purpose is only
to verify the end-to-end identity chain; the remaining eleven sessions and
paper campaign stay disabled.

CWRU job `3787430` closed this gate at exact clean commit `d795fac` on
`compt348`. The native run completed without retry or restart, cleanup removed
the runtime, and the independent read-only audit passed 377/377 checks with no
run-tree mutation. This validates the query identity chain only and does not
change the single-query, single-sequence claim boundary.

F2C0 now removes an independent scheduler ambiguity before any multi-query
design is chosen. A side-effect-free compiler expands one query-bound session
into explicit per-method tasks rather than leaving execution as the implicit
product of query and repetition IDs. Every task freezes its query-contract
identity, order, isolated memory namespace, eligible predecessor set, and
success-plus-exact post-task commit gate. The current selective session yields
six unique tasks and correctly fails the multi-task-memory readiness check: it
has one unparameterized query and no bound transfer model. This contract does
not select between the proposed single-family, family-local, or global-transfer
research designs and does not authorize another CWRU run.

F2C1 now implements the first family-local compatibility compiler. It verifies
query-spec source hashes, extracts hard binding identity separately from the
stable semantic/operator, constraint-schema, output, artifact-interface,
candidate-space, and version signature, and rejects structural drift or two
family labels for one compatibility key. It freezes seed versus held-out
instance roles, disallows cross-family reads and evaluation writes, and forces
held-out families to cold start. The one-family development registry is
deliberately not ready: typed operator-DAG and backend-template binding,
workload/oracle contracts, additional families, 30--50 instances, and the
statistical protocol remain open.

F2C2 adds a separately versioned typed parameterized query contract for the
financial-risk family without changing the audited v1 query. It freezes the
selected semantic policy: clarified entity identity, time, and amount are
hard; risk, predicate, and direct-path shape have only explicitly bounded
relaxations. A typed seven-node semantic DAG, complete slot coverage, backend
parameter types, and compile-time/runtime/intermediate binding stages now feed
a value-independent family compatibility hash and a value-bound instance hash.
The current contract is deliberately unexecuted: F2C3 must bind literal-free
Neo4j/Fuseki templates, a shared multi-instance workload, and exact source and
final oracles before any remote run.

F2C3 now provides that binding as a deterministic development bundle. One
shared snapshot contains four people, 30 companies, and 720 transfers; four
seed and two held-out instances vary actual person/date/amount/risk bindings
under the same family key. Each instance has stage-separated parameters,
compiled Neo4j/Fuseki artifacts, source oracles, and a final oracle. The
recursive hash manifest and deterministic loader reject both ordinary tamper
and content-plus-digest rewrites. The bundle remains unexecuted and covers only
the exact interpretation.

F2C4 now wires this format into the coordinator and a separate native-service
mode without changing the audited F2B4 route. A deterministic task stream runs
the parallel-hash and risk-first-bind plans for each of the four seed and two
held-out instances. Plan construction uses only the typed bundle and the full
declared ID-domain alignment catalog; answers are consulted only afterward for
validation. The native gate loads one shared dataset, verifies twelve source
queries, executes twelve exact plan runs and 24 backend calls, and emits a
separate read-only audit surface. CWRU job `3787592` completed this path at
exact clean commit `66327a47`; its independent audit passed all 172 checks
without mutating the run tree. Cross-task memory, plan choice, relaxation,
Pareto enumeration, and comparative measurements remain later milestones.

F2C5 now implements the first executable family-local transfer protocol above
that exact stream. It introduces a separate method x family x workload x
runtime memory identity instead of weakening exact snapshot compatibility.
Four successful exact seed tasks append typed binding/cost observations; the
store is reopened and frozen before either held-out instance, and evaluation
writes or cross-context reads fail closed. A replaceable development KNN picks
one exact plan without oracle inputs. The selected plan runs before any
optional alternate-plan evaluation shadow, and the two call classes are
reported separately. The native lifecycle now derives an allocation-scoped
runtime identity, runs through a dedicated Slurm entry, and has a read-only
auditor that binds exact seed costs to append-only memory, the frozen view to
both held-out choices, and online versus shadow calls to distinct trace roles.
Local acceptance and tamper tests are complete. One CWRU mechanism gate,
multiple families, a frozen paper model, counterbalanced measurement, and
preregistered analysis remain open.

The CWRU F2C5 mechanism gate is now closed by job `3787610`: its independent
audit passed 278 checks, both held-out selected plans were exact, and the
family-memory lifecycle behaved as specified. The development KNN selected
neither of the two later observed shadow winners. This negative diagnostic is
retained without reactive tuning; the paper policy must be trained and frozen
from a larger development split, then evaluated under counterbalanced
repetitions.

F2C6 now adds the bounded semantic solution-space layer without making the
ontology or LLM a mandatory runtime dependency. A value-independent
development catalog supplies explicit one-step risk and predicate transitions
and one- or two-step path expansions. Enumeration recompiles every binding as
the same typed family and rejects hard-constraint changes, undeclared
transformations, excessive steps, or missing evidence. Semantically equivalent
derivations merge before one lowest-cost physical representative is retained
per class. Pareto, semantic-preserving epsilon dominance, and deterministic
K-bounded selection prevent the system from returning every generated plan.
The reference query produces 12 bounded interpretations and at most four
returned representatives. Local acceptance validates the mechanism only;
F2C7 must bind relaxed values to executable backend artifacts and semantic
answer-quality oracles before any live relaxation gate is admitted.

F2C7A now performs that binding as an explicit coverage audit. Against the
current F2C3 bundle, it reports one already-bound exact class, one risk-only
class ready for deterministic generation, and ten blocked classes rather than
claiming that all 12 F2C6 interpretations are executable. F2C7B1 materializes
the supported HIGH-to-MEDIUM risk interpretation into a new, regenerable
overlay bundle with compiled Neo4j/Fuseki artifacts and source/final oracles.
The base data remains byte-identical and no blocked predicate or path class is
included. The next implementation step can add payment-predicate support
without a research decision. Multihop execution remains gated on the author's
definition of how immutable time and amount constraints apply along the path.

F2C7B2 binds the one supported risk class to one fixed risk-first physical plan
and a fresh native Neo4j/Fuseki lifecycle. CWRU job `3787648` completed at exact
clean commit `2197aef` on `compt386` in 81 seconds. It executed the relaxed plan
with two backend calls, moved 3,963 bytes, and returned the exact 11-row oracle
while preserving every hard binding. The dedicated read-only audit passed
133/133 checks without changing the run tree. This closes the live mechanism
gate only; it is not a strategy comparison or semantic-quality result. The
compact evidence record is
`experiments/artifacts/m15_f2c7b2_cwru_native_semantic_risk_relaxation_20260906.json`.

F2C8A adds the versioned payment-predicate artifact layer without changing the
frozen F2C3 bundle. A catalog-bound development mapping compiles
`payment_to_company` to a Neo4j `PAYMENT_TO_COMPANY` relationship and generates
720 deterministic payment edges independently of the 720 transfer edges. The
cumulative bundle contains the exact class plus all three non-exact direct
classes; their final oracles contain 11 risk-only, 6 predicate-only, and 9
combined rows. Both physical plans execute exactly against backend doubles,
and the ordinary fixture boundary verifies all nine bundle instances. Full
local acceptance passes 825 tests with 36 gated skips. This is artifact and
execution-plumbing evidence only; a native runner and independent auditor are
required before any CWRU payment-predicate job is authorized. All eight
multihop classes remain blocked pending the author's path semantics.

F2C8B adds the dedicated live runner, native-service mode, allowlisted Slurm
wrapper, and independent read-only auditor for the two predicate-changing
direct classes. It builds both plans before oracle access, fixes one risk-first
strategy per class, and expects exactly four backend calls and exact 6- and
9-row answers. The fixture path revalidates the cumulative overlay and all nine
query instances. Full local acceptance passes 834 tests with 36 gated skips;
the local synthetic native run tree passes all 150 audit checks and answer or
plan tampering is rejected. CWRU job `3790680` completed at exact clean commit
`2d39c3c` on `compt295` in 96 seconds. It returned both exact relaxed answers
with four calls and 6,262 moved bytes; the independent audit passed 150/150
checks without mutation. This closes live predicate execution plumbing but
does not provide comparative, semantic-utility, ontology-truth, or paper
evidence.

F2C9A adds a capability-aware direct semantic frontier. It keeps all 12
semantic-class identities visible, excludes the eight unbound multihop classes
from executable planning, and constructs two physical plans for each of the
four direct classes. A complete hash-bound estimate snapshot must be sealed
before execution and may contain predictions only; answer fields and observed
execution measurements fail closed. Physical reduction precedes the
semantic-deviation/predicted-cost Pareto, 5% epsilon, and K=4 passes. The
controlled fixture reduces 8 physical candidates to 4 class representatives,
4 Pareto points, and 3 returned semantic plans with exact semantics first.
F2C9B persists that selected frontier inside a fresh native-service mode. A
versioned controlled estimate source binds all eight direct physical plans;
the complete candidate set, snapshot, and three returned representatives are
written before any oracle or backend access. Only the exact, combined, and
risk-only returned plans execute, for six expected backend calls, and failure
stops without retry. A dedicated allowlisted Slurm wrapper and independent
read-only reconstruction audit cover the whole lifecycle. Controlled local
doubles return exact 11-, 9-, and 11-row answers, the synthetic audit passes
211/211 checks, and full local acceptance passes 853 tests with 36 gated
skips. The one authorized CWRU mechanism job, `3791375`, completed at exact
commit `2c0ee7f` with exit `0:0`; its three returned plans produced the exact
11-, 9-, and 11-row answers with six calls. The first independent audit failed
20 preflight checks because the auditor looked under the outer run root while
the producer had sealed the artifacts under `native-service-run`. The
production/test path mismatch is fixed at `9e1a1db`; a read-only v2 audit of
the immutable run is still required before the live gate is accepted. Do not
rerun the job.
Controlled estimates must not be promoted into a performance claim, and
multihop remains blocked.

F2C10A generalizes the direct frontier under a new versioned contract while
leaving every frozen F2C9 v1 hash unchanged. The author-selected preserve-all
policy compiles all catalog-adjacent direct interpretations: HIGH/LOW yield
four classes and eight plans, while MEDIUM yields six classes and twelve
plans. Across the existing development split this creates 28 semantic tasks
and 56 physical candidates, with 18 training and 10 held-out tasks. Every
derived interpretation inherits its base query's split and preserves entity,
time, and amount bindings. Selection-safe train/held-out views contain no
answer artifacts; a separately hash-bound evaluation registry holds the
post-selection oracle references. Full local acceptance passes 862 tests with
36 gated skips. This is a zero-external-call development and leakage gate, not
a measured result; the 4/2 base-query population is too small for a paper
claim.

F2C10B now compiles a sealed, strategy-conditioned family-memory prediction
source without opening the held-out evaluation registry. The controlled local
memory covers all 18 training interpretations and 36 physical plans with 72
raw counterbalanced successful/exact repetitions. It produces one prediction
for each of the 20 held-out physical candidates: twelve for the MEDIUM query
and eight for the LOW query. Every source binds the complete ordered training
memory and model configuration; cold start, held-out observation, answer-row
storage, current-query profiling, fallback, and post-execution updates fail
closed. The sources feed the unchanged variable-cardinality snapshot and
Pareto/epsilon/K selector. No held-out query or backend executes, and the
constructed training values are not measurements. Full local acceptance at
that boundary passed 870 tests with 36 gated skips.

F2C10C now persists the complete selection boundary before controlled oracle
access: training observations, immutable memory, all 20 held-out predictions,
per-query candidate/snapshot/frontier artifacts, and a hash manifest over
every selection file. It then executes only the four returned semantic plans
and stops on the first failed call without retry. The clean-commit mechanism
run at `4fe396a` returned exact 11-, 9-, 12-, and 7-row answers with eight
calls; a separate read-only reconstruction passed 134/134 checks and proved
the run tree unchanged. Full local acceptance passes 879 tests with 36 gated
skips. These are deterministic backend doubles and constructed training
values, so F2C10D still requires an author-frozen native measurement campaign
before any accuracy, latency, resource, or generalization claim.

F2C10D freezes that native development campaign. Four counterbalanced blocks
execute 18 training interpretations under both strategies (144 plan runs),
then family memory and all held-out prediction/frontier artifacts are sealed
with zero current-query profiling. The two held-out base queries retain their
independent true Pareto/epsilon/K frontiers, yielding 2--8 online selected
plans rather than forcing an artificial global count. A complete 20-plan by
four-repetition shadow matrix follows only after selection, so the bounded
campaign contains 226--232 plan runs and 452--464 plan backend calls. The
native wrapper reserves 45 minutes and each backend request has a 60-second
deadline; failure stops immediately and no automatic retry is allowed. The
post-selection report contains prediction error, winner accuracy, latency and
byte regret, and predicted/observed frontier overlap. Local implementation,
native lifecycle wiring, preflight sealing, and read-only reconstruction
passed 898 tests with 36 gated skips at the first submission boundary. CWRU
job `3791589` then exposed a pre-mutation fixture handoff defect: the generic
fixture loader tried to parse the nested predicate-extended bundle with the
base parameterized schema loader. The repair revalidates the enclosing
direct-semantic contract at fixture time, does not widen either schema, and
passes 899 full-suite tests with 36 gated skips. The failed job is immutable
diagnostic evidence. The next gate is exactly one
explicitly new clean-repair-commit CWRU pilot, followed on success by exactly
one read-only audit; it remains non-confirmatory and `paper_result=false`.

F2C11 freezes the downstream physical baseline and ablation surface before
that replacement pilot result is read. It compares the primary sealed
family-memory predictor with a family strategy-median ablation that removes
instance features, two fixed physical strategies, and a shadow-derived oracle
upper bound. All ten held-out semantic tasks are included. Four-repetition
shadow medians independently reconstruct the observed physical winners;
latency and byte regrets have separately declared nonnegative reference
oracles. A successful mutation-free F2C10D audit is both required and rerun
read-only at analysis time. The analyzer makes zero external calls, ignores
online selected-plan results and answer-row values for selection and metrics,
writes only outside the source run tree, and remains exploratory with
`paper_result=false`. Its policy and implementation were fixed while repair
job `3791600` was still pending, so the method set cannot be selected from the
observed outcome.

F2C11 also has an independent read-only evidence auditor. It reruns the source
admission audit and the five-method reconstruction, requires exact equality
with the persisted analysis rather than trusting a self-hash, and compares
source-tree digests before and after. A valid analysis therefore needs both a
zero-exit analyzer artifact and a separate zero-exit audit with no failed
checks or run-tree mutation; both stay exploratory and outside the source run.

F2C12A freezes the later live current-query profiling baseline before accepted
F2C10D/F2C11 outcomes can influence its design. Each of the ten held-out
semantic tasks profiles both complete federated physical plans once, seals a
latency/bytes/plan-ID choice, executes the selected plan once, and then runs
four counterbalanced evaluation repetitions for both strategies. Acquisition
and selected execution cost count toward the method; shadow traffic does not.
The compiled development schedule has 110 plan runs and 220 backend calls,
five AB and five BA acquisition orders, and 2/2 shadow position balance per
strategy. It makes no call, uses no family memory, LLM, ontology service,
answer row, or pre-selection oracle, and remains `paper_result=false`. The next
implementation gate is a native producer plus an independent auditor; the
compiler itself authorizes no CWRU submission and no comparison across prior
allocations.

Repair job `3791600` and the frozen F2C11 comparison are now accepted. The
pilot made 462 backend calls over 231 plan runs and passed a 1,289-check
read-only audit. The five-method result is deliberately retained even though
the primary family-memory predictor achieved 0.60 physical-winner accuracy and
2.282 ms mean latency regret, behind fixed parallel's 0.80 and 1.276 ms. The
primary reduced mean byte regret to 4,658 from 5,625.6, exposing rather than
eliminating the latency/transfer trade-off. A separate F2C11 reconstruction
audit passed all 17 checks. No predictor retuning on these ten tasks is
permitted. F2C12 live implementation and a larger multi-family workload are
the next experimental gates.

The first selective submission, job `3787167` at clean commit `36281aa`,
failed at Neo4j fixture load before any profile or query call. Generator v1
used JSON object syntax inside a Cypher `UNWIND` literal; Neo4j 5.26 requires
identifier keys. Generator v2 uses a target-specific literal encoder and is
locally regression-tested. The failed v1 run remains immutable diagnostic
evidence and must not be counted as a performance result.

The new job `3787173` at clean commit `3a2bce9` passed that syntax boundary and
made both services healthy, but timed out on load statement 6/6 after the first
five succeeded. The final statement contained all 5,000 transfers. Generator
v3 and bundle schema v2 now declare and enforce fixed 100-row Neo4j batches;
the selective workload therefore has 56 statements. The 30-second request
deadline and zero-retry policy remain unchanged. This second failed run is also
immutable diagnostic evidence, not a performance result.

Generator-v3 job `3787213` at clean commit `32c157f` completed on `compt336`.
Neo4j loaded all 56 fixed batches, the coordinator returned the exact 120-row
answer with risk-first bind, two remote calls, and 28,702 bytes moved, and the
independent read-only audit passed 188/188 checks without mutating the run tree.
The compact evidence record is
`experiments/artifacts/m15_f0_cwru_scaled_selective_success_20260905.json`.
It is a one-run system gate, not calibrated or comparative paper evidence.

## Historical Milestones

## M0 Project Skeleton

Goal: Create the Python package, documentation, examples, and tests.

Files involved: `src/xgap/**`, `docs/**`, `examples/**`, `tests/**`, `pyproject.toml`.

Acceptance criteria: Package imports work, placeholder modules exist, future behavior raises `NotImplementedError`, and pytest can discover tests.

Current status: DONE

## M1 Data Model

Goal: Implement the path-based data model and directed labeled property graph.

Files involved: `src/xgap/algebra/types.py`, `src/xgap/algebra/graph.py`, `tests/test_path_types.py`, `tests/test_graph.py`.

Acceptance criteria: `Path`, `PathSet`, `SolutionSpace`, and `PropertyGraph` satisfy the M1 behavior; graph nodes and edges convert to `PathSet`.

Current status: DONE

## M2 Core Algebra

Goal: Implement executable semantics for `Nodes(G)`, `Edges(G)`, `Selection`, `Union`, and `Join`.

Files involved: `src/xgap/algebra/conditions.py`, `src/xgap/algebra/ops.py`, `src/xgap/algebra/evaluator.py`, `tests/test_conditions.py`, `tests/test_core_ops.py`.

Acceptance criteria: Implemented operators evaluate over `PathSet`; conditions cover labels, properties, length, and boolean composition; unimplemented operators raise `NotImplementedError`.

Current status: DONE

## M2.5 Logical Plan Infrastructure

Goal: Add validation, optimizer passes, and plan formatting infrastructure.

Files involved: `src/xgap/algebra/validation.py`, `src/xgap/algebra/optimizer.py`, `src/xgap/algebra/pretty.py`.

Acceptance criteria: Plans can be validated and optimized without changing semantics; unsupported rewrites fail clearly.

Current status: DONE

## M3 Recursive Algebra

Goal: Implement `Recursive` semantics for `WALK`, `TRAIL`, `ACYCLIC`, `SIMPLE`, and `SHORTEST`.

Files involved: `src/xgap/algebra/ops.py`, `src/xgap/algebra/evaluator.py`, `src/xgap/algebra/types.py`, recursive tests.

Acceptance criteria: Recursive path expansion is deterministic, mode-specific, and tested.

Current status: DONE

## M4 SolutionSpace Algebra

Goal:
Implement GroupBy, OrderBy, and Projection over SolutionSpace.

Files involved:
src/xgap/algebra/types.py, src/xgap/algebra/ops.py, src/xgap/algebra/evaluator.py, src/xgap/algebra/validation.py, src/xgap/algebra/pretty.py, tests/test_solution_space.py, examples/solution_space_demo.py.

Acceptance criteria:
GroupBy transforms PathSet into SolutionSpace; OrderBy updates ranks without changing membership; Projection transforms SolutionSpace back into PathSet; selector-style plans such as ANY SHORTEST TRAIL can be represented and evaluated.

Current status:
DONE

## M4.5 Semantic Audit

Goal:
Audit the full logical algebra semantics after M4.

Files involved:
docs/operator_semantics.md, tests/**, examples/**, semantic-audit notes.

Acceptance criteria:
The implementation is checked against the path algebra paper's core, recursive, and extended semantics; selector examples are verified; empty input and tie-breaking behavior are documented; all acceptance tests pass.

Current status:
DONE

## M5 Pattern AST And Lowering

Goal:
Define structured path-pattern query objects and lower them deterministically to path-algebra logical plans.

Files involved:
`src/xgap/pattern/ast.py`, `src/xgap/pattern/types.py`, `src/xgap/pattern/typecheck.py`, `src/xgap/pattern/lowering.py`, `tests/test_pattern_typecheck.py`, `tests/test_lowering.py`, `examples/lowering_demo.py`.

Acceptance criteria:
- Regex AST supports at least `Rel`, `Seq`, `Alt`, `Plus`, and `Star`.
- Selector AST supports `ALL`, `ANY`, `ANY k`, `ANY SHORTEST`, `ALL SHORTEST`, `SHORTEST k`, and `SHORTEST k GROUP`.
- Restrictors reuse existing `PathMode` values.
- `PathPatternQuery` lowers to a valid logical operator tree.
- Lowering has no LLM dependency.
- Lowering emits only existing logical operators.
- Lowered plans pass `validate_plan`.
- Lowered plans can be evaluated by the reference evaluator.
- No compiler, backend, optimizer, or LLM logic is added.

Current status:
DONE

## M5.5 Pattern-Lowering Audit

Goal:
Audit the full M5 GPC-Lite pattern layer and deterministic lowering pipeline.

Files involved:
`tests/test_pattern_lowering_audit.py`, `examples/pattern_lowering_audit_demo.py`, `docs/pattern_lowering_audit.md`, `docs/architecture.md`, `docs/roadmap.md`, `docs/status.md`, `docs/decisions.md`, `scripts/run_acceptance.sh`.

Acceptance criteria:
- GPC-Lite AST validity, type checking, regex lowering, descriptor lowering, selector mapping, determinism, validation, and reference evaluation are audited.
- Unsupported full-GPC and future milestone features fail clearly.
- No M6 or later functionality is implemented.
- `python -m pytest` passes.
- `./scripts/run_acceptance.sh` passes.

Current status:
DONE

## M6 Bounded Focused Quantified Pattern Semantics

Goal:
Add a bounded QGP-inspired fragment for focus-oriented, rooted tree
patterns.

Files involved:
`src/xgap/pattern/quantified_ast.py`,
`src/xgap/pattern/quantified_typecheck.py`,
`src/xgap/pattern/quantified_lowering.py`,
`src/xgap/algebra/bindings.py`, focused binding operators in
`src/xgap/algebra/ops.py`, evaluator, validation, pretty printing,
tests, and `examples/quantified_pattern_demo.py`.

M6 extends the structured pattern layer with a bounded, QGP-inspired
fragment for focus-oriented rooted tree patterns.

The deterministic flow is:

FocusedQuantifiedPatternQuery
-> type_check_focused_quantified_pattern
-> validate_quantifier_bounds
-> lower_focused_quantified_pattern
-> LogicalPlan
-> validate_plan
-> reference evaluation

M6 supports quantifiers attached to atomic directed pattern edges:

existential: at least one distinct child match
numeric count: = k and >= k
ratio: = r and >= r
universal: ratio = 100%
negation: no child satisfies the complete branch pattern

Counting uses distinct child-node bindings. It does not count paths,
parallel edge instances, or complete binding multiplicities.

Ratio denominators contain distinct child nodes reachable through the
edge descriptor before applying the child-node descriptor and the child
subtree. Positive ratio conditions use non-vacuous semantics: an empty
denominator does not satisfy a ratio or universal condition.

Pattern-level negation is lowered through anti-semi-join semantics. It is
different from scalar boolean negation inside a local property condition.

M6 applies static structural bounds. On every root-to-leaf pattern path:

at most two quantifiers may be non-existential;
at most one edge may be negated.

Sibling quantified or negated branches are allowed because sibling
branches represent conjunction rather than nested quantification.

M6 introduces a minimal set-valued BindingRelation and a focused
binding-operator layer. This is an implementation substrate for bounded
focused patterns; it is not a full GPC assignment implementation.

M6 does not support:

full QGP
arbitrary conjunctive or cyclic graph patterns
quantifiers over Plus, Star, or other regular-path expressions
path counting
edge-instance counting
bag or null semantics
multiple query-focus outputs
unbounded quantifier nesting
backend compilation or execution
optimizer, LLM, disambiguation, or KGQA functionality

Current status:
DONE

## M6.5 Quantified-Pattern Semantic Audit

Goal:
Audit the M6 quantified-pattern semantics and lowering pipeline.

Files involved:
semantic audit document, audit tests, audit demo, current-state docs, and
acceptance wiring.

Acceptance criteria:
Confirms counting, ratio, negation, bounds, determinism, validation,
reference evaluation, and execution boundaries.

Current status:
TODO

## M7 Backend Infrastructure

Goal:
Move beyond local database bootstrapping by giving XGAP a backend
infrastructure layer for descriptors, runtime records, native smoke
clients, and experiment logs.

Files involved:
`services/docker-compose.yml`, `services/.env.example`,
`scripts/server/**`, `examples/financial_risk/**`,
`examples/datasets/financial_risk_toy.yaml`,
`descriptors/backends/**`, `src/xgap/infrastructure/**`,
`src/xgap/backends/**`, `src/xgap/experiments/**`,
`tests/test_backend_infrastructure.py`,
`tests/test_backend_live.py`, and backend documentation.

Acceptance criteria:
Neo4j and Fuseki can be started on a server; the financial-risk toy data
can be loaded into both backends; native Cypher/SPARQL smoke queries
return non-empty high-risk company rows; descriptor YAML files load;
runtime records serialize to JSON; the registry can list and filter
backends; default pytest does not require live services; optional live
smoke tests run when `XGAP_RUN_BACKENDS=1`; each harness run writes
`query_logs.jsonl` and normalized result JSON.

Current status:
DONE

## M8 Backend Capability Profile + Compiler Boundary Preflight

Goal:
Upgrade backend capabilities from descriptive metadata into
program-checkable capability profiles, and define the exact boundary
between XGAP logical plans, backend support checks, compiler inputs,
compiler outputs, and unsupported-feature reports.

M8 answers five questions:

1. Which XGAP path/GPC fragments does Neo4j support?
2. Which XGAP path/GPC fragments does Fuseki support?
3. Which M0-M6 logical constructs can be safely compiled?
4. Which constructs must explicitly return unsupported?
5. What is the format of compiler input, output, and failure reports?

Expected result:
Descriptor `capabilities` stop being purely descriptive metadata and
become capability profiles that can be checked by program logic.

Files expected:
`docs/m8_backend_capability_preflight.md`, backend descriptor schemas or
capability-profile modules, compatibility-check tests, and current-state
documentation. Existing M0-M7 APIs remain stable.

Acceptance criteria:
Neo4j and Fuseki profiles state support and unsupported reasons using
XGAP path/GPC vocabulary; M0-M6 constructs are mapped to supported,
conditionally supported, or unsupported categories; compiler artifact
boundaries are documented; unsupported constructs fail explicitly in
profile checks; no optimizer, semantic-deviation scoring, planner, LLM,
ontology reasoning, dominance pruning, top-K selection, KGQA evaluation,
or logical-plan-to-native-query compiler implementation is added.

Current status:
DONE

## M9 Minimal Compilers For Backend MVP

Goal:
Implement the first deterministic native-query compiler slice after M8:
validated ALL-selector path patterns or bounded path-algebra fragments
are checked against backend capability profiles and emitted as native
row-oriented `QueryArtifact` values.

Files involved:
`src/xgap/compilers/base.py`, `src/xgap/compilers/gql.py`,
`src/xgap/compilers/cypher.py`, `src/xgap/compilers/sparql.py`,
`src/xgap/compilers/artifacts.py`, `src/xgap/compilers/errors.py`,
`src/xgap/compilers/features.py`, compiler tests,
`examples/compiler_mvp_demo.py`, and `docs/m9_minimal_compilers.md`.

Acceptance criteria:
Cypher and SPARQL compilers support the agreed minimal path/GPC
fragment; GQL fails explicitly; M8 capability checks happen before
native artifact emission; unsupported features raise structured
failures; native output is deterministic; default pytest requires no
live backend services; acceptance passes.

Current status: DONE

## M10 LLM Planner Boundary + Structured Candidate Interface

Goal:
Define the boundary between future LLM-based natural-language planning
and XGAP's deterministic path/GPC stack.

Files involved:
`src/xgap/llm/schemas.py`, `src/xgap/llm/parser.py`,
`src/xgap/llm/protocol.py`, `src/xgap/llm/mock.py`,
`src/xgap/llm/validation.py`, `src/xgap/llm/planner.py`,
LLM-boundary tests, `examples/llm_boundary_demo.py`, and
`docs/m10_llm_planner_boundary.md`.

Acceptance criteria:
Structured candidate JSON parses deterministically into
`PathPatternQuery`; invalid JSON fails explicitly; native query fields
are rejected; `plan_from_question()` requires an explicit provider;
mock provider tests run without a live model; candidate validation can
run type checking, lowering, and plan validation; default pytest does
not require live LLM services.

Current status:
DONE

## M11 Ontology-Bounded Physical Planning

Goal:
Keep logical compilation deterministic for each interpretation and search
only physical realizations: backend placement and explicit cross-backend
exchange decisions. Ontology, schema, source mappings, and semantic
alignment are external, versioned planning inputs rather than search
dimensions.

M11 is decomposed into:

- M11-A Planning Objective and Physical-State Contract
- M11-B Bounded Branch-and-Bound Physical Search
- M11-C Bayesian Cost Model and Search Trace
- M11-D XGAP Main Planner and Exhaustive Oracle Evaluation

Files involved:
`src/xgap/planning/**`, `src/xgap/experiments/**`, M11 tests and controlled
artifacts, M11 demos, `docs/m11_ontology_bounded_physical_planning.md`,
and current-state documentation. Existing logical operators, deterministic
lowering, backend capability profiles, compiler contracts, and M10
candidate objects are reused rather than duplicated.

Acceptance criteria:

- physical states have deterministic identities and contain a fixed logical
  plan, backend placements, and exchange decisions;
- mapping sufficiency and semantic deviation are resolved through pluggable,
  versioned ontology/alignment providers before physical search;
- bounded best-first branch-and-bound search charges one budget unit per
  processed `ExtractMin`, preserves anytime prefixes, and retains the
  discovered complete plan with minimum conservative upper estimate;
- cost observations contain positive raw costs for complete plans and a
  frozen Gaussian-process snapshot predicts log-cost confidence bounds;
- returnable plans satisfy the strict hard bound `C_bar < T_max` and the
  strictly positive Nash-output domain;
- at most one representative is retained per interpretation and deterministic
  top-K ranking uses the planning-time Nash score;
- a tiny exhaustive oracle measures planning regret and search reduction in
  tests and experiments without being used by the production planner;
- compiler and runtime gaps are represented explicitly rather than expanded
  or approximated;
- unit tests, controlled demos, full pytest, and acceptance pass.

M11 does not implement live LLM providers, KGQA loading/evaluation, LoRA or
model training, automatic ontology induction, a built-in general-purpose
OWL/DL reasoner, full GQL, new compiler coverage for recursive/selectors/M6,
logical rewrite enumeration, new execution engines, or distributed
cross-backend runtime orchestration.

Current status:
DONE

## M12 Experimentalization

Goal:
Turn the M10/M11 controlled pipeline into a reproducible experiment surface
without changing the deterministic planner core.

M12 is decomposed into:

- M12-A Experiment Artifact Contract + Dataset Bundle
- M12-B Live LLM + Ontology/Alignment Artifacts
- M12-C Cost Calibration + Online GP Protocol
- M12-D Baselines/Ablations + Server Experiment Runner

M12-A freezes experimental semantics and introduces versioned contracts for
dataset bundles, model bundles, experiment specifications, semantic
deviation, GP protocols, metrics, execution protocols, manifests, hashing,
and run artifacts. It also adds a controlled financial-risk development
bundle and offline development runner over existing M10/M11 interfaces.

M12-B adds a generic OpenAI-compatible structured provider, a fixed DashScope
Qwen ModelBundle, a portable vLLM configuration boundary, bounded runtime
ontology/schema retrieval, query anchors, candidate slot realizations, and a
gold-free file-backed runtime alignment provider. It supplies real runtime
semantic/model inputs to the unchanged M11 planner while reusing M12-A's
frozen semantic deviation exactly.

Files involved:
`src/xgap/experiments/**`, `datasets/**`, `models/**`, `experiments/**`, M12-A
tests and demo, `docs/m12_experimentalization.md`, the M12-A sprint prompt,
and current-state documentation. M11 planner contracts are reused unchanged.

M12-A acceptance criteria:

- the frozen directional ontology-hop semantics and uniform slot aggregation
  are typed, serializable, and tested;
- DatasetBundle, ModelBundle, and ExperimentSpec load deterministically with
  stable versions and content hashes;
- fragment-support, baseline, ablation, metric, execution, GP, and run-layout
  contracts reject invalid combinations explicitly;
- missing optional benchmark gold data remains explicitly unavailable;
- a controlled financial-risk development bundle exercises the contract;
- one offline runner materializes the complete M12 artifact tree through the
  existing M10 mock boundary and M11 planner;
- targeted tests, full pytest, the development run, and acceptance pass.

M12-B acceptance criteria:

- changing only ExperimentSpec/ModelBundle selects the mock or live structured
  candidate provider;
- one generation call and at most one repair call produce no more than M
  grounded `PathPatternQuery` candidates;
- prompt context is bounded, deterministic, content-hashed, and contains no
  gold answers, gold logical forms, gold alignments, or evaluation labels;
- query-side anchors and candidate slot realizations remain separate and feed
  the frozen M12-A `c_sem` implementation;
- ontology/entity IDs, slot coverage, and backend mappings are validated
  explicitly before the unchanged M11 planner runs;
- DashScope uses the fixed `qwen3-max-2026-01-23` snapshot and the same generic
  provider remains configurable for a future/local vLLM endpoint;
- default pytest remains offline, fake-HTTP tests exercise the full provider
  path, and the real Qwen smoke test is explicitly gated.

M12-B does not implement LoRA, model deployment, full ontology reasoning,
real D0 collection, GP calibration, executable baselines/ablations, final
KGQA evaluation, or server experiment orchestration.

M12-C implements real-cost calibration and the online GP lifecycle while
preserving M11 planning semantics. It provides deterministic complete-plan
calibration workloads, repeated Neo4j/Fuseki execution through the existing
M7 clients and M9 compiler boundary, backend-specific D0 artifacts, fitting
of the existing RBF GP family, immutable calibrated-model registration, and
atomic between-task posterior updates.

M12-C acceptance criteria:

- Neo4j and Fuseki use independent backend-local `D0` datasets and RBF GPs;
- raw execution cost is persisted in milliseconds and the GP target is its
  natural logarithm;
- only complete, backend-local, actually executed plans become observations;
- calibration and evaluation splits are distinct and evaluation gold is not
  admitted to calibration cases or features;
- repeated measurements, failures, feature schema, protocol, D0, model, and
  hyperparameter identities are persisted and hashed;
- hyperparameters remain frozen during evaluation, and all plans in task q
  use the same posterior derived from `D_(q-1)`;
- a task batch is appended only after execution and updates only the model for
  the observed backend;
- unsupported distributed movement remains explicitly unavailable;
- offline tests and demos do not require live services, while live calibration
  is explicitly gated;
- M11 search, M12-B inference semantics, and all previous acceptance tests
  remain unchanged.

M12-C does not implement a joint backend-aware GP, transfer-cost learning,
new compiler coverage, distributed runtime orchestration, executable
baselines/ablations, experiment-matrix scheduling, new benchmarks, or new
LLM/ontology behavior.

M12-D composes the frozen M10-M12-C boundaries into a configuration-driven,
resumable experiment system. It implements explicit policies for
`full_xgap`, `random_feasible`, `mean_only`, `no_pruning`,
`no_online_update`, `single_backend`, controlled `exhaustive_oracle`, and the
separate `direct_text2graphquery` system baseline. Frozen candidate artifacts
support fair planner comparisons, while matrix expansion varies dataset,
model, method, epsilon, budget, and seed without planner-code changes.

M12-D acceptance criteria:

- task q plans against one immutable `D_(q-1)` snapshot and commits its
  successful execution observations atomically only after task execution;
- all frozen method and ablation identifiers have explicit behavior or an
  explicit controlled-only boundary;
- candidate generation can be frozen and replayed across comparable physical
  planning methods;
- deterministic matrix run IDs, collision checks, checkpoints, resume, and
  completed-run skipping make sequential server runs reproducible;
- execution records distinguish nonempty success, empty success, and error,
  and retain normalized `row_count`;
- planning, prediction, confidence, latency, failure, and aggregate-ready
  metrics remain separate and unavailable gold/oracle values remain null;
- readiness distinguishes development, pilot, and paper modes, with Python
  3.10+, immutable hashes, pinned backend versions/images, and a consistent
  DatasetBundle mapping/data/M9 native-IRI contract required for paper mode;
- aggregation emits analysis-ready JSON and CSV without claiming publication
  results;
- default pytest remains offline and live backend/model tests are explicitly
  gated.

M12 completion means the experiment infrastructure is ready for paper-grade
dataset/model artifact preparation and large-scale runs. It does not mean
that final datasets or numbers exist, MetaQA/QALD are integrated,
cross-backend distributed execution or movement-cost learning exists, or new
compiler fragments are supported.

Current status:
M12-A DONE; M12-B DONE; M12-C DONE; M12-D DONE

## M13 Automated Semantic Disambiguation

Goal:
Replace controlled semantic-deviation inputs with a separately specified,
evidence-backed disambiguation stage. Reuse M11 one-representative Nash top-K
rather than introducing a second physical ranking algorithm.

Files involved:
Disambiguation modules, ranking modules, tests.

Acceptance criteria:
XGAP can derive reproducible semantic-deviation evidence for candidate
interpretations and supply it through the M11 scorer boundary while keeping
semantic quality separate from conservative execution cost.

Current status:
TODO

## M13-C GrailQA Paper Vertical Slice

Goal:
Extend the current fixed-path fragment only where justified by the GrailQA
audit, normalize the public ontology reproducibly, construct evaluation-only
ambiguity evidence and a versioned pilot DatasetBundle, and run an actual
semantic-to-native-compilation vertical slice.

Acceptance criteria:
The historical M13-A output remains unchanged; the v2 audit reports measured
coverage and structural diversity; ontology SCC normalization and backend
mapping are frozen; gold artifacts remain isolated from inference; the pilot
traverses deterministic lowering, M11 planning, and M9 compilation; unavailable
Freebase execution is reported rather than fabricated; all tests and
acceptance checks pass.

Current status:
DONE. GrailQA is currently recommended for semantic-only paper evaluation.
Real Freebase execution and a rich physical-plan space remain unavailable.

## M13-D Server-Executed GrailQA Semantic Pilot Preparation

Goal:
Freeze and package the first real GrailQA RQ1 semantic pilot so a human can run
it on the experiment server without Codex, source edits, or parameter choices.
The path is NL question to query-independent public metadata retrieval, bounded
M12-B Qwen candidates, existing deterministic validation/grounding, unchanged
`c_sem`, epsilon filtering, deterministic semantic ranking, conservative
reference support, and automatic metrics.

Acceptance criteria:
The repository contains a versioned public inference catalog, file-level
gold-isolation boundary, deterministic retrieval and post-inference Recall@k,
immutable 150-ID spec, safe resumable runner, exact readiness/smoke/full
commands, first-failure accounting, all required raw/summary outputs, and a
150-query fake-provider orchestration run. Existing M12-B prompt/model bounds
remain frozen, candidate generation is reused across epsilon, and normal tests
never call live Qwen.

Current status:
DONE. Local fake-provider orchestration and the real frozen 150-query server
run completed. The result is retained as a diagnostic baseline: zero joint
prompt reachability makes its zero Candidate Recall unsuitable as an isolated
model-capability result. M13-D does not add backend execution, RQ2/RQ3, KQA
Pro, prompt tuning, new algebra, or changed M11/GP/Nash behavior.

## M13-E1 GrailQA Reachability And Interpretation Contract Repair

Goal:
Repair the scientific inference/evaluation boundary before another paid run:
replace the incomplete entity-source path with a reproducible query-independent
Freebase catalog build, measure catalog/retrieval/prompt reachability, separate
semantic choices from canonical representation, and guard a small live
preflight with an offline gate.

Acceptance criteria:
M13-D reachability is reproducible; catalog v2 construction accepts no gold
input and records public provenance/hashes; deterministic retrieval persists
alias, relation-slot, reverse, and domain/range evidence; typed conditions and
canonical normalized equivalence agree; failures and `c_sem` are observable;
the 18-query live runner cannot call the provider when reachability fails; no
full live run, tuning, algebra extension, `c_sem` change, M11/GP change, or
backend execution is added.

Current status:
LOCAL OFFLINE IMPLEMENTATION DONE; SERVER DATA GATE BLOCKED. The v1 audit
reproduces joint prompt reachability 0/150. The comprehensive official Freebase
dump is not local, so catalog-v2 counts, all-35,439 catalog coverage, repaired
retrieval metrics, and the credentialed v2 preflight remain unclaimed until
the server builder and offline gate pass.

## M13-E2 CWRU H100 + vLLM Experiment Backend

Goal:
Make the existing OpenAI-compatible structured-candidate interface runnable
as a self-contained Slurm job on CWRU Pioneer using one scheduler-selected
H100 NVL and the frozen dense `Qwen/Qwen3-32B` vLLM condition.

Acceptance criteria:
Configuration externalizes endpoint, credential environment, and served model;
non-thinking JSON Schema requests are preserved in exact request artifacts;
the shared environment/cache and resolved revision are verified and logged;
readiness and a tiny structured smoke precede inference; generic and 18-query
preflight Slurm wrappers capture reproducibility artifacts and always clean up;
normal tests require no GPU; M13-E1's gate remains authoritative; no semantic,
planning, GP, backend, training, or 150-query behavior changes.

Current status:
LOCAL IMPLEMENTATION DONE; CWRU SUBMISSION PENDING THE M13-E1 CATALOG GATE.
The manually validated CWRU runtime is frozen in a machine-readable contract.
No live H100 inference was run by local acceptance.

## M13-E3 Freebase Catalog-v2 Construction And Reachability Audit

Goal:
Instantiate the existing M13-E1 query-independent catalog design over a frozen
representation of the final public Freebase data and determine, entirely offline, whether all
reference-required GrailQA entities, relations, and types are jointly visible
to the bounded inference prompt.

Acceptance criteria:
Raw download, checksum verification, streaming build, integrity validation,
and reachability audit are independent and restart-safe; external persistent
storage is configurable; the catalog records MID/name/English-alias/type
metadata while retaining the frozen GrailQA ontology as schema authority; all
35,439 supported questions receive catalog coverage; the frozen 150 receive
Recall@1/5/10/20, relation-slot/all-required metrics, prompt truncation, Q/path
strata, and first-loss attribution; compact hashed outputs expose an explicit
`live_preflight_allowed` decision; normal tests use only fixtures and no LLM,
GPU, backend, or download.

Current status:
**IMPLEMENTATION READY; REAL CWRU BUILD AND AUDIT PENDING.** The CPU Slurm job,
runbook, manifests, fixture tests, and report templates are ready. M13-E3A
freezes the reachable `CleverThis/freebase` archival Parquet tree at immutable
revision `dbb1931c2698295653effe9b980a02ab29f004e0` after direct Google object
retrieval returned HTTP 403 from CWRU. Source selection is explicit and has no
fallback; both source modes feed unchanged Catalog-v2 extraction semantics.
No catalog statistics or improved retrieval claims are made before all 964
shards are processed and the compact audit results are returned.

## M13-E3B Gold-Blind Query-Conditioned Local Freebase Catalog

Goal:
Determine whether bounded inference-time grounding can replace a global
Freebase entity index for the frozen 18-query preflight and 150-query pilot.
For each question, derive a local candidate universe solely from its text,
public Freebase English names/aliases/type metadata, and the frozen GrailQA
ontology, while allowing one physical scan to batch independent questions.

Acceptance criteria:
Construction accepts only inference question IDs/text; rejects gold,
reference, answer, and logical-form fields; uses the immutable E3A Parquet
source without redownload; performs bounded name/alias selection and retained
MID type enrichment; produces two isolated Catalog-v2-compatible artifacts;
enforces per-question candidates by ID and text hash; publishes from node-local
staging atomically; preserves persisted query-local entity ranking at
downstream retrieval while leaving global Catalog-v2 FTS unchanged; runs
M13-E1 reachability metrics only after construction; distinguishes
local-catalog misses; preserves the 0.20 gate; and leaves the independent
global E3/E3A job unchanged.

Current status:
**M13-E3B.4 COMPLETE; M13-E3B.5 LOCALLY IMPLEMENTED, CWRU LIVE PREFLIGHT
PENDING.** The real preflight18 build completed with 865 unique entities and
900 assignments. Its
first audit exposed a generic local/global ranking-contract mismatch: local
entity coverage was 10/18 but entity Recall@20 and joint prompt reachability
were both 0/18. E3B.2 makes persisted per-question rank authoritative only for
explicit query-local catalogs, adds before/after and relation/type diagnostics,
and leaves global FTS, candidate construction, prompt bounds, and the 0.20 gate
unchanged. The real E3B.2 rerun validated Entity Recall@1/5/10/20 of 3/7/8/8
over 18 and exposed relation/type ranking as the remaining bottleneck.

E3B.3 freezes deterministic phrase-aware relation/type ranking, ontology-only
IDF tie-breaking, bounded relation-slot domain/range coherence, and
pre-truncation type provenance. Its audit preserves prior artifact hashes and
writes relation/type ranking decompositions, v2 failure stages, and exact
before/after metrics. The real rerun improved Relation Recall@1/5/10/20 to
5/11/12/13 of 18 and relation prompt coverage to 10/18. Type Recall@1/5/10/20
became 1/4/8/13, explicit Type prompt coverage remained 4/18, and joint prompt
reachability remained 1/18.

E3B.4 freezes a shared role-aware relation-endpoint visibility contract. Exact
domain/range types may ground only the source/target endpoint adjacent to the
candidate's selected prompt-visible relation, respecting OUT, IN, and
UNDIRECTED direction. Fixed linear paths use the first and last relation hop;
ambiguous regular expressions receive no derived evidence. Offline audit keeps
explicit Type metrics unchanged, reports `effective_type` separately, and uses
that same runtime contract for joint reachability and the existing gate. Its
real acceptance was an audit-only rerun over the existing preflight18 SQLite
artifact. Effective Type prompt coverage rose from 4/18 to 12/18 and joint
prompt reachability from 1/18 to 5/18, so the unchanged 0.20 gate passed at
0.2778 while explicit Type Top-4 remained 4/18.

E3B.5 connects that passing query-local artifact to the frozen 18-query CWRU
Qwen3-32B preflight. An explicit artifact profile validates the exact question
set, catalog hash, audit hash, reachability-row hash, prompt bound, and
endpoint contract before model startup. The structured request exposes the
same endpoint rule used by deterministic runtime validation, and evaluation
reports both overall metrics and metrics conditioned on the jointly reachable
five-question subset. It does not rescan Freebase, alter Top-50 or Top-4,
change the gate, run pilot150, or modify ranking, Qwen parameters, planner,
compiler, or backend behavior.

The first real CWRU E3B.5 submission passed the 5/18 gate but stopped before
model loading because readiness compared JSONL row order with spec order.
E3B.5.1 treats physical row order as irrelevant while still requiring one
unique record for every frozen preflight ID and no extras. The second
submission passed readiness, loaded Qwen3-32B on H100, and passed strict
structured-output serving. It then exposed one additive diagnostic-contract
gap: the shared classifier rejected the already documented local-catalog stage
`reference_not_in_local_catalog`. E3B.5.2 admits that stage without weakening
unknown-stage rejection. The next submission completed cleanly but every live
request received HTTP 400 before generation: the 8192-token serving context
could not hold the observed 4146-4590 input tokens plus the frozen 4096 output
budget. E3B.5.3 preserves both bundle budgets and expands only the deployment
context to their exact sum, 12288. It also checks that arithmetic before model
startup. The next run reached 17/18 provider success and 5/5 provider success
on the jointly reachable subset, with zero malformed responses, but strict
guided decoding returned `candidates=[]` for every successful call because the
schema permitted an empty array. E3B.5.4 requires one to three generated
candidates in the CWRU schema and prompt while preserving all downstream
validation and rejection boundaries. The next run proved that vLLM 0.11.1 did
not enforce those array cardinality keywords and again returned only empty
arrays. E3B.5.5 deterministically checks the active bundle's candidate
`minItems/maxItems` at the provider boundary and routes violations through the
existing single repair call. The rerun remains the next experiment action.

## M14 KGQA Evaluation

Goal: Add KGQA dataset loading, execution harnesses, and evaluation reporting.

Files involved: `src/xgap/datasets/kgqa.py`, evaluation scripts, dataset tests.

Acceptance criteria: Evaluation can compare generated queries or answers against KGQA benchmarks.

Current status: TODO
