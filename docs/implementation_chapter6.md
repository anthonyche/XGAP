# Chapter 6 implementation map — unified lookahead v1

2026-09-22 numbering note: this filename is retained for existing links. The
user's current Chapter 6 is the [experimental study](ch6_experiment_plan_20260922.md);
this document remains an implementation map, not the new chapter outline.

External baseline update: ARUQULA→FedX now completes tiny single/two-source NL
execution with disclosed serialization and tool compatibility. Both answers are
wrong and remain unchanged. Its worker is now connected to the five-method batch
dispatcher; the shared-question gate retained an external harness-budget cut as
study-censored, not an incorrect answer. See the
[shared batch evidence](report/ch6_five_method_gate_20260923.md).

2026-09-21. This maps the admitted implementation to the revised manuscript.
2026-09-22 follow-up: optional deadlines retain fully scored root incumbents with
all outcome reserves; bounded request-local caches avoid repeated proof/seed work.
[Real engineering evidence](report/ch6_planner_external_followup_20260922.md) includes
a changed interpretation and lower answer F1, not a same-query universal speedup.
Current entry: `xgap.api.answer_unified`; algorithm contract:
[unified migration](decisions/unified_lookahead_migration_20260921.md).
The [readiness report](report/unified_prerelease_20260921.md) separates implemented,
actually exercised and still unsupported capabilities. The prior full-policy
implementation is [preserved here](implementation_chapter6_history_20260921_before_unified.md).

## 6.1 Interfaces and admitted semantics

|Step|Implementation under `src/xgap/`|Boundary|
|---|---|---|
|NL proposal|`llm/compact_interpretation.py`|One compact-model call, no hidden repair; development template separately labelled|
|Candidate family|`semantic/intent_scope.py`|1–8 proposals; default 64 complete candidates, explicit capacity ceiling 1024/32 coordinates; bound checked before Cartesian expansion; large-N formal inputs still need admission|
|Representation identity|`semantic/compact_identity.py`|Bounded role refinement and renamed AST equality; literal/direction meaning unchanged|
|Scope authority|`agent/scope_authority.py`|Question-bound private query; paid containment; no free selected candidate|
|Mandatory validation and loss|`agent/unified_contract.py`|Direct registered evidence, independent Lambda and epsilon; bounded certificate cache|
|Online search|`agent/unified_lookahead.py`|Fixed D, all declared outcomes, one actual action then replan|
|Domain and completion|`agent/unified_family.py`|Protected seeds, bounded plan pools, nonrecursive completion estimate/reservation|
|Physical changes|`runtime/unified_physical.py`|One checked transformation per action, no alternative-plan executions|
|Information tools|`agent/unified_information.py`|Pinned scalar metadata/probe artifacts and exhaustive finite categories including unknown|
|Costs|`planning/joint_cost.py` plus domain score|Frozen model/fallback plus declared information work units|
|Compiler/runtime|`semantic/compact_lowering.py`, `compilers`, `runtime/scheduler.py`|Cypher/SPARQL, coordinator operations, one final dispatch|
|New configuration/methods|`experiments/unified_contract.py`|Distinct NL/controlled tracks; no mixing legacy mode controls|
|Durable worker|`experiments/bounded_joint_worker.py`|Versioned dispatch, compressed core/answers/captures, no reference rows|
|Batch and scoring|`common_method_trial.py`, `common_row_score.py`, `query_loss_score.py` in `experiments`|Code/input pins; post-seal scoring; no repeating attempted cells|

The compact grammar admits at most 8 node variables, 12 explicit edges,
32 predicates, 16 output expressions and one directed bounded path of 1–3 hops
(WALK or ACYCLIC). It supports connected typed patterns, property/time comparisons,
sum/count/min/max, declared contribution/deduplication, ordering and explicit
bounded limits. Actual compiler/capability checks may reject a syntactically valid
query. This does not expand the audited [operator semantics](operator_semantics.md).

Candidates use explicit business IDs/literals or frozen finite alternatives and
share one fixed query skeleton. Arbitrary named-entity holes or unrelated candidate
topologies are outside this entry. Cartesian and proposals-only support remain
separate declared constructions. Neither may truncate uncertainty to pass a cap.
A host domain is a bounded computational support, not a proof of arbitrary NL
coverage. Only the paid authority can confirm containment.

## 6.2 Validation is separate from interpretation loss

For an actual state s, Q(s) contains all queries consistent with observed binding
replies. Current d is exact rational weighted coordinate discrepancy: any hard
coordinate disagreement is infinite, otherwise use normalized soft-coordinate
Hamming distance; all fixed fields match by admission. The implemented certificate
is `rho(q,s) = max_{q* in Q(s)} d(q*,q)`.

An eligible query needs confirmed coverage, every designated validation outside
Lambda, consistency and `rho <= epsilon`. Singleton support or epsilon=0 does
not discharge a missing validation. Hard-coordinate conflicts remain ineligible
even if a requirement is named in Lambda. This profile admits direct authority
only, not arbitrary inference rules. Controlled initial clues require an explicit
publisher attestation and retain the full family/loss denominator.

