# XGAP Design Decisions

## D1 Logical algebra alignment

XGAP's path-algebra vocabulary aligns with the path algebra from
"Path-based Algebraic Foundations of Graph Query Languages".

M6 adds a separate minimal focused binding layer for quantified-pattern
semantics. `BindNode`, `BindEdge`, `BindingJoin`, `BindingProject`,
`QuantifiedCheck`, `AntiSemiJoin`, and `FocusProjection` are not claimed
to be operators from the path-algebra paper.

Reason:

The existing path algebra should remain theoretically identifiable.
QGP-inspired counting requires correlated bindings and anti-existence,
which cannot be represented faithfully by `PathSet` and
`SolutionSpace` alone.

## D2 Path-centric MVP

The MVP supports path-centric graph queries and regular path queries.

## D3 Entity grounding is outside algebra

Entity lookup, schema matching, ambiguity grounding, and disambiguation are outside the logical algebra.

## D4 No fake future features

Unimplemented future features must raise NotImplementedError.

## D5 Deterministic lowering

LLM output may propose candidate interpretations, but algebraic correctness must be guaranteed by deterministic validation and lowering.

## D6 Reference evaluator first

The in-memory reference evaluator defines executable semantics for tests and compiler validation. Backend execution comes later.

## D7 Backend configuration is separate from compiler logic

Backend capability profiles, connection information, and supported semantics should be configured separately from query compilation.

## D8 Extended algebra uses SolutionSpace

XGAP implements GroupBy, OrderBy, and Projection through a secondary data object called SolutionSpace.

Reason:

The extended path algebra uses SolutionSpace = (S, G, P, α, β, △) to express selector-style semantics. This keeps the core and recursive algebra closed over PathSet, while allowing GQL/SQL-PGQ selectors to be represented algebraically.

## D9 GroupBy does not order or remove paths

GroupByOp only organizes paths into partitions and groups. It initializes all ranks to 1.

Reason:

Ordering is the responsibility of OrderByOp, and path selection is the responsibility of ProjectionOp.

## D10 OrderBy only updates ranks

OrderByOp preserves paths, partitions, groups, path-to-group assignments, and group-to-partition assignments. It only updates the rank function.

Reason:

This follows the formal semantics of the extended algebra, where τθ(SS) returns a new solution space with the same S, G, P, α, and β, but with an updated rank function △.

## D11 Projection is deterministic in the reference evaluator

When ranks tie, ProjectionOp uses stable deterministic tie-breakers.

Reason:

Selectors such as ANY and ANY SHORTEST may be nondeterministic, but XGAP's reference evaluator must be reproducible for tests, debugging, and compiler validation.

## D12 Empty SolutionSpace canonicalization

If GroupByOp receives an empty PathSet, XGAP returns an empty SolutionSpace with no partitions and no groups.

Reason:

Projection over empty input should naturally return an empty PathSet. This avoids artificial empty partitions or groups in the reference evaluator.

## D13 Restrictors and selectors are implemented separately

Recursive modes implement path restrictors, while GroupBy, OrderBy, and Projection implement selector semantics.

Reason:

This separation matches the algebraic structure of path queries and keeps the implementation modular.

## D14 Pattern AST is above logical algebra 
`PathPatternQuery` is a structured query-intent object that sits above the logical algebra. Reason: The logical algebra should remain limited to path-algebra operators. Query-level concepts such as selectors, restrictors, regex syntax, and endpoint constraints should be represented in the pattern layer and lowered deterministically. 
## D15 M5 lowering is deterministic and LLM-free 
M5 lowering must not call an LLM. Reason: LLMs may propose candidate interpretations in later milestones, but algebraic correctness must be guaranteed by deterministic lowering and validation. 
## D16 M5 does not implement a text parser 
M5 implements Python data structures for path-pattern queries and deterministic lowering rules. It does not parse GQL, Cypher, SPARQL, or natural language text. Reason: Parsing concrete languages and natural language planning are separate milestones. M5 should only connect structured path-pattern intent to the logical algebra. 
## D17 Regex lowering targets existing logical operators 
Regular-expression AST nodes lower only to existing logical operators. Examples: - `Rel(label)` lowers to `Selection(label(edge(1)) = label, Edges(G))`. - `Seq(a, b)` lowers to `Join(lower(a), lower(b))`. - `Alt(a, b)` lowers to `Union(lower(a), lower(b))`. - `Plus(a)` lowers to `Recursive(mode, lower(a))`. - `Star(a)` lowers to `Union(Nodes(G), Recursive(mode, lower(a)))`. Reason: M5 must not introduce new logical operators.

