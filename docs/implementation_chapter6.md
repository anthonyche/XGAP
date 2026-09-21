# Chapter 6 implementation map — bounded joint system v1

This describes executable T4 code, not the complete space of research ideas.
Current entry: `xgap.api.answer`. Engineering evidence and limitations are in
[the T4 report](report/bounded_joint_system_20260917.md). The Chapter 7 plan was
adopted on 2026-09-20; [T6 readiness](report/chapter7_readiness_20260920.md) extends
the interfaces below. Earlier T3 results belong to their recorded version.

The 2026-09-20 [T5 batch acceptance](report/bounded_joint_batch_20260920.md) adds
current-method dispatch, independent compressed-answer scoring and nonduplicating
batch resume. It does not change the core algorithm or discrepancy definition.

## 6.1 Interfaces and admitted semantics

|Step|Implementation|Boundary|
|---|---|---|
|NL proposal|`llm/compact_interpretation.py`|One frozen compact-model call, no repair; deterministic template is an explicit alternative|
|Candidate construction|`semantic/intent_scope.py`|1–8 proposals; frozen coordinate domains; ≤64 complete candidates, ≤32 coordinates|
|Predicate coordinates|`semantic/intent_scope.py`|Optional public property/operator locator; unique match required before expansion; ambiguous/overlapping coordinates fail closed|
|Scope authority|`agent/scope_authority.py`|Private full query; paid containment yes/no; no candidate ID disclosed|
|Terminal certificate|`agent/intent_certificate.py`|Fixed skeleton, hard coordinates, rational weighted soft-coordinate distance|
|Policy search|`agent/intent_strong.py`, `agent/strong_planning.py`|One shared finite AND/OR search; every selected outcome needs a continuation|
|Joint objective|`planning/joint_cost.py`|Information + estimated final execution in declared comparable work units|
|Physical preparation|`agent/intent_execution.py`, `runtime/one_shot_planning.py`|Lazy per certified candidate; bounded strategies, frozen scoring, no execution trials|
|Compilation/execution|`semantic/compact_lowering.py`, `compilers`, `runtime/scheduler.py`|Cypher/SPARQL; coordinator joins/filters/aggregates; retain root rows|
|Durable entry|`experiments/bounded_joint_worker.py`|Pinned input/profile/scope/user; compressed evidence; no answer labels|
|Batch method boundary|`experiments/nl_method_worker.py`, `common_method_trial.py`, `bounded_joint_contract.py`|Explicit current IDs, pinned scope/config/user, worker/source/study budgets; old IDs unchanged|
|Independent scoring|`experiments/common_row_score.py`|Post-seal raw/gzip rows; hashes, declared row equivalence, order and bags|
|Controlled initial state|`api.answer_controlled`, `experiments/controlled_state.py`|Shared planner/runtime; full loss denominator; no NL timing or free replayed clarification|
|Complete policy evidence|`agent/policy_evidence.py`|Every selected outcome plus physical plans; observed state IDs separate; no hypothetical measurements|
|Query representation identity|`semantic/compact_identity.py`|Bounded alpha-renaming/conjunction order; literal/semantic fields unchanged; stored slot coordinates unchanged|
|Independent query loss|`experiments/query_loss_score.py`|Post-seal private comparison; no certificate-as-observation or answer-error guarantee|
|Equivalent source projections|`runtime/shared_match_projections.py`|Compiler-proved complete Match reuse under output renaming; original native representative, consumer schemas preserved|
|Evidence and source accounting|`experiments/evidence_store.py`, `campaign_source_observer.py`|Separate stored bytes from logical transferred bytes; lossless replay|

Paths in this table are under `src/xgap/`.
The supported compact language contains ≤8 node variables, ≤12 explicit edges,
≤32 predicates, ≤16 output expressions and at most one directed bounded path of
1–3 hops (`WALK` or `ACYCLIC`). It supports connected typed patterns, equality and
ordered property/time comparisons, optional sum/count/min/max, declared
contribution/deduplication, order and a bounded explicit limit. The compiler and
source capabilities can reject a structurally valid query; syntax validation alone
does not establish executable semantics.

