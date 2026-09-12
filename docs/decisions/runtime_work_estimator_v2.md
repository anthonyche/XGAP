# Frozen workload estimator v2 — bounded development contract

2026-09-12. This addresses the efficiency-side core gap observed at 41a3cca;
it does not change the supported query semantics, candidate neighborhood or
historical v1 estimator. Scope: runtime-plan features, a separately versioned
frozen model, loading at the ordinary entry, and independent tiny preparation.
Old source/data/gold/model files and the accepted B01 execution stay unchanged.

User clarification: this is one implemented surrogate, not a requirement that
XGAP accurately regress milliseconds. Relative ordering/preference is sufficient
as an estimator objective under the [selection contract](one_shot_modes_v1.md#selection-oriented-estimation--user-update).
Observed numerical underprediction alone does not establish wrong selection;
the previous feature aliasing and unsupported extrapolation motivated bounded
engineering fixes, not a mandate to optimize time error before core completion.
Keep the frozen model and its measurements intact. Do not rerun fitting or native
gates merely to improve residuals; rank-only integration, if needed, requires an
explicit output/selection contract rather than relabeling an arbitrary score as ms.

The current feature vector aliases two placements that swap Path and Match
between Neo4j/Fuseki. Four Match-only labels also cause unconstrained log-ridge
to extrapolate an eleven-node bind plan to 0.0054 ms. The new risk checks must
distinguish those placements and prevent increasing represented work from
lowering the prediction when other features are fixed.

## Features and prediction

Read typed runtime structure, compiler descriptors and frozen source statistics
only. Associate each remote Match/Path, full/bind invocation and its work proxy
with its actual backend. Include path expansion span, projected width, incoming
bind work and coordinator/exchange work. Query IDs, native query text, gold,
answers, actual rows/times and observed winners are not feature inputs.

Work units are explicitly coarse proxies derived from logical source-record
counts, compiler-described path spans/columns and DAG dependencies. They are
not result-cardinality estimates or guarantees; unknown predicate selectivity
is not filled with an invented selectivity. Missing compiler descriptors or
statistics fail as unavailable. Numeric overflow is unavailable, never zero.

Fit an additive nonnegative model offline using fixed-sweep nonnegative
coordinate descent on relative squared error, with a positive ridge penalty.
Feature scales are positive and there is no mean centering or log-cost
extrapolation. Therefore a componentwise increase of represented work, at fixed
other features/model, cannot reduce predicted cost. This is a property of the
surrogate, not a claim that actual backend latency is monotone.

An unseen remote workload/backend category or coordinator kind is unavailable
until covered by independent training. Numeric features outside their training
range remain explicitly marked; nonnegative extrapolation is permitted but has
no calibrated accuracy/error guarantee. No current-query fit or probe repairs
missing support. Native-query correctness and hard constraints are unaffected.

For total explicit DAG size L, B source entries, N <= 256 training records,
d = O(B + number of runtime kinds) features and a fixed S <= 256 fit sweeps:
extraction is O(L+B), fit O(SNd), and prediction O(L+B+d+N), including provenance.
The fixed iteration bound does not claim exact NNLS convergence. The existing
planner's estimated argmin and conditional 2η regret statement retain their
original candidate-domain/error assumptions; v2 supplies no new actual-latency
bound or global-optimality claim.

## Acceptance for this milestone

Only new-risk checks: swapped backend/workload feature distinction; exclusion
of answer/query-label metadata; nonnegative/visible extrapolation and unseen
category admission; immutable model/loader/split identity; and one affected
ordinary-entry integration. Do not rerun the 64 accepted gates.

Prepare a small, separately declared training workload covering Match, Path,
coordinator join, bind, exchange and both backend assignments. Freeze its IDs,
plans, order, budget and excluded B01–B05 before measurement. Use one bounded
local native collection, with source loading and any warmup separate. Do not
collect the old four Match queries again or use B01's observation as a label.
After fit/freeze, a distinct tiny held-out query can verify one estimated choice
and one final execution; no execute-all oracle or comparison campaign is needed.

Report feature support, residuals, held-out errors, all failures and costs. This
is estimator/core engineering evidence, not effectiveness, speedup or SOTA
evaluation. Missing selectivity and broader workload coverage remain explicit.
