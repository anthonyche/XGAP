# XGAP Status

## Current Mainline Milestone

M15-A **Contracts, Tools, Memory, and Bounded Goal Loop** is implemented
locally. XGAP now has a typed semantic DAG with unresolved entity, predicate,
type, and source holes; explicit hard/relaxable constraints; typed and
allowlisted tools; a pluggable black-box backend registry; adapters for the
existing healthcheck/execute clients; provenance-bearing memory; and a bounded
goal loop with success, blocked, failed, and budget-exhausted outcomes.

The deterministic sequential policy is the first baseline. It does not use an
LLM, does not automatically retry tool failures, and records every tool result
as both an observation and execution-memory record. M15-A adds no cross-source
movement, coordinator join, plan search, or live service claim.

M15-E1 is now locally implemented as a selective semantic-resolution policy on
that same goal loop. Four typed tool roles cover catalog lookup, ontology
lookup, bounded LLM proposal, and user clarification. Fully bound programs use
zero tools; ambiguous identities are never sent to ontology or LLM and require
an authoritative bounded clarification. Non-entity candidates may use optional
ontology/model evidence, but model output cannot add IDs, claim authority,
carry native query text, or hide more than one external call. Hard constraints
are hashed and preserved, calls are observable and stored in execution memory,
and failures are never retried.

M15-E2A now supplies the OpenAI-compatible adapter as a separate candidate-ID
protocol and frozen Qwen3-32B bundle. Its per-request schema enumerates exactly
the bounded candidate set; the bundle caps results at eight IDs and 256 output
tokens, uses a 60-second timeout, permits one external request, and disables all
repair calls. Entity/configuration failures occur before network access, while
transport, timeout, malformed-response, and out-of-set failures retain their
one-call cost in the ordinary tool result. The provider remains
non-authoritative and cannot emit native query text. Focused E1/E2 acceptance
passes 42 tests and full local acceptance passes 967 tests with 36 explicit
skips. Those E2A tests are offline-transport results; the separate E2B live
lifecycle is recorded below. Real catalog/ontology wiring and parser-to-hole
construction are handled by E3, while UI clarification transport remains
pending.

M15-E2B now has a verified live lifecycle and independent audit boundary. It
seals one four-candidate predicate request before service startup,
reuses the exact CWRU Qwen3-32B environment, performs no generic inference
smoke, and executes exactly one model-backed tool call through the goal loop.
The wrapper has a 45-minute H100 allocation limit, loopback-only service,
bounded shutdown, zero repair, and zero automatic retry. The auditor
reconstructs the preflight, CWRU environment, tool result, provider invocation,
execution memory, lifecycle, and artifact inventory while checking that the run
tree is unchanged. CWRU job `3792284` first proved model startup and readiness
but failed before generation because vLLM 0.11.1 rejected the guided-decoding
keyword `uniqueItems`; it spent one request with zero tokens and is preserved.
The provider-facing schema now omits only that unsupported keyword while the
deterministic validator still rejects duplicates. Replacement job `3792307`
at exact clean commit `a2ed618` completed on `gput073`: Qwen3-32B returned the
in-set candidate `predicate:transferred_to` in one 1.877-second inference with
452 input and 21 output tokens, one tool/provider call, zero repairs/retries,
and preserved hard constraints. Its read-only audit passed 127/127 checks with
no run-tree mutation. This is accepted mechanism evidence, not a quality or
paper result.

M15-E3 now closes the deterministic intake and local artifact-provider gap.
One versioned exact-phrase template turns the controlled financial-risk request
into four existing semantic operators, four typed holes, two hard constraints,
and two relaxable constraints with zero external calls. The relationship-
strength hole preserves single-transfer, window-total, and window-frequency
meanings instead of treating `密切` as only a predicate. Versioned catalog and
ontology providers expose bounded IDs, raw artifact SHA-256, provenance, and
zero-call cost through the same E1 tools. Ontology expansion is one hop and is
restricted to predicate/type holes. The alias `Alice` yields two catalog
identities and cannot proceed without an explicit in-set user clarification;
without that tool the goal blocks after one catalog read and makes no ontology
or model call. With the explicit development selection, the route succeeds in
six calls: four local catalog reads, one local ontology read, one user
clarification, zero LLM calls, and zero backend calls. The fixtures do not
claim general NL understanding or ontology truth and remain
`paper_result=false`.

M15-E4 now verifies that sealed E3 commit before it creates an execution plan.
The three relationship-strength candidates and two predicate candidates form
six stable semantic classes. A pair of bridge-registered, SHA-256-bound Neo4j
templates supplies the hard exclusive month upper bound that the parent F2C
family lacks. The two single-transfer classes each map to the registry's two
physical strategies, while the four window-total/frequency classes remain
explicitly unavailable because `SUM` and `COUNT/HAVING` capabilities are not
registered. No class, hard constraint, or clarified identity is silently
changed. Bridge compilation makes zero backend, model, and ontology-service
calls and exposes no native query text. Offline post-construction validation
executes all four plans against deterministic fixtures. Repository-wide counts
are now refreshed: the bridge/E3/registry-focused gate passes 32 tests, and
full local acceptance passes 1,003 tests with 36 explicit skips. All artifacts
remain `paper_result=false`.

M15-E4B now supplies the local native execution and independent evidence gate
for that bridge. A self-hashed preflight reconstructs the run-local resolution
and bridge spec, preserves all six semantic classes, and seals four physical
candidates before Neo4j or Fuseki starts. The allocation-scoped runner loads a
hash-bound fixture and executes exactly two strategies for each of the two
executable classes: one Neo4j plus one Fuseki call per plan, eight calls total,
zero profile/model/ontology calls, and zero retry. The four unsupported
aggregate classes never reach a backend. The auditor independently recompiles
the bridge and workload, compares exact post-execution oracles, validates the
service lifecycle and invocation graph, detects row tampering, and proves the
run tree unchanged. CWRU job `3792349` executed the gate at exact clean commit
`8056ee4` on `compt292` in 94 seconds: all four physical plans completed, the
eight-call contract held, the runtime was removed, and cleanup succeeded. The
first independent audit exposed an auditor-only schema mismatch: it expected a
synthetic `loopback_only` field not emitted by the real service-plan schema.
Fix `aed12e3` now reconstructs isolation from the persisted endpoints, Fuseki
startup arguments, and Neo4j listen/advertised addresses. Re-auditing the same
immutable run passed 152/152 checks with no run-tree mutation; no experiment
was retried. The compact record is
`experiments/artifacts/m15_e4b_cwru_native_resolution_execution_20260906.json`.
The audit-fix branch passes full local acceptance with 1,010 tests and 36
explicit skips. This is mechanism evidence only; `paper_result=false` remains
mandatory.

M15-E5 now has its semantic-objective and clarification decisions: the author
selected a two-level
interpretation-set and relaxation-frontier design. E4 emits co-equal unresolved
interpretations with no
authoritative zero-deviation class; E2B provides bounded but non-authoritative
candidate IDs without confidence; F2C10 family memory predicts only physical
latency and bytes; and F2C9 requires exactly one global
`semantic_deviation=0` class. Directly wiring these layers would invent user
intent. The selected design performs physical reduction and anchored relaxation
frontiers inside each interpretation, then bounded representative selection or
clarification across unresolved interpretations. R1 freezes the impact rule:
aggregation, path, quantifier, answer-meaning, output-contract, or executable-
capability differences require clarification, while same-structure predicate
alternatives remain bounded representatives. The current question must ask
whether `密切` means a single transfer, cumulative window amount, or frequency.
The first offline mechanism now passes its invariant suite. It preserves all
six E4 interpretations, obtains four physical estimates from sealed family
memory with zero current-query profiling, and keeps one representative inside
each executable interpretation. Before clarification it emits one R1 question
and returns no execution-eligible semantic plan; a controlled authoritative
single-transfer selection returns the two same-structure predicate
representatives while retaining all unavailable classes. E5B now requires a
second explicit authority event before treating either predicate as the exact
base. It verifies the E4-sealed E3 ontology, admits only the declared one-hop
bidirectional sibling, attaches the relation's `0.25` development deviation
and provenance, and applies Pareto/5%-epsilon/K only inside that anchored set.
With `transferred_to` as base both plans survive; with lower-cost `paid_to` as
base the relaxed transfer class is dominated. The selector retains all six E4
classes and makes zero current-query profile, backend, LLM, or ontology-service
calls. The compact E5B record is
`experiments/artifacts/m15_e5b_local_anchored_interpretation_frontier_20260907.json`.
Focused E5 acceptance passes 20 tests and full repository acceptance passes
1,030 tests with 36 explicit skips. This remains local nonmeasurement
mechanism evidence. E5C now adds the missing resumable authority transport.
Its two content-addressed questions keep R1 structural authority separate from
the predicate base required for anchored relaxation. Each accepted response is
an explicit in-set user event bound to the session, sequence, hole, and pending
question hash; arbitrary conversation text cannot serve as authority. The full
event log reconstructs the same state after a process restart. Choosing either
unsupported aggregate interpretation terminates without execution, while a
ready session creates a hash-bound handoff containing all and only the E5B
returned runtime plans in selection-rank order. The portable handoff exposes no
Cypher or SPARQL and allowlists only `runtime.execute_plan`; a controlled test
passes each attached plan through that existing interface and observes no
unselected plan. An independent reconstruction audit passes 13/13 checks, the
focused E4/E5 regression passes 43 tests, and full repository acceptance passes
1,044 tests with 36 explicit skips. The compact nonmeasurement record is
`experiments/artifacts/m15_e5c_local_clarification_transport_20260907.json`.
E5D now provides the separate live selected-plan gate. It imports the accepted
F2C10D historical family-memory view by exact identity, requires explicit R1
structural and predicate authority, and seals the reconstructed E5C session,
events, frontier, handoff, and expected calls before native services start.
One finite goal exposes only `runtime.execute_plan`, executes every and only
the ranked handoff plans, stops after the first failure, and never retries.
Selection has zero current-query profiles, backend, LLM, ontology-service, or
oracle calls; answer oracles open only after all execution succeeds. A separate
read-only auditor reconstructs E4/E5C, goal/memory/results/invocations, cleanup,
and actual Neo4j/Fuseki loopback configuration. CWRU job `3793365` completed at
the frozen commit on `compt351` in 82 seconds and passed all 127 independent
audit checks without mutating its run tree. It executed two selected semantic
plans through two goal calls and four backend calls, returned 11 and 6 rows,
and moved 17,784 bytes. Selection made zero current-query profile, LLM, or
ontology-service calls and used no retry. It remains `paper_result=false`. See
`experiments/artifacts/m15_e5d_local_live_selected_session_readiness_20260907.json`,
`experiments/artifacts/m15_e5d_cwru_native_selected_session_20260907.json`, and
`docs/m15_e5_interpretation_relaxation_gate.md`.

E6A now supplies the missing typed control-plane envelope needed by that
adapter. Per-job environment values are accepted only for the exact allowlisted
Slurm script; the E5D wrapper alone accepts its six non-secret memory, session,
and authority fields. Other scripts reject them, and unsafe or oversized values
fail before any SSH call. Fixed runtime settings remain separate, no credentials
or native query text are accepted, and returned observations expose keys rather
than values. Full repository acceptance passes 1,055 tests with 36 explicit
skips. This is local mechanism readiness only; no remote or backend call was
made. See
`experiments/artifacts/m15_e6a_local_remote_authority_envelope_20260907.json`.

E6B now supplies the presentation-independent UI adapter. It exposes only the
hash-bound E5C question and candidate IDs, delegates selected IDs to the E5C
authority-event builder, and refuses out-of-set or terminal responses. A ready
session can produce one explicit-confirmation E5D submission preview only when
its two events share one authority source and its historical-memory hash still
matches the E5C source contract. The preview uses the fixed E5D script and
exactly six E6A fields; it exposes no native query, credential, arbitrary
environment, or shell command. Full repository acceptance passes 1,061 tests
with 36 explicit skips. This remains local nonmeasurement readiness; an HTTP
server and interactive page do not yet exist. See
`experiments/artifacts/m15_e6b_local_clarification_ui_adapter_20260907.json`.

E6C now supplies the smallest interactive local working surface over that
adapter. A loopback-only Python service reconstructs E5C from a sealed
resolution artifact, the accepted historical-memory view, fixed policies, and
a content-hashed two-event store. The displayed request must match the sealed
resolution question hash. Browser actions carry the current session/question
hash, an in-set candidate ID, and explicit confirmation; the browser cannot
provide the authority-source ID, remote memory path, environment values,
credentials, native query text, or a shell command. Remote submission is off by
default. When explicitly enabled, one confirmed terminal handoff may invoke
only the existing typed `remote.executor` for the fixed E5D wrapper and is never
automatically retried, including when the outcome is uncertain. The local page
uses the same two actions for visible controls and its declared model-context
tools. Focused controller/server acceptance passes 34 tests, full repository
acceptance passes 1,075 tests with 36 explicit skips, the production frontend
build passes, and page-level static checks pass. No CWRU job or external service
was invoked. Model-context runtime registration has not yet been browser-
validated, and the page has not undergone a user study or paper experiment.
See `experiments/artifacts/m15_e6c_local_clarification_ui_20260907.json`.

The last published M15-D1 gate passed 128 focused tests with two real-service
tests skipped. Full-suite acceptance passed with 600 tests and 36 explicitly
gated or external-artifact tests skipped. Refreshed CWRU CPU smoke job
`3787126` then reproduced that gate at exact clean commit `4c26eea` on
`compt331`: exit `0:0`, 128 passes, two gated skips, seven declared artifacts,
and all three control-path oracles passed. Its compact record is
`experiments/artifacts/m15_d1_cwru_core_smoke_20260905.json`. The subsequent
local M15-C2/D2 live adaptive implementation passes 140 focused tests with two
live-service skips and full acceptance with 612 passes and 36 explicit skips.
It is committed and CWRU job `3787152` has now verified the real-service path;
its tiny uncalibrated fixture correctly retained the initial plan and remains
an engineering acceptance result rather than paper-performance evidence.

M15-F0 now supplies the next experiment substrate locally. Two committed,
strict specifications generate rather than store their larger artifacts. Both
use 200 companies and 5,000 transfers: `selective-dev-v1` places 20 high-risk
companies outside the hot set and yields 120 exact rows, while
`broad-hot-dev-v1` places 160 high-risk companies across the hot region and
yields 4,800. Generated Neo4j/Fuseki loads, full/bound queries, source oracles,
and final answers are namespaced, no-overwrite, and SHA-256 bound inside the run
tree. Generator v3 additionally fixes Neo4j load batches at 100 rows and binds
the strategy, batch size, and statement count into bundle schema v2. The same
exact semantic program, two candidate plans, observation tuple,
and common probe run through a separate `scaled_adaptive` native mode. Its
auditor binds the profile to the committed spec and validates the bundle and
full service/query chain. At that checkpoint the local M15 gate passed 159
tests with two live skips and full acceptance passed 631 tests with 36 gated
skips. F0 remains
`paper_result=false`. Its first CWRU selective submission, job `3787167` at
commit `36281aa`, reached live Neo4j fixture loading but failed before profile
or query execution because generator v1 placed JSON-quoted map keys in a
Cypher `UNWIND` literal. Generator v2 then emitted deterministic validated
Cypher map syntax. Explicitly new job `3787173` at clean commit `3a2bce9`
proved that repair and made both services healthy, but failed at statement 6/6:
one request still contained all 5,000 transfers and exceeded the fixed
30-second Neo4j deadline after five successful statements. It made zero profile
and query calls. Both failures are preserved as non-paper diagnostic artifacts;
generator v3 uses 100-row deterministic batches without changing the timeout
or retry policy. Job `3787213` at clean commit `32c157f` then completed on
`compt336` in 89 seconds. Neo4j loaded all 56 statements in 18.26 seconds,
Fuseki loaded once, and the exact 120-row answer used risk-first bind, two
remote calls, and 28,702 transferred bytes. The separate read-only audit passed
188/188 checks with no run-tree mutation. This closes the single-run selective
engineering gate, not calibration, repetition, or comparative performance.

M15-F1 now has a locally executable cross-task method surface. Snapshot reuse
is guarded by a SHA-256 context over semantics, candidate plans and native
artifacts, observation requests, cost parameters, workload manifest, and
catalogs. Full agent distinguishes a cold profile-and-persist task from a warm
memory-hit task; the warm path removes three repeated profile calls, executes
one reusable common-prefix probe, updates append-only memory, and permits one
plan change. Two fixed-plan controls, `no_memory`, `no_profile_probe`, and
`no_replan` are explicit policies rather than aliases. In the controlled
selective matrix, all six methods returned the exact answer; only full agent
acted on the induced stale-to-current plan flip, while no-replan observed but
kept the old plan. The clean-commit F1 gate passed 640 tests and the subsequent
F0 batch-protocol regression raised that checkpoint to 641. After F1L, F2B4,
and the F2C0--F2C10A stream, family, typed-query, workload, exact-execution,
family-memory, semantic-frontier, execution-readiness, overlay, native
frontier, variable-cardinality split, and F2C10D pilot contracts, current full
local acceptance passes 899 tests with 36 gated skips. This is
`paper_result=false`; no live comparative timing claim is made.
The compact clean-commit mechanism record is
`experiments/artifacts/m15_f1_local_controlled_method_matrix_20260905.json`.

