# T3-A: a static physical baseline through the normal question entry

2026-09-11, frozen on73575c7 before implementation. The live-model package
bc2bb67 remains fixed and independent of this next local development step.

Observed gap: the generic run_question -> bound execution -> run_semantic_plans
entry acquires all unique observations unless given a cost snapshot. Existing
static FinBench baselines belong to specialized runners. A same-entry baseline
that makes no planning observations is necessary to test whether acquisition and
selection pay for themselves. A fabricated cost snapshot is not a static policy.

Add an optional explicit backend-priority tuple to this entry. After the normal
capability/semantic compilation, rank admitted placements lexicographically by
that fixed priority in sorted semantic source-operator order. Choose one plan
before dispatch, without reading observations, estimates, timings or answers.
Equivalent placement candidates and semantic meaning are unchanged. Backend
priorities must cover the admitted backends; conflicting snapshot/static input
fails before backend calls. Record the chosen policy and selected plan, leaving
cost estimates unavailable. Existing costed selection stays the default.

Both methods use the same resolution, hard constraints, candidate enumeration,
compiler and executor. Static selection changes physical placement only; it is
not semantic relaxation, post-failure fallback, memory learning or a new optimizer.
An execution failure remains terminal without selecting another backend.

Allowed scope: semantic_planning selection, optional agent-entry plumbing,
toy experiment invocation, focused tests and the existing native harness.
No algebra/compiler rewrite, new graph/gold/catalog, new general experiment
framework, prior FinBench/GrailQA protocol/population change or server run.

Acceptance: same admitted plan space and independent answers; priority changes
placement without observations; invalid policy or mixed meanings stops before
dispatch; execution failure keeps actual calls with no fallback. Exercise static
question entry on B01–B05 and independently verify native Neo4j/Fuseki answers,
including unavailable replica admission. Run focused tests and one final broad
gate. Tiny timings are diagnostics, not speedup evidence. Real-model/native
connection and frozen real-data baselines remain the next external gates.
