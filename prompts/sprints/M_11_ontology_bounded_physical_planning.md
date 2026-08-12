# M11 Ontology-Bounded Physical Planning

Implement M11-A through M11-D in order while preserving M0-M10 public
behavior and the existing path/GPC logical vocabulary.

## M11-A

Add frozen, deterministically serializable contracts for physical state,
placement/exchange decisions, complete plans, ontology/alignment evidence,
mapping sufficiency, semantic deviation, objectives, execution observations,
cost predictions, traces, and planner configuration. Add pluggable protocols
for alignment, deviation, features, cost, budget, and physical compilation.

## M11-B

Implement finite best-first branch-and-bound over backend placements and
configured exchange decisions for one fixed logical plan. Charge one budget
unit per processed `ExtractMin`, use lower-bound priority, retain the complete
state with smallest discovered conservative upper bound, and prune when a
lower bound cannot improve the incumbent. Keep deterministic anytime behavior.

## M11-C

Add a versioned positive raw-cost/log-cost observation store, deterministic
state features, a Gaussian-process log-cost estimator, finite-state confidence
bounds, across-task delta allocation, immutable planning snapshots, and JSONL
search traces.

## M11-D

Compose M10 candidates, external alignment, semantic admissibility,
deterministic lowering, bounded physical search, hard execution threshold,
one representative per interpretation, deterministic Nash top K, and existing
M9 compiler boundaries. Add a configuration-driven controlled runner and a
tiny test/experiment-only exhaustive oracle.

## Hard Rules

- Return plans only when `C_bar < T_max`; never relax the threshold.
- Treat `c_sem <= epsilon` as semantic admissibility, but require strictly
  positive semantic and execution utilities for Nash output.
- Missing, unknown, unsupported, or insufficient mapping evidence is never
  successful.
- Ontology/alignment is fixed external context, not a BnB dimension.
- Do not enumerate logical rewrites or claim budgeted search is globally
  optimal.
- Do not extend M9 compiler coverage or fake multi-backend execution.
- Do not implement live LLMs, KGQA, LoRA/training, ontology induction,
  general OWL/DL reasoning, full GQL, new engines, or distributed execution.

## Verification

Run focused tests after every subphase, then controlled demos,
`python -m pytest`, and `./scripts/run_acceptance.sh`. Record actual results in
`docs/status.md`.