F1L now adds a separate real-service method-matrix path without changing the
audited F0 run. One verified workload and one Neo4j/Fuseki allocation execute
the two static controls, `no_memory`, `no_profile_probe`, `no_replan`, and
`full_agent`. A common three-observation calibration is excluded from method
metrics; each method has an independent event phase and answer artifact, and
warm policies use isolated append-only memory files seeded from the same
snapshot. The mode-aware auditor requires the exact 18-call trace, workload
hashes, policy contracts, snapshot identities, six oracle-equal answers,
service lifecycle, and cleanup. CWRU job `3787267` completed on `compt336` in
92 seconds at exact clean commit `6aafafd`. Every method returned the exact
answer, the phase counts were `3+2+2+5+2+2+2=18`, three warm methods used
separate append-only memory files, and guarded runtime cleanup succeeded. The
independent read-only audit passed all 326 checks with no run-tree mutation.
Its fixed order, shared unknown backend cache, single selective workload, and
uncalibrated cost constants keep `paper_result=false` and preclude a latency
ranking. The compact evidence record is
`experiments/artifacts/m15_f1l_cwru_native_method_matrix_20260905.json`.

M15-F2 now has a pure development campaign compiler. It hash-binds the two F0
workload specifications, freezes all six F1 policies, and builds a seeded
Williams design with six sequences per workload and block. The compiler proves
that every method occupies each position once and that all 30 directed
first-order method transitions occur once per stratum. It declares fresh
service lifecycle, cache state, common calibration exclusion, method-isolated
memory, warmup and measured attempts, exact-answer gating, and zero retry.
Compilation makes zero backend/model/ontology calls and emits no measurements.
The current configuration produces 12 sessions and 72 measured query attempts,
but is intentionally not paper-ready: it has only one query label per
workload and therefore cannot measure cross-task memory reuse, those labels
are not hash-bound query artifacts, coordinator costs are uncalibrated,
isolation is not live-validated, and repetition/statistical
choices remain author-owned.

M15-F2C0 now compiles the implicit query/repetition products of one selected
F2B session into explicit, ordered task identities. The compiler recomputes
the incoming portable query-binding and session-schedule hashes, preserves the
exact query-spec and bundle-contract identities on every task, isolates all
method namespaces, freezes each pre-task history view, prohibits within-task
memory visibility, and permits post-task commits only after successful exact
answers for write-enabled policies. It makes no external call. The current
selective session expands to six measured tasks and remains
`multi_task_memory_ready=false` because each method still has only one query
task, the query is not parameterized, and an executable family-local transfer
model has not been bound. This local contract remains `paper_result=false`.

The F2C1 research choice is now frozen at the architectural level: use
multiple parameterized query families and transfer memory only within an exact
family compatibility key. Held-out instances of known families will test
within-family reuse; held-out families will be cold-start fallback conditions.
The exact family inventory, 30--50 instance allocation, split, and statistical
protocol are not yet frozen or executed.

The initial F2C1 compiler is locally implemented. It separates family
compatibility from concrete hard bindings, verifies every query-spec source,
rejects structural or version drift, assigns immutable family and instance
hashes, and freezes seed/held-out memory routing. Its development family key is
`47ebfcfe5a119122ea299d67bd8c3b93f777ac965649a64c88f0c10d6b1a5b4b`.
The registry has one Alice seed only, so the compiler reports missing typed
operator-DAG and backend-template bindings, workload/oracle contracts,
held-out coverage, additional families, and the 30--50 instance target. It
makes no external call and remains `paper_result=false`.

M15-F2C2 is now locally implemented as a new v2 parameterized-query contract;
the audited v1 query and F2B4 run remain unchanged. The selected policy makes
clarified entity identity, time lower bound, and amount lower bound immutable,
while risk, transfer predicate, and direct-path shape may use only their
declared bounded relaxations. The compiler materializes a typed seven-node
semantic DAG, enforces exact binding coverage, type-checks backend parameters,
and distinguishes compile-time templates, runtime values, and runtime
intermediates. Its family compatibility hash is
`34d432efccebd8d4000d52f910a25746b01e6d884f99eb41de6cbe846c13dfec`;
the current Alice instance hash is
`f23a1d799e73362e28686d8f9f2f9f514fbdfd26b2af68b95a9bca2cc001c266`.
The contract does not yet bind executable backend query files, a
multi-instance workload, or answer oracles, makes zero external calls, and is
`paper_result=false`. F2C3 is therefore a local artifact-binding milestone,
not a CWRU experiment.

M15-F2C3 is locally implemented. Its deterministic development bundle binds
the F2C2 family to literal-free Neo4j full/bound templates, a literal-free
Fuseki risk template, one shared multi-person dataset, per-instance binding
records, and independently generated source/final oracles. The snapshot has
four people, 30 companies, 720 transfers, four seed queries, and two held-out
instances. Final oracle row counts are 11, 13, 16, 42, 11, and 7; every source
and final oracle is nonempty. All instances retain family hash
`34d432efccebd8d4000d52f910a25746b01e6d884f99eb41de6cbe846c13dfec`,
and the bundle content hash is
`b06b1c4b4e630e37cbea8d4cf5d81bbc31c4a2280b97a64f5a4a9efed0d434e7`.
The bundle is fully regenerable and rejects content-plus-manifest tampering.
It has not called or been validated against live backends, covers only the
zero-relaxation interpretation, represents one development family, and stays
`paper_result=false`.

M15-F2C4 is verified on CWRU. Every
one of the six parameterized instances compiles into the same two exact
federated strategies and has passed local end-to-end scheduler execution
against deterministic backend doubles. The new explicit task stream contains
four seeds followed by two held-out instances. Its native mode loads the shared
bundle once, verifies twelve real source fragments, then runs both plans for
all six instances through the ordinary backend tool and coordinator. Alignment
uses the declared full company-ID domain rather than answer oracles. A separate
read-only auditor binds the generated bundle, service lifecycle, fixture
verification, 24-call task trace, candidate plans, and twelve exact answers.
Memory, plan selection, relaxation/Pareto logic, LLM, and ontology are disabled
in this gate, so it remains `paper_result=false` and makes no performance or
transfer claim. Job `3787592` completed at exact clean commit `66327a47` on
`compt298` in 69 seconds. Its independent read-only audit passed 172/172
checks with no failed IDs and no run-tree mutation. The compact evidence record
is `experiments/artifacts/m15_f2c4_cwru_native_parameterized_stream_20260905.json`.

M15-F2C5 is locally implemented above the unchanged F2C4 execution bridge.
Its family memory is not the old exact-context cache: compatibility is bound
to method, structural family, workload bundle, and runtime. Four seed tasks
measure both exact strategies and append only after complete success and
post-execution oracle validation; stored records contain typed bindings and
costs but no answer rows. The store is reopened and frozen before evaluation.
Both held-out instances read the same seed-only view, select one plan with an
oracle-free development KNN, and never write. Optional alternate-plan runs are
post-selection evaluation shadows with separate call accounting. Thirteen new
tests cover deterministic feature identity, cross-context rejection, frozen
predecessor visibility, persistent memory, choice changes, cold start, online
execution, and zero-retry failure evidence. The native mode now binds memory
to the exact Slurm allocation, filesystem, Java, runtime lock, staging
manifest, and backend versions. Its dedicated wrapper and read-only auditor
verify seed result-to-memory costs, one frozen view, oracle-free selections,
selected-before-shadow call roles, exact answers, clean shutdown, and zero
retry. CWRU job `3787610` completed at exact clean commit `30214cb` on
`compt298` in 69 seconds. The outer run succeeded, guarded cleanup removed the
runtime, and the independent read-only audit passed 278/278 checks with no
failed IDs or run-tree mutation. This closes native family-transfer plumbing;
both held-out selected answers were exact, but the development KNN selected
zero of two post hoc observed latency winners. Because each shadow ran after
the selected plan, this is an order-confounded diagnostic rather than a regret
estimate. It must not be tuned against. Multiple families, a paper-frozen
model, and comparative claims remain open. The compact evidence record is
`experiments/artifacts/m15_f2c5_cwru_native_family_transfer_20260906.json`.

M15-F2C6 is locally implemented as a planning-only bounded semantic solution
space. The catalog covers all and only the three declared relaxable
constraints, while the clarified person identity, time lower bound, and amount
lower bound remain unchanged in every derived typed query. The HIGH-risk
reference instance produces 12 raw interpretations. Duplicate semantic
derivations merge before physical planning; each class keeps one lowest-latency
successful plan with resource and plan-ID tie breakers. A standard
semantic-deviation/latency/resource Pareto pass, a semantic-preserving 5%
minimum-gain epsilon rule, and deterministic exact/extreme/max-min selection
then return at most four representatives. These values are development
settings rather than frozen paper parameters. The mechanism makes no backend,
LLM, or ontology call during enumeration and does not yet execute or validate
relaxed answers, so it remains `paper_result=false`.

M15-F2C7A/B1 is locally implemented. A zero-call readiness audit binds the
F2C6 semantic classes to the verified F2C3 generator and bundle instead of
assuming declared relaxations are executable. Of 12 classes, one exact class
is already bound, one HIGH-to-MEDIUM risk-only class can be generated with the
current artifacts, and ten are blocked by missing predicate and/or path
support. The supported class is materialized into a separate deterministic
seven-instance overlay bundle while the base six-instance bundle and both
shared backend loads remain byte-identical. The new risk-relaxed instance has
an 11-row final oracle; it has not run against live backends. Predicate support
and multihop semantics remain open, so this is artifact readiness rather than
semantic-quality or performance evidence. The compact local record is
`experiments/artifacts/m15_f2c7b1_local_semantic_overlay_20260906.json`.

M15-F2C7B2 is verified on CWRU. Job `3787648` ran exact clean commit `2197aef`
on `compt386` for 81 seconds. Its dedicated native mode regenerated the base
bundle and semantic overlay, verified the full seven-instance fixture, and
executed only the approved HIGH-to-MEDIUM class with one fixed risk-first plan.
The two-call execution moved 3,963 bytes and returned all 11 exact oracle rows;
person identity, time, and amount hard bindings remained unchanged. The
independent read-only audit reconstructed the full chain and passed 133/133
checks with no failures or run-tree mutation. This closes a real-backend
mechanism gate only: it does not compare physical strategies, use
memory/LLM/ontology, validate user utility, or enable a paper claim. The
compact record is
`experiments/artifacts/m15_f2c7b2_cwru_native_semantic_risk_relaxation_20260906.json`.

M15-F2C8A is locally accepted. Its mapping specification binds the cataloged
`transfer_to_company` to `payment_to_company` transition to a closed Neo4j
relationship type and a deterministic independent payment-edge fixture. A new
cumulative overlay preserves 47 base files byte-for-byte, retains the frozen
Neo4j load as an exact prefix, reuses the Fuseki data unchanged, and appends
eight fixed-size payment batches. It binds all four direct semantic classes:
exact, risk-only, predicate-only, and combined risk-plus-predicate. The three
added final oracles contain 11, 6, and 9 rows. Both existing physical strategies
return each added oracle in local scheduler tests, and the normal fixture path
verifies 18 source queries across nine instances. Full pytest passes 825 tests
with 36 gated skips and the complete acceptance script passes. The mapping is
a development fixture rather than ontology truth; live payment execution,
semantic utility, and every multihop class remain open. The compact record is
`experiments/artifacts/m15_f2c8a_local_predicate_overlay_20260906.json`.

M15-F2C8B is verified on CWRU. A dedicated
runner executes only the predicate-only and risk-plus-predicate direct classes,
using one fixed risk-first plan per class. It constructs both plans before any
oracle access, preserves all hard bindings, expects four backend calls, and
validates exact 6- and 9-row answers only after execution. The native service
mode revalidates the predicate overlay at the fixture boundary and the new
Slurm wrapper is on the remote executor allowlist. The independent read-only
auditor reconstructs both plans and oracles from the base bundle, catalog,
mapping, and overlay; its local synthetic run tree passes 150 checks and its
tamper tests reject changed answers and plan identities. CWRU job `3790680`
ran exact clean commit `2d39c3c` on `compt295` for 96 seconds. Both classes
matched their exact 6- and 9-row oracles in four aggregate calls and moved
6,262 bytes; the independent audit passed 150/150 checks with no failures or
run-tree mutation. No semantic-user-utility evidence, ontology call, plan
comparison, or paper claim exists. The live record is
`experiments/artifacts/m15_f2c8b_cwru_native_predicate_relaxation_20260906.json`.

M15-F2C9A is locally accepted. The new capability-aware candidate set retains
all 12 declared class identities but admits only the four verified direct
classes and records all eight multihop classes as unavailable. Two physical
strategies per direct class produce eight candidates. A complete hash-bound
prediction snapshot is sealed before execution; oracle fields, post-execution
evidence, incomplete or duplicate estimates, runtime-plan drift, and post-seal
mutation fail closed. Selection keeps one predicted-cost physical plan per
class before applying semantic-deviation/predicted-latency/predicted-resource
Pareto, 5% epsilon, and K=4 reduction. The controlled fixture exercises an
8-to-4-to-4-to-3 path and retains exact semantics first. Full acceptance passes
844 tests with 36 gated skips. The estimates are constructed, no external call
occurs, and no performance or semantic-utility claim is enabled. The compact
record is
`experiments/artifacts/m15_f2c9a_local_direct_semantic_frontier_20260906.json`.

M15-F2C9B is accepted live. Its one authorized native mechanism job finished
at the scheduler level, and the corrected auditor has now verified the same
immutable run tree. A versioned
controlled estimate source is copied into the immutable run tree and bound to
all eight direct physical candidates. The runner persists the candidate set,
estimate source, sealed snapshot, and three-plan frontier before reading an
answer oracle or invoking a backend. It then executes only the returned exact,
combined, and risk-only plans in rank order, for exactly six expected backend
calls; any first external failure stops the run without retry or fallback. The
new native mode, dedicated allowlisted Slurm wrapper, and independent read-only
auditor cover overlay regeneration, fixture verification, frontier
reconstruction, exact answers, call order, service shutdown, and runtime
cleanup. The controlled native-double path returned 11, 9, and 11 exact rows,
and its reconstructed synthetic run tree passed 211/211 audit checks. Full
local acceptance passes 853 tests with 36 gated skips. CWRU job `3791375`
completed at exact commit `2c0ee7f` on `compt298` in 94 seconds with exit
`0:0` and returned the expected exact 11-, 9-, and 11-row answers. Its first
audit failed 20 preflight checks because the auditor searched the outer run
root instead of the producer's service root. The fix at `9e1a1db` was applied
only to the auditor; the v2 read-only audit then passed 211/211 checks against
the unchanged job tree with `run_tree_mutated=false`. The job must not be
rerun. No semantic-utility,
comparative, performance, ontology, or paper claim is enabled. The local
readiness record is
`experiments/artifacts/m15_f2c9b_local_native_direct_frontier_readiness_20260906.json`.

M15-F2C10A is locally accepted. The author selected family-memory prediction
and preservation of every catalog-adjacent direct interpretation. A new
versioned compiler expands the six frozen development base queries into 28
semantic tasks and 56 physical candidates: HIGH/LOW have four classes and
eight plans, while MEDIUM keeps both adjacent risk directions and therefore
has six classes and twelve plans. The four seed base queries produce 18
training tasks; the two held-out base queries produce 10 held-out tasks. Every
interpretation inherits the base split and preserves the hard entity, time,
and amount bindings. Hash-bound selection views expose no answer artifacts,
while an independent evaluation registry binds their post-selection location
and hashes. The generalized F2C10 v2 selector accepts either cardinality and
still applies physical reduction, Pareto, epsilon, and K; the three frozen
F2C9 v1 hashes remain byte-identical. Full acceptance passes 862 tests with 36
gated skips. No backend, LLM, or ontology-service call or measurement occurs,
and the development population supports no performance, utility, or
generalization claim. The compact record is
`experiments/artifacts/m15_f2c10a_local_direct_semantic_workload_20260906.json`.

M15-F2C10B is locally accepted as a leakage-safe prediction mechanism. A
versioned predictor policy freezes five typed features, strategy-conditioned
K=3 neighbors, per-plan median aggregation, inverse-distance weighting,
explicit weighted-MAD uncertainty, and fail-closed cold start. A complete
training memory view covers 18 training interpretations and 36 physical plans
with 72 raw counterbalanced successful/exact repetitions while excluding
held-out IDs, answer rows, oracle inputs, and current-query observations. The
compiler produces all 20 held-out estimates—12 for MEDIUM and eight for LOW—
and binds them to the complete ordered training memory, model configuration,
and candidate identities before the unchanged variable frontier selector.
The controlled fixture makes no backend, held-out-query, LLM, or ontology
call and is not measured evidence. The compact record is
`experiments/artifacts/m15_f2c10b_local_family_memory_prediction_20260906.json`.
Full local acceptance passes 870 tests with 36 gated skips.

M15-F2C10C is locally accepted as the persistent selected-only reconstruction
gate. A clean run at commit `4fe396a` sealed all training-memory, prediction,
candidate, snapshot, and frontier files before controlled runtime oracle
access. It executed four returned plans, made eight execute calls, and produced
exact 11-, 9-, 12-, and 7-row answers. The independent auditor regenerated the
entire selection and execution identity chain, passed 134/134 checks, and
verified that the run tree was unchanged. Full local acceptance passes 879
tests with 36 gated skips. Its deterministic doubles and constructed training
values remain `paper_result=false`; no native timing, prediction-accuracy,
resource, semantic-utility, or generalization result exists. The compact record
is `experiments/artifacts/m15_f2c10c_local_controlled_family_memory_validation_20260906.json`.

