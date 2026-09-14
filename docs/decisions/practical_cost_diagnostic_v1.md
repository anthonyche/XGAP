# Fixed small-graph cost diagnosis

2026-09-14, after0f0e888. Scope: one diagnostic script and evidence/documents;
no changes to planner, source engines, frozen estimator weights, baseline or
evaluation population. The user authorized autonomous tiny development and
necessary measurements. This is not a new paper campaign or an ablation sweep.

Existing observations do not establish whether coordinator, first-hop fanout or
progressive binding is fastest: the two executed binding plans came from separate
fresh service sessions. Full source calls clustered around984ms in the old
session; first bound calls around1047ms in the new session. Source-node durations
overlap and must not be summed as the query wall time. The model's ranking must
not be declared wrong from those unpaired observations or millisecond error.

On the separate live-slot request, information acquisition497.617ms dominates
the812.198ms request; strong search46.093ms accounts for about5.7%. Holding all
other costs fixed, eliminating that search saves at most that observed fraction.
This is a local accounting implication, not a measured speedup guarantee.

## Frozen question, factors and procedure

The existing8-node/16-relation tiny graph and first `compact_anchor_v1` gold
program are fixed. The factor is one of three existing complete physical plans:
coordinator, anchor_fanout_bind, progressive_entity_bind. Outcomes are wall time,
source calls/response bytes, per-node work, and exact normalized answer rows.
The frozen estimator's scores and all plans are sealed before source execution.

Use one fresh owned Neo4j/Fuseki serving copy from the same pinned prepared stores.
Execute exactly this sequence, stopping on a failed call/answer/resource closure:

1. First exposure: coordinator, anchor fanout, progressive binding.
2. After all three first exposures: progressive binding, anchor fanout, coordinator.

Each cell executes once and records every actual call. Maximum6 plans/96 source
calls,16 calls per phase,20s native query timeout,120s per phase and600s process
deadline. No model calls, fitting, runtime catalog build, data reload, hidden
retry or candidate selection based on observations. First-exposure costs remain
visible and separate from the second sequence. This does not guarantee every
engine state is warm, eliminate order effects or estimate a population mean.
One second-sequence observation per strategy supports only a descriptive local
comparison. No significance, confidence interval, overall/SOTA or global-optimum
claim. The ordinary planner does not consume this diagnostic's winner or labels.

Default script operation is offline preflight, checking bounded construction and
frozen scores. The explicit native operation follows only after preflight passes
on committed code. Services close in a finally block, preserving captures and
discarding only owned reconstructable serving copies. A recording or native
failure remains sealed and is diagnosed offline; no automatic rerun.

Accept when all six predeclared cells have durable outcomes, independently
specified answers match, usage reconciles and owned services are terminal. The
experiment can complete even if progressive is slower or the frozen rank is
wrong. Afterward use the observations to identify the next engineering risk;
do not outcome-tune the current model. Formal mode/estimator evaluation still
requires the approved experiment-release protocol and a held-out population.
