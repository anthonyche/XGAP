# Acquisition search order and unknown cost

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