M15-F2C10D is locally implemented. The author froze four counterbalanced repetitions of all
18 training semantic tasks and both physical strategies (144 plan runs), then
an immutable family-memory freeze, zero-current-query-call prediction, and
independent per-query Pareto/epsilon/K selection. The true frontier—not a
forced session-wide count—returns one to four plans for each of two held-out
base queries, so online execution is bounded at 2--8 plan runs. Only after the
selection seal may the runner execute those online plans and the complete
20-plan by four-repetition shadow matrix (80 plan runs). The resulting total
is 226--232 plan runs and 452--464 measured plan backend calls. Native clients
use a 60-second request timeout; the dedicated Slurm wrapper uses 45 minutes;
the first failure stops the campaign and automatic retries remain zero. The
analysis reports latency/byte prediction error, physical-winner accuracy,
latency/byte regret, and predicted/observed frontier overlap. A service-start
preflight seals the schedule and count bounds, and a separate read-only
auditor reconstructs the schedule, measurements, memory, predictions,
frontiers, exact answers, analysis, and call-phase order. A separate compact
summary accepts only a successful mutation-free audit and retains the claim
boundary alongside the requested metrics. Full local acceptance at the first
submission boundary passed 898 tests with 36 gated skips.

The first native pilot, job `3791589` at exact clean commit `d4db59a`, failed
on `compt303` after 87 seconds. Workload generation and the pre-service
schedule seal completed, but fixture handoff reopened the nested
predicate-extended parameterized bundle with the base parameterized-bundle
loader and was rejected with `bundle schema_version is unsupported`. The
failure occurred before the fixture run directory, pilot run directory, or any
pilot plan call was created; no automatic retry occurred and guarded cleanup
removed the runtime. The repair does not widen a schema allowlist: fixture
handoff now revalidates the enclosing direct-semantic workload and extracts
its verified nested bundle; full repair acceptance passes 899 tests with 36
gated skips. Job `3791589` remains immutable non-paper
diagnostic evidence and must not be rerun. Exactly one explicitly new pilot is
required at a clean repair commit. The compact failure record is
`experiments/artifacts/m15_f2c10d_cwru_native_direct_family_pilot_failure_20260906.json`.
The six-query pilot and all outputs remain `paper_result=false`.

M15-F2C11 is locally implemented as a results-blind physical comparison layer
for the eventual accepted F2C10D run. Before repair job `3791600` produced an
outcome, the repository froze five methods: primary family memory, a
no-instance-feature family strategy-median ablation, fixed parallel hash,
fixed risk-first bind, and an observed shadow oracle used only as an upper
bound. The analysis covers all ten held-out semantic tasks, independently
reduces each of 20 shadow plans over four repetitions, and reports physical
winner accuracy, nonnegative latency and byte regret, and strategy counts.
It requires and immediately reruns the full mutation-free F2C10D read-only
audit, reconstructs the sealed prediction suite from training measurements,
and rejects source drift. Online selected-plan results and answer-row values
are excluded from selection and metrics. It makes no backend, LLM, ontology,
profile, sample, or explain call and cannot write below the source run tree.
Full local regression passes 901 tests with 36 environment-gated skips. The
comparison remains exploratory six-query development evidence with
`paper_result=false` until job `3791600` finishes and passes its independent
audit.

The F2C11 comparison now has a separate results-blind evidence auditor. It
reruns the F2C10D admission audit, reconstructs all five methods over all ten
held-out semantic tasks, and requires exact equality with the persisted
analysis even if a tampered artifact recomputes its self-hash. It also verifies
zero external calls, exclusion of online results and answer-row values, false
confirmatory and paper flags, and an unchanged source-tree digest. Local
focused acceptance passes; a CWRU F2C11 result and its independent audit remain
pending the accepted F2C10D producer chain.

M15-F2C12A/B now freezes, implements, and verifies the cost-inclusive current-query profiling baseline at
the schedule boundary, before accepted F2C10D/F2C11 metrics are available to
the implementation. For each of ten held-out semantic tasks, both complete
federated physical candidates are profiled once at the coordinator boundary,
selection uses only latency, bytes, and plan ID, and exactly one selected plan
then executes. A four-repetition evaluation shadow follows the sealed choice.
The resulting development protocol contains 20 acquisition, ten selected, and
80 shadow plan runs (220 backend calls). It includes acquisition overhead in
method cost, proves five AB/five BA acquisition balance and per-task shadow
position balance, and forbids family memory, answer-row selection, early oracle
access, fallback, retry, LLM, and ontology calls. The compiler makes no
external call. F2C12B adds a fail-closed live producer, allocation-scoped
Neo4j/Fuseki mode, 30-minute Slurm entry, pre-service schedule seal, and
independent read-only reconstruction auditor. Controlled execution makes
exactly 220 calls in acquisition/selected/shadow order; the auditor rebuilds
cost estimates, choices, metrics, and hashes and detects tampering of analysis,
profile costs, selection, or a self-consistently rehashed schedule that differs
from the copied source inputs. Full acceptance passes 919 tests with 36
environment-gated skips. CWRU job `3791649` then completed all 110 plan runs
and 220 backend calls at exact clean commit `64f750b` on `compt268`; its
independent outer-root audit passed 1,185/1,185 checks without mutation. The
profiler selected all ten observed latency winners, with zero latency regret
and 5,625.6 mean byte regret. Median acquisition cost was 61.816 ms and 14,082
bytes; median acquisition-plus-selected cost was 84.279 ms and 23,791 bytes.
These are allocation-local development observations. Cross-allocation timing
comparison with F2C10D remains forbidden and all artifacts stay
`paper_result=false`.

M15-F2C13A freezes the same-allocation comparison needed to interpret the
two mechanisms. It reuses the exact F2C10D 144-run training schedule and the
exact F2C12 20-run acquisition and 80-run shadow schedules. Family-memory
choices are sealed before profiling; then family memory and dual profile each
execute one selected plan for all ten semantic tasks under a five/five
counterbalanced method order. The complete future allocation is fixed at 264
plan runs and 528 backend calls. Training, acquisition, serving, and shadow
costs are separate, fixed and oracle controls are evaluation-only, and the
count-based historical-training break-even is reported as 72 future tasks.
The compiler makes no call and does not authorize a live run. This remains a
descriptive physical-selection protocol, not a semantic-frontier or paper
claim. Full local acceptance passes 931 tests with 36 explicit environment or
external-artifact skips.

M15-F2C13B now provides the executable boundary for that frozen comparison.
The producer seals all 264 scheduled runs before service startup, uses exactly
60-second backend timeouts, and records 528 execute calls across four
contiguous phases with no automatic retry. Family-memory selections are
materialized before any current-query profile; profile selections are sealed
before method-specific serving and shared shadow evaluation. A dedicated
45-minute wrapper and remote-control allowlist entry are present. The
independent read-only auditor recompiles the copied source contracts and
schedule, reconstructs training memory, predictions, both selections, and all
paired metrics, and checks every phase/run invocation identity. Controlled
success, first-profile-failure, first-selected-failure, and evidence-tampering
tests pass. CWRU job `3792343` then completed the exact 264-plan/528-call
schedule at clean commit `cf3d430` on `compt292` in 134 seconds. The outer run
and cleanup succeeded, and the read-only reconstruction audit passed
2,735/2,735 checks without mutating the run tree.

M15-F2C13C precommitted the result-reduction boundary before those measurements
were read. Its no-overwrite summary CLI accepts only a
successful independent read-only audit, verifies the exact commit, schemas,
264-plan/528-call ledger, ten-task seal coverage, artifact hashes, and
evaluation-only shadow boundary, and emits one content-hashed comparison. The
output keeps historical training, current-query profile acquisition, selected
serving, and shadow evaluation costs distinct. In the accepted ten-task
summary, family memory used zero current-query profile calls and selected 7/10
shadow-median latency winners, compared with 5/10 after 20 profile acquisitions.
Their mean latency regret was nearly tied at 2.733 versus 2.808 ms; profiling
reduced mean byte regret from 4,658 to 3,346.4 but cost a mean 35.154 ms and
14,056 bytes to acquire both candidates. Fixed parallel remained the strongest
evaluation-only latency control at 9/10 and 0.289 ms mean regret. Historical
training is reported separately at 144 runs, with only a count-based 72-future-
task break-even reference. This mixed result is preserved without retuning and
remains single-allocation descriptive evidence with no generalization,
semantic-frontier, LLM, ontology, or paper claim. Its compact record is
`experiments/artifacts/m15_f2c13c_cwru_paired_physical_summary_20260906.json`.

M15-F2C14A now replaces the stale one-label family-readiness view with a
reconstructable executable package registry. The current financial-risk
package binds its seven-node typed semantic DAG, hard/relaxable schemas, three
literal-free registered backend templates, six base query instances and their
source/final oracles, 28 direct semantic tasks, 56 physical candidates,
selection-safe training/held-out views, and family-memory predictor policy.
Compilation verifies every source SHA-256, regenerates both workload layers in
temporary storage, and rejects generated hash, count, family, or operator
drift. It makes zero backend, LLM, or ontology-service calls.

The registry also states the agent boundary directly: XGAP coordinates
black-box Neo4j and Fuseki; semantic, memory, coordinator, and registered
backend execution are its tools; hard-constraint changes, arbitrary native
queries, backend-internal inspection, pre-execution oracle reads, and automatic
retry are forbidden. The old typed-DAG/template/workload/oracle blockers are
closed for this one family. Paper readiness remains false because only one
family and six base instances exist, no entirely held-out family is executable,
and inferential analysis is not preregistered. Future family/domain selection
remains with the author; F2C14A authorizes no CWRU job and all artifacts remain
`paper_result=false`. Full local acceptance passes 946 tests with 36 explicit
environment or external-artifact skips.

M15-F2C14B has progressed from the population decision to a locally executable
development benchmark, but not yet to a native or paper-result gate.
The design note `docs/m15_f2c14b_multi_family_design_gate.md` defines the
research question, structural family boundary, variables, endpoints,
confounds, and three population alternatives. Its concrete P1 proposal turns
the recommended staged hybrid into an author-selectable 36-instance primary
population: the existing direct join, an exact-two-hop path join, and an
entirely held-out aggregate-ranking family, with explicit backend ownership,
hard and relaxable slots, physical candidates, splits, and a zero-profile
aggregate-first cold-start rule. The author selected Option C: three controlled
financial structures are primary and a smaller external-validation stratum
follows. The original all-local synthetic P1 world is not accepted as paper
evidence. Its three DAG shapes remain candidates, but they must be rebound to a
traceable public artifact. The recommended path is FinBench v0.1.0-derived
heterogeneous physical execution, GrailQA semantic evaluation, an execution-
optional FIBO mapping, and a cutoff-bounded FedShop validation slice. The
official FinBench SF0.01 archive was downloaded outside the repository,
inspected, and verified at SHA-256
`888c8fbe06b68cc48de9f07fde8c0fd3295618fc41af13ae1aa216aaec1e0430`.
The deterministic source-partition gate is now implemented across all 18
snapshot tables. A real local build processed 36,881 rows, rejected no
relationship endpoint, and emitted 160 batched Neo4j statements plus 28,374
Fuseki triples under one content-hashed manifest. Transaction, path,
ownership, withdrawal, loan, guarantee, investment, and numeric-flow facts are
Neo4j-authoritative; types and semantic/control classifications are
Fuseki-authoritative; stable entity IDs are the only intentional identity
replication. The bundle generator is atomic, non-overwriting, archive-verified,
and makes no backend/model/ontology/oracle call. The next boundary is local
F1--F3 query/oracle admission followed by one CWRU SF0.01 load-and-correctness
pilot; this data-readiness result remains `paper_result=false`.
The local F1--F3 admission is now also implemented. It compiles 36 nonempty
SF0.01 development queries (12 direct, 12 temporal-path, and 12 aggregate),
with 16 training, eight held-out-instance, and 12 entirely held-out-family
assignments. Nine literal-free Neo4j/SPARQL templates expose two physical
routes per family, while exact source/final rows live only in a separately
hashed oracle file whose pre-selection access is forbidden. Real compilation
identity is `6cf2aa7a09bebbae7e0ff244e0d2c8f850bd44393461c8b8c22e4ea2f68b5647`.
The shared federated compiler and coordinator are now implemented for all
three families. Both exact routes for all 36 queries were replayed against the
sealed SF0.01 oracle after plan construction, and all 72 comparisons passed.
The new F3 path uses common collection semi-join, grouped aggregation, and
ordered-limit operators rather than a benchmark-specific evaluator. Native
CWRU load-and-correctness job `3793654` completed with exit `0:0` in 245
seconds on `compt292` at exact clean commit `a718e91`; its official archive
download and inspection passed on CWRU before submission. The outer producer
status is success. The first independent-audit invocation reconstructed the run
but exposed an auditor-only `PosixPath` JSON serialization defect before an
audit file could be written. The repaired auditor explicitly serializes only
path-valued check fields; it then re-audited the unchanged run and passed all
363 checks without run-tree mutation. All 72 plans were exact, each physical
pair was answer-equivalent, and the run made 144 backend calls with zero retry.
This accepts live public-data compiler/coordinator correctness, not performance
comparison or confirmatory sampling. The immutable compact record is
`experiments/artifacts/m15_finbench_sf001_cwru_correctness_20260907.json`.
The first CWRU archive-preparation attempt failed safely with HTTP 403 before
Slurm submission or any backend/query action. The default Python request is
now replaced by a fixed XGAP user agent with identity encoding while all
official-host, redirect, size, SHA-256, single-attempt, and no-overwrite gates
remain intact. A real local official-URL fetch verified the pinned archive and
all 18 tables. An independent no-mutation correctness auditor is also locally
implemented and rejects altered execution answers. Server preparation was
retried from the repaired commit and passed; job `3793654` must not be
duplicated.
In parallel, SF0.1 is pinned as the next scale gate. Its official archive
contains 365,181 snapshot rows; a real local partition with batch size 2,000
produced 194 Cypher statements, 282,426 Turtle triples, and approximately
123 MB of load payload. The same three-family compiler produced 36 distinct
scale-bound queries. Job `3793654` and its independent audit now satisfy the
precondition for the dedicated 16-GiB, 90-minute SF0.1 wrapper. SF0.3/SF1,
repetitions, and statistical analysis remain protocol decisions rather than
implicit defaults.
The first FinBench-specific family-memory protocol is now implemented locally.
It admits exactly 32 physical-plan observations from the 16 declared training
queries, requires at least four successful exact counterbalanced repetitions
per plan, and freezes raw repetitions plus medians under content identity. It
uses only the public ingestion-time feature declared by each query family and
predicts one route plus a physical Pareto set for the eight held-out-instance
queries with zero current-query profiles and no oracle or post-execution input.
The 12 entirely held-out F3 queries are reported as a separate cold-start
stratum: only their predeclared fallback may run, and no predicted frontier or
metric is fabricated. Revalidation rejects recomputed-hash semantic tampering,
held-out leakage, incomplete strategy history, and false exact matches caused
by a zero-width feature range. This is protocol/model readiness only; no native
training observations or comparative result exist and `paper_result=false`.
The next same-allocation development comparison is now frozen locally. Its
result-blind schedule contains 128 training, 40 current-query profile
acquisition, 40 paired selected-serving, and 160 evaluation-shadow plan runs,
for 368 complete plans and 736 backend calls. The eight known-family held-out
queries use the zero-profile family-memory method; the 12 F3 queries retain a
separately labeled predeclared cold-start fallback. Both are paired against
the cost-inclusive dual-profile method under balanced order and distinct
selection seals. The compiler opens no backend or oracle and makes no LLM or
ontology call. The native producer and independent read-only auditor are now
implemented against this exact schedule. The producer admits training
exactness only from a successful external correctness audit, seals all 72
physical candidates before fixture loading, seals family-memory selection
before current-query profiling, seals the profile comparator before paired
serving, and opens the answer oracle only after all 368 runs and 736 backend
calls. Its analysis reports known-family prediction error, physical-winner
accuracy, latency/byte regret, frontier overlap, and selection-plus-serving
cost while keeping F3 cold-start separate. Full repository acceptance passes
1,125 tests with 36 intentional live/external skips. This is executable
development readiness, not authorization to run before the SF0.1 correctness
audit succeeds; `paper_result=false` remains fixed.
The first SF0.1 scale attempt is preserved as a failed load diagnostic. Job
`3793681` reached healthy Neo4j and Fuseki services and sealed all 72 plans,
then Neo4j returned HTTP 500 at fixture statement 46/194 after approximately
537 seconds of fixture work. No query plan executed and no oracle content was
opened. Batch-step peak RSS was about 2.06 GB of the requested 16 GB. The
client now retains bounded structured Neo4j HTTP error details and the loader
adds content-free statement identity metadata. The preserved Neo4j console log
shows a normal start and request-initiated shutdown, not a crash; statement 46
is deterministically the first 2,000-row transfer-relationship batch. Partition
schema v2 now replaces inline row literals with hash-bound `$rows` batches,
verifies affected-row counts, remains first-error/zero-retry, and keeps v1
audits readable. The SF0.1 wrapper explicitly records a 1/2/1-GiB
initial-heap/max-heap/page-cache profile inside its unchanged 16-GiB request.
Local regression and full acceptance must pass before one repaired CWRU gate;
no old run is retried or counted as a result.
The repair implementation passed the complete local acceptance suite at its
published commit: 1,123 tests passed and 36 explicitly live/external tests were
skipped. Shell syntax validation and `git diff --check` also passed. The single
repaired CWRU SF0.1 correctness run has been submitted as job `3793698` at
exact commit `bc57a9d`; its terminal status and independent read-only audit are
still pending. Do not submit a duplicate or start the 736-call campaign from
an unaudited scale run.
The current `financial_risk_dev` bundle is explicitly a toy regression fixture.
XGAP has already crossed the real-backend boundary through audited native
Neo4j/Fuseki runs; the pending boundary is public benchmark data and a frozen
paper protocol. The accelerated target is local ingestion and family
correctness by Sep 9, a first CWRU paper-candidate pilot by Sep 10, and protocol
freeze immediately afterward. Decisions 2--6, paper-scale execution, and
inferential claims remain unresolved; `paper_result=false` remains mandatory.