The new route requires complete candidates: explicit business IDs/literals or
frozen finite coordinate alternatives. Unresolved named-entity holes are outside
this release's current entry; the older catalog-grounding implementation remains
available only in its historical profile. Do not describe this as arbitrary NL
entity grounding. All candidates must share one fixed query skeleton; alternate
unrelated graph topologies are rejected. Distinct fixed fields cannot be relaxed.
Scope construction explicitly chooses either finite Cartesian expansion or the
`proposals_only` Top-K support (≤8 proposals). The latter validates coordinates
against frozen domains without inventing Cartesian combinations. Both require paid
authoritative containment; model scores never certify support. Constant coordinates
remain fixed fields rather than diluting distance. Cartesian product size is checked
*before* generation; neither path truncates uncertainty to fit K. K bounds computational support, not real-world NL coverage.

## 6.2 Authority and the two modes

For a family Q and acquired truthful replies o, let Q(o) be its consistent subset.
For two candidates, d is infinity when any declared hard coordinate disagrees;
otherwise d is weighted Hamming distance over soft coordinates, divided by their
total weight (or one when there are none). Fixed non-coordinate structure is
identical by admission. The certificate is

`U(q,o) = max { d(q,q') : q' in Q(o) }`.

A terminal must belong to Q(o), have confirmed scope/snapshot identity, and satisfy
`U ≤ epsilon`. EXACT uses epsilon=0. PERFORMANCE uses the declared epsilon.
A full/scoped user reply narrows Q(o); it does not rewrite the candidate or silently
replace it with gold. Contradictions and out-of-scope intent are explicit failures.

The simulated user holds a frozen, question-bound complete query independent of
the proposed release. `confirm_scope` is an actual metered action in both modes.
It reveals only containment, not the chosen intent. Only subsequent paid
clarification reveals requested coordinates. Offline gold/reference rows are
excluded from `answer` and the worker. Correctness scoring must happen afterwards.
This is a deterministic structured-intent guarantee conditional on truthful scope
and replies. It is not an answer-F1, probability-of-error or open-domain guarantee.

## 6.3 One joint cost objective

`J(terminal plan) = estimated execution work`

`J(acquire a) = declared acquisition work(a) + max_outcome J(child)`

Information prices are frozen call/field costs; an available compatible offline
estimator supplies execution predictions, normalized into the same work units.
If unavailable/incompatible, an explicitly labelled fallback counts remote plan
nodes plus coordinator work. Actual bind batches can cause more calls than this
static count. This fallback is a ranking heuristic, not measured latency.
Unavailable evidence stays recorded; model confidence never establishes intent.

Both modes use the same cost profile, actions and physical neighborhood. The
initial model proposal and scope confirmation are common costs and included in
the reported estimated total when usage is known. Actual CPU time, tokens, user
calls, remote bytes and execution latency are reported independently.
The current search does not choose whether to call the initial LLM or purchase new
statistics: those are future optional actions. Do not claim saved LLM/probe calls
from a workload in which they are common or absent.

T6's `execution_cost_feedback=False` zeros execution estimates only in policy
backup; per-candidate physical estimation/ranking remains enabled. It implements
the approved feedback ablation rather than reverting to the historical worker.

## 6.4 Bounded feasible-first AND/OR search

```text
build bounded candidate scope from public proposals/domains
pay for authoritative scope confirmation; stop explicitly if absent/false
search(state):
    check terminal certificates before generating information actions
    lazily prepare/cache certified candidate plans; keep a feasible incumbent
    if needed, try a full clarification as the feasible-policy seed
    for bounded alternative actions:
        admit ALL declared outcomes atomically within remaining budgets
        construct a feasible continuation for EVERY outcome
        compare action cost + worst-outcome continuation with the incumbent
    spend remaining allowance on certified terminal/physical improvements
    return best discovered COMPLETE policy, else safe non-answer
follow actual paid replies through that policy; execute one final plan
```