This is a conditional interpretation-loss guarantee over a confirmed finite
family. It is NOT an output answer-error, result-F1, probability-of-error or
open-domain semantic guarantee. Independent answer/query-loss scoring happens
only after execution evidence seals. Private answers never enter planning.

## 6.3 State, local transformations and information

The actual domain state records checked bindings, disclosed-coordinate count,
finite information categories and plan-pool keys. A bounded registry stores each
plan once. Protected seeds are never evicted by optional search, and removing an
optional plan never removes its interpretation from the loss calculation.
The coordinator additionally tracks completed steps, spent resources and attempts.

Supported local actions each perform one change:

- One source replica substitution with equal schema/namespace/version and an
  unchanged native fragment.
- One exact read contraction or compiler-proved projection-sharing contraction.
- One necessary native row prefilter, preserving full query filters.
- One bounded entity-bind restriction at an exclusive acyclic inner join,
  preserving the original join and all answer semantics.

This is a polynomial local neighborhood, not all placements/join orders. Physical
seeds are compiled before eligibility so later validation cannot leave a query
with no protected route solely because optional generation consumed its allowance.
General missing mandatory-capability discovery is not implemented: admitted seeds
rely on frozen configured capabilities. A failed seed is recorded, not silently
removed from semantic support.

Named metadata/probe targets are frozen host registrations tied to source/backend
versions. Only a selected target is invoked. A single scalar response maps to a
fixed category; errors/malformed responses become explicit unknown where the
contract permits. Categories change a declared cost model or gate optional rules;
they never establish user intent or replace compiler capability proofs.
Estimate caches depend on relevant target identity/category; unrelated receipts do
not invalidate them. An unchanged unknown outcome does not authorize the same
probe again. Frozen candidate priors and target probabilities are required for
expectation; no uniform prior is silently invented.

## 6.4 Online planning and completion protection

```text
prepare bounded family and protected seeds; record initialization separately
for at most H nonterminal actions:
    check actual terminal eligibility
    construct/check a compact completion recipe and resource reservation
    compare eligible terminals with depth-D symbolic actions
        every declared outcome must preserve a completion recipe
        leaf score includes remaining mandatory work and final execution
    if optional limit reached: select saved completion's first action
    if Execute chosen: recheck actual state/snapshots; execute once; return
    perform only the chosen action; validate response and actual spend; replan
at H: execute an eligible terminal, otherwise explicit non-answer
```

The leaf heuristic is the cost of one coherent bounded completion routine,
separately recording remaining validation, capability/plan work where applicable,
and execution. Here protected seeds and known capabilities exist at entry, so
that continuation needs authoritative disclosure followed by a retained plan.
Its calculation scans the explicit family; it does not recursively search all
possible validation policies.

Before an optional action, the controller checks its cost-independent certified
resource consumption plus the completion reserve for EVERY outcome, including
unknown and probability-zero outcomes. Remaining-step rank decreases along the
saved routine. On an optional deadline/state/record cap, the protected routine
remains executable without another optional search. Small terminal enumeration
caps cannot erase its direct terminal check. Execute wins cost ties.

The protection is conditional on truthful normal replies, unchanged snapshots,
sound resource bounds and supported execution contracts. It prevents optional
work from consuming a KNOWN feasible route. It does not establish feasibility
for all inputs, global optimality or a whole-policy approximation ratio.
`strong_plan=False` and `root_gap=null` are intentional: a D-step decision is not
a materialized full strong policy or a proven optimality gap.

For fixed D, coordinator work is bounded by
`O((H+1) * sum_{j=0..D} (A*Delta)^j * T_local)` plus bounded initialization.
H, actions A, outcomes Delta, candidates, plan pools, arithmetic representation
and local compilation/rewriting/certificate work must remain polynomial in
explicit admitted input size. Merely finite but input-growing D is insufficient.
No recursive horizon search is hidden in the completion heuristic. Cooperative
wall/state/byte guards are additional safeguards, not a proof about arbitrary
callbacks, remote execution complexity or preemption.

Current defaults/caps: D=1 (accepted 1–4), H=16 (0–64), 4096 expanded states
(max 8192), 128 actions/state (max 256), 64 outcomes/action and terminals/state
(max 256), 4 retained plans/query (1–16), 1024 registry plans (max 4096), 32 MiB
canonical plan representations (max 256 MiB), 1 MiB/plan, at most 16 information
targets with at most 10 categories each. Certificate/estimate/move caches are
bounded to 1024/4096/128 entries. Registry byte size is serialized representation,
not measured Python heap. Optional deadline defaults to 1000 ms per decision;
initialization, fallback checking, local actions and whole request need separate
measurement and outer worker budgets.

## 6.5 Costs, resources and observed evidence

A terminal is scored by estimated execution work. An action is scored by its
declared work plus the request-fixed max or expectation of child values. Every
outcome must remain feasible even under expectation. A rank-only model can order
plans; comparing acquisition with execution additionally needs declared common
numerical units. No regression to milliseconds is required. Uncalibrated priors,
row estimates and prices must be labelled as assumptions, not measured facts.