## D18 GPC-Lite is intentionally path-centric

M5 implements GPC-Lite as a structured path-pattern layer, not full GPC.

M6 introduces a separate bounded focused quantified-pattern fragment
and a minimal `BindingRelation` substrate. This does not retroactively
change M5 and does not constitute full GPC assignment or general
BindingRelation semantics.

Reason:

The M5 scope remains path-centric graph queries and regular path
queries. M6 adds only the minimum binding functionality required for
rooted tree-shaped quantified branches. Arbitrary conjunctive patterns,
query-level joins, `Maybe`, group-variable runtime semantics, bag
semantics, and null semantics remain future work.

## D19 Type checking precedes lowering

`PathPatternQuery` objects must pass `type_check_path_pattern()` before deterministic lowering constructs a logical plan.

Reason:

Variable-kind conflicts, selector limit mistakes, repeated edge variables in recursive expressions, and unsafe `WALK` recursion should fail before a logical plan is emitted.

## D20 Unsupported GPC-Lite placeholders fail clearly

`OptionalExpr`, `Bounded`, reverse direction, and undirected direction remain AST-level placeholders in M5 and M5.5. They must raise explicit lowering errors instead of being approximated with existing operators.

Reason:

Approximating these features would silently change semantics and would amount to implementing future functionality during an audit milestone.

## D21 Pattern lowering remains runtime-independent

Pattern lowering must not call the reference evaluator, backend compilers, backend execution, or LLM code.

Reason:

Lowering is a deterministic structural transformation. Validation and reference evaluation are downstream checks, not dependencies used to decide the lowered plan.


## D22 M6 is additive to M5

`FocusedQuantifiedPatternQuery` is a sibling query-intent representation
rather than an extension that changes `PathPatternQuery`.

Reason:

M5 and M5.5 have already established and audited deterministic
path-pattern semantics. Quantified tree patterns require different data
objects and lowering rules and must not silently change the audited M5
contract.

## D23 M6 patterns are focused rooted trees

An M6 query has one focus node, a connected rooted tree of atomic
pattern edges, and one structural parent for every non-focus node.
Sibling branches are conjunctive. Query output is the distinct set of
focus-node bindings.

Reason:

This captures common star-like and bounded nested quantified queries
without claiming arbitrary conjunctive graph-pattern support.

## D24 Quantifiers attach only to atomic directed edges

M6 quantifiers may be attached only to atomic `OUT` edge patterns.
They may not quantify `Seq`, `Alt`, `Plus`, `Star`, or another regular
path expression.

Reason:

The referenced QGP semantics count child matches of graph-pattern
edges. Counting paths or regular-path witnesses requires separate
decisions about path identity, duplicate paths, repeated nodes, and
unbounded walks.

## D25 Quantifiers count distinct child nodes

For a quantified edge from `u` to `v`, M6 counts distinct bindings of
the child variable `v`.

Parallel edges, multiple witness rows, and multiple paths that reach the
same child node do not increase the count.

Reason:

This follows the child-set interpretation of QGP counting and avoids
making results depend on incidental witness multiplicity.

## D26 Ratio domains are edge-local and non-vacuous

For a ratio quantifier, the denominator contains distinct target nodes
reachable from the parent through the edge descriptor. Child-node
descriptors and child-subtree predicates are applied only to the
numerator.

An empty denominator does not satisfy a positive ratio or universal
condition.

Reason:

The denominator represents the relevant edge-neighbor domain.
Non-vacuous semantics prevents nodes with no relevant neighbors from
satisfying universal conditions automatically.

## D27 Pattern negation uses anti-semi-join

A `NONE` quantified branch is implemented by removing candidate
bindings for which at least one complete branch witness exists.

Reason:

Pattern-level negation is a `NOT EXISTS` condition. Boolean negation of
a scalar property predicate cannot represent the absence of a complete
matching branch.

## D28 Quantifier bounds are structural and path-wise

For every root-to-leaf structural path, M6 allows at most two
non-existential quantifiers and at most one negated edge.

Sibling quantified and negated branches are allowed.

Reason:

The bound limits nested quantification and double negation while
retaining common star-shaped query structures. The value two is an
initial XGAP system bound, not a general empirical or complexity claim.

## D29 M6 BindingRelation uses set semantics

M6 `BindingRelation` values are immutable, deduplicated, and
deterministically ordered for formatting and reference evaluation.

Reason:

QGP-style counting is defined over distinct child bindings. Bag and null
semantics would introduce additional choices that are outside M6.

## D30 Selector GroupBy is not an aggregation operator

The existing `GroupBy`, `OrderBy`, and `Projection` operators remain
exclusive to selector-style `SolutionSpace` semantics.

`QuantifiedCheck` performs quantified child counting.

Reason:

Reusing selector `GroupBy` for `COUNT(DISTINCT child)` would conflate
path ranking with correlated graph-pattern aggregation.

## D31 Scalar predicates and counting quantifiers are separate

Local node and edge comparisons such as `amount >= 1000` are scalar
property predicates and lower to `Selection`.

Conditions such as “at least three matching neighbors” are counting
quantifiers and lower through the focused binding layer.

Pattern-level `NONE` is anti-existence and lowers through
`AntiSemiJoin`.

Reason:

These three conditions operate over different semantic domains and
must not share an ambiguous lowering rule.

## D32 M6 lowering is canonical and runtime-independent

M6 lowering must use stable branch ordering, run type checking and bound
validation before plan construction, and call `validate_plan()` after
construction.

It must not call the reference evaluator, backend code, optimizer, LLM,
or cost estimator to decide plan shape.

Reason:

The same structured quantified query must always produce the same
logical-plan structure.

## D33 M6 is not full QGP

M6 may be described as a bounded QGP-inspired focused quantified
fragment. It must not be described as full QGP support, and complexity
results for general QGP matching must not be attributed to M6 without a
separate proof.

Reason:

M6 uses rooted tree topology, a single focus, set-valued bindings,
atomic directed edges, and XGAP-specific deterministic lowering. These
restrictions differ from the complete QGP model.

## D34 Native backend smoke execution is not compilation

The backend infrastructure layer may execute already-authored native
Cypher and SPARQL smoke artifacts against Neo4j and Fuseki.

It must not compile `LogicalPlan` objects, invoke deterministic lowering,
add planner logic, or reinterpret XGAP path/GPC semantics.

Reason:

Native smoke execution verifies server connectivity, dataset loading,
runtime records, and result normalization before full backend capability
profiles and compilers exist.

## D35 Capability profiles precede compilers

M8 must make backend capability profiles program-checkable before XGAP
implements logical-plan-to-native-query compilers.

Profiles must use XGAP path/GPC vocabulary and report whether a
construct is supported, conditionally supported, or unsupported. They
must also give explicit unsupported reasons.

Reason:

XGAP should know whether Neo4j or Fuseki can preserve the semantics of a
validated M0-M6 logical fragment before a compiler emits Cypher or
SPARQL. This separates support checking from native query generation and
prevents accidental semantic claims based only on successful smoke
queries.

## D36 M9 compilers are bounded native artifact emitters

M9 compilers emit native Cypher and SPARQL `QueryArtifact` values only
for a small row-oriented path/GPC fragment after M8 capability checks.

The fragment is limited to `Nodes(G)`, `Edges(G)`, `Selection`,
path-chain `Join`, and ALL-selector fixed-OUT `PathPatternQuery`
fragments. Native output uses row bindings and does not claim full
XGAP `PathSet` object preservation.

Reason:

This closes the first backend MVP loop without conflating compilation
with optimization, planning, selector semantics, M6 quantified binding
semantics, semantic-deviation scoring, ontology reasoning, LLM
generation, or KGQA evaluation.

## D37 LLMs propose structured candidates only

M10 places LLM behavior behind a structured candidate boundary.