M15-F2C10D repair job `3791600` is now accepted as a real-backend development
pilot. It ran exact clean commit `08f1911` on `compt303` for 220 seconds,
executed 231 plans and 462 backend calls, returned seven semantic frontier
plans across the two held-out base queries, made no current-query profile call
or retry, and passed a 1,289-check independent audit with no run-tree mutation.
Its physical-winner accuracy is 0.60 and mean predicted/observed semantic
frontier Jaccard is 0.55. The result remains a six-query, non-confirmatory
development observation.

The pre-frozen F2C11 analysis is also accepted after its independent auditor
reconstructed the exact artifact and passed 17/17 checks. Family memory chose
6/10 observed latency winners with 2.282 ms mean latency regret and 4,658 mean
byte regret. Fixed parallel and the no-instance family-median ablation each
chose 8/10 winners with 1.276 ms mean latency regret and 5,625.6 mean byte
regret. Fixed risk-first has zero byte regret but 6.024 ms mean latency regret.
This is preserved as an exploratory negative result for the present predictor;
it does not support retuning on the ten held-out tasks or a general claim about
memory. Compact immutable records now exist for both F2C10D and F2C11.

M15-F2B4 is now verified on CWRU. Job `3787430` ran exact clean commit
`d795fac` on `compt348` for 73 seconds. The query-bound selective session used
the frozen registry and schedule hashes, started Neo4j 5.26.30 and Fuseki 5.6.0
on loopback only, made no automatic retry or service restart, and removed the
runtime after clean shutdown. Its independent read-only audit recompiled the
identity chain and passed 377/377 checks with no failures or run-tree mutation.
This is a one-query engineering result and supports no latency ranking or
cross-task-memory claim. The compact record is
`experiments/artifacts/m15_f2b4_cwru_native_query_bound_session_20260905.json`.

F2A now executes one hash-bound development session. The preflight recompiles
the campaign and rejects campaign-hash, schedule-hash, workload-source,
normalized bundle-spec, session, query, measured-task, logical-memory, or
method-order drift before a backend call. Only a complete campaign binding
unlocks a custom Williams order in the live six-method runner. The
native-service mode and allowlisted Slurm wrapper
give the session a fresh Neo4j/Fuseki lifecycle; the read-only auditor checks
the outer job, bundle, plan, selected session, binding, nested matrix, exact
answers, memory records, 18-call trace, shutdown, and cleanup. It accepts
exactly one development query and therefore remains `paper_result=false`,
cannot measure cross-task memory, and cannot complete the counterbalanced
campaign. CWRU job `3787291`
verified this path at exact clean commit `c9a7afe` on `compt336`: all six
methods returned exact answers in the compiled order, the trace contained 18
tool invocations and zero retries, and cleanup succeeded. Its independent
read-only audit passed 374/374 checks without changing the run tree.

M15-F2B1 now has a standalone resolved-query contract compiler. The development
query specification makes entity, time, amount, and risk constraints
non-relaxable and names the semantic operators, output schema, exact Neo4j and
Fuseki artifact roles, bound-query parameter schema, and answer oracles. The
compiler loads a fully verified workload bundle, binds every referenced query
and oracle by SHA-256, and emits a portable contract hash that is stable across
filesystem locations. It rejects schema, role, parameter, symlink, or
constraint-relaxability drift before any external call. The historical F2A
audit remains reproducible because this primitive is wired through a new F2B2
campaign layer rather than by modifying the v1 campaign/session path.

M15-F2B2 adds a separate query-bound campaign registry without rewriting the
audited F2A configuration. It verifies the exact base campaign-spec and
schedule hashes, requires complete workload/query coverage, validates each
resolved-query source hash, freezes the expected selective and broad-hot
bundle-dependent contract hashes, and adds those references to every method
stream. The resulting query-bound schedule hash excludes local path provenance
and is stable when identical query specs move. This is still a side-effect-free
plan: live bundle verification and runner/auditor consumption remain F2B3, so
no additional CWRU session is authorized.

M15-F2B3 adds direct live-bundle consumption. Its preflight verifies the
registry and query-bound schedule hashes, selects the exact session, loads the
deterministic bundle, recompiles the resolved-query contract, and checks the
observed query-spec and contract hashes before output creation or backend
healthcheck. The existing six-method matrix accepts those identities only in a
new v2 binding and preserves the compiled order, exact-answer requirement,
18-call budget, and zero-retry rule. A deliberately self-consistent registry
with the wrong expected contract is rejected. This path remains local and
`paper_result=false`; native lifecycle, Slurm packaging, and read-only audit
are still required before an F2B CWRU gate.

M15-F2B4 adds a separately versioned `scaled_query_bound_session` native mode,
dedicated Slurm wrapper, and remote allowlist entry. The native runner accepts
query-bound inputs only as a complete set and executes the F2B3 contract
preflight before Java inspection or service startup. Its read-only auditor
recompiles the fixed registry and selected contract from the run's verified
bundle, then checks the service wrapper, query-bound plan/session, v2 matrix
binding, persisted contract, exact six-method results, 18-call trace, shutdown,
and outer cleanup. Normal and adversarial local tests pass; one selective CWRU
engineering gate is ready, while the other eleven sessions and all paper
claims remain disabled.

M15-B now has a **real Neo4j+Fuseki vertical slice verified on CWRU; streaming,
batching, and live cancellation remain pending**. The local
runtime compiles independent fragments through the existing M9 compilers,
runs independent remote nodes in parallel, performs explicit ID alignment and
exchange, joins or merges rows at the coordinator, propagates failures, skips
invalid descendants, and returns end-to-end latency, row, remote-call, and
transfer-byte metrics through the goal loop. Its deterministic vertically
partitioned fixture gives Neo4j only identity/transfer facts and Fuseki only
company risk/name facts, so neither source can contain the final answer. A
fail-closed live runner uses the real Neo4j and Fuseki plugin path and persists
the semantic program, execution DAG, source hashes, health, result, validation,
status, and manifest without automatic retry. The separately gated,
deployment-neutral loader applies namespaced Neo4j statements and Fuseki Graph
Store appends, checks both against exact per-source oracles, preserves partial
failures, and records no credential material. B2B now adds a frozen native
runtime lock plus a fail-closed archive preparer: only exact official Neo4j and
Fuseki archives can enter the shared cache; existing conflicts are not
overwritten; invalid downloads are removed when the preparer exits; and no
attempt is automatically retried. B2C adds safe allocation-local staging:
each cached archive is re-verified, every tar member is bounded and checked,
only regular files and directories below the frozen product root are accepted,
and extraction is privately staged before atomic publication into a new empty
runtime directory. Links, traversal, duplicate members, special files, partial
products, and manifests inside the ephemeral root are rejected.

The official-source local supply diagnostic preserved an initial Fuseki short
read of 50,007,922 bytes against the locked 50,290,245 bytes and did not publish
it. A separately numbered diagnostic made one additional Fuseki request while
reusing the verified Neo4j cache with no request; it received HTTP 200 with the
exact Content-Length and passed the frozen SHA-512. Both exact real archives
then passed B2C inspection and staging. This is development evidence, not a
CWRU live-service or paper-result claim; its compact record is
`experiments/artifacts/m15_b2_local_native_supply_20260905.json`.

B2D implements the complete allocation-scoped launcher and was not exercised
against local services. It requires exact Java 17 and an allowlisted node-local
filesystem, reserves three dynamic loopback ports, keeps every Neo4j/Fuseki
state path below the ephemeral root, and uses only their public HTTP
interfaces. Readiness polling has a fixed deadline and never restarts a failed
process. The runner performs one fixture load and one federated execution,
then shuts down job-owned process groups in reverse order, archives logs and
lifecycle evidence, and lets the Slurm wrapper remove only its validated
runtime directory. Both real archives passed the exact command-plan audit, and
job `3787110` subsequently exercised the complete service lifecycle on CWRU.

A read-only post-run auditor now rejects an otherwise successful allocation if
its full commit, frozen lock snapshot, archive provenance, staging record,
Java/runtime evidence, service plan and configuration, health, fixture load,
federated answer, shutdown, or guarded cleanup disagree. It writes reports
only outside the immutable run tree and does not retry or repair failed runs.

CWRU B2B artifact job `3787101` completed at commit `2ce4b53` on `compt398`.
Its immutable manifest reports exactly two downloads and zero automatic
retries. Neo4j Community 5.26.30 matched 162,360,826 bytes and its frozen
SHA-256; Fuseki 5.6.0 matched 50,290,245 bytes and its frozen SHA-512. The job
did not extract either archive, start a service, or persist credentials. The
shared supply cache was therefore accepted for the live service run.

M15-C1 now has a locally executable initial plan space. A versioned observation
catalog restricts schema, explain, profile, and sample actions to registered
read-only artifacts; Neo4j exposes native `EXPLAIN`/`PROFILE`, while unsupported
engine observations remain explicit. The runtime adds bounded bind queries and
coordinator semi joins. Two exact-semantic M15 DAGs—parallel hash and risk-first
bind—produce the same answer. A frozen-snapshot critical-path and exchange-cost
selector chooses bind under transfer pressure and parallel when bound-query
latency is controlled to be high. The demonstration moves 530 versus 363
fixture bytes and is labeled `controlled_model_sanity_check` with
`paper_result=false`; it is not live calibration or a paper result.

M15-D1 is locally implemented as a controlled adaptive loop. Memory records can
now survive process boundaries in an append-only JSONL history, while current
values retain version, provenance, confidence, and expiry semantics. A
versioned plan snapshot is never silently overwritten. The scheduler can
continue from a validated ancestor-closed successful prefix, and the adaptive
executor admits a probe only when it is an exact common prefix of every
candidate. In the controlled M15 case, stale execution memory initially picks
parallel hash; the runtime prefix observation exposes a 2000x latency deviation,
selection changes to risk-first bind, and the already executed Fuseki prefix is
reused. The exact answer still requires only two total backend calls. A failed
probe causes no fallback execution, and a no-replan control is implemented.
This is local orchestration evidence, not a real-backend adaptive or paper
result.

M15-C2/D2 now adds a separate local live-service adaptive path without changing
the verified M15-B execution mode. Before query execution, a bounded collector
invokes exactly three catalog-registered observations once each: Neo4j PROFILE
for the full-transfer and bound-transfer artifacts, followed by the Fuseki
high-risk artifact through an explicitly labeled wall-clock execution fallback.
It publishes no snapshot after partial observation failure. A successful
snapshot is persisted and reopened before the adaptive executor runs the two
backend query calls, reuses the exact common prefix, and permits at most one
replan. The run records the complete three-profile/two-execute tool sequence,
two append-only memory versions, plan snapshots, fixed cost configuration,
answer validation, and source provenance. Query-probe failure is fail-closed
and does not fall back to another plan or duplicate memory. The native service
lifecycle exposes this as a distinct `adaptive` mode with its own Slurm entry
point, while the read-only evidence auditor validates either the historical
vertical slice or the adaptive artifact set. The cost model is explicitly
uncalibrated and every adaptive manifest sets `paper_result=false`;
calibration, scaling, and the complete baseline matrix remain pending.

The first CWRU D2 submission, job `3787144` at exact clean commit `ee52c86`,
failed after two seconds before creating a run tree, staging an archive,
starting a service, or invoking a query. The copied Slurm wrapper incorrectly
resolved its sibling service script relative to the spool copy. The local
repair uses `XGAP_REPO_ROOT` or `SLURM_SUBMIT_DIR`, validates the checkout and
target script, and is covered by a wrapper regression assertion. The failed
attempt is frozen in
`experiments/artifacts/m15_d2_cwru_adaptive_wrapper_failure_20260905.json` and
is not a live adaptive result.

The repaired wrapper was exercised by explicitly new CWRU D2 job `3787152` at
exact clean commit `247e714` on `compt336`. It completed in 96 seconds with
exit `0:0`, ran Neo4j 5.26.30 and Fuseki 5.6.0 on allocation-local XFS with
Java 17, and shut down and removed the runtime cleanly. The independent
read-only audit passed 173/173 checks with no run-tree mutation. The exact
three-profile/two-execute trace and both append-only memory versions passed;
the selector retained `m15-parallel-hash` before and after the common probe,
so `replan_count=0` is a valid no-replan outcome. The exact answer required
two query calls and 530 transferred bytes. The compact record is
`experiments/artifacts/m15_d2_cwru_native_adaptive_20260905.json`; it remains
`paper_result=false` because the fixture is tiny and the cost model is not
calibrated.

M15-B2D/B3 job `3787110` ran exact clean commit `cd564de8` on `compt331` in
62 seconds. Neo4j 5.26.30 and Fuseki 5.6.0 ran on allocation-local XFS and
loopback-only ports with Java 17. The fixture load passed, the coordinator
returned the exact expected row with two remote calls, both services shut down
without kill escalation, and the validated runtime directory was removed. The
separate read-only audit returned exit 0 with 102/102 checks passing, no failed
check IDs, and `run_tree_mutated=false`. The compact evidence record is
`experiments/artifacts/m15_b2d_cwru_native_service_20260905.json`. This is a
system acceptance result, not a latency/throughput paper result. Streaming or
batched result handling and live cancellation remain M15-B follow-up work.

M15-B0/B1 provide a read-only CWRU environment probe and a 15-minute CPU
Slurm smoke job. B0 verified an exact checkout, Slurm, `gpu2h100`, an
existing vLLM environment, and Python 3.11.5 after loading the CWRU
`Miniconda3` module. The separate user-owned `xgap-core` environment now has
the editable package and pytest, and its generated untracked metadata was
removed so the server checkout is clean. Podman was visible on `hpc5`, while
no supported container runtime was visible on `hpc7`; this is node-dependent
evidence, not a selected B2 architecture. The batch wrapper now loads
Miniconda explicitly and records the runtime inside its allocated compute
node. B1 job `3784974` completed at exact commit `4c45931` on `compt365` in
13 seconds with exit `0:0`; 40 tests passed, one live gate skipped, and the
coordinator returned the one expected row using two calls and 206 transferred
bytes. The allocated node reported `backend_runtime=none`, so Podman is not a
valid Slurm service strategy. B2 prerequisite job `3784980` completed at exact
commit `1d7af1d` on `compt386` in 36 seconds. It verified loopback and all
archive/hash/process tools, but its raw artifacts prove the inherited Java was
OpenJDK 8 and `/home` was NFS-backed. The Java module inventory advertises
`Java/17.0.6` and no Java 21. The v1 probe's command-presence-only
`native_service_prerequisites_ready=true` is therefore invalid and is not used
as a gate; probe v2 parses the Java major, attempts the pinned module, and
requires version compatibility. The archive gate is now verified by job
`3787101`. The B2C/B2D implementation staged and ran those cached archives
successfully in job `3787110`. Extracted service state and database files
remained allocation-local and were removed after the audited run. See
`docs/m15_remote_execution_loop.md`.

The `remote.executor` tool and environment-configured CLI are implemented and
locally tested. Exact-commit staging, allowlisted submission, normalized
status, bounded log reads, scoped artifact retrieval, and default-disabled
cancellation are covered by fake-transport tests. No CWRU credential is
stored and no remote mutation has been invoked by this implementation.

See `docs/agentic_architecture.md`, `docs/m15_agentic_federated_core.md`, and
`docs/ui_remote_execution.md`.

## Legacy M13 Experiment Track

M13-E3 remains **IMPLEMENTATION READY**. M13-E3B.4 is complete after the real
CWRU audit-only rerun. With entity and schema ranking unchanged, exact
role-aware relation endpoint evidence raised effective Type prompt coverage
from 4/18 to 12/18 and joint prompt reachability from 1/18 to 5/18 (27.78%).
The unchanged 0.20 engineering gate passed with
`live_preflight_allowed=true`; explicit Type Top-4 coverage remained 4/18.

M13-E3B.5 is **LOCALLY IMPLEMENTED; CWRU 18-QUERY LIVE PREFLIGHT RERUN
PENDING**. It
wires the passing query-local `preflight18` catalog and `audit_summary.json`
into the existing Qwen3-32B preflight through an explicit artifact profile.
Readiness now validates the exact frozen IDs, catalog and audit hashes, row
hash, prompt bound 4, and relation-endpoint contract before a provider call.
Structured requests carry that endpoint contract, and metrics report both all
18 questions and the 5-question jointly reachable subset. Top-50, Top-4, gate
0.20, ranking, ontology, model parameters, and pilot150 remain unchanged.

The first CWRU E3B.5 submission, Slurm job `3741724`, verified the catalog,
audit, row hash, endpoint contract, model bundle, and credential and passed the
unchanged gate at 5/18. Qwen was not loaded because readiness additionally
required the physical `reachability.jsonl` row order to equal the spec order.
M13-E3B.5.1 removes only that invalid ordering requirement: query-local
artifacts must contain the exact unique frozen 18-ID set, while row order is
irrelevant. Missing, extra, duplicate, hash-mismatched, or contract-mismatched
records still fail closed. The second CWRU submission, Slurm job `3763061`,
then passed readiness, verified the frozen runtime, started Qwen3-32B on an
H100 NVL, and passed the strict JSON-schema serving smoke. Evaluation stopped
before metrics because the shared first-failure classifier did not yet accept
the documented query-local stage `reference_not_in_local_catalog`.
M13-E3B.5.2 adds only that missing taxonomy member, retaining fail-closed
behavior for every unknown stage. The third submission, Slurm job `3763119`,
completed and wrote all 17 expected run artifacts, but all 18 provider calls
were rejected before generation with HTTP 400. The frozen bundle requested
4096 output tokens for prompts of 4146-4590 tokens while vLLM served only an
8192-token context window. Consequently provider and structured-valid rates
were both zero, no candidate reached parsing or lowering, and the reported
zero Candidate Recall is not a model-quality result.

