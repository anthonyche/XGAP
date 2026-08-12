# M11 Ontology-Bounded Physical Planning

## Scope

M11 connects M10 structured interpretation candidates to bounded physical
planning while preserving the deterministic XGAP logical core:

```text
PlannerCandidate I
  -> external ontology/alignment resolution
  -> semantic admissibility
  -> deterministic PathPatternQuery lowering L_I
  -> bounded physical search over (placement, exchange)
  -> conservative execution-bound check
  -> one representative per interpretation
  -> deterministic Nash top K
  -> existing M9 compiler or explicit unsupported result
```

Logical compilation is fixed for one interpretation. M11 does not enumerate
logical rewrites and does not alter path/GPC operator semantics.

## Paper Notation And Code Objects

| Paper notation | M11 code contract |
| --- | --- |
| `I` | existing `PlannerCandidate` containing a `PathPatternQuery` |
| `L_I` | existing validated `AlgebraOp` produced by deterministic lowering |
| `s=(L_I, Pi, Delta)` | frozen `PhysicalState` with logical-plan identity, placements, and exchanges |
| `Psi` | frozen `PhysicalPlan`/realization for a complete state |
| `c_sem(I;u,T)` | `SemanticDeviationResult.value` from a pluggable scorer |
| `epsilon` | `PlanningConfig.semantic_threshold` |
| `C_bar(Psi)` | `CostPrediction.upper` |
| `T_max` | `PlanningConfig.execution_threshold` |
| `B` | budget returned by a `BudgetPolicy` |
| `S_Nash` | `ObjectiveScore.nash_score` |

Operator identifiers and state identifiers are derived deterministically
from logical-tree positions and canonical JSON. Python object identity is
not part of the public physical-state identity.

## Public Interfaces

M11 defines driver-independent protocols for:

- `OntologyAlignmentProvider`: resolves versioned ontology, schema, mapping,
  alias, and alignment evidence for one interpretation;
- `SemanticDeviationScorer`: returns an explicit semantic-deviation result
  from the fixed interpretation and alignment context;
- `StateFeatureExtractor`: extracts a deterministic versioned feature vector;
- `CostEstimator`: predicts log-cost mean/uncertainty and conservative raw-cost
  bounds from one immutable model snapshot;
- `BudgetPolicy`: assigns a finite physical-search budget;
- `PhysicalCompiler`: maps a complete physical state to existing M9 artifacts
  or a structured unsupported boundary.

Controlled artifact-backed implementations support deterministic tests. They
are fixtures for the interface, not ontology reasoning.

The implementation is under `src/xgap/planning/`:

- `contracts.py` and `protocols.py`: public records and replaceable boundaries;
- `topology.py`: stable indexing of existing logical-plan occurrences;
- `ontology.py`: controlled versioned artifact adapter and supplied scorer;
- `search.py`: bounded deterministic physical BnB;
- `features.py`, `cost.py`, and `trace.py`: state features, observations, GP,
  confidence utilities, and JSONL trace persistence;
- `compiler.py`: adapter to the unchanged M9 compiler surface;
- `planner.py`: main admissibility/search/Nash/top-K composition;
- `oracle.py`: test/experiment-only exhaustive enumeration.

## Physical-State Contract

A physical state contains:

- the deterministic identifier and stable topological operator order of
  `L_I`;
- zero or one backend placement for each logical-operator occurrence;
- explicit exchange decisions for every dependency whose endpoints are
  placed on different backends;
- deterministic completeness and state identity metadata.

Placements are permitted only when the selected M8 profile can support the
operator's existing XGAP path/GPC feature. Cross-backend dependencies require
an exchange strategy supplied by configuration. M11 adds no exchange logical
operator and no distributed runtime.

A complete planning artifact may therefore be physically describable but not
currently executable end to end. Existing M9 compilation coverage and
cross-backend runtime gaps are reported explicitly.

## Ontology And Alignment Boundary

Ontology and alignment inputs are external and versioned. The provider result
records artifact identifiers/versions, ontology terms used by the
interpretation, source mappings, aliases, evidence, and a four-way mapping
sufficiency status: sufficient, insufficient, missing, or unsupported.

Only `sufficient` evidence enters physical search. Unknown evidence never
defaults to success. The ontology context is fixed for an interpretation's
search tree; `BnBSearch` cannot enumerate or change interpretations, ontology
terms, mappings, or deviation rules.

## Search Semantics

M11-B uses deterministic best-first branch-and-bound:

1. `OPEN` is ordered by predicted lower cost and deterministic state ID.
2. One budget unit is charged for each processed `ExtractMin`.
3. Placement decisions follow stable topological operator order; exchange
   choices follow stable dependency and strategy order.
4. The first feasible complete state initializes the incumbent.
5. A later complete state replaces it only when its conservative upper bound
   is strictly smaller.
6. A successor is pruned when `successor.lower >= incumbent.upper`.
7. If an extracted state's lower bound is already at least the incumbent
   upper bound, its expansion terminates immediately.
8. Capability-infeasible states and states lacking an exchange strategy are
   discarded explicitly.
9. Search stops when `OPEN` is empty or the finite budget is exhausted.

The result is the best conservative complete plan discovered within the
budget. It is not called globally optimal. Increasing the budget preserves an
anytime prefix and cannot worsen the retained incumbent upper estimate under
a fixed model snapshot.