A future model may propose controlled JSON that parses into an existing
`PathPatternQuery`. It may not directly emit native Cypher, SPARQL, GQL,
logical operators, optimized plans, backend execution instructions, or
semantic-deviation scores.

Reason:

XGAP's correctness depends on deterministic type checking, lowering,
plan validation, capability checks, and compiler boundaries. Keeping
the LLM outside those deterministic stages lets XGAP use model
suggestions without letting model output redefine algebra semantics.

## D38 M11 searches physical realizations, not logical rewrites

For one interpretation, deterministic lowering fixes `L_I`. M11 search may
choose only backend placements and explicitly configured exchange
realizations.

Reason:

This matches the paper's current planning algorithm and preserves the audited
M5/M6 logical semantics. Different logical rewrite orders must not become an
untracked interpretation variable.

## D39 Ontology and alignment are fixed external planning inputs

Ontology/schema artifacts, source mappings, aliases, mapping sufficiency, and
semantic-deviation inputs are resolved through versioned providers before one
physical search tree begins. Missing or insufficient mapping evidence never
defaults to success.

Reason:

The ontology is part of planning feasibility, but ontology reasoning and
interpretation enumeration are different concerns from backend placement.
Keeping this boundary external allows a future production alignment provider
to replace the controlled artifact adapter without changing BnB.

## D40 M11 execution threshold and Nash domain are strict

A returnable plan must satisfy `C_bar < T_max`. Semantic deviation equal to
`epsilon` is semantically admissible but has zero semantic utility and is not
eligible for Nash-ranked output. M11 does not relax the execution threshold
and does not add a Pareto filtering phase.

Reason:

This follows the reconciled Chapter 5 procedure and keeps semantic
admissibility distinct from the strictly positive Nash-output domain.

## D41 M11 BnB incumbents minimize discovered conservative upper cost

One budget unit is charged per processed `ExtractMin`. The first feasible
complete state initializes the incumbent, and replacement requires a strictly
smaller conservative upper estimate. Lower-bound pruning uses the current
incumbent upper estimate.

Reason:

The search is finite and anytime, but a bounded run does not prove global
minimum true execution cost. This rule states exactly what the returned
per-interpretation representative guarantees.

## D42 Cost snapshots learn only from complete-plan observations

M11 records finite positive raw costs and log costs only for complete physical
plans. One immutable Gaussian-process snapshot is used throughout a planning
task; new execution observations affect later snapshots only. The exhaustive
oracle is restricted to tests and controlled experiments.

Reason:

Partial-state optimal-completion costs are latent rather than observed.
Separating the experiment oracle from production planning prevents evaluation
knowledge from influencing search decisions.

## D43 M12 experiment semantics are versioned artifacts

Directional ontology-hop penalties, uniform slot aggregation, epsilon values,
the GP calibration/update protocol, baseline IDs, ablation switches, metric
availability, and execution protocol are serialized and content-hashed above
the deterministic planner core.

Reason:

Experimental choices must be traceable and replaceable without introducing
dataset-specific logic into M10 validation, logical lowering, or M11 search.

## D44 Missing experimental evidence remains unavailable

Missing gold forms, alignments, backend measurements, calibration
observations, oracle truth, GPU/CUDA metadata, and backend versions are
represented by explicit unavailable states. They are never replaced by empty
labels, fabricated values, or silent success.

Reason:

Coverage and supported-subset results are meaningful only when unavailable
evidence can be distinguished from negative observations and true zeros.

## D45 Live model inputs are bounded and gold-free

M12-B live inference receives one content-hashed bounded ontology/schema view
and may make one generation call plus at most one syntax/schema repair call.
It may return only controlled grounded `PathPatternQuery` candidates. Query
anchors and candidate slot realizations are represented separately and are
validated against prompt-visible ontology/entity IDs before the frozen M12-A
semantic-deviation scorer and unchanged M11 planner run.

Gold answers, gold logical forms, gold alignments, and evaluation labels are
not available to retrieval, prompting, candidate validation, semantic
deviation, or planning.

Reason:

The live model is an interpretation proposer, not an algebra, planner,
compiler, or evaluation oracle. Bounding calls/context and enforcing the
anti-leakage boundary makes runtime behavior reproducible enough for
experimentation while preserving XGAP's deterministic correctness core.