M13-E3B.5.3 repairs only that deployment-budget contradiction. The unchanged
bundle budgets of 8192 input plus 4096 output now run against a 12288-token
vLLM context window. A fail-fast check verifies the bundle, spec, deployment
hashes, and exact token arithmetic before loading Qwen3-32B. Prompt contents,
Top-50, Top-4, candidate cap 3, model generation parameters, retrieval,
grounding, `c_sem`, and downstream planning remain unchanged.

The fourth submission, Slurm job `3763174`, validated that repair: vLLM served
12288 tokens, 17/18 provider calls succeeded, all five jointly reachable calls
succeeded, and malformed output fell to zero. However, every successful call
returned the shortest schema-valid value `candidates=[]`. The frozen vLLM JSON
Schema had no `minItems` on the candidate array, so strict guided decoding was
allowed to terminate without attempting an interpretation. No candidate
reached type checking, lowering, or `c_sem`; zero Candidate Recall is still not
a model-quality result.

M13-E3B.5.4 repairs that candidate-generator contract without adding examples
or gold information. The CWRU schema and prompt now require between one and
the frozen cap of three candidates. Generated candidates remain subject to all
existing parser, type, grounding, semantic-admissibility, and equivalence
checks, so this does not make any candidate valid by construction.

The fifth submission, Slurm job `3763298`, loaded the corrected bundle and
again reached 17/18 provider success with zero malformed responses, but vLLM
0.11.1 still emitted `candidates=[]` for every successful call. This proves its
guided decoder did not enforce the declared array `minItems/maxItems`; XGAP's
provider boundary had also trusted those constraints without checking them.

M13-E3B.5.5 adds deterministic candidate-array cardinality validation at that
provider boundary. It reads `minItems/maxItems` from the active bundle schema,
rejects violations, and invokes the already frozen single repair call. Bundles
without those declared constraints retain their prior behavior. Parser,
retrieval, grounding, semantics, lowering, model parameters, and experiment
bounds remain unchanged. One final CWRU 18-query resubmission is pending.

## Completed

- M15-A Agentic Contracts, Tools, Memory, and Bounded Goal Loop
- M0 Project Skeleton
- M1 Data Model
- M2 Core Algebra
- M2.5 Logical Plan Infrastructure
- M3 Recursive Algebra
- M4 SolutionSpace Algebra
- M4.5 Semantic Audit
- M5 GPC-Lite Pattern AST And Lowering
- M5.5 Pattern-Lowering Audit
- M6 Bounded Focused Quantified Pattern Semantics
- M7 Backend Infrastructure
- M8 Backend Capability Profile + Compiler Boundary Preflight
- M9 Minimal Compilers For Backend MVP
- M10 LLM Planner Boundary + Structured Candidate Interface
- M11 Ontology-Bounded Physical Planning
- M12-A Experiment Artifact Contract + Dataset Bundle
- M12-B Live LLM + Ontology/Alignment Artifacts
- M12-C Cost Calibration + Online GP Protocol
- M12-D Baselines/Ablations + Server Experiment Runner
- M13-A GrailQA Paper Artifact Feasibility Audit
- M13-B KQA Pro Paper Artifact Feasibility Audit
- M13-C GrailQA Paper Vertical Slice + Minimal Fragment Expressiveness Upgrade
- M13-D Local Preparation for Server-Executed GrailQA Semantic Pilot
- M13-D Frozen 150-Query Server Pilot Execution
- M13-E1 Local Offline Reachability And Interpretation-Contract Repair
- M13-E2 CWRU H100 + vLLM Experiment Backend (local implementation)
- M13-E3B.2 Query-Local Entity Retrieval Contract Repair
- M13-E3B.3 Ontology-Aware Schema Ranking Repair
- M13-E3B.4 Relation-Endpoint Grounding Contract

## In Progress

- M15-B Executable Two-Engine Vertical Slice
- M13-E3 real CWRU construction of query-independent Freebase catalog v2
- M13-E3 all-35,439 coverage and frozen-150 offline reachability audit
- M13-E3A download and empirical validation of the frozen archival source
- M13-E3B.5 query-local artifact wiring and CWRU 18-query live preflight
- M13-E3B real CWRU query-local pilot150 build, after reviewing preflight18

## Next Planned Legacy Milestone

Leave the running global M13-E3/E3A job untouched. Pull the M13-E3B.5
deterministic candidate-cardinality repair on CWRU,
run `scripts/server/check_cwru_grailqa_preflight_ready.sh`, and submit exactly
the frozen 18-query Qwen3-32B Slurm preflight. Review overall Candidate Recall
and the separately reported jointly reachable 5-question subset before any
larger experiment. Freebase rescanning, prompt-bound changes, embeddings,
pilot150, RQ2/RQ3, full M13 disambiguation, and M14 remain outside this step.

## M13-E3 Freebase Catalog-v2 And Reachability Audit

M13-E3 reuses the M13-E1 extraction semantics, SQLite/FTS5 catalog,
deterministic entity/relation/type retriever, three bounded relation-hop pools,
prompt construction, and fail-closed 0.20 gate. M13-E3A adds explicit
`google_rdf_gzip` and `hf_archival_parquet` source modes with no fallback. The
current CWRU artifact freezes `CleverThis/freebase` revision
`dbb1931c2698295653effe9b980a02ab29f004e0`: 964 Parquet shards, 32,476,432,840
bytes, 3,130,753,066 rows, and six nullable string columns. The adapter streams
shard by shard, row group by row group, into the unchanged triple extraction
logic; it never reconstructs the full N-Triples dump.

The archival inventory records immutable URLs, LFS SHA-256 values, Git blob
IDs, sizes, the verified conversion revision, and schema fingerprint. Local
verification rejects missing, extra, truncated, or altered shards. A real
first-row-group smoke of frozen shard `0000` found MIDs, English canonical
names, aliases, type memberships, and English literals. N-Triples/Parquet
fixtures produce identical catalog rows and retrieval candidates.

M13-E3A.1 makes archival downloads compatible with CWRU's older system curl.
The shared shell helper always uses `--retry` and `--retry-delay`, discovers
`--retry-all-errors` through `curl --help all`, and passes it only when the
installed binary advertises support. No curl upgrade, sudo, alternate
downloader, or weaker integrity policy is required.

The offline audit now reports entity/relation/type/joint catalog coverage over
all 35,439 supported GrailQA train/dev questions and the frozen 150 separately.
For the pilot it reports Recall@1/5/10/20, per-slot relation recall, at-least-one
versus all-required relation recall, prompt truncation loss, deployed joint
prompt reachability, Q/path-length strata, and first-stage loss counts. Six
compact JSON reports reference the hashed external query-level artifacts.

The local fixture workflow is complete, but real catalog counts and metrics are
deliberately unset. M13-E3 calls no LLM, does not tune the M13-E1 retriever, and
does not alter `c_sem`, Nash ranking, PathPatternQuery/algebra semantics, M11,
GP, compilers, backend execution, or the M13-E2 provider boundary. See
`docs/report/freebase_catalog_v2_cwru_runbook.md` and
`docs/report/grailqa_freebase_catalog_v2_reachability.md`.

Direct CWRU requests to the documented Google Freebase objects returned HTTP
403 on 2026-08-19. The archival transport is Freebase data, not a new ontology
or replacement knowledge graph. After the unchanged audit, the separate
evaluation-only compatibility artifact reports missing pilot/supported MIDs,
missing ontology relations/types, and JointCatalogCoverage.

## M13-E3B Query-Conditioned Local Freebase Catalog

M13-E3B adds a separate, gold-blind grounding experiment over the same frozen
E3A Parquet source. For each question, contiguous normalized text spans are
matched exactly against English Freebase canonical names and aliases, then a
frozen maximum of 50 ranked MIDs is enriched with public type memberships. A
batched scan maintains independent candidate maps, and the persisted
`question_id` plus question-text hash controls the Catalog-v2 entity allowlist.
Candidates selected for one question are therefore unavailable to another.

The source is scanned at most twice: name/alias matching, followed by
name/alias/type enrichment restricted to retained MIDs. Relation/type terms,
domain/range, reverse relations, and hierarchy continue to come from the
frozen GrailQA ontology. No factual edge, k-hop snapshot, embedding index, NER,
LLM call, semantic change, or retrieval tuning is included.

Construction accepts only the inference question artifact and rejects records
containing gold/reference/logical-form/answer fields. SQLite/FTS construction
runs under node-local staging and the complete validated subset is copied to
an output-adjacent path before atomic publication. Evaluation is a separate
phase that first persists retrieval, then opens references and reports local
catalog loss separately as `reference_not_in_local_catalog`.

The implementation, fixture tests, CPU Slurm job, 18/150 frozen configuration,
comparison utility, and report are ready. The real CWRU `preflight18` build
retains 865 unique entities and 900 assignments in an approximately 14.4 MB
SQLite artifact after about 45 minutes. Its first audit reports entity catalog
coverage 10/18, entity Recall@20 0/18, relation Recall@20 8/18, type Recall@20
6/18, and joint prompt reachability 0/18. These are diagnostic engineering
results, not paper metrics. The global E3/E3A job and its staging/output remain
independent and unchanged. See
`docs/report/grailqa_local_freebase_catalog.md`.

M13-E3B.1 fixes the first real CWRU preflight failure without changing the
catalog policy. Parameter 8 of the `query_entity_candidates` INSERT is
`source_shard`; the Parquet adapter supplies its safe relative path as a
`PosixPath`, which SQLite cannot bind. The materialization boundary now maps
only `pathlib.PurePath` values to path strings, preserves supported SQLite
primitives unchanged, and rejects unknown parameter types. The same provenance
is string-normalized for JSONL output. The local-catalog sbatch script now runs
`module load Miniconda3` before invoking Python.

M13-E3B.2 fixes the contract defect exposed by that completed build. Catalogs
whose manifest declares `requires_query_entity_filter=true` now return only
the current question's persisted candidates ordered by local rank and MID,
with the persisted lexical score. They no longer pass that universe through
the global FTS scorer. Global Catalog-v2 retrieval is unchanged. Offline audit
now writes `entity_retrieval_before_after.json`, `relation_diagnostics.jsonl`,
and `type_diagnostics.jsonl`; relation/type retrieval itself is unchanged.
The real post-fix CWRU audit measured entity Recall@1/5/10/20 of 3/7/8/8 over
18, entity prompt coverage 7/18, and joint prompt reachability 1/18. This closes
E3B.2 while preserving the 0.20 gate, prompt limit 4, top-50 construction,
ontology, and model path.

M13-E3B.3 repairs the generic relation/type ranking boundary. It
aggregates all bounded descriptors by schema term before any Top-k, ranks with
the frozen lexicographic hierarchy exact multi-token phrase, complete
informative tokens, contiguous partial phrase, informative partial overlap,
generic single token, and zero overlap, and uses ontology-descriptor IDF only
as a deterministic secondary tie-break. Relation slots use query-local entity
types and bounded bidirectional domain/range propagation; no direction is
invented when the existing slot has none. Type ranking combines lexical,
entity-attached, relation-induced, and bounded ontology-expansion provenance
before truncation. Audit-only writes the versioned before/after and ranking
diagnostic artifacts without replacing historical E3B.2 diagnostics. The code
completed its real CWRU audit-only rerun. Relation Recall@1/5/10/20 is now
5/11/12/13 of 18, relation prompt coverage is 10/18, Type Recall@1/5/10/20 is
1/4/8/13, and explicit Type prompt coverage is 4/18. The remaining losses are
5 relation retrieval, 3 relation prompt-truncation, 5 type retrieval, and 9
type prompt-truncation cases; joint reachability remains 1/18.

M13-E3B.4 keeps those ranking outputs fixed and makes relation endpoint
metadata operational at the grounding boundary. For a selected fixed linear
path, the first relation's source endpoint and last relation's target endpoint
are derived exactly from domain/range and edge direction. A derived type is
accepted only for its matching source/target role; no hierarchy expansion,
lexical fallback, prompt-term insertion, or benchmark-specific alias is used.
Runtime grounding and offline reachability call the same versioned helper.
`type` continues to report explicit Type candidates, while `effective_type`
and `joint` include valid endpoint evidence. The audit adds
`endpoint_grounding_before_after.json` and
`relation_endpoint_diagnostics.jsonl` without rewriting E3B.2/E3B.3 history.
The real CWRU audit-only rerun retained explicit Type prompt coverage at 4/18,
raised effective Type coverage from 4/18 to 12/18, and raised joint prompt
reachability from 1/18 to 5/18. The unchanged 0.20 gate therefore passed at
0.2778. This is an inference-context ceiling, not Qwen accuracy.

M13-E3B.5 connects that exact passing artifact to the existing CWRU live
preflight. `query_local_e3b4` is an explicit runtime profile; it reads
`audit_summary.json` directly and rejects profile, question-ID-set,
catalog-hash, audit-hash, reachability-row-hash, prompt-bound, or endpoint
contract drift. The Qwen request receives the versioned role/direction rule
already used by runtime validation and the audit. Overall 18-query metrics are
preserved, while a separate jointly reachable subset reports provider success,
structured validity, and Candidate Recall among the five questions for which
all required grounding context is prompt-visible.

## M13-E2 CWRU H100 + vLLM Experiment Backend

M13-E2 adds a frozen CWRU Pioneer environment contract, a Qwen3-32B vLLM
ModelBundle, a model-specific copy of the unchanged 18-question M13-E1
preflight contract, generic OpenAI-compatible model/endpoint environment
selection, and configuration-owned non-thinking requests. Existing model
bundles retain their hashes.

The Slurm infrastructure requests one scheduler-selected `gpu2h100` GPU, eight
CPUs, and 64G memory. It resolves an existing shared-cache model revision,
binds vLLM only to `127.0.0.1`, polls `/v1/models`, runs a tiny strict JSON
Schema smoke, captures credential-free environment metadata, executes an
explicit command/spec, inventories artifacts, and terminates vLLM through a
trap. The GrailQA wrapper checks the M13-E1 offline gate before model startup.

Normal tests do not require Slurm, H100, vLLM, or model weights. M13-E2 does
not change `c_sem`, pattern semantics, algebra, M11, GP, GrailQA references,
the M13-D result, model weights, or any 150-query run. See
`docs/report/cwru_vllm_experiment_backend.md` and
`docs/report/cwru_vllm_runbook.md`.

## M13-E1 Reachability And Contract Repair

M13-E1 preserves M13-D as an immutable diagnostic baseline. Its reusable
offline audit reproduced catalog entity availability 12/150, retrieval Top-20
entity/relation/type coverage 10/47/67, deployed prompt Top-4 coverage 9/22/38,
and joint prompt reachability 0/150. This explains why the frozen Candidate
Recall 0 cannot be attributed to Qwen capability.

The implementation adds a streaming, query-independent catalog-v2 builder for
the final official Freebase RDF dump, deterministic alias/FTS5 entity
retrieval, public-metadata relation retrieval, three bounded relation-hop
pools, domain/range type expansion, catalog/retrieval/prompt decomposition,
and a fail-closed live gate. No question, answer, logical form, alignment, or
reference interpretation is accepted by catalog construction or inference.

The v2 interpretation boundary defaults canonical fixed-path fields through a
named general profile, derives SIMPLE node inequalities deterministically,
defines a complete typed recursive condition schema, compares normalized
interpretations component by component, and attributes failures by stage.
The M13-D parser/spec/model bundle remains unchanged. `c_sem`, M11, GP,
compilers, logical operators, and backends are unchanged.

The comprehensive approximately 22 GB compressed Freebase source is not
present locally. Consequently committed catalog-v2 and reachability-v2
manifests are explicitly `blocked`; no v2 counts or improved Recall@k are
claimed. The frozen 18-query preflight spec hash is
`b02e67acd1f7b8f79d2cb7f3d48df7e5b2beb6c9e6624d1b1f5740921e3f2f35`.
Readiness refuses all provider calls until built artifact hashes match and the
offline gate passes. See the five M13-E1 reports under `docs/report/`.

## M13-D GrailQA Semantic Pilot Preparation

M13-D freezes the first real GrailQA RQ1 semantic pilot while preserving all
M13-C interpretation and algebra boundaries. It adds no PathPatternQuery form,
logical operator, `c_sem` rule, M11/Nash behavior, GP behavior, backend
execution, KQA Pro path, RQ2, or RQ3 functionality.

The query-independent public inference catalog contains 14,951 entities,
10,656 types, 13,747 relations, 5,531 scalar properties, and 9,908 directed
reverse-property entries. Its catalog hash is
`b547bf391a2dadf6c5affd205689da325bd4bce31b179b3d0a1f3c6bc4c4d416`;
the normalized ontology hash remains
`8bd4f19503d3a61a89831da1d040afea93fae1f64446e0ffb206b510bb69c10b`.
The entity source is the public FB15k-237 MID-name subset, so it is explicitly
incomplete and retrieval recall is measured after inference.

