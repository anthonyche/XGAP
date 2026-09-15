# Acquisition search order and unknown cost

## Strong search amendment — 2026-09-15

The strong-only view now orders retained actions by known estimate, estimated
milliseconds, declared priority, then stable ID. When all costs are unknown,
the original priority order remains. Estimates participate in the existing
acquisition-plus-worst-outcome terminal score; they are not probabilities or
latency guarantees. Root improvement and all AND continuations retain their
original budgets. O(M log M) ordering and O(M) storage remain polynomial.
No optimality or approximation ratio follows from this heuristic order.

The underlying domain's declaration order and fixed external frontend remain
priority-first as below. In particular a baseline configured model-before-authority
keeps that sequence even when the recorded authority estimate is lower. This
amendment changes XGAP's own planning, not an author's baseline result.

Actual development costs are measured separately under the
[cost-basis contract](practical_information_cost_basis_v1.md). New cost values
must cite their sample, observation scope and uncertainty. Do not use arbitrary
rank values as milliseconds or tune from evaluation answers. The prior all-null
profiles and their captured results remain unchanged.

## Original declaration order and historical gate

2026-09-14. Implements the approved brief's distinction between default search
order, semantic authority and actual cost. This extends the practical strong
profile; it does not change the legacy one-shot/baseline paths.

`BindingAction.search_priority` is a frozen integer in [0,4096]. Sort by priority,
known-before-unknown estimate, estimate and stable action ID. The existing default
priority 0 preserves prior numeric-cost ordering. The old default 1ms estimate
remains only for interface compatibility; new profiles must explicitly provide
an independently prepared estimate or null, never a fake cost to force selection.

Acquisition estimates may be null. Any AND policy containing an unknown action
or child cost has a null estimated score. Such a policy is still eligible when
feasible; it cannot numerically displace an incumbent with a known score. Priority
changes search order, not the semantic admission or the cost backed up at a node.
Reports serialize the complete action specifications, order, actual observations,
reserved resource counters and separate actual costs.

The same-request tiny gate uses the brief's model-before-experiment-clarification
ordering, no action latency estimates, and zero improvements after the first
feasible root policy. Clarification remains an available root alternative and a
declared continuation for failed/empty model output. This is a declared heuristic
profile, not evidence that LLM is faster than local clarification or cost optimal.
Reordering the profile demonstrably yields the zero-model clarification path.

For M explicit actions, ordering adds O(M log M) comparisons and O(M) storage.
The existing global state/action/outcome/depth bounds and complete-AND induction
remain. No new approximation bound, calibrated intent distribution, discrepancy
metric or global-optimality certificate is introduced.

Development risks checked: both real predicate meanings, multiple/invalid model
responses, authority following proposal in EXACT, absent failure continuation,
unknown action score propagation, and explicit priority reversal. All use the
ordinary question route and real in-process SPARQL with a controlled wire.
