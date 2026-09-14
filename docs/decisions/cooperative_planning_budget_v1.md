# Check optional planning work between construction and scoring steps

2026-09-15. The strong search previously checked its deadline around a domain
callback. One callback could eagerly construct an entire optional physical domain
and score it before yielding again. The existing polynomial caps still applied,
but tight performance-mode time budgets could not stop that unnecessary work.

Scope: optional source/strategy construction, progressive composition, estimation
and strong-domain handoff. No new query semantics, data, estimator weights,
candidate ordering, baseline algorithm, source call or formal experiment change.
The question is whether an expired optional budget stops further work while
preserving a usable complete policy. This is a controlled development gate, not a
measurement of aggregate performance-mode superiority.

The practical entry attaches one CooperativePlanningBudget immediately before
strong search. Check before optional local-replica compilation, each placement,
candidate feature/serialization construction, anchor targets, join directions,
progressive rewrite directions, plan normalization and each cost prediction.
PlanningBudgetExpired is distinct from unsupported-source/strategy exceptions;
it unwinds optional construction rather than repeatedly attempting other placements.
Legacy calls without a checkpoint retain the same candidate domain and serialization.

Construct the first feasible baseline without interrupting it halfway. If its
atomic construction consumes the budget, retain that complete plan and skip
optional estimation, recording planning_budget_exhausted with an unknown score.
After the baseline has been yielded, an interrupted optional domain cannot erase
it. During scoring, retain the best completed estimate and stop before the next
prediction; a completed better plan survives even if its own atomic prediction
used the last available time. An unfinished composed plan is never published.
No candidate execution/probe occurs in this process.

All selected AND outcomes still require complete continuations. This adds no
early partial-branch acceptance and no hidden query fallback after execution.
The global strong search retains its original state/action/terminal limits and
monotone estimated incumbent choice. Checkpoint count and whether expiry was seen
are recorded separately from its stop reason.

This remains cooperative, not hard real-time: an individual compiler, normalizer,
serializer or frozen-model prediction cannot be preempted here. Overshoot can
include that atomic operation and the work needed to seal/return the incumbent.
The existing whole-request process guard supplies the separate external wall/RSS
boundary. Do not describe a500ms planning setting as an unconditional500ms OS-level
guarantee. The finite input and candidate bounds remain the Ptime argument.

Additional checks are linear in the existing local alternatives/placements/
candidate/target/join visits, so asymptotic polynomial time/space does not grow.
No global-optimality certificate, runtime ratio or discrepancy bound is added.

Acceptance: six focused cases with a controlled clock, explicit finite test
estimates and actual tiny in-process SPARQL. Both modes preserve a baseline after
atomic compilation exhausts time, skip estimation and return bag count14 with one
source call. Optional construction stops after the first completed candidate;
an already scored5-unit candidate survives after an initial100-unit feasible plan;
progressive cancellation leaves its input untouched; unexpired/no-checkpoint
legacy domains agree. One affected complete ordinary-entry replay also passes.
Test scores are fixtures, not new model training or observed physical latency.