Inference now reads a gold-free question projection. A strict pre-provider
audit rejects gold forms, annotations, answers, references, canonical plans,
`Q(u)`, and `A(u)`. Evaluation-only references and workload statistics are
opened only after all selected questions have inference state. Deterministic
lexical retrieval persists IDs, labels, scores, ranks, question/catalog hashes,
and configuration; entity/relation/type Recall@1/5/10/20 is joined afterward.

The existing M12-B prompt and provider remain unchanged:
`qwen3-max-2026-01-23`, temperature 0, top-p 1, candidate cap 3, no supported
seed, and at most one repair. The frozen M grid is `{1,3}` because that M12
candidate cap supersedes requested values 5 and 10. Epsilon is
`{0,0.1,0.25,0.5,0.75,1}` and one generated candidate set is reused throughout.
Reference support is conservative variable-insensitive structural equality;
it is not a claim of general graph-query equivalence.

The ambiguity sanity audit selects recommendation C: exclude `A(u)` from this
pilot because it measures bounded ontology-neighborhood density rather than a
validated question-conditioned ambiguity quantity. `Q(u)` remains a complexity
stratum.

The immutable spec is
`experiments/specs/grailqa_semantic_pilot_v1.json`, with file SHA-256
`736237ec3293a1b3a86e94e7f2592b36179a6edf97635e07c306ba4c91a9ca48`
and canonical freeze hash
`5aeb1813813ca0c0835e30fa9c92644cf51a25b14480b6aa8b3d7e6938304e28`.
The local fake provider processed all 150 IDs, made 150 deterministic fixture
requests, produced 450 validated/grounded candidates, used no repairs, and
wrote every output. That run is orchestration-only and makes no accuracy claim.

Server commands are documented in
`docs/report/grailqa_semantic_pilot_server_runbook.md`. The frozen M13-D server
run subsequently completed all 150 questions: 132 provider successes, 18
malformed failures, 40 repairs, Candidate Recall 0, Top-1 0 for every epsilon,
and Feasible Coverage 0.48 for every epsilon. These remain immutable baseline
results; M13-E1 diagnoses their zero joint prompt reachability rather than
rewriting them.

Large generated benchmark bodies are intentionally excluded from Git. The
server now runs `scripts/server/fetch_grailqa_m13d_artifacts.sh` after `git
pull`. The script downloads pinned public GrailQA, official ontology, and
FB15k-237 sources, verifies their SHA-256 values, reproducibly rebuilds the
temporary v2 audit plus the required pilot/catalog, validates both against the
frozen experiment spec, and installs them atomically. On the experiment server,
it prepares `/home/<user>/xgap-data` as a symlink to
`/data/<user>/xgap-artifacts`, so large downloads and temporary builds do not
consume the home filesystem. A forced local fresh
rebuild reproduced all 64,331 audit classifications, the 35,439 supported
records, all 150 pilot IDs, catalog hash
`b547bf391a2dadf6c5affd205689da325bd4bce31b179b3d0a1f3c6bc4c4d416`,
and pilot bundle hash
`dd27f7fecdb226bef89beb50339932793bd5ffe1b987e1ce4144f6391caacd72`.
The dataset-bundle and RDF-mapping loaders normalize schema-declared empty YAML
mappings, including dataset metadata, alias groups, and compiler-token groups;
malformed non-mapping values remain rejected. Server bootstrap also exposed an
environment-dependent ontology mismatch: PyYAML coerced the valid unquoted
Freebase relation key `null` to a null object while XGAP's bundled parser kept
the required string identifier. Repository YAML now always uses the bundled
deterministic subset parser, preserving frozen artifact bytes and canonical
hashes whether or not PyYAML is installed.

## M13-C GrailQA Paper Vertical Slice

M13-C selected GrailQA as the current primary ontology-bounded semantic
interpretation benchmark and made one minimal generic semantic extension:
`NodeNotEquals` compares identity at fixed path-node positions and lowers
through the existing `Selection` operator. No logical operator, `c_sem`
definition, Nash objective, BnB rule, or GP confidence formula changed.

The full v2 audit classified all 64,331 public questions:

- 35,439 train/dev questions are supported, up 12,283 from M13-A;
- support is 69.352% of the 51,100 gold-available questions and 55.089% of all
  public questions;
- supported paths have lengths 1/2/3 with counts 26,002/8,952/485;
- `Q(u)` now has values 13/19/25, mean 14.680, median 13, p90 19, maximum 25;
- the operator totals are `Edges` 45,361, `Join` 9,922, `Selection` 151,678,
  `GroupBy` 35,439, and `Projection` 35,439;
- fixed numeric path-property comparisons contribute 466 supported questions;
  count, superlative, focus-only, branching, and multi-anchor forms remain
  explicitly unsupported.

The ontology is normalized by deterministic SCC condensation. Ten cyclic
components containing 18 terms become a 10,648-component DAG with 18,142
hierarchy edges. The normalized hash is
`8bd4f19503d3a61a89831da1d040afea93fae1f64446e0ffb206b510bb69c10b`;
no ontology edge is invented.

Reference `A(u)` is evaluation-only and is derived from the unchanged frozen
`c_sem`, exact interpretations, and bounded direct hierarchy neighbors. The
predefined epsilon analysis recommends 0.10 for pilot stratification but does
not freeze a final paper value.

`datasets/grailqa_pilot_v1/` contains 150 deterministic public train/dev cases
(seed 1303; 120 train and 30 dev). Its content hash is
`87ae8633712a54e30dd96154201248bbf3abe1fde5bdf104f09a92c5a472bac4`.
Gold answers, forms, alignments, slots, and reference interpretations are
evaluation-only; runtime aliases/entity catalog remain empty.

The controlled three-case vertical slice covers `Q=13/19/25` and traverses
the real `PathPatternQuery` lowering, M11 planning, and M9 Cypher/SPARQL
compilers. The controlled semantic metrics are pipeline-integrity checks, not
paper results. M13-C did not run live Qwen because it had no inference-safe
public entity catalog; M13-D later supplied a separate public catalog and
completed the frozen live 150-query diagnostic run. Freebase execution
feasibility is outcome C: semantic evaluation only is currently practical. No
financial-risk D0 was reused and no GrailQA D0 was created.

All 150 pilot interpretations currently expose one M11 all-local complete
realization; the fraction with more than one is zero. Two native compiler
targets do not constitute a rich physical search space. The current
recommendation is therefore **GrailQA for semantic-only paper evaluation**.
See `docs/report/grailqa_fragment_extension_analysis.md`,
`docs/report/grailqa_artifact_audit_v2.md`, and
`docs/report/grailqa_vertical_slice.md`.

## M13-B KQA Pro Artifact Feasibility Audit

M13-B classified all 117,970 public KQA Pro questions from verified official-
format artifacts using an isolated paired KoPL/SPARQL converter and unchanged
production XGAP boundaries.

- train has 94,376 questions, validation has 11,797, and public test has
  11,797; test masks KoPL, SPARQL, and answers;
- 1,690 train/validation questions lower through the strict linear fixed-path
  fragment and pass native Cypher/SPARQL compiler probes;
- 116,280 questions are explicitly unsupported or lack public gold;
- support is 1.592% of 106,173 gold-available questions and 1.433% of all
  public questions;
- supported M11 planning plans comprise 1,561 one-hop plans with `Q(u)=7` and
  129 two-hop plans with `Q(u)=15`;
- all 1,690 fit the controlled 4,096-state oracle bound, but no oracle or live
  backend measurement was run;
- the KB exposes 794 concepts, 16,960 entities, 363 observed relations, 629
  attributes, 275 qualifier keys, and an acyclic 365-edge concept hierarchy;
- the official download link was unavailable during the audit, so a complete
  public mirror revision and all four file hashes are frozen in the artifacts;
- native compilation feasibility uses an ephemeral term probe only. Current
  KQA Pro end-to-end execution coverage remains zero because final mappings,
  loaders, answer normalization, and a loaded backend snapshot do not exist.

The result is **unsuitable** as the primary current XGAP end-to-end and
physical-planning paper benchmark. It may be retained as a future restricted
diagnostic after a separate integration milestone. See
`docs/report/kqapro_artifact_audit.md` and `datasets/kqapro_audit/`.

## M13-A GrailQA Artifact Feasibility Audit

M13-A classified all 64,331 public GrailQA questions using an isolated audit
converter and the unchanged production `PathPatternQuery` lowering pipeline.

- 23,156 questions are structurally supported under the explicit one-hop
  entity-anchor and Freebase mapping contract;
- 41,175 questions are explicitly unsupported or lack public gold annotations;
- support is 45.315% of the 51,100 gold-available train/dev questions and
  35.995% of all public questions;
- 51,085 gold-available questions expose complete ontology-slot anchors from
  the parsed public resources;
- official ontology resources are substantial but require documented
  normalization, cycle handling, a type-to-label policy, and validation before
  they can become an M12 `OntologyGraph` artifact;
- a complete public alias lexicon, full entity catalog, Freebase backend
  mapping, executable graph snapshot, and public test gold are unavailable.

The result is **suitable with restrictions** for a future frozen train/dev
semantic-interpretation subset. It is not a completed DatasetBundle, backend
integration, ambiguity benchmark, or paper result. See
`docs/report/grailqa_artifact_audit.md` and `datasets/grailqa_audit/`.

## M12 Experimentalization

Current phase status:

- M12-A Experiment Artifact Contract + Dataset Bundle: Completed
- M12-B Live LLM + Ontology/Alignment Artifacts: Completed
- M12-C Cost Calibration + Online GP Protocol: Completed
- M12-D Baselines/Ablations + Server Experiment Runner: Completed

M12-A freezes experiment-facing semantics and artifact contracts. It does not
claim, by itself, live model access, production ontology reasoning/alignment,
KGQA execution, a final financial-risk benchmark, or final SIGMOD
experimental results. M12-B through M12-D add bounded live inputs, real-cost
calibration, and reproducible orchestration while preserving that separation.

See `docs/m12_experimentalization.md`.