Terminal-first describes the order of checking. With the joint objective, finding
one certified terminal does not prove that its estimated cost is best; further
bounded estimated improvement may be worthwhile. No future private reply is read
while building symbolic branches. Optional work cannot replace a complete
incumbent with a partial AND subtree. A preparation failure is not hidden.

Let K be admitted candidate count, L the bounded query/coordinate representation,
S the global retained-state cap, A the global action cap, and F the physical
candidate cap per semantic candidate. Scope/distance construction costs
O(K² L). Terminal checking is bounded conservatively by O(S K² L), action
partitioning/backup by O(A K L). Physical preparation costs O(K F C), where C is
the polynomial cost of compiling/scoring one admitted bounded program. Query
parsing, snapshot hashing and frozen-estimator loading are polynomial in their
explicit bounded inputs. Search state, depth, action and outcome limits are global,
not exponentially reset at each recursive level.

The physical placement neighborhood contains the minimum-call seed plus each
single-operator replica deviation: P = 1 + sum(r_i−1). Its strategy construction
bound is P × (1 + 2J + B + I_progressive), checked against F before construction.
It does not enumerate the full Cartesian placement or join-order space. Baseline
compilation is retained if optional generation/scoring reaches its cooperative
planning deadline. This is a bounded polynomial heuristic with no global optimum
or approximation-ratio guarantee. `root_gap=null` means unproved, not zero.
The bounds concern planning, not arbitrary database execution or external latency.
A feasible policy is conditional on admitted inputs, adequate budgets and working
backends; no planner can promise an answer for unsupported/inconsistent inputs.

## 6.5 Memory, storage and reproducibility

The scheduler retains root rows and releases intermediate relations using the
existing audited retention policy. Current backend recording uses `retain_payloads=False`
and streams JSON to level-1 gzip instead of creating a second whole-response JSON
string. Records carry compressed and logical SHA-256/length; replay verifies both.
Buffering is bounded apart from individual JSON scalar encoding and the input
result object. This does not turn the backend parser into a streaming row engine;
large result objects still exist in memory and need response/runtime budgets.

The source observer also streams gzip to disk and replays logical bytes downstream.
Accounting still measures original source traffic, not the smaller stored artifact.
Compression consumes CPU; its measured effect is reported separately. New workers
compress core/answer artifacts as well. Old raw replay schemas remain readable;
strict source/model/profile identity checks are not weakened to pass old fixtures.
Study-wide disk/memory censoring retains its primary reason even when terminating
a worker subsequently causes a transport error.

The current batch driver (`scripts/run_bounded_joint_batch.py`) consumes an ordered
pinned manifest. Its output pins the clean source commit, locks concurrent entry,
and records a cell intent before each worker. Resume skips successes, failures and
incomplete intents; it reports these separately. A missing resource-closure receipt
blocks automatic resume. Serving copies are owned and closed; only successful
phases may reuse a session. The concrete cache/order protocol belongs to Chapter 7.
The scorer currently parses bounded JSON in memory (512 MiB evidence-read ceiling);
this is not a guarantee that large-result scoring fits every RAM budget.

## 6.6 Review and writing boundaries

Use the current API and this map for Chapter 6. The three historical controllers
are isolated under `xgap.legacy`; thin old-path imports retain compatibility.
Shared compiler/runtime modules remain current. [Legacy inventory](legacy_inventory.md)
records the boundary. Prototype engineering gates are not comparative evaluation.
The user explicitly adopted the [20-figure plan](research_experiment_plan_20260920.md).
Dataset admission and development pilots now precede formal sample/budget freezing;
the current implementation and readiness evidence do not constitute formal results.