## Cost Contract

Execution observations are accepted only for complete plans with finite,
strictly positive raw cost. The observation store is versioned JSONL and
records task, interpretation, plan, state, feature schema, backend/exchange
context, raw cost, log cost, and provenance.

The M11-C Gaussian-process estimator uses deterministic versioned features
and fits observations in log-cost space. Missing statistics are represented
by explicit presence features. For a finite state-space bound `N_I` and
failure probability `delta_I`, it reports:

```text
beta = 2 log(2 N_I / delta_I)
lower = exp(mu - sqrt(beta) sigma)
upper = exp(mu + sqrt(beta) sigma)
```

For task sequence index `q` and `M` interpretations, the across-task schedule
is `delta_qI = 6 delta / (pi^2 q^2 M)`. A conservative combinatorial bound is
computed from operator placement and exchange-option counts without
enumerating the search space. One immutable estimator snapshot is used for an
entire planning task; observations from execution affect only later snapshots.

The repository currently has no NumPy, SciPy, or scikit-learn dependency. The
initial GP therefore uses a small jittered Cholesky implementation from the
Python standard library. It is isolated from the algebra core and intended for
the controlled M11 state spaces. A future estimator can replace it through the
same `CostEstimator` protocol.

Search traces are JSONL and include state/action IDs, OPEN size, budget,
lower/upper estimates, incumbent upper bound, pruning reason, completeness,
feature-schema version, model version, and timestamp.

## Objective And Hard Constraints

An interpretation is semantically admissible when:

```text
c_sem <= epsilon
```

It is eligible for ranked output only when both utilities are strictly
positive:

```text
U_sem = epsilon - c_sem > 0
U_exec_hat = T_max - C_bar > 0
S_Nash = U_sem * U_exec_hat
```

Consequently, `c_sem == epsilon` is admissible but not Nash-rankable. A plan
is returnable only when `C_bar < T_max`; M11 never relaxes `T_max`. At most one
physical representative is retained per interpretation, and top K is ordered
by decreasing Nash score with deterministic identifiers as tie breakers. M11
does not add a Pareto filtering phase.

## Artifacts And Configuration

The controlled experiment runner consumes versioned JSON configuration,
structured M10 candidates, backend descriptors, ontology/alignment evidence,
exchange strategies, cost-model metadata, and an optional observation store.
It writes under `runs/<run_id>/`:

- resolved configuration and input candidate JSON;
- alignment and semantic-deviation records;
- physical search trace JSONL;
- discovered complete plans and selected representatives;
- compiled `QueryArtifact` JSON or structured unsupported records;
- a summary containing budgets, pruning, selection, and reason codes.

The runner has no live LLM dependency and does not execute a distributed plan.

The checked-in controlled inputs are:

- `examples/configs/m11_candidates.json`;
- `examples/configs/m11_alignment.json`;
- `examples/configs/m11_controlled_planner.json`.

Run them with:

```text
python -m xgap.experiments.physical_planner \
  --config examples/configs/m11_controlled_planner.json
```

The alignment artifact is explicitly marked as a fixture and reports that no
reasoning was performed.

## Exhaustive Oracle Boundary

A tiny exhaustive oracle exists only in tests and controlled experiments. It
enumerates complete realizations for small logical plans, uses controlled true
costs, and reports oracle best cost, discovered-plan regret, reachable,
processed, generated and pruned states, pruning ratio, search reduction, and
budget-versus-quality observations. It is never called by the production main
planner.

Controlled true-cost tests and GP-estimator tests remain separate. The former
validate pruning and anytime behavior; the latter validate posterior and
confidence-bound calculations.

## Explicit Unsupported Boundaries

M11 does not implement live LLM providers, KGQA loading/evaluation, LoRA or
model training, automatic ontology induction, a hard-coded OWL/DL reasoner,
full GQL, new compiler support for `Recursive`, selector operators, or M6
binding operators, logical rewrite enumeration, new backend engines, or
distributed cross-backend runtime orchestration.

## Acceptance

M11-A through M11-D are complete. Verification on 2026-08-11:

- focused M11 suite: 26 passed;
- `python examples/m11_physical_planner_demo.py`: passed, selected 2 plans;
- `python examples/m11_exhaustive_oracle_demo.py`: passed, 3 reachable and 3
  processed states, oracle/BnB cost `2.0`, regret `0.0`;
- `python -m pytest`: 298 passed, 2 skipped;
- `./scripts/run_acceptance.sh`: passed with all prior and M11 demos.

No live backend or live LLM is required by default tests.

## Current Compiler Constraint

Existing deterministic `PathPatternQuery` lowering represents selector `ALL`
through `GroupBy` and `Projection`. Current Neo4j/Fuseki M8 profiles and M9
compilers do not support those complete logical operators, even though M9 can
compile a `PathPatternQuery` through its special bounded ALL input boundary.

M11 physical search is defined over fixed `L_I`, so it does not bypass that
logical plan by recompiling the original candidate. The controlled main demo
therefore finds a reference-evaluator realization. Direct logical fragments
inside the current M9 slice can still compile to Cypher/SPARQL. This is an
existing architecture boundary, not new compiler coverage or a semantic
approximation introduced by M11.