## D46 M12-C calibrates independent backend-local RBF GPs

The default M12-C protocol builds separate `D0_neo4j` and `D0_fuseki`
datasets and fits one existing-family RBF GP per backend. Both models use the
same deterministic M11 feature-schema contract and millisecond/log-millisecond
cost convention, but observations never cross backend boundaries. There is no
default joint backend-aware GP.

Reason:

Current infrastructure can measure backend-local native query execution but
cannot attribute arbitrary distributed movement cost. Independent models keep
measurement provenance explicit without changing the paper-level physical
state model or M11 `CostEstimator` boundary. A joint model remains a possible
future ablation, not an M12-C default.

## D47 M12-C freezes hyperparameters and updates posterior between tasks

GP hyperparameters, feature ordering, missing-value representation, and
normalization are fitted or frozen from D0 before evaluation. Task q receives
one immutable posterior based on `D_(q-1)`. Only successful, positive-cost,
complete-plan executions from task q are appended, as one atomic batch, after
the task finishes. No partial-state label, within-task update, future-task
observation, or cross-backend movement observation is admitted.

Reason:

This enforces the Chapter 5 temporal boundary, prevents evaluation leakage,
and lets every search decision in one task use the same confidence model.
Append-only observations and posterior hashes make `D_(q-1) -> D_q`
replayable without changing BnB, confidence schedules, or Nash selection.

## D48 M12-D methods are explicit policies over frozen components

Every frozen baseline or ablation identifier selects documented behavior;
none silently aliases `full_xgap`. Comparable physical-planning methods reuse
the same immutable candidate, grounding, ontology, backend, D0, feature,
execution-protocol, budget, and seed inputs. The direct text-to-graph-query
baseline uses a separate native-query prompt and bypasses the XGAP
interpretation and physical-planning path.

Reason:

Planner comparisons must isolate the named mechanism. Candidate freezing
prevents model sampling from becoming an uncontrolled physical-planning
variable, while preserving a scientifically distinct direct-system baseline.

## D49 M12-D commits online observations only at task boundaries

Task q uses one immutable backend-local posterior derived from `D_(q-1)` for
all candidate and plan decisions. Successful complete-plan observations are
committed as one atomic K_q batch only after all selected executions finish.
Checkpoint recovery uses committed per-task artifacts and never reruns a
completed task implicitly. `no_online_update` persists measurements but plans
every task from D0.

Reason:

This preserves M12-C temporal anti-leakage during continuous workloads and
makes interruption/resume behavior replayable from disk.

## D50 Execution success and answer correctness are separate

Runtime reports record normalized `row_count` and distinguish nonempty
success, empty success, and execution error. Empty success is neither backend
failure nor answer correctness. Calibration diagnostics may flag an explicitly
configured expected-nonempty query, but may not reinterpret arbitrary empty
results as failures.

Reason:

Transport/runtime success, result cardinality, and benchmark correctness are
different experimental observations and must remain separately auditable.

## D51 Paper mode requires an explicit frozen environment

Development, pilot, and paper modes share the same runner. Paper mode requires
Python 3.10+, immutable artifact hashes, an appropriate clean/fixed repository
state, and identified pinned backend images/versions. Floating images remain
development-only. The exact runtime version, such as Python 3.10.12, is still
recorded in every environment manifest. Readiness diagnoses state without
mutating the host.

Reason:

Reproducible paper measurements require environment identity beyond a
successful smoke query. The freeze manifest defines this identity without
claiming that final benchmark artifacts or results already exist.

## D52 DatasetBundle backend mapping owns native identifier semantics

Canonical XGAP terms and bounded compiler tokens resolve through the active
DatasetBundle backend mapping before native query emission. The M9 SPARQL
compiler must not construct a dataset-specific RDF namespace. For controlled
RDF bundles, readiness audits the loaded data term, mapped IRI, and M9-emitted
IRI and requires equality. A missing mapping fails explicitly.

Reason:

Backend transport success can hide a semantically empty query when the native
identifier contract drifts. Keeping the mapping authoritative lets a future
dataset change native IRIs by replacing its artifact rather than editing the
compiler.
