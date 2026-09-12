# One-shot two-mode research prototype — approved contract v1

Approved by the user on 2026-09-12. This decision supersedes historical pause,
mandatory clarification, same-meaning-only joint selection, and online full-plan
probing priorities **for this new explicit profile**. Existing v1 APIs and frozen
results retain their contracts. This document defines implementation targets;
acceptance evidence is recorded separately, not inferred from a written design.

## Research scope

RQ: Can bounded joint interpretation and federated physical planning, guided by
frozen estimates and an explicit information budget, improve the measured
accuracy/total-online-cost tradeoff across heterogeneous graph sources?

The proposed contribution is the coherent joint decision, not catalog building
or testing all plans. Effectiveness measures answer EM/F1 and successful completion
with failures in the denominator. Efficiency measures total online latency,
planning latency, tokens, backend calls and exchanged logical bytes. Scalability
varies source/data size, program size and interpretation budget within the declared
profile. A speedup or global Pareto claim is not established by engineering tests.

## One request, two actual modes

The common entry accepts an explicit precision or performance profile. It reads
frozen resolution/statistics/model artifacts, makes at most one bounded top-K
interpretation request, resolves admitted candidates within its local information
budget, generates legal physical strategies, predicts their costs, selects one
interpretation/plan, and executes that final plan once. Multiple backend fragments
belonging to this plan are allowed. Default online PROFILE, full-plan acquisition,
automatic repair, retry, execute-all-and-pick, and mandatory clarification loops
are absent. Missing capabilities produce a terminal typed failure.

Initial defaults (versioned configuration, not proven optimal hyperparameters):
precision K=3, performance K=1; absolute interpretation cap=8. Precision may spend
more on catalog/ontology evidence and quality preference; performance may truncate
retrieval/candidate coverage and choose an uncertain interpretation. Approximation
must appear in the answer trace with its scope and assumptions. A successful
execution is not a claim of gold correctness. Parse/backend errors are never
renamed approximate answers. Explicit request hard constraints and requested
output contracts remain binding; predicted meaning and recall may be imperfect.

No new universal semantics are required. Reuse supported semantic Match, Traverse,
Filter, Project, Join, Union, Aggregate, OrderLimit and Align forms and existing
capability admission. Limit a program to 64 operators; enforce existing finite
path-expansion work <=4096 before compilation. Backend and strategy-specific
unsupported combinations are reported explicitly. New profile caps for holes,
local options and calls must be finite and serialized. Do not truncate the actual
query result or change operator truth conditions merely to meet a planning budget.

## Strategy, estimator and selection

A strategy is an executable physical DAG over the same admitted semantic program,
including legal independent reads/coordinator joins versus bound remote filtering.
It is not an alias for equivalent source replicas or a hand-written query ID.
A finite declared strategy family and bounded polynomial placement rule define
the search domain. No Cartesian expansion over local choices is allowed.

The frozen estimator consumes typed features of the **actual runtime plan** and
versioned source statistics. Fitting and collection are offline. Prediction may
use empirical/fitted models, with training identity, feature schema and limitations
visible. Toy fitting verifies mechanics, not real calibration or generalization.
Missing features/costs are explicit, not zero observations. Historical held-out
results do not silently become training data. Runtime never fits on the current
question or runs alternatives to obtain its estimate.

For each admitted interpretation i, choose p_i minimizing estimated execution cost
within its admitted physical candidate domain. Joint ranking uses a configured
cost/quality objective (e.g. estimated cost + lambda*(1-quality_proxy), with finite
lambda and documented unknown-quality handling). Both modes share this selector;
their information budgets and quality preferences differ. A model confidence is
an uncalibrated quality proxy until separately validated. Information already
acquired for the request is charged once to total online cost, not once per plan.