## Implemented Logical Operators

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive`
- `GroupBy`
- `OrderBy`
- `Projection`

## Implemented Deterministic Core

LogicalPlan
  -> validate_plan
  -> reference evaluation

## Implemented Structured Pattern Layer

PathPatternQuery
  -> type_check_path_pattern
  -> deterministic lowering
  -> LogicalPlan

FocusedQuantifiedPatternQuery
  -> type_check_focused_quantified_pattern
  -> validate_quantifier_bounds
  -> deterministic lowering
  -> LogicalPlan

## Implemented M6 Binding Layer

- `BindingRelation`
- `BindNode`
- `BindEdge`
- `BindingJoin`
- `BindingProject`
- `QuantifiedCheck`
- `AntiSemiJoin`
- `FocusProjection`

M6 supports bounded, focused, rooted-tree quantified patterns with
non-injective set-valued bindings, distinct child-node counting, exact
ratio thresholds, non-vacuous ratio and universal semantics, anti-semi-
join `NONE`, focus-only queries, deterministic lowering, static schema
inference, plan validation, pretty printing, and reference evaluation.

M6 remains QGP-inspired only. It is not full QGP, not full GPC, and not
backend support.

## Not Implemented Yet
- Full GQL / Cypher / SPARQL compiler coverage
- GQL compiler support
- Recursive, selector, and M6 quantified-pattern backend compilation
- Logical rewrite optimization
- Paper-scale calibrated observations beyond the controlled development workload
- Production ontology/schema, stronger retrieval, and automated reasoning
- Distributed cross-backend execution
- Provider-specific production hardening beyond the generic OpenAI-compatible boundary
- Disambiguation
- KGQA evaluation

## M7 Backend Infrastructure

M7 Backend Infrastructure is completed.

Server-side Docker Compose scaffolding exists for starting local Neo4j
and Apache Jena Fuseki services on a lab machine, plus a minimal
financial-risk toy dataset and smoke-query scripts.

The server scripts default to the current repository checkout instead of
creating a fixed `/xgap-lab` directory. Operators can still override
`XGAP_REPO_ROOT` explicitly when needed.

When a user cannot access the Docker daemon socket directly, the server
scripts automatically fall back to `sudo docker`.

Backend healthcheck uses Neo4j `cypher-shell` readiness over Bolt
instead of requiring the Neo4j HTTP browser endpoint to respond first.

This is runtime environment setup only. It is not a compiler, planner,
semantic-deviation layer, ontology-reasoning feature, LLM feature, or
KGQA evaluation harness.

Earlier backend-environment scaffold verification, before the full M7
infrastructure layer:

- `bash -n scripts/server/*.sh`: passed.
- `docker compose --env-file services/.env.example -f services/docker-compose.yml config`:
  not available in the local development environment because the Docker
  CLI is not installed here.

Full M7 verification is recorded below.

## M7 Backend Infrastructure Protocol And Experiment Harness

XGAP now has JSON-serializable backend infrastructure records and a
minimal native-query execution harness:

- backend descriptors under `descriptors/backends/` for
  `reference_evaluator`, `neo4j`, and `fuseki`;
- `BackendDescriptor`, `BackendStatus`, `DatasetSpec`, `QueryArtifact`,
  `ExecutionReport`, and `RunRecord`;
- a descriptor registry with load, get, list, and language-filter
  helpers;
- a minimal `BackendClient` protocol with `healthcheck()` and
  `execute(QueryArtifact)`;
- native Neo4j Cypher and Fuseki SPARQL clients implemented with the
  Python standard library rather than backend driver dependencies;
- `examples/datasets/financial_risk_toy.yaml`;
- `xgap.experiments.backend_smoke`, which executes native smoke query
  files and writes `query_logs.jsonl` plus normalized result JSON under
  `runs/<run_id>/`.

This layer executes already-authored native Cypher/SPARQL smoke queries
only. It does not compile XGAP logical plans, does not implement
semantic-deviation scoring, ontology reasoning, bounded planning,
dominance pruning, top-K selection, LLM candidate generation, KGQA
evaluation, or logical-plan-to-native-query compilation.

Default pytest skips live backend execution unless `XGAP_RUN_BACKENDS=1`
is set.

Latest backend-infrastructure verification:

- `python -m pytest tests/test_backend_infrastructure.py tests/test_backend_live.py`:
  7 passed, 2 skipped.
- `python -m pytest`: 241 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, and `examples/quantified_pattern_demo.py`.
- Server live backend test:
  `PYTHONPATH=src XGAP_RUN_BACKENDS=1 python -m pytest tests/test_backend_live.py`:
  2 passed.

## M8 Backend Capability Profile + Compiler Boundary Preflight

M8 is completed.

M8 is not a database bootstrapping milestone. It assumes the M7 backend
services and native smoke harness are available.

M8 answers five questions:

1. Which XGAP path/GPC fragments does Neo4j support?
2. Which XGAP path/GPC fragments does Fuseki support?
3. Which M0-M6 logical constructs can be safely compiled?
4. Which constructs must explicitly return unsupported?
5. What is the format of compiler input, output, and failure reports?

Descriptor `capabilities` now include program-checkable capability
profiles for `reference_evaluator`, `neo4j`, and `fuseki`.

Implemented M8 objects:

- `SupportLevel`
- `SupportReason`
- `FeatureSupport`
- `BackendCapabilityProfile`
- `CompatibilityReport`
- `UnsupportedFeature`
- `CompilerInputSpec`
- `CompilerOutputSpec`
- `CompilerFailureSpec`

Implemented M8 compatibility helpers:

- `check_backend_support(profile, feature_request)`
- `check_backend_features(profile, feature_requests)`

The compatibility checker is static. It does not compile logical plans,
call backend clients, call the reference evaluator, run optimizer code,
or invoke planner, LLM, ontology, cost, or evaluation code.

M8 remains a preflight and boundary-definition milestone. It must not
implement optimizer algorithms, semantic-deviation scoring, ontology
reasoning, bounded planning, dominance pruning, top-K selection, LLM
candidate generation, KGQA evaluation, or logical-plan-to-native-query
compilation.

Latest M8 verification:

- `python -m pytest tests/test_backend_capabilities.py tests/test_backend_compatibility.py`:
  13 passed.
- `python -m pytest tests/test_backend_infrastructure.py tests/test_backend_live.py`:
  7 passed, 2 skipped.
- `python -m pytest`: 254 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, and `examples/quantified_pattern_demo.py`.

See `docs/m8_backend_capability_preflight.md`.

## M9 Minimal Compilers For Backend MVP

M9 is completed.

XGAP now has the first deterministic native-query compiler slice after
M8 capability preflight.

Implemented M9 compiler boundary:

- `compile_cypher(...)` returns a compiled Cypher `QueryArtifact` for
  Neo4j.
- `compile_sparql(...)` returns a compiled SPARQL `QueryArtifact` for
  Fuseki.
- `compile_gql(...)` remains an explicit unsupported boundary and
  raises `UnsupportedCompilationError`.
- Compiler failures carry `CompilerFailureSpec` records with backend,
  language, unsupported feature, support level, reason, and metadata.

Supported M9 fragment:

- `Nodes(G)`;
- `Edges(G)`;
- `Selection`;
- path-chain `Join`;
- fixed-length `OUT` path fragments;
- node-label and edge-label predicates;
- scalar property equality and numeric comparisons already represented
  by XGAP conditions;
- `PathPatternQuery` only for selector `ALL`.

M9 compiler outputs are row-oriented native artifacts. They do not claim
native XGAP `PathSet` object preservation.

M9 explicitly rejects:

- `Union`;
- `Recursive`;
- `GroupBy`;
- `OrderBy`;
- selector-style `Projection`;
- M6 focused binding operators;
- `FocusedQuantifiedPatternQuery`;
- `PathPatternQuery` selectors other than `ALL`;
- reverse or undirected edge lowering;
- unsupported regex placeholders;
- boolean `OR` and `NOT` conditions;
- path-length conditions;
- GQL compilation.

M9 does not implement optimizer rules, cost estimation, semantic-
deviation scoring, ontology reasoning, bounded planning, dominance
pruning, top-K selection, LLM candidate generation, natural-language
planning, or KGQA evaluation.

Latest M9 verification:

- `python -m pytest tests/test_compiler_boundaries.py tests/test_cypher_compiler.py tests/test_sparql_compiler.py`:
  11 passed.
- `python examples/compiler_mvp_demo.py`: passed.
- `python -m pytest`: 265 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, `examples/quantified_pattern_demo.py`,
  and `examples/compiler_mvp_demo.py`.

See `docs/m9_minimal_compilers.md`.

## M10 LLM Planner Boundary + Structured Candidate Interface

M10 is completed.

XGAP now has a structured LLM boundary without connecting any live model
provider.

Implemented M10 objects and helpers:

- `PlannerRequest`
- `PlannerCandidate`
- `PlannerResponse`
- `CandidateValidationReport`
- `StructuredCandidateProvider`
- `MockStructuredCandidateProvider`
- `PlannerSchemaError`
- `parse_path_pattern_query(...)`
- `parse_planner_response(...)`
- `path_pattern_query_to_dict(...)`
- `plan_from_question(...)`
- `plan_response_from_question(...)`
- `validate_candidate(...)`

M10 accepts only controlled JSON that parses into existing
`PathPatternQuery` objects. It rejects native query fields such as
`cypher`, `sparql`, `gql`, `native_query`, and `query_text`.

`plan_from_question()` has no default live provider in M10. Callers must
pass an explicit provider, and the included mock provider is for tests
and local demos only.

Candidate validation is deterministic:

PathPatternQuery
  -> type_check_path_pattern
  -> lower_path_pattern
  -> validate_plan

M10 does not implement Qwen/OpenAI/DashScope/vLLM clients, LoRA,
prompt optimization, semantic-deviation scoring, ontology reasoning,
logical optimization, bounded planning, dominance pruning, top-K
selection, KGQA evaluation, native query generation by an LLM, or live
model tests.

Latest M10 verification:

- `python -m pytest tests/test_llm_boundary.py`: 7 passed.
- `python examples/llm_boundary_demo.py`: passed.
- `python -m pytest`: 272 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check,
  pytest, all existing examples, `examples/quantified_pattern_demo.py`,
  `examples/compiler_mvp_demo.py`, and `examples/llm_boundary_demo.py`.

See `docs/m10_llm_planner_boundary.md`.

## M11 Ontology-Bounded Physical Planning

M11 is completed in four sequential phases:

- M11-A Planning Objective and Physical-State Contract
- M11-B Bounded Branch-and-Bound Physical Search
- M11-C Bayesian Cost Model and Search Trace
- M11-D XGAP Main Planner and Exhaustive Oracle Evaluation

The logical plan for an interpretation remains the deterministic output of
the existing M5/M10 pipeline. M11 does not enumerate logical rewrites. Its
search variables are backend placement and explicit cross-backend exchange
decisions for that fixed logical plan.

Ontology/schema definitions, source-to-ontology mappings, aliases, alignment
evidence, and semantic-deviation inputs are external, versioned,
replaceable planning artifacts. Missing, unknown, unsupported, or
insufficient mapping evidence is not treated as success. Bounded physical
search neither invents nor enumerates ontology mappings.

The M11 planning contract uses a strict execution threshold: a plan is
returnable only when its conservative upper estimate satisfies
`C_bar < T_max`. No threshold relaxation or fallback outside that bound is
allowed. Each interpretation contributes at most one discovered physical
representative, chosen by minimum conservative upper estimate within the
search budget. Final deterministic top-K ranking uses the Nash score only
when semantic and execution utilities are both strictly positive.

M11 explicitly excludes live LLM providers, KGQA dataset integration,
LoRA/model training, automatic ontology induction, a built-in OWL/DL
reasoner, full GQL, new M9 compiler coverage, logical rewrite search, new
backend engines, and distributed cross-backend execution.

Implemented M11-A contracts and interfaces:

- deterministic frozen physical-state, placement, exchange, realization,
  plan, objective, cost, feature, observation, trace, and configuration
  records;
- stable logical-operator and dependency identifiers derived from existing
  plan structure;
- `OntologyAlignmentProvider`, `SemanticDeviationScorer`, `CostEstimator`,
  `StateFeatureExtractor`, `BudgetPolicy`, and `PhysicalCompiler` protocols;
- controlled `ArtifactOntologyAlignmentProvider` and
  `ProvidedSemanticDeviationScorer` boundaries.

Implemented M11-B physical search:

- deterministic child-before-parent placement order;
- configured exchange strategies with automatic single-strategy resolution,
  branching only for explicitly supplied alternatives, and explicit
  infeasibility when none exists;
- lower-bound priority queue, one budget unit per processed `ExtractMin`,
  strict incumbent replacement by lower conservative upper cost, successor
  pruning, early bound termination, and anytime-prefix records.

Implemented M11-C cost and trace layer:

- positive complete-plan log-cost observations in a versioned append-only
  JSONL store;
- deterministic features with explicit missing-value flags;
- an immutable RBF Gaussian-process snapshot in log-cost space;
- finite combinatorial state-space bounds, per-interpretation and across-task
  confidence utilities, positive raw-cost bounds, and deterministic JSONL
  traces.

The repository has no NumPy, SciPy, or scikit-learn dependency. The M11 GP is
therefore a deliberately small standard-library implementation using a
jittered Cholesky factorization, isolated from the algebra core and tested on
controlled small planning datasets.

Implemented M11-D composition and experiments:

- M10 structured candidates through versioned alignment, supplied semantic
  deviation, deterministic lowering, bounded physical search, strict
  `C_bar < T_max`, one representative per interpretation, positive-utility
  Nash ranking, and deterministic top K;
- an adapter to existing M9 compilers or structured unsupported boundaries;
- `python -m xgap.experiments.physical_planner --config <path>` and complete
  `runs/<run_id>/` planner artifacts;
- a test/experiment-only tiny exhaustive oracle with true-cost regret,
  reachable/processed/generated/pruned metrics, pruning and reduction
  measures, budget-quality curves, and the `eta_search + eta_select`
  decomposition.

Controlled M11 inputs are:

- `examples/configs/m11_candidates.json`;
- `examples/configs/m11_alignment.json`;
- `examples/configs/m11_controlled_planner.json`.

These are deterministic fixtures, not a production ontology, automated
alignment system, ontology reasoner, live model, or benchmark dataset.

The current deterministic `PathPatternQuery` lowering preserves selector
`GroupBy`/`Projection` operators. Neo4j and Fuseki profiles correctly reject
those complete logical plans under current M8/M9 coverage, so the controlled
end-to-end M11 demo selects the reference evaluator. M11 does not bypass the
logical plan by compiling the original pattern directly and does not expand
M9 selector coverage. Direct logical fragments already within M9 remain
compilable through the adapter.

Latest M11 verification:

- `python -m pytest tests/test_m11_contracts.py tests/test_m11_search.py tests/test_m11_cost.py tests/test_m11_planner.py tests/test_m11_oracle.py tests/test_m11_runner.py tests/test_m11_compiler_adapter.py -q`:
  26 passed.
- `python examples/m11_physical_planner_demo.py`: passed; 2 selected plans,
  both with conservative upper estimate `6.289246`.
- `python examples/m11_exhaustive_oracle_demo.py`: passed; 3 reachable states,
  3 processed states, oracle and BnB true cost `2.0`, log-cost regret `0.0`.
- `python -m pytest`: 298 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including harness check, full pytest,
  all M0-M10 examples, and both M11 demos.

See `docs/m11_ontology_bounded_physical_planning.md`.

## M12-A Experiment Artifact Contract + Dataset Bundle

M12-A is completed. It freezes and implements the experiment-facing
contracts around the existing M10/M11 deterministic pipeline without
changing M11 planning behavior.

Implemented M12-A artifacts and APIs:

- stable SHA-256 canonical hashing that excludes resolved local bundle roots;
- `DatasetBundle`, normalized question/entity/alignment/schema records, and
  the four-way fragment-support taxonomy;
- validated ontology graphs with positive `H`, directed shortest-hop
  subsumption distance, and explicit admissible sibling pairs;
- directional semantic deviation with fixed multipliers `0`, `1/3`, `2/3`,
  and `1`, uniform slot aggregation, and symbolic `infinity` for missing,
  incomplete, unrelated, or inadmissible evidence;
- the default epsilon sweep `{0, 0.1, 0.25, 0.5, 0.75, 1.0}` with config
  override support;
- `ModelBundle` and prompt contracts plus an offline M10 mock response
  bundle, with no live model endpoint;
- `ExperimentSpec`, GP/calibration and M11 feature-schema references,
  execution protocol, explicit artifact availability, baseline IDs,
  ablation switches, and grouped nullable metric records;
- frozen run layout and traceable manifest with explicit unavailable
  CUDA/GPU/Docker/backend-version fields;
- `python -m xgap.experiments.run --config <path>` for the controlled
  `full_xgap` development path only.

The frozen GP experiment protocol retains the M11 RBF GP and
`log_execution_cost` target. Future calibration samples complete physical
plans into `D_0`, fits hyperparameters once on `D_0`, freezes those
hyperparameters during evaluation, and permits posterior updates only
between tasks. M12-A serializes and validates this protocol; it does not
collect real observations or perform server calibration.

The controlled development bundle at `datasets/financial_risk_dev/` contains
20 explicitly synthetic cases spanning exact, specialization,
generalization, explicit sibling, inadmissible/missing/incomplete mapping,
fixed path, filter, compiler/representation gaps, multiple interpretations,
and placement alternatives. It reuses the existing native financial-risk
load artifacts. It is not the final paper benchmark.

The formal development run used two currently representable OUT-path cases
and three controlled candidates. It produced 27 files under
`runs/m12-financial-risk-xgap-dev/`, including logical and physical plans,
search traces, reference logical query artifacts, manifests, and explicit
`not_available` backend-result records. Both questions completed
successfully. No backend execution is claimed.

Frozen baseline IDs:

`full_xgap`, `random_feasible`, `mean_only`, `no_pruning`,
`no_online_update`, `single_backend`, `exhaustive_oracle`, and
`direct_text2graphquery`.

Frozen ablation switches:

`no_uncertainty`, `no_pruning`, `no_online_learning`, `no_semantic_bound`,
`cost_only`, and `no_nash`.

M12-A executes only the controlled `full_xgap` development path. M12-D
subsequently adds executable baseline and ablation policies around the frozen
pipeline.

Latest M12-A verification:

- `PYTHONPATH=src python -m pytest tests/test_m12_semantic.py tests/test_m12_contracts.py tests/test_m12_runner.py -q`: 15 passed.
- `python examples/m12_experiment_contract_demo.py`: passed; 2/2 questions
  succeeded and 27 artifact files were produced in the temporary run.
- `PYTHONPATH=src python -m xgap.experiments.run --config experiments/configs/financial_risk_xgap_dev.json`: passed; 2/2 questions succeeded and
  the frozen run tree was produced.
- `python -m pytest`: 313 passed, 2 skipped.
- `./scripts/run_acceptance.sh`: passed, including the harness, full pytest,
  all previous examples, both M11 demos, and the M12-A demo.

M12-B subsequently replaces the controlled inference inputs with the bounded
live/runtime path described below. M12-C subsequently implements real-backend
D0 collection capability and the online posterior lifecycle. M12-D now
provides executable baselines, ablations, and server orchestration.

See `docs/m12_experimentalization.md`.

## M12-B Live LLM + Ontology/Alignment Artifacts

M12-B is completed. The same configuration-driven M12 runner now selects
either the existing M12-A mock path or a live structured provider path from
`ExperimentSpec` and `ModelBundle`; the M11 physical planner is unchanged.

Implemented M12-B boundaries:

- a generic `OpenAICompatibleStructuredCandidateProvider` implementing the
  existing M10 `StructuredCandidateProvider` protocol;
- one generation call and at most one schema/syntax repair call, with exact
  generation/repair counts and exact sanitized assembled requests in run
  artifacts;
- a fixed DashScope ModelBundle for `qwen3-max-2026-01-23` and a portable
  configuration-only vLLM OpenAI-compatible template;
- deterministic bounded lexical/alias retrieval over the versioned ontology,
  entity catalog, source schema snapshot, and backend mappings;
- per-question `PromptSchemaView`, explicit query anchors, separate candidate
  slot realizations, prompt-visible ID validation, full slot-coverage checks,
  real kind-compatible pattern-component validation, and explicit
  missing-mapping failures;
- `FileBackedRuntimeAlignmentProvider`, which creates real runtime inputs for
  the frozen M12-A directional ontology-hop `c_sem` implementation without
  using benchmark gold artifacts;
- live invocation, exact sanitized assembled requests, usage, prompt-view,
  query-slot, grounding, alignment, diagnostics, and optional live-generation
  metrics artifacts;
- stable failure categories for provider, parsing, repair, grounding,
  mapping, semantic, representation, and compiler boundaries.

The anti-leakage boundary excludes gold answers, gold logical forms, gold
alignments, and evaluation labels from runtime retrieval, prompts, model
requests, candidate validation, semantic deviation, and M11 planning. The
runtime artifact loader has no gold-bearing DatasetBundle reference after
construction. Gold remains available only to a future explicit evaluation
path.

The financial-risk ontology remains a controlled development artifact. The
retriever is deterministic lexical/alias retrieval, not a full OWL/DL
reasoner. The live provider emits grounded `PathPatternQuery` JSON only;
native Cypher, SPARQL, or GQL remains deterministic compiler output.

The M12-B end-to-end audit is recorded in
`docs/report/m12b_llm_boundary_audit.md`. Its final verdict is PASS after the
required fixes and a credentialed post-fix smoke. The fixes persist
`llm_requests.jsonl`, reject empty semantic context, validate typed
`component_ref` attachments, and clarify the zero-shot semantic contract and
interpretation diversity. They do not change M11, `c_sem`, PathPatternQuery
semantics, or downstream planning.

M12-B itself does not implement model training, LoRA, model deployment, real
D0 collection, GP calibration, online posterior updates, executable
baselines, ablation matrices, KGQA evaluation, or server-scale orchestration.
M12-C and M12-D subsequently add calibration/lifecycle and experiment
orchestration; model training, deployment, and KGQA remain later work.

Latest M12-B verification:

- `python -m pytest tests/test_m12b_provider.py tests/test_m12b_runtime_alignment.py tests/test_m12b_runner.py tests/test_m12b_live.py -q`:
  23 passed, 1 skipped;
- `python -m pytest tests/test_llm_boundary.py tests/test_m12_contracts.py tests/test_m12_runner.py tests/test_m12_semantic.py tests/test_m12b_provider.py tests/test_m12b_runtime_alignment.py tests/test_m12b_runner.py tests/test_m12b_live.py -q`:
  45 passed, 1 skipped;
- `python -m pytest -q`: 336 passed, 3 skipped;
- the skipped M12-B test is the real DashScope smoke test, gated by both
  `XGAP_RUN_LIVE_LLM=1` and `DASHSCOPE_API_KEY`;
- credentialed post-fix command
  `XGAP_RUN_LIVE_LLM=1 PYTHONPATH=src python -m pytest tests/test_m12b_live.py -v`:
  1 passed in 33.64 seconds;
- the post-fix run made one generation call and no repair call, persisted an
  exact `llm_requests.jsonl` payload whose hash matches the invocation, and
  produced one fully validated logical/physical candidate;
- the fake-HTTP integration exercised the real OpenAI-compatible provider,
  runtime grounding, frozen `c_sem`, unchanged M11 planner, and live artifact
  layout without network access;
- the M12-A mock runner regression planned 2/2 questions successfully;
- `./scripts/run_acceptance.sh`: passed with 336 tests passed, 3 gated live
  tests skipped, and all existing examples successful.

## M12-C Cost Calibration + Online GP Protocol

M12-C is completed. It adds a separate, server-friendly calibration path and
does not modify `PathPatternQuery`, logical lowering, M11 BnB, `c_sem`, the
Nash objective, or the frozen M12-B model/alignment boundary.

Implemented M12-C boundaries:

- typed calibration config, case, workload, plan, measurement, D0, calibrated
  model, posterior snapshot, and posterior-update artifacts;
- deterministic stratified selection of complete plans from a dedicated
  calibration split;
- M9 compilation followed by repeated execution through the existing Neo4j
  and Fuseki clients, including support for M9 `compiled` native artifacts;
- raw millisecond and `log(execution_ms)` persistence with all warmup and
  measured repetitions retained;
- separate `D0_neo4j` and `D0_fuseki` datasets with no cross-backend
  observation mixing;
- deterministic negative-log-marginal-likelihood calibration of the existing
  RBF GP family, with repeated-run noise evidence and a positive noise floor;
- persisted config, protocol, descriptor, feature-schema, D0, model, and
  hyperparameter hashes;
- immutable `BackendCostModelRegistry` snapshots that expose calibrated
  estimators through the existing M11 `CostEstimator` interface;
- `OnlinePosteriorLifecycle`, which gives task q one fixed `D_(q-1)` snapshot
  and atomically appends only successful executed complete-plan observations
  after the whole task batch finishes;
- backend-isolated updates, batch IDs and K_q records, temporal anti-leakage
  checks, persisted execution evidence, and unchanged hyperparameter hashes;
- explicit unavailable handling for unsupported distributed cross-backend
  movement measurement;
- a two-plan financial-risk development workload, a dual-backend calibration
  config, an offline deterministic demo, and an optional gated live smoke.

The local offline development run created two D0 records per backend and two
independently calibrated model artifacts. It demonstrated that the calibrated
posterior differs from the development prior for at least one state. These are
explicit fake development latencies and are not claimed as real Neo4j/Fuseki
calibration results.

Real server command:

```bash
XGAP_RUN_BACKENDS=1 PYTHONPATH=src \
python -m xgap.experiments.calibrate \
  --config experiments/configs/financial_risk_gp_calibration_dev.json
```

Optional live pytest additionally requires `XGAP_RUN_CALIBRATION=1`. Default
pytest remains fully offline.

M12-C does not add a joint backend-aware GP, cross-backend movement-cost
learning, distributed runtime orchestration, new compiler coverage, baseline
or ablation execution, matrix scheduling, new benchmarks, semantic-deviation
changes, ontology reasoning, or new LLM behavior. M12-D subsequently adds
baseline/ablation execution and matrix scheduling without adding the other
features.

Latest M12-C verification:

- `PYTHONPATH=src python -m pytest tests/test_m12c_calibration.py tests/test_m12c_live.py -q`:
  9 passed, 1 live calibration test skipped;
- the M11/M12-A/M12-B focused regression suite: 57 passed, 1 gated live LLM
  test skipped;
- `PYTHONPATH=src python examples/m12c_calibration_demo.py`: passed, with 2
  explicit fake D0 records and one calibrated model per backend;
- `python -m pytest`: 345 passed, 4 gated live tests skipped;
- `./scripts/run_acceptance.sh`: passed, including the harness, full pytest,
  all historical examples, and the M12-C offline calibration demo.

The real M12-C backend calibration was run separately on the server after both
native smoke queries returned nonempty results. The two backend live tests and
the live calibration test reported `3 passed in 2.11s`; calibration reported
`measurement_source=real_backend` and D0 observation count 2 for each of
Neo4j and Fuseki. These are development acceptance observations, not final
paper calibration data.

## M12-D Baselines/Ablations + Server Experiment Runner

M12-D is completed. It composes the frozen M10-M12-C boundaries into a
declarative, resumable experiment system without changing logical semantics,
`c_sem`, M11's default BnB/Nash behavior, or GP formulas.

Implemented M12-D boundaries:

- explicit policies for `full_xgap`, seeded `random_feasible`, `mean_only`,
  `no_pruning`, `no_online_update`, configured `single_backend`, controlled
  bounded `exhaustive_oracle`, and separate `direct_text2graphquery`;
- real behavior for `no_uncertainty`, `no_pruning`, `no_online_learning`,
  `no_semantic_bound`, `cost_only`, and configured `no_nash` ablations, with
  contradictory combinations rejected;
- immutable candidate/grounding artifacts shared across comparable planning
  methods, with prompt/model/grounding/artifact hashes and exact live request
  evidence where available;
- an online task runner that snapshots `D_(q-1)`, fixes it for all planning
  decisions in task q, executes selected complete plans, then atomically
  commits K_q observations to produce D_q;
- deterministic matrix expansion and run IDs, completed-run skipping,
  explicit resume/retry, per-task recovery records, collision checks, and a
  bounded 12-run financial-risk development matrix;
- normalized execution cardinality and separate
  `execution_success_nonempty`, `execution_success_empty`, and
  `execution_error` statuses;
- calibration-query cardinality diagnostics with explicit expected-nonempty
  cases, relevant mapped IRIs, and separate empty-success handling;
- method-aware search traces, cost prediction/confidence observations,
  separated latency/result/failure metrics, and JSON/CSV aggregation;
- development/pilot/paper modes, environment capture, readiness checks, and a
  paper freeze manifest. Paper mode supports Python 3.10+ and requires pinned,
  identified backend versions/images plus a passing RDF mapping/data/compiler
  contract. Exact runtime and image identity remain recorded per run.

Offline completion verifies the runner lifecycle and D0 -> D1 -> D2
transition using deterministic fake backend timings. The real M12-D online
D0 -> D1 -> D2 pilot remains a separately gated server command and is not
claimed by local completion.

M12 completion means experiment infrastructure is ready for paper-grade
dataset/model artifact preparation and large-scale runs. It does not mean
final datasets or paper numbers exist, MetaQA/QALD are integrated,
cross-backend distributed execution or transfer-cost learning exists, or new
compiler fragments are supported.

## Post-M12-D Paper-Environment Hardening

This completed hardening pass did not change `PathPatternQuery`, logical
algebra, `c_sem`, M11 search/ranking, GP formulas, prompt/schema contracts,
baselines, or M12-D experiment semantics.

- package metadata, paper readiness, and the online paper gate now support
  Python 3.10+; the dependency and 3.10 syntax/API audit found no blocker;
- paper backend startup uses `services/.env.paper` and requires current
  validated `repository@sha256:<digest>` image references, while development
  floating tags remain warning-only;
- environment manifests record repository, tag, digest, local image ID and
  RepoDigests when visible, plus backend-reported software version where
  available;
- the DatasetBundle backend mapping is now the sole source for M9 SPARQL RDF
  IRIs; missing or invalid mappings fail explicitly;
- the financial-risk RDF bundle retains reified Transfer records and adds the
  mapped direct `transfersTo` predicate needed by the existing bounded M9 path
  fragment;
- `python -m xgap.experiments.backend_mapping_audit` verifies
  `URI_data == URI_mapping == URI_m9`, and readiness fails on any unresolved
  mismatch;
- readiness also rejects paper use of Fuseki calibration artifacts whose
  query mapping hash is absent or differs from the active DatasetBundle, so
  pre-hardening D0 must be regenerated after the updated data is loaded;
- configured expected-nonempty live calibration cases assert positive Fuseki
  row counts; arbitrary empty results remain valid successful executions.

## Required Acceptance Command

```bash
./scripts/run_acceptance.sh
```

# Latest Known Acceptance Status

M0-M15-F2C8B live semantic-relaxation and F2C9B local native-direct-frontier
implementation tests passed. M7 backend
smoke and
M12-C real calibration acceptance passed on the server. A real DashScope M12-B
development run completed one question with one generation call, no repair,
and three candidates; its credentialed post-fix rerun verified the revised
prompt, typed grounding, and exact-request artifact. M12-D live online and
direct-baseline tests remain explicitly gated and have not been claimed from
the local completion run.

Latest recorded command results:

- CWRU F2C8B job `3790680`: the predicate-only and
  risk-plus-predicate direct classes completed at exact clean commit
  `2d39c3c` in 96 seconds on `compt295`. Their fixed risk-first plans returned
  exact 6- and 9-row answers in four aggregate backend calls and moved 6,262
  bytes. The independent read-only audit passed 150/150 checks without
  mutating the run tree. This is a live mechanism gate, not a comparative,
  semantic-utility, ontology-truth, or paper result.
- `./scripts/run_acceptance.sh`: 853 passed and 36 explicitly gated or
  external-artifact tests skipped on Python 3.10.19. F2C9B carries the F2C9A
  capability-aware direct frontier into a native-service mode using a
  versioned controlled estimate source. Selection is persisted before oracle
  or backend access; only three returned plans execute, the controlled native
  double path makes six calls and returns exact 11-, 9-, and 11-row answers,
  and its independent reconstruction audit passes 211/211 checks. This is
  local mechanism readiness, not real-backend or performance evidence.
- CWRU F2A job `3787291`: one selective hash-bound campaign session completed
  at exact clean commit `c9a7afe` in 86 seconds on `compt336`. The compiled
  Williams order drove the six real-service methods, all answers were exact,
  and the trace contained exactly 18 tool invocations with zero retry. Its
  independent read-only audit passed 374/374 checks and reported
  `run_tree_mutated=false`. This is a single-session mechanism gate, not a
  comparative result.
- CWRU F2C4 job `3787592`: the six-instance exact parameterized stream
  completed at exact clean commit `66327a47` in 69 seconds on `compt298`.
  All twelve strategy executions were exact, their task trace contained 24
  backend calls with zero retry, and the independent read-only audit passed
  172/172 checks with `run_tree_mutated=false`. This closes an executable
  parameter-variation gate, not a memory-transfer or performance result.
- CWRU F2C5 job `3787610`: the family-transfer mechanism completed at exact
  clean commit `30214cb` in 69 seconds on `compt298`; four seed records fed one
  frozen view and two held-out selections, all selected answers were exact,
  and the independent read-only audit passed 278/278 checks without run-tree
  mutation. The development KNN selected 0/2 post hoc observed latency winners;
  fixed selected-then-shadow order makes that a diagnostic, not a comparative
  estimate.
- `./scripts/run_acceptance.sh`: 814 passed and 36 explicitly gated or
  external-artifact tests skipped on Python 3.10.19. This includes the F1L
  real-service method-matrix contracts, the F2 counterbalanced campaign
  compiler, its hash-bound single-session native runner/auditor, the F2B1
  portable resolved-query contract compiler, and the F2B2 query-bound campaign
  compiler. F2C2 adds the v2 typed parameterized financial-risk contract,
  selected hard/relaxable policy, value-independent family identity, and
  typed backend binding stages. F2C3 binds six distinct instances to shared
  data, literal-free backend templates, and exact per-instance oracles. F2C4
  adds the oracle-independent alignment catalog, two exact executable plans
  per instance, a six-query native task stream, and its read-only audit. The
  F2C5 slice adds a separately keyed family-memory model, exact-only seed
  commits, one reopened frozen evaluation view, oracle-free held-out plan
  selection, separated online versus evaluation-shadow calls, an
  allocation-scoped native runtime identity, dedicated service mode, and an
  independent memory/evidence auditor. F2C6 adds evidence-backed bounded
  relaxation enumeration, typed recompilation, semantic-equivalence merging,
  per-class physical reduction, Pareto/epsilon filtering, and a K-bounded
  representative set without making external calls. The
  F2C7A readiness matrix then separates one bound, one safely generatable, and
  ten blocked semantic classes. F2C7B1 materializes only the supported
  risk-level alternative in an immutable overlay with bound source/final
  oracles and identical shared data. F2C7B2 adds one fixed-plan live runner,
  allocation-local native mode, allowlisted Slurm entry, and independent
  tamper-detecting evidence auditor; CWRU job `3787648` closed the live gate
  with an exact 11-row result and a 133/133 read-only audit. The
  F2B3 direct runner verifies the selected
  contract from the
  live bundle before passing a v2 identity into the six-method matrix. F2B4
  adds the native-service mode, dedicated Slurm entry, and independent
  recompilation audit; CWRU job `3787430` subsequently closed that gate.
  CWRU F1L job `3787267` separately passed
  its independent 326-check read-only audit at exact commit `6aafafd`.
- CWRU F2B4 job `3787430`: one selective query-bound session completed at
  exact clean commit `d795fac` in 73 seconds on `compt348`. The independent
  read-only audit recompiled the registry and live-bundle query contract and
  passed 377/377 checks with `run_tree_mutated=false`. This is an identity-chain
  engineering gate, not a comparative or cross-task-memory result.
- `./scripts/run_acceptance.sh`: 612 passed and 36 explicitly gated or
  external-artifact tests skipped on Python 3.10.19. The M15-focused subset
  passed 140 with two live-service skips. Shell syntax validation passed for
  the CPU smoke, native vertical-slice, and separate native adaptive-service
  entry points.
- `PYTHONPATH=src python -m pytest`: 492 passed, 10 skipped, including the
  focused M13-E1 catalog-v2 fixture, M13-E2 CWRU/vLLM contracts, M13-E3 source
  checksum/restart/integrity/audit tests, and M13-E3A frozen-inventory,
  mode-selection, compatibility-report, and CPU workflow tests. Three M13-E3A
  file-level Parquet tests are skipped only when optional PyArrow is absent;
  M13-E3A.1 covers both old and new curl capability paths. M13-E3B covers
  question-only construction, query isolation, local type enrichment,
  Catalog-v2 compatibility, local loss attribution, pending-full reports, and
  E3B.1 `PosixPath` materialization normalization. E3B.2 adds persisted-rank
  entity retrieval, global-FTS non-regression, Top-k prefix/isolation, and
  relation/type diagnostic-stage regressions. E3B.3 adds phrase-tier,
  term-aggregation, stable-tie, slot-isolation, domain/range-coherence,
  type-provenance, and no-gold contract regressions. E3B.4 adds exact
  direction/role mapping, runtime accept/reject, explicit-versus-effective
  Type reachability, prompt truncation, and endpoint audit-artifact regressions.
  E3B.5 adds explicit query-local profile success, contract/ID/hash fail-closed
  cases, structured endpoint-contract request propagation, conditional metric
  separation, order-independent exact-ID-set validation, and CWRU wrapper
  syntax/path checks.
- `./scripts/run_acceptance.sh`: passed with the same 492 passed and 10 skipped,
  followed by all required deterministic examples and acceptance checks.
- `PYTHONPATH=/private/tmp/xgap-m13e3a-pyarrow:src python -m pytest
  tests/test_m13e3a_freebase_parquet.py tests/test_m13e3_freebase_catalog.py
  -q`: 14 passed, including N-Triples/Parquet catalog and retrieval parity.
- `PYTHONPATH=/private/tmp/xgap-m13e3a-pyarrow:src python -m
  xgap.experiments.freebase_sources smoke ... --max-row-groups 1`: passed on
  the real frozen `0000` shard; 649,794 rows contained every required construct.
- `PYTHONPATH=src python -m pytest tests/test_m13e3b3_schema_ranking.py
  tests/test_m13e1_reachability_contract.py tests/test_m13e3a_freebase_parquet.py
  tests/test_m13e3b_local_catalog.py -q`: 40 passed, 3 skipped.
- `bash -n scripts/server/build_grailqa_local_catalog.sh`, `bash -n
  scripts/slurm/build_grailqa_local_catalog.sbatch`, and `git diff --check`:
  passed.
- M13-D offline reachability reproduction: catalog entity 12/150; retrieval
  Top-20 entity/relation/type 10/47/67; deployed prompt 9/22/38; joint 0/150.
- M13-E1 local readiness: refused the live path because catalog v2 and
  reachability v2 are explicitly incomplete; no provider call was made.
- full official GrailQA audit command: completed 64,331 classifications with
  23,156 supported and 41,175 unsupported records.
- full GrailQA v2 audit command: completed 64,331 classifications with 35,439
  supported and 28,892 unsupported records; the gold-available support ratio
  is 69.352%.
- GrailQA pilot command: built and validated 150 questions with bundle hash
  `dd27f7fecdb226bef89beb50339932793bd5ffe1b987e1ce4144f6391caacd72`;
  its controlled `Q=13/19/25` vertical slice completed.
- M13-D deterministic fake-provider run: accounted for all 150 frozen IDs,
  completed 150 fixture requests, produced 450 validated and grounded
  candidates, used no repairs, and wrote every required output. It is marked
  orchestration-only and makes no accuracy claim.
- full KQA Pro audit command: completed 117,970 classifications with 1,690
  structurally/planning-supported and 116,280 unsupported records; current
  integrated KQA Pro execution coverage remains zero.
- `python -m pytest` over the focused M9-M12-D and hardening regression set:
  109 passed, 5 live-gated tests skipped.
- `python -m xgap.experiments.backend_mapping_audit --dataset
  datasets/financial_risk_dev`: passed with no three-way IRI mismatches.
- `python examples/quantified_pattern_demo.py`: passed.
- `python examples/compiler_mvp_demo.py`: passed.
- `python examples/llm_boundary_demo.py`: passed.
- `python examples/m11_physical_planner_demo.py`: passed.
- `python examples/m11_exhaustive_oracle_demo.py`: passed.
- `python examples/m12_experiment_contract_demo.py`: passed; 2/2 controlled
  questions and 27 artifact files.
- `python examples/m12c_calibration_demo.py`: passed; the explicit offline
  fake path produced 2 D0 records and one calibrated GP per backend.
- `python examples/m12d_experiment_matrix_demo.py`: passed; 12 runs and 12
  aggregate groups completed with frozen candidate reuse.
- `./scripts/run_acceptance.sh`: passed with 436 passed and 7 live-gated
  skips, including harness check, pytest, all existing examples,
  `examples/quantified_pattern_demo.py`,
  `examples/compiler_mvp_demo.py`, `examples/llm_boundary_demo.py`, both M11
  demos, the M12-A demo, the M12-C calibration demo, and the M12-D matrix
  demo. The M12-B fake-HTTP and M12-D offline paths are exercised by pytest.
- `git diff --check`: passed.

Expected checks include:

- harness check
- pytest
- examples/core_algebra_demo.py
- examples/plan_print_demo.py
- examples/recursive_demo.py
- examples/solution_space_demo.py
- examples/semantic_audit_demo.py
- examples/lowering_demo.py
- examples/pattern_lowering_audit_demo.py
- examples/quantified_pattern_demo.py
- lowering tests
- pattern-lowering audit tests
- quantified-pattern tests
- M9 compiler tests
- M10 LLM-boundary tests
- M11 contracts, search, cost, main-planner, oracle, and runner tests
- examples/m11_physical_planner_demo.py
- examples/m11_exhaustive_oracle_demo.py
- M12-A semantic, bundle/contract, and runner tests
- examples/m12_experiment_contract_demo.py
- M12-C calibration, model, measurement, and online-posterior tests
- examples/m12c_calibration_demo.py
- M12-D methods, ablations, candidate freeze, direct baseline, online
  lifecycle, matrix, resume, aggregation, and readiness tests
- examples/m12d_experiment_matrix_demo.py