The opt-in Chapter 6 source-work ranker uses frozen complete source populations;
v2 additionally separates relation/direction endpoint degree moments. Singleton
and multi-key fanout use mean and size-biased mean proxies respectively. No
current-query trial execution or answer participates. Unknown many-to-many joins
are no longer assumed to preserve the larger input's row count. These estimates
are relative work, not milliseconds or hard resource certificates.

One checked physical move can reduce an existential degree-one leaf to one
jointly satisfying witness per bound retained endpoint. It requires that both
the edge and leaf disappear at the explicit contribution projection and that
all their predicates are evaluated before representative selection. It declines
unbound retained-variable dependencies and unsupported property/path cases.
Cypher uses a correlated per-key subquery; RDF uses capped singleton UNION
branches with a whole-request byte bound. Output cardinality is bounded by sent
keys, but adjacency scan work remains estimated. RDF leaf-property guards use
a correlated existential test: their scalar is not projected. This prevents
ARQ filter placement from splitting the edge-to-leaf connection and evaluating
an endpoint-adjacency / global-property Cartesian prefix. Missing properties
do not qualify; multiple values require one jointly satisfying value.
The online controller selects
one plan from symbolic estimates and executes it once.

Only actual actions are charged to `realized_acquisition_cost_estimate`.
`selected_execution_cost_estimate` remains a prediction; the NL report's
`realized_trace_work_estimate` combines actual-path declared work, observed common
usage priced in those units, and that prediction. These are not money or observed
end-to-end time. Unknown failed-action costs remain unknown.

Report separately: model requests/tokens, scope/clarification, metadata/probe calls,
physical actions, initialization, planning wall/CPU time, certificate time, selected
local-action time, acquisition wait, final execution time and request latency.
Certificate time overlaps its owning phase; do not add it twice. Source observer
HTTP counts/bytes are actual traffic; static plan nodes/adapter calls are different
units. Hypothetical branches make zero external calls.

The family adapter reserves online authoritative/remote adapter calls with the
current one-invocation-per-remote-node scheduler; bind overflow fails explicitly
before another hidden batch. It does not certify final rows, transfer bytes or
peak memory. Those quantities remain unknown and cannot admit a finite hard
completion bound. Runtime/process/response guards still cap attempted work, but
may stop it without an answer. Initial model/scope/seed work is outside the online
resource ledger and is included separately in whole-request usage/timing; online
reservation is not a whole-request resource guarantee.

## 6.6 Storage and experiment boundary

The shared runtime releases intermediate rows and keeps required root results.
Captures, core and answer files use lossless gzip with logical/stored hashes;
source transfer accounting uses uncompressed bytes. This avoids duplicate large
serialized payloads, but backend parsers still materialize result objects and
scoring reads bounded JSON. It is not an unlimited streaming execution engine.

Historical internal method IDs add `xgap-unified-two-stage`, `xgap-unified-no-probe`,
`xgap-unified-shallow`, `xgap-unified-myopic` to `xgap-unified-lookahead`.
The old `xgap-unified-sequential` still means full validation and is historical.
Configuration v2 adds information/action objectives; strict v1 loading preserves
the old defaults. Manifest remains `xgap-unified-lookahead-batch-v1`.
The internal two-stage diagnostic stops at common semantic eligibility, selects a candidate by ID and
then runs the shared physical stage. No execution cost enters semantic ranking;
execution resource reservations still apply. `ch6_direct.answer_direct` reuses
the physical domain and online controller with an unvalidated fixed proposal;
it cannot issue an intent certificate or clarify. Its batch adapter is implemented
but excluded by the latest user correction. Neither internal method represents
the paper's external Two-stage. See [current definitions](decisions/ch6_external_twostage_20260922.md).
NL and controlled tracks remain distinct and hidden references stay offline.

Batch execution pins clean source/config/data, records intent before effects,
compresses artifacts, scores after sealing and skips every attempted cell on
resume. Failed/incomplete attempts remain visible. Owned services must close
before reuse/resume. Catalog/data/estimator creation remains offline and frozen.
The current tiny admissions prove these interfaces, not comparative effectiveness
or scalability. Full dataset/method admission and the revised Chapter 7 release
remain separate gates.


### 单边 RDF 编译中的正向标签条件（2026-09-23）

针对 reified one-edge Match，正向原子类型/标签检查编译为固定宾语三元组，
与端点和边的基本图模式连续合并，重复边标签三元组只保留一次。端点与边变量
已由图模式绑定，RDF 集合中相同三元组至多出现一次，因此与原 EXISTS 语义等价，
不会增加每行多重性。不同标签约束均保留；OR/NOT 与多边编译继续使用原条件编译器。
存在性叶节点的联合 ID 属性条件仍使用相关 EXISTS，避免提前跨接所有节点 ID。
该编译优化不改变候选/估计器选择、不观察当前查询答案、不影响外部 baseline 编译。