If K interpretations have at most S polynomially constructed strategies and each
compile/predict costs C(m)+E(m,N), ranking is O(K*S*(C+E)), plus polynomial grounding
and validation. Report the actual construction bound as implemented; a cap alone
is not a proof of solution quality. Argmin is exact only over the admitted estimated
candidate domain. Under a uniform cost-estimation error <=eta in that domain,
selected execution-cost regret is <=2eta. For joint objective error <=delta the
analogous regret is <=2delta. These assumptions are not yet established empirically.
No universal approximation ratio to arbitrary physical plans or true latency is
claimed. A nondominated predicted candidate subset is only a proxy frontier;
measured answer-quality/latency frontiers belong to later evaluation. Old fixed-DAG
monotonic lower bounds do not automatically apply to a learned estimator/new DAG.

## Implemented first neighborhood and explicit limits

The current ordinary-entry profile admits k_i local backends for each source.
Its baseline chooses a minimum-call feasible local backend per source with stable
ties; each alternative changes exactly one source relative to that baseline.
There are P <= 1 + sum_i(k_i-1) placements. For J joins, each placement compiles
a coordinator strategy and each legal single entity-bind rewrite, at most 1+2J.
The complete declared construction bound is P*(1+2J); an over-budget domain is
rejected before building it. This is a bounded **single-change neighborhood**,
not a claim to search arbitrary join orders, combined rewrites or every placement.

The implementation scores all available predictions in this domain, so its
estimated execution cost cannot exceed its baseline's estimate when that baseline
has a compatible estimate. Among the scored candidates it is exact. The 2eta
cost-regret statement follows from C(selected) <= Chat(selected)+eta <=
Chat(optimum_in_domain)+eta <= C(optimum_in_domain)+2eta; it gives no bound on
plans outside this neighborhood. Current source/statistics mismatch and unknown
estimates are explicitly excluded from the scored domain with recorded reasons.

Construction/selection costs O(K*(L*C(m) + P*(1+2J)*(C(m)+E(m,N)))) plus local
grounding, where L=sum_i(k_i), K<=8 and N<=256 frozen training records. Grounding
chooses one catalog-backed binding per hole without combining all hole choices.
The existing expansion<=4096 and64-operator profile precedes lowering. Native
query execution and LLM inference are bounded external actions, not claimed to
have the planner's Ptime complexity.

Frozen ridge regression currently uses typed DAG/parallelism/dependency/source
size features. Training is real fitting, but first integration checks use analytic
toy labels; arbitrary predicate selectivity and real transfer/generalization are
not established. Source ID and snapshot version must match the model. Precision
uses K3/catalog64/ontology fallback/quality_penalty1000ms; performance uses K1/
catalog8/no ontology/quality_penalty0ms. Unknown quality staysnull with a declared
0.5 ranking fallback. These are initial settings, not empirically optimized ones.
A provider's pinned wire cap must match its mode before any model call.

## Cost and evaluation boundary

Separate offline catalog/index/statistics construction, training/collection and
online interpretation/grounding/planning/final execution/persistence. Report
one-time costs and amortization as offline_cost/Q, alongside raw online numbers;
do not label one-time construction as per-query work or hide paid preparation.
Unknown token, network or wall accounting remains unknown. Keep logical exchange
bytes distinct from actual wire traffic. Save failed responses once for replay.

Until the coherent ordinary entry passes its small vertical slice, do not launch
new ablations, baseline comparisons or scale sweeps. Use tiny development graphs
and independently specified NL -> gold program -> expected plan/query -> answer
contracts for the affected operators, with interpretation and deterministic chains
separately inspectable. Reuse prior accepted evidence instead of rerunning it.

After core freeze, discuss 16–20 figures with explicit RQ, X, Y, population, cost
boundary and external SOTA comparators in the same comparable plots. Internal
variants are ablations, not the whole baseline roster. Existing FinBench negative
results, original48 exposure/splits, LINK3/5, GrailQA150 not-run and every historical
failure remain unchanged. They are not new two-mode XGAP evaluation results.
