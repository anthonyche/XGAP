# XGAP Design Decisions

Current engineering loop and evidence: [engineering_state.md](engineering_state.md).

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

## D53 Fixed-path node identity is a scalar condition

`NodeNotEquals(left, right)` compares graph-node identity at two fixed
`NodeRef` positions. It lowers to the existing `Selection` operator and
compiles to native identity inequality. Numeric references are valid only for
fixed-length path expressions and must be in range. The condition does not
impose implicit all-different semantics and is not property inequality.

Reason:

GrailQA simple-path reference forms explicitly distinguish query nodes. The
existing path-position references make this a small generic condition gap;
adding a dataset-specific operator or changing `Join` semantics would be
broader and incorrect.

## D54 Interpretation equality follows a named canonical profile

For the bounded fixed-path experiment profile, omitted path selection defaults
to `ALL`, omitted repetition semantics defaults to `SIMPLE`, and SIMPLE's
pairwise node-identity inequalities are derived after fixed topology is known.
Variable spelling and commutative condition ordering are normalized. Different
entities, types, relations, directions, topologies, explicit predicates,
focus, or explicit non-default path semantics remain unequal.

Reason:

An LLM should propose ambiguous question semantics, not reproduce deterministic
serialization conventions. A named profile keeps this rule general and
auditable without a GrailQA branch in the parser, pattern AST, or algebra.

## D55 Paid semantic runs require offline reference reachability

A GrailQA live run may start only after a query-independent public catalog is
hashed, the frozen evaluation sample has separate catalog/retrieval/prompt
coverage artifacts, and the predeclared joint prompt-reachability safeguard
passes. Gold is permitted only in this offline diagnosis and is never exposed
to retrieval, prompting, generation, grounding, or planning.

Reason:

Candidate Recall is not an interpretable model metric when the controlled
output contract forbids the reference IDs. Failing closed avoids paying for a
non-diagnostic run while preserving difficult/unreachable questions and the
original evaluation criterion.

## D56 Local vLLM is a frozen deployment condition

CWRU Qwen3-32B uses the existing OpenAI-compatible structured-candidate
protocol. Endpoint and served model are selected through declared ModelBundle
environment names; `enable_thinking=false` is a model-specific request
parameter, not a global provider rule. The Slurm job resolves and logs one
existing Hugging Face cache snapshot, binds only to loopback, verifies strict
JSON Schema serving, records the runtime without credential values, and owns
the vLLM process lifetime.

Reason:

Changing from remote Qwen3-Max to local dense Qwen3-32B is an experimental
model/deployment condition, not a semantic-planner change. Keeping it outside
the deterministic core preserves the M13-E1 gate and makes results auditable
without introducing a parallel LLM framework or depending on a named compute
node.

## D57 Freebase source transport is explicit and immutable

Catalog-v2 accepts only the named `google_rdf_gzip` and
`hf_archival_parquet` source modes and never falls back between them. The CWRU
paper artifact freezes `CleverThis/freebase` revision
`dbb1931c2698295653effe9b980a02ab29f004e0`, its exact 964-shard inventory,
LFS SHA-256 values, sizes, schema, and immutable URLs. Parquet rows are streamed
into the existing triple extraction contract; Catalog-v2 schema, normalization,
retrieval, and evaluation semantics do not depend on source format.

Reason:

All tested Google dump objects returned HTTP 403 from CWRU on 2026-08-19, while
the frozen archival representation is reachable. Treating transport as a
verified adapter preserves Freebase/GrailQA provenance and source-format
parity without silently substituting a different knowledge graph or ontology.

## D58 Query-local catalogs are inference artifacts, not benchmark slices

For a question `u`, the M13-E3B entity universe is a deterministic function of
only `text(u)`, public English Freebase names/aliases/type metadata, and the
frozen GrailQA ontology. Exact normalized contiguous text spans select at most
50 MIDs per question. Batched source scans maintain independent candidate maps,
and Catalog-v2 retrieval enforces the persisted `question_id` and question-text
hash before applying that question's MID allowlist. Construction APIs accept no
reference, logical-form, answer, or gold input; evaluation opens references
only after retrieval has been persisted.

Reason:

A bounded local grounding artifact can reduce global SQLite/FTS materialization
without changing the scientific inference boundary. Per-query isolation and a
separate evaluation phase make batching an I/O optimization rather than
cross-query benchmark leakage, while explicit local-catalog misses preserve the
cost of localization in reported reachability.

## D59 Query-local candidate rank is an inference contract

M13-E3B local candidate construction already performs the gold-blind entity
selection and freezes its rank. For a manifest with
`requires_query_entity_filter=true`, that persisted rank is authoritative at
the downstream bounded entity interface. Retrieval orders by `rank` and then
`entity_id`, preserves the local lexical score, and does not apply the global
FTS entity scorer again. Global Catalog-v2 retrieval retains its original
score-descending FTS behavior.

Reason:

The real CWRU preflight contained reference entities at local ranks 1-3 that
were absent from downstream Top-20 after FTS reranking. Preserving the frozen
local ordering repairs a generic contract defect without tuning lexical
scores, changing candidate generation, or using evaluation references.

## D60 Schema ranking is phrase-first, term-level, and ontology-aware

Relation and type descriptors are normalized and aggregated by canonical
schema term before ranking or Top-k truncation. Lexical evidence is a frozen
lexicographic hierarchy: exact normalized multi-token phrase, complete
informative-token coverage, contiguous partial phrase, informative partial
overlap, generic single-token overlap, and zero overlap. IDF computed only from
the frozen ontology descriptor vocabulary is a secondary tie-break; GrailQA
question or reference frequencies are never used.

Query-local entity types provide the first relation slot's coherence context.
Later bounded slots propagate public domain/range endpoint types from the
visible relation prefix. Compatibility is bidirectional when no deterministic
slot direction exists; reverse metadata is recorded but does not invent a
direction. Type candidates aggregate lexical, entity-attached,
relation-domain/range, and bounded ontology-expansion provenance before
truncation. Exact phrase evidence remains stronger than provenance, and all
ties end with ascending schema ID.

Reason:

The real E3B.2 audit showed a complete ontology universe but relation/type
losses dominated by lexical retrieval and prompt truncation. A term-level,
explainable contract repairs generic short-token and post-truncation provenance
defects without fitted weights, gold-derived aliases, embeddings, another
model, larger prompt bounds, or changes to the live gate.

## D61 Relation endpoint types are role-aware grounding evidence

For a fixed linear path candidate, an exact domain/range type carried by a
selected prompt-visible relation may make the adjacent endpoint type visible.
OUT maps domain to source and range to target; IN reverses those roles;
UNDIRECTED admits either exact endpoint type for either role. Multi-hop paths
use the first selected relation for the outer source and the last selected
relation for the outer target. Alternation and repeated/optional expressions
do not receive derived endpoint evidence.

This is a versioned deterministic grounding contract shared by runtime
validation and offline reachability. It does not add the endpoint type to the
explicit Type Top-4 list, expand the ontology hierarchy, apply lexical
fallback, increase prompt bounds, or use evaluation gold during inference.
Offline artifacts therefore retain the explicit `type` metric, report
`effective_type` separately, and compute joint reachability from the effective
runtime-visible set.

Reason:

The real E3B.3 audit exposed questions where the exact required relation was
already prompt-visible with the required source or target type in its public
domain/range metadata, while the runtime grounding boundary and offline gate
still treated that type as invisible. A shared role-aware rule makes the
metadata already supplied to the model operational without changing retrieval,
ranking, prompt size, the gate threshold, or model behavior.

## D62 Prompt Top-4 is a frozen experimental bound, not a semantic constant

The M13-E1/E3B preflight exposes at most four entity candidates, four explicit
type candidates, and four relation candidates per bounded relation slot to the
model. The value comes from the frozen preflight spec field
`prompt_candidates_per_slot=4` and the Catalog-v2 prompt-view bound. It is not
part of PathPatternQuery, the path algebra, GrailQA semantics, or a theoretical
success-rate claim.

Increasing the bound cannot remove a reference term that is already visible
under a fixed ranking, so offline prompt recall is non-decreasing. It also
increases prompt tokens, serving latency, and the number of plausible but
incorrect grounding choices; model accuracy is therefore not guaranteed to be
monotonic. Any comparison of bounds such as 1/2/4/8/16 is a separately declared
ablation. The current live preflight keeps 4 fixed rather than selecting a
value after observing the gate.

Reason:

Prompt reachability and model correctness are different experimental layers.
A frozen bounded context makes cost and ambiguity reproducible, while a later
bound-sensitivity study can measure the recall-versus-confusion tradeoff without
silently changing the primary condition.

## D63 Live preflight artifact profiles are explicit and fail closed

The CWRU M13-E3B.5 preflight selects the query-local artifact with the explicit
`query_local_e3b4` profile. Readiness consumes its native
`audit_summary.json` and `reachability.jsonl` paths and validates the exact 18
question-ID set, Catalog-v2 content hash, audit content hash, reachability
row hash, prompt bound 4, gold-blind catalog declaration, and relation-endpoint
contract version. The older query-independent `summary.json` layout remains a
separate profile and cannot silently accept a query-local catalog.

Reason:

The passing 5/18 reachability result belongs to one precise query-local
artifact and endpoint contract. Explicit profile selection prevents the live
job from accidentally reading the stale global artifact layout or mixing
coverage evidence from a different question set.

Physical JSONL row order is not part of artifact identity. Runtime lookup is by
`question_id`, and experiment execution follows the frozen spec order. The
validator therefore requires exact unique set equality and rejects missing,
extra, or duplicate IDs without imposing an unrelated serialization order.

## D64 CWRU serving context covers the complete frozen request budget

The CWRU Qwen3-32B deployment must satisfy
`max_model_len >= input_budget + output_budget` before model startup. For the
M13-E3B.5 preflight, the unchanged ModelBundle budgets are 8192 input tokens
and 4096 output tokens, so vLLM serves a 12288-token context. The environment
contract, experiment spec, and launch argument record the same value, and a
fail-fast runtime check rejects hash drift or insufficient context.

Reason:

Job `3763119` showed that independent input and output limits are not valid
when their sum exceeds the served context: all 18 requests received HTTP 400
before generation. Expanding the deployment window preserves prompt and
candidate-generation semantics, whereas silently truncating output would
change the frozen experiment condition.

## D65 The CWRU structured candidate generator returns a nonempty bounded set

The CWRU Qwen3-32B JSON Schema requires `1 <= len(candidates) <= 3`, and its
system prompt states the same request-relative rule. This requirement applies
only at candidate generation. Every emitted candidate must still pass the
controlled parser, type checking, grounding, semantic bound, ranking, and
equivalence checks; the schema does not assert candidate correctness.

Reason:

Job `3763174` reached 17/18 provider success and zero malformed responses, but
all successful responses used the shortest legal array `candidates=[]` because
the strict schema omitted `minItems`. That behavior measured an under-specified
guided-decoding contract rather than interpretation quality. Adding a nonempty
bound fixes the generator interface without using gold, examples, or observed
answer terms.

## D66 XGAP revalidates declared candidate cardinality after guided decoding

The OpenAI-compatible provider reads `properties.candidates.minItems` and
`maxItems` from its active structured schema and checks the decoded response
before the controlled parser. A violation is a structured-output error and may
use the existing maximum of one repair call. Bundles that omit either keyword
do not acquire an implicit bound.

Reason:

Job `3763298` used the corrected CWRU schema and prompt but vLLM 0.11.1 still
returned an empty candidate array for every successful call. Guided-decoder
support for JSON Schema keywords is therefore not a sufficient correctness
boundary. Revalidating only explicitly declared bounds is deterministic,
portable across providers, and does not invent constraints for historical
bundles.

## D67 The mainline is goal-driven agentic federation

XGAP jointly plans information-acquisition actions and federated execution
actions for partially bound semantic graph programs over heterogeneous
black-box graph engines. Cross-platform execution is the environment;
ontology, catalogs, LLMs, and clarification are optional tools.

Reason:

This creates one system mechanism rather than an additive collection of
ambiguity, ontology, LLM, and federation features. It also makes end-to-end
tool and execution cost observable under one objective.

## D68 Semantic, control, and runtime operators are typed separately

The Semantic Graph Program contains backend-independent query/dataflow nodes.
Agent decisions represent information acquisition, binding, clarification,
and replanning. Federated runtime nodes represent remote calls, exchange,
coordinator joins, materialization, and merge.

`ResolveAmbiguity` may be a user-facing composite label, but executable actions
use typed primitives such as `ResolveEntity`, `ResolvePredicate`, `Clarify`,
and `Relax`. None of these redefine the audited path algebra.

Reason:

A single untyped workflow graph would obscure value types, semantic
equivalence, effects, cost attribution, and failure behavior.

## D69 PathPatternQuery is a reusable Traverse sub-IR

`PathPatternQuery` and its deterministic lowering remain supported, but the
object is no longer the complete system-level interpretation. A semantic
`Traverse` may carry it as a path-expression payload.

Reason:

The existing path representation has precise and tested semantics, while a
complete agentic federated plan must also express bindings, source choices,
cross-source joins, tool observations, clarification, and replanning.

## D70 Every agent execution is an explicit finite goal loop

A goal declares objective, success criteria, allowed tools, step budget, and
tool-call budget. Tools return success, error, or unavailable observations.
Failures are not automatically retried, and terminal states are explicit.

Reason:

An agent must be experimentally reproducible and unable to hide unbounded LLM,
network, or backend work behind an informal reasoning loop.

## D71 Backends are observable plugins, not internal physical engines

Backend plugins may expose healthcheck, schema inspection, explain, profile,
sample, and execute operations. The first adapter exposes the existing
healthcheck and native execution clients; unsupported operations return
`unavailable`.

Reason:

XGAP cannot and should not modify Neo4j or Fuseki internals. Its physical
decisions are fragment placement, remote invocation, scheduling, transfer,
coordinator execution, and adaptation.

## D72 UI is optional and remote execution is batch-first

The paper experiment path remains a CLI plus immutable artifacts. A future
thin UI consumes the same goal and trace contracts. CWRU execution should use
an SSH/Slurm remote-executor plugin for submission, polling, and artifact
retrieval; an SSH tunnel is optional for interactive demonstrations only.

Reason:

Batch execution survives VPN or laptop disconnection and preserves exact
experiment artifacts. A UI is valuable for clarification and visualization
but should not delay the cross-engine execution evidence.

## D73 Federated runtime plans have explicit coordinator semantics

M15-B runtime plans are finite DAGs containing `RemoteQuery`, `Align`,
`Exchange`, `CoordinatorJoin`, and `Merge`. Independent remote nodes may run in
parallel. Descendants of a failed node are skipped, remote-call and parallelism
budgets are checked before execution, and transfer bytes are charged only at
explicit exchange nodes.

Per-backend semantic fragments compile independently through the existing M9
compiler boundary. The coordinator consumes normalized rows; it does not
reinterpret backend-internal physical plans.

Reason:

The original M11 state could describe multi-backend placement but could not
execute it. Explicit runtime and failure semantics provide the smallest
measurable cross-platform loop while retaining the existing compiler and
backend-client investments.

## D74 Remote readiness is evidence-gated before backend packaging

The M15 CWRU path first records a read-only login-environment probe and then
runs the deterministic coordinator smoke in a CPU Slurm allocation. Live
Neo4j/Fuseki packaging is selected only after the probe identifies an available
container runtime or establishes that native Java or approved persistent
services are required. A historical M13 H100 run does not count as M15 remote
verification.

Reason:

Pioneer login nodes must not carry experiment workloads, and availability of
Slurm or an H100 does not imply availability of Docker or a safe service
lifecycle. Separating B0, B1, and live-service gates gives every claim a
specific artifact and prevents environment assumptions from being reported as
experimental evidence.

## D75 Remote experiment control is typed, scoped, and non-retrying

The `remote.executor` tool represents stage, submit, status, bounded-log,
artifact-fetch, and cancel as typed operations. Staging verifies a clean
checkout and the exact full commit fetched from an explicit branch. Slurm
scripts are allowlisted, remote and local paths remain below configured roots,
and SSH credentials stay in the user's SSH configuration. Cancellation is
unavailable unless separately enabled and the job ID is repeated as a
confirmation. A failed operation returns one recorded error and is never
silently retried.

Reason:

Scheduling and experiment transport are agent actions with measurable latency
and failure behavior, but they are not database-internal physical operators.
A narrow tool contract lets the same coordinator drive OnDemand/Slurm today
and a thin UI later without granting an LLM a general remote shell or hiding
failed experimental attempts.

## D76 Native service supply is pinned and separate from runtime state

The CWRU native-service path uses one common Java 17 module, Neo4j Community
5.26.30 LTS, and Apache Jena Fuseki 5.6.0. The versions, official HTTPS URLs,
archive lengths, digests, and extract roots are frozen in
`services/m15-native-runtime.lock.json`. Archive preparation is a separate,
explicitly gated batch action. It makes at most one request per missing
archive, publishes only after exact validation, never overwrites an invalid
existing cache entry, and never extracts or starts a service.

Verified archives may reside on shared storage. Extracted binaries, logs, and
database state for a live run must reside on allocation-local storage and are
destroyed only by the job-owned lifecycle. The Java version is parsed and
checked rather than inferred from command presence. Jena 6 is not selected
because the observed CWRU module inventory stops at Java 17, while Jena 5.6 is
the final Java-17 release and Neo4j 5.26 LTS supports Java 17.

Reason:

The real B2 probe found an inherited Java 8 executable and an NFS-backed home
directory. Treating those as a runnable database environment would make the
deployment neither correct nor reproducible. A shared compatible runtime
avoids an unnecessary third binary dependency, while separating immutable
archives from ephemeral database state respects backend filesystem
requirements and leaves every network or integrity failure visible.

## D77 Native service archives are staged through a job-owned trust boundary

The live B2 path never extracts an archive directly into shared storage or an
existing directory. Before extraction, XGAP re-verifies the frozen byte length
and digest and inspects every tar member. Members must be regular files or
directories below the single locked product root; absolute paths, traversal,
backslashes, duplicate names, links, devices, special files, excessive member
counts, and excessive expanded size are rejected. Extraction creates files
exclusively in a private temporary directory and publishes the finished
product root by rename only after the complete pass succeeds.

The destination must be an absolute, existing, empty, non-symlink directory
owned by the current allocation. The durable staging manifest must live
outside that ephemeral directory and records the first failure, verified
archive provenance, extracted member counts and bytes, Java requirement, and
zero automatic retries. A later service launcher must separately prove that
the destination filesystem is allocation-local before using these staged
binaries or creating database state.

Reason:

An exact archive digest establishes artifact identity but does not by itself
make archive extraction or database placement safe. Keeping verification,
staging, service lifecycle, and query execution as distinct evidence gates
prevents a malformed archive, shared-filesystem path, or partial extraction
from silently becoming experimental state.

## D78 The two native backends share one allocation-scoped lifecycle

M15-B2D starts Neo4j and Fuseki as black-box operating-system processes inside
one Slurm CPU allocation. The wrapper loads the exact Java 17 module, chooses
only `SLURM_TMPDIR` or `/tmp`, records the mounted filesystem, and accepts only
an explicit local-filesystem allowlist. Three ephemeral loopback ports are held
until immediately before their owning service starts. Neo4j receives a copied
job-local configuration with all data, transaction, log, run, import, and
plugin paths below the ephemeral root. Fuseki uses a job-local `FUSEKI_BASE`
and the archive-verified command contract `--localhost --ping --update --mem
/xgap`. Neither backend exposes a public port or requires a persisted secret.

Readiness probes may poll the same live process within a fixed deadline, but a
failed service is never restarted. After one fixture load and one federated
run, processes are stopped in reverse order by their job-owned process groups;
SIGKILL is permitted only after a bounded SIGTERM wait and is recorded. Logs,
configuration, health, shutdown, fixture, and query evidence are copied to the
durable run directory before the shell removes only the validated job-owned
runtime path.

Reason:

The backend boundary is the public Neo4j and Fuseki interface, not an internal
engine hook. A single allocation keeps coordinator traffic local, makes port
and process ownership unambiguous, and permits exact cleanup without turning
service bootstrap into an agent-visible general shell tool. Separating bounded
readiness polling from process restart also preserves failed startup attempts
as experimental evidence.

## D79 A live-run claim requires a read-only cross-artifact audit

A completed M15 native-service allocation is not accepted from its Slurm exit
code or outer status alone. The read-only `m15_native_evidence` audit binds the
full Git commit, frozen runtime lock, archive sizes and digests,
allocation-local staging record, exact Java version, loopback-only service
plan, generated Neo4j configuration, health and shutdown records, fixture
load, federated result, and guarded cleanup into one verdict. It also requires
the service manifest to contain exactly the plan, health, and shutdown records
stored in their separate files. The audit writes no output below the completed
run tree; any report must be placed in a separate evidence directory.

The Slurm lifecycle snapshots the exact runtime lock into the immutable run
directory before staging. Failed checks remain individually visible and do
not trigger a retry, restart, repair, or mutation of the original run.

Reason:

An exit code can remain zero while a copied manifest, source artifact, service
configuration, or answer is inconsistent. Cross-artifact validation makes the
real Neo4j-plus-Fuseki claim reproducible and tamper-evident without treating
the auditor itself as part of the measured query path.

## D80 Observation tools select frozen artifacts, not arbitrary query text

Schema inspection, sampling, explain, and profile are exposed through a
versioned coordinator-owned catalog. An observation action selects a registered
artifact ID and cannot provide native query text or extra payload fields.
Neo4j native plans and profiles are stored as black-box evidence; they never
become XGAP physical operators. An engine without a native explain interface
returns `unavailable`; profile may use measured execution of the registered
read-only artifact when that fallback is declared in the result.

Reason:

The agent needs bounded information acquisition, not a second unrestricted
query channel. Catalog ID, version, artifact digest, observation mode, rows,
and elapsed time make every estimate attributable while preserving the public
backend boundary.

## D81 Physical selection occurs only within one exact semantic class

The M15-C selector accepts candidates only when they share one explicit
semantic-equivalence key. It estimates critical-path latency and exchange bytes
from one frozen, versioned observation snapshot and uses deterministic tie
breaking. It does not compare relaxed interpretations, trade semantic
deviation against execution cost, or use backend-native plan nodes as its
search states.

Reason:

Choosing a physical representative and choosing among semantic interpretations
are different decisions. Keeping them separate prevents a cheap semantic
deviation from being mislabeled as query optimization and leaves future Pareto
selection auditable.

## D82 Bind and semi joins are explicit bounded coordinator strategies

`RemoteBindQuery` consumes one driving relation, deterministically deduplicates
one declared binding field, refuses non-scalar/null values and lists above a
fixed bound, and never overwrites an existing query parameter. Empty bindings
short-circuit with zero backend calls. `CoordinatorSemiJoin` retains matching
left rows without importing right-side columns. Failures skip every transitive
descendant, including chains longer than one edge.

Reason:

These strategies make cross-platform scheduling materially nontrivial without
claiming access to Neo4j or Fuseki internals. Explicit bounds and accounting
also prevent a data-dependent bind step from hiding uncontrolled calls or
transfer work.

## D83 Cross-task plan memory is append-only and version-addressed

Experiment execution memory may use a single-writer JSONL store. Every put
appends the full typed record and fsyncs it; reopening reconstructs the current
value without deleting the replacement history. Federated observation
snapshots use keys containing both snapshot ID and version, and an existing
live version cannot be silently overwritten.

Reason:

An in-process dictionary cannot support cross-task adaptation or post-run
audit. Append-only JSON records remain inspectable and make stale versus
updated estimates explicit without introducing a database dependency into the
coordinator.

## D84 Replanning reuses an exact common prefix and is bounded to one change

The initial adaptive executor permits at most one within-query plan change. A
probe plan must be ancestor-closed and every probe node must be structurally
identical in every candidate before any tool is invoked. Successful prefix
results seed the chosen continuation and retain their remote-call and transfer
accounting; they are not executed again. A failed probe terminates the adaptive
run without an implicit fallback.

Reason:

Re-executing a probe would disguise retry cost as optimization, while reusing a
semantically different prefix could corrupt the answer. One explicit change is
enough to test memory-guided adaptation and gives the experiment a finite,
auditable replan budget.

## D85 Cost snapshots require a complete declared observation tuple

Plan-cost evidence is collected only from registered `profile` or `sample`
artifacts. The collector validates request identity, uniqueness, and all local
cost parameters before invoking a backend. It then executes the finite request
tuple once in declared order. The first unavailable, erroneous, malformed, or
raised observation terminates collection, retains the partial tool results,
and produces no snapshot.

Reason:

A partially populated snapshot can make an arbitrary candidate appear cheaper,
while implicit retries hide planning overhead. Complete, provenance-bearing
snapshots let the experiment report observation cost separately from query
execution and make missing backend capabilities explicit.

## D86 Live adaptive validation is a separate workload mode

The native-service runner keeps the already audited `vertical_slice` mode as
its default and adds an explicit `adaptive` mode. The adaptive mode loads the
same split fixture, performs three registered profile calls, persists the
complete snapshot, runs one two-call adaptive query with at most one replan,
and preserves both snapshot versions. It has its own run schema, Slurm entry
point, and read-only evidence-audit branch.

The current bandwidth, exchange, and coordinator-row constants are labeled as
fixed development configuration with `calibrated=false` and
`paper_result=false`.

Reason:

Changing the old service job in place would blur the evidence boundary of the
verified vertical slice. A separate mode allows live control-path validation
without presenting fixture-scale timings or hand-set cost constants as a
performance result.

## D87 Scaled federation workloads are generated from frozen bounded specs

M15-F0 commits small, strict workload specifications rather than generated
database dumps. A deterministic generator materializes namespaced Neo4j and
Fuseki load/query artifacts, per-source oracles, and the exact federated answer
inside a new run directory. Every member is bound by SHA-256 in a no-overwrite
manifest. The loader, adaptive runner, and evidence auditor reopen and validate
that bundle instead of trusting an in-memory object. The auditor additionally
binds the declared `selective` or `broad_hot` profile to its exact committed
specification. Configurations with an empty federated answer are rejected.

The existing tiny `vertical_slice` and `adaptive` modes remain unchanged.
Scaled execution uses an explicit `scaled_adaptive` mode, a separate run schema
and Slurm entry point, and remains `paper_result=false` until CWRU execution,
calibration, repetitions, and comparative baselines are complete.

Reason:

Committing large generated files would make scale changes difficult to audit,
while generating unbound data would weaken reproducibility. Frozen parameters
plus deterministic, hash-bound run artifacts preserve exact provenance and let
selectivity/skew change independently of query semantics or hand-set costs.

## D88 Generated native load artifacts use target-language literals

The M15-F0 generator serializes Cypher load data with a dedicated deterministic
Cypher literal encoder. Map keys must be identifier-shaped and remain unquoted;
values are restricted to the bounded JSON-compatible scalar/list/map subset.
JSON serialization remains authoritative only for JSON artifacts. Changing the
native artifact bytes increments the generator version, and an earlier bundle
cannot be silently admitted under the new version.

Reason:

CWRU job `3787167` reached the Neo4j fixture stage but Neo4j 5.26 rejected the
first generated `UNWIND` value because the v1 generator embedded JSON objects,
whose quoted keys are not Cypher map syntax. Keeping separate serializers makes
the target-language boundary explicit and preserves the failed v1 bundle as
diagnostic evidence rather than rewriting it.

## D89 M15 task methods remove explicit agent mechanisms

Cross-task plan memory is reusable only when one SHA-256 context fingerprint
matches the semantic-equivalence key, complete candidate DAGs and native
artifacts, declared observation tuple, cost-model parameters, workload
manifest, and observation catalogs. A full-agent cold task profiles the
complete tuple and persists it; a compatible warm task skips those profiles,
runs one exact common-prefix probe, updates memory, and permits at most one
plan change.

The controlled comparison surface contains two fixed-plan static baselines,
`no_memory` (re-profile every task), `no_profile_probe` (use frozen compatible
memory without current observation), `no_replan` (observe the same probe but
keep the initial plan), and `full_agent`. Each policy serializes its enabled
actions and reports profile, probe, query, memory, LLM, ontology, latency,
transfer, and replan counts. A missing or incompatible warm snapshot fails
before a backend call. A common pre-task calibration is reported separately
and is not silently included in one method's measurements.

Reason:

The earlier live adaptive gate always collected all profiles inside one run,
so reopening its JSONL file demonstrated durability but not useful memory
reuse across tasks. Explicit policies and a fingerprinted cold/warm boundary
make the memory and replanning mechanisms behaviorally distinguishable and
prevent named ablations from aliasing the full system.

## D90 Scaled native fixture writes use fixed, manifest-bound batches

Generated Neo4j load artifacts divide company and transfer rows into
deterministic batches of at most 100 map literals. The bundle manifest declares
the batching strategy, size, and resulting statement count, and the loader
recomputes that contract from the hash-bound workload specification. Every
statement still has one attempt; request deadlines and query semantics are
unchanged. Changing this native load protocol increments both the generator and
bundle schema versions.

Reason:

CWRU job `3787173` proved that generator v2 fixed Cypher syntax and that both
services became healthy, but its sixth and final Neo4j statement put all 5,000
transfers in one HTTP request and timed out after the preceding five statements
had succeeded. Fixed-size generation makes request work bounded and auditable
without disguising the failure through a larger timeout or an automatic retry.

## D91 A single scaled success closes an engineering gate, not a paper claim

The first successful selective run is accepted only when the exact clean Git
commit, generated workload, service lifecycle, load reports, adaptive result,
oracle, cleanup, and an external read-only audit agree. It establishes that the
scaled pipeline can execute on real Neo4j and Fuseki. It does not estimate a
latency distribution or support a comparison because it has one repetition,
fixed development cost constants, one workload regime, and no counterbalanced
baseline matrix.

Reason:

CWRU job `3787213` passed all 188 independent checks after two informative
failed attempts. Keeping the system-acceptance claim separate from a SIGMOD
performance claim allows implementation to advance without treating one warm
cluster observation as statistically meaningful evidence.

## D92 The first live method matrix is a mechanism gate with declared interference

The first real-service F1 matrix executes the six frozen method policies in a
fixed order inside one allocation and against one loaded selective workload.
One common three-observation calibration is persisted separately from method
metrics and seeds isolated append-only memory files for the three warm-memory
methods. Each method then has its own backend-event phase and exact-answer
artifact. The auditor requires 18 total tool invocations, the declared
per-method call budgets, compatible snapshot identities, all six oracle-equal
answers, zero retries, and an immutable run tree.

The manifest also declares that execution order is not counterbalanced and
that backend cache state is shared and unknown. Consequently this run can show
that static, no-memory, no-profile/probe, no-replan, and full-agent controls are
behaviorally executable on the same black-box services. It cannot support a
latency ranking or paper comparison; calibrated randomized repetitions require
a later scheduler and remain `paper_result=false` here.

Reason:

Running all policies in one service lifecycle is the smallest bounded test of
the complete experimental mechanism. Hiding shared cache or charging common
calibration to one policy would create a misleading comparison, while starting
with a full counterbalanced campaign before validating every trace would make
failures expensive and difficult to localize.

Job `3787267` subsequently closed this gate at exact clean commit `6aafafd`.
All six methods returned the exact answer, the complete phase trace contained
18 calls, cleanup succeeded, and the independent read-only audit passed
326/326 checks without run-tree mutation. The run did not remove the declared
interference and remains `paper_result=false`.

## D93 Paper-method scheduling is compiled and balance-checked before execution

M15-F2 represents a method campaign as a deterministic plan rather than a loop
embedded in a service runner. For the six frozen methods, each workload/block
uses the even-treatment Williams construction: six sequences give each method
every position exactly once and cover every directed first-order method
transition exactly once. A content seed deterministically permutes labels and
dispatch order. Each sequence declares a fresh Neo4j/Fuseki pair, common
calibration excluded from method metrics, separate per-method memory, explicit
warmup and measured attempts, and stop-without-retry failure behavior.

The compiler binds workload specifications, validates the complete method set
and expansion budget, proves balance, and makes zero external calls. Its output
is always an unexecuted plan with `paper_result=false`. The initial development
schema intentionally identifies query streams only by label, so it cannot
become paper-ready until those labels are replaced or supplemented by
hash-bound query artifacts. Fewer than 30 workload-query contexts and an
unfrozen inferential analysis also become explicit blockers rather than silent
defaults. A workload with fewer than two tasks is separately blocked because
it cannot measure the cross-task memory behavior claimed by the agent design.

Reason:

The F1L mechanism gate showed that all policies execute but also exposed fixed
order and shared-cache interference. Counterbalancing these effects must be a
verifiable input to execution, not a retrospective analysis choice. Keeping
the first compiler plan-only prevents an unrun schedule, an arbitrary
repetition count, or development query labels from being promoted into a
SIGMOD comparison.

## D94 Custom method order requires a complete compiled campaign binding

The F1L matrix keeps its historical fixed order by default. A caller may
change that order only by supplying an F2 binding containing the campaign ID,
campaign-spec hash, schedule hash, session and workload identities, block and
sequence positions, query IDs, measured task IDs, logical memory namespaces,
and the exact six-method order. The F2 session
preflight recompiles the campaign and matches the generated bundle's normalized
spec hash before any backend call. The native lifecycle repeats this preflight
before starting services and the matrix persists the same binding beside its
trace.

The first executor accepts only one declared development query and one session
per fresh backend allocation. It has no automatic retry and remains
`paper_result=false`; one sequence neither completes the Williams design nor
measures cross-task memory. The read-only auditor must reconstruct the selected
session from the committed configuration and match the wrapper, service, and
nested matrix artifacts.

Reason:

Allowing a free-form method list at the live runner would make the compiled
counterbalance unverifiable. Running the entire campaign before testing one
bound sequence would multiply lifecycle failures. The single-session gate
therefore validates the compiler-to-executor seam while preserving a hard
boundary around the still-unimplemented multi-query paper experiment.

## D95 One audited Williams sequence closes F2A but not the campaign

CWRU job `3787291` is accepted as the F2A compiler-to-live-runner engineering
gate. It ran exact clean commit `c9a7afe`, used the compiled selective
`b01.s01` method order, returned exact answers for all six methods, recorded 18
tool invocations with no automatic retry, cleaned up the native runtime, and
passed a 374-check independent read-only audit without mutating its run tree.

The run is not treated as a method comparison. It contains one query, one
workload, and one of the twelve development sequences; therefore it neither
completes Williams counterbalancing nor measures cross-task memory. The run
tree remains immutable, the compact repository artifact is
`paper_result=false`, and remaining session dispatch stays disabled until a
standalone resolved-query artifact contract replaces the current query label.

## D96 Query identity is a contract over semantics, artifacts, and oracles

F2B starts with a standalone resolved-query specification rather than adding
more query labels to the campaign. The specification records the resolved
intent, non-relaxable hard constraints, semantic operator IDs, output fields,
the three exact backend artifact roles and parameter contract, and the source
and final answer oracles. A side-effect-free compiler binds that specification
to an already verified workload bundle and hashes the complete portable
contract. The hash excludes the local source path but includes the query-spec
bytes, workload identity, generated query hashes, oracle hashes, and row
counts.

The F2A campaign configuration and audited job remain immutable. The first F2B
compiler is a local primitive and is not yet consumed by campaign/session
execution, so it does not remove the campaign's query-artifact blocker or
authorize the remaining eleven sessions. This version boundary preserves the
ability to re-audit job `3787291` against its exact v1 inputs while F2B wiring
is developed separately.

## D97 Layer query binding over the audited campaign instead of rewriting it

F2B2 introduces a separate query-bound campaign registry whose base inputs are
the exact F2A campaign-spec and schedule hashes. Every workload/query key must
have one registry binding containing a repository query-spec reference, its
expected source hash, and the expected bundle-dependent query-contract hash.
The compiler rejects incomplete coverage and any drift in the base campaign or
query specification, then adds contract references to all twelve sessions and
computes a new query-bound schedule hash.

The query-spec path is provenance, not experimental identity: it remains in
the registry output but is excluded from the portable binding and schedule
hashes. Identical content relocated within a repository therefore preserves
the query-bound schedule. The compiler freezes expected contract hashes but
does not claim they match a live generated bundle; that check belongs to the
next session preflight. The plan remains side-effect free,
`paper_result=false`, and cannot authorize remote dispatch by itself.

## D98 Recompute expected query contracts before the first backend observation

F2B3 adds a new direct live-session path rather than weakening the F2A v1
binding. Its preflight recompiles the query-bound campaign, checks the
caller-supplied registry and bound-schedule hashes, selects the exact session,
loads the verified workload bundle, recompiles each resolved-query contract,
and compares the observed query-spec and bundle-dependent contract hashes with
the registry. It then derives a v2 matrix binding containing the base campaign
identity plus registry, query-binding, bound-schedule, and per-query contract
identities.

The matrix accepts this larger field set only under its v2 binding schema. A
wrong expected contract is rejected before output creation or backend
healthcheck even when the registry and schedule agree with each other. Query
contract verification is a completed preflight fact and is not erased if a
later backend operation fails. The direct runner remains a local engineering
gate with no native service lifecycle or independent evidence audit; neither
remote dispatch nor a paper claim is enabled yet.

## D99 Audit query identity by recompilation, not by trusting run metadata

F2B4 adds `scaled_query_bound_session` as a separate native-service mode. The
mode requires the registry path, session ID, registry-spec hash, and
query-bound schedule hash together. After the deterministic bundle is
generated but before Java inspection or service startup, the native runner
recompiles the selected live-bundle contract through the F2B3 preflight. A
wrong or incomplete identity therefore creates no native-service run and
observes no backend.

The Slurm entry point is separately allowlisted and preserves allocation-local
state, loopback-only Neo4j/Fuseki, zero retry, and guarded cleanup. Its
read-only auditor independently recompiles the fixed query-bound registry and
the selected contract from the immutable run bundle, then compares the plan,
session, v2 binding, contract artifact, matrix namespace, service manifest,
and 18-call trace. This authorizes one CWRU engineering gate after a clean
commit is pulled; it does not authorize the other eleven sessions or convert
the result into comparative evidence.

## D100 Expand query/repetition products into explicit task and history contracts

F2C does not treat `query_ids × measured_run_ids` as an executable stream.
Before multi-query work can run, one selected query-bound session is expanded
in method-major order into unique tasks. Each task binds one logical run ID,
one query-spec hash, one bundle-dependent query-contract hash, one method, and
one phase. The query-stream hash covers the complete portable task order,
method policies, query identities, memory rules, expected counts, and design
validation; the compiler also recomputes the incoming query-binding and
session-schedule hashes instead of trusting their recorded values.

Memory visibility is frozen before each task. A method can read only eligible
predecessors in its own session/method namespace, filtered to successful exact
commits. Within-task writes are invisible, and a post-task commit is permitted
only for a policy that writes memory and only after both execution success and
exact-answer validation. Static and no-memory methods therefore cannot acquire
history accidentally, and one method can never observe another method's
history.

The current development session expands to six uniquely identified measured
tasks but still contains only one query. The compiler consequently reports
that cross-task memory is not ready: query instances are not parameterized,
there are fewer than two measured tasks per method stream, and no cross-task
transfer model is bound. This is a route-independent structural prerequisite,
not evidence that the existing exact-context snapshot cache learns across
queries. It makes zero external calls and remains `paper_result=false`.

Reason:

A count derived from a Cartesian product does not define task identity,
history visibility, or a causal update boundary. Those omissions would allow
memory leakage between ablations, within-task feedback, or duplicated query
labels to masquerade as cross-task learning. Freezing this protocol before the
query-family design keeps the A/B/C research choice author-owned while making
all three choices implementable and auditable.

## D101 Transfer planning memory only within a declared query family

The first paper design uses multiple parameterized query families. A family
fixes the resolved semantic/operator DAG shape, output schema, hard-constraint
schema and relaxability mask, backend artifact roles and parameter schema,
candidate-plan space, and compatibility-version inputs. Instances vary only
declared hard binding values and data/selectivity context. Those values remain
part of task identity and execution evidence, but are excluded from the stable
family key that gates memory reuse.

Planning memory is isolated by method and family. A task may read only prior
successful exact commits from the same compatibility key; it never searches a
global pool of heterogeneous query histories. Held-out instances of seen
families test within-family transfer. Entirely held-out families start cold and
test correctness, safe fallback, and planning overhead rather than being
silently mapped to a superficially similar family. A later hierarchical or
cross-family prior would be a separately named method, not an implementation
detail of `full_agent`.

The target benchmark remains 30--50 hand-verified query instances distributed
over multiple families. Exact family count, instance allocation, split seed,
repetition count, and inferential analysis must be frozen before paper runs.
Duplicating query labels or changing only an unbound label does not create a
new instance. Every instance must carry a distinct resolved binding contract,
oracle, and bundle-dependent contract hash.

Reason:

Family-local transfer gives the memory mechanism a defensible compatibility
boundary while still allowing binding-sensitive plan choices. It avoids the
weakness of a single-template benchmark and avoids claiming an unvalidated
global similarity model. It also makes a cold, previously unseen family an
explicit evaluation condition instead of an accidental cache miss.

## D102 The query-bound native identity chain is accepted end to end

CWRU job `3787430` closes the F2B4 engineering gate at exact clean commit
`d795fac`. The selective query-bound session completed on `compt348` with no
retry or service restart, both loopback-only services shut down cleanly, and
the outer runtime was removed. The independent read-only auditor recompiled
the registry and live-bundle query contract and passed 377/377 checks with no
failed IDs and no run-tree mutation.

This result validates the identity and lifecycle chain only. It contains one
query and one Williams sequence, so it is not counterbalanced comparative
evidence, does not measure cross-task memory, and does not authorize the other
eleven development sessions. The next remote experiment must consume the F2C
family/instance and explicit task-stream contracts rather than repeat the old
single-query schedule.

## D103 Family labels never define memory compatibility by themselves

F2C1 compiles each family key from its ordered semantic-operator IDs, output
schema, hard-constraint schema and relaxability mask, backend artifact
interfaces, candidate strategy space, and explicit compatibility versions.
The family ID is descriptive and is not part of this key. Two differently
named families with the same structural key are rejected, as is any instance
whose verified query specification drifts from the declared structure.

Concrete hard values are hashed into instance identity but excluded from the
family key. Duplicate hard bindings inside one family are rejected because a
renamed query is not a new parameterized instance. Query-spec paths remain
provenance and are excluded from the portable family-plan hash. Seen-family
evaluation reads one snapshot frozen after successful exact seed commits and
cannot write during evaluation. Held-out families receive an empty snapshot;
all cross-family reads are prohibited.

The current query specification exposes an operator-ID sequence and artifact
interfaces, not a fully typed operator DAG or literal-free backend template.
The compiler therefore records those missing bindings along with workload,
oracle, family-count, instance-count, split, and analysis blockers. Its
one-family development registry proves fail-closed routing only and remains
`paper_result=false`.

## D104 Version semantic policy instead of rewriting audited query evidence

F2C2 introduces a separate v2 parameterized query specification. It does not
modify the v1 resolved-query specification, F2B4 contract, or CWRU job
`3787430`. In v2, the clarified entity identity, time lower bound, and amount
lower bound are hard constraints and cannot be relaxed. Risk level, transfer
predicate, and direct path shape are relaxable only through their declared
bounded transformations: one ontology-adjacent risk step, one ontology-sibling
predicate step, and at most two bounded path-expansion steps. The exact
interpretation is the zero-relaxation instance; later alternatives must be
compared on semantic deviation and execution cost rather than relabeled as
exact answers.

The compiler materializes a typed semantic operator DAG and verifies complete
binding coverage across both semantics and backend artifact interfaces.
Artifact parameters distinguish runtime values, compile-time query-template
choices, and runtime intermediate bindings; their declared types must match
the source binding-slot kinds. Concrete values and descriptive family/template
labels are excluded from the structural family compatibility hash. Query IDs
and resolved-intent prose remain provenance rather than identity: only the
family key, concrete binding values, and bound typed program define a query
instance, so renaming a label cannot manufacture a new instance.

This closes the typed-template contract only. The declared Cypher/SPARQL
interfaces are not yet bound to literal-free query files, a multi-instance
workload bundle, or source/final oracles. F2C2 performs no backend, LLM, or
ontology call, contains no measurement, remains `paper_result=false`, and does
not authorize a CWRU submission. F2C3 must bind those executable artifacts
before the v2 family can enter a task stream.

## D105 Parameterized instances share data but own bindings and oracles

F2C3 binds the v2 typed financial-risk family to three literal-free backend
templates and one deterministic shared data snapshot. Runtime person, date,
and amount values remain Neo4j parameters. Transfer predicate and path shape
are compiled only through closed mappings because Cypher relationship and path
syntax is not a value parameter. Risk is safely compiled into the SPARQL
artifact. The bound Neo4j query receives company IDs only as a declared
runtime intermediate produced by alignment of the Fuseki result.

The development workload contains four resolved person identities, 30
companies across three risk levels, and 720 dated transfers. Its six query
instances comprise four seeds and two held-out instances. All six share the
F2C2 family compatibility key, have distinct semantic binding identities, and
carry their own compiled artifacts, stage-separated binding record, source
oracles, and final oracle. Renaming an instance with unchanged bindings is
rejected as a duplicate. The bundle is recursively hash-bound and the loader
regenerates every artifact from its included inputs, so changing a file and
its recorded digest together still fails deterministic validation.

This bundle executes only the zero-relaxation interpretation. It does not yet
enumerate relaxed interpretations, calculate semantic deviation, or produce a
Pareto set. It also remains one development family rather than the final
30--50-instance, multi-family benchmark. F2C3 makes no external call and is
`paper_result=false`; F2C4 must connect its parameter and oracle contracts to
the coordinator/native-service task path before a new CWRU gate is admitted.

## D106 Exact parameterized execution precedes memory and relaxation experiments

F2C4 admits the six v2 instances through an explicit seed-then-held-out task
stream and executes both exact physical strategies for every instance. The
parallel plan reads the full transfer and risk fragments; the bind plan first
aligns the risk fragment and passes canonical company IDs into the declared
Neo4j runtime-intermediate parameter. Both plans use the same semantic
equivalence key, carry zero semantic deviation, and must match each instance's
final oracle in exactly two backend calls.

Namespace alignment is compiled from the workload's declared company-ID domain
and backend prefixes. It is never inferred from source or final answer oracles.
The fixture verifier may read source oracles only after the plans and artifacts
already exist, and its calls are recorded outside the task-stream execution
totals. A new additive native mode generates the hash-bound bundle inside one
fresh Slurm run, starts loopback-only Neo4j and Fuseki, loads the shared data
once, verifies all twelve source fragments, executes twelve plan runs, and
shuts down with zero retry. A separate read-only auditor checks every task,
plan, result, call, lifecycle artifact, and identity edge.

This milestone proves executable parameter variation and exact-plan
equivalence only. Memory is deliberately disabled, no strategy is selected by
an oracle, and no relaxation, Pareto ranking, LLM, or ontology call occurs.
Consequently the local implementation may authorize one CWRU engineering gate
after a clean commit, but remains `paper_result=false` and cannot support a
cross-task-memory or performance claim.

## D107 Family transfer is a distinct memory model, not an exact-context cache

F2C5 does not relax the identity checks on the existing plan-snapshot cache.
That cache remains valid only for the exact semantic, artifact, observation,
cost, workload, and catalog fingerprint that created it. Cross-query transfer
uses a new memory context keyed by method namespace, structural query-family
compatibility, workload bundle, and runtime compatibility. A record contains
typed query bindings and measured per-strategy latency, bytes, and call count;
it deliberately contains no answer rows or source/final oracle data.

Only a seed task whose complete candidate set executed successfully and
matched the exact answer may append one observation. Before evaluation, the
store is reopened and a single immutable view is frozen over explicitly named
successful seed predecessors. Held-out instances may read that view but may
not write, and current/future, cross-method, cross-family, cross-workload, and
cross-runtime records fail closed. The exact-answer oracle is available only
after a plan has executed as a correctness gate; it is never an input to
feature extraction or plan selection.

The first development policy uses a transparent Gower-distance KNN over typed
bindings and selects by predicted elapsed time with predicted bytes as a
deterministic tie-breaker. It is an executable reference policy, not the
frozen paper model. Seed tasks measure both exact strategies. A held-out task
executes the selected plan first; the alternate plan is optional post-decision
evaluation shadow traffic and cannot affect selection or memory. This local
slice proves the temporal and compatibility protocol, not transfer benefit:
it has one family, four seeds, two held-out instances, an order-confounded
shadow diagnostic, no preregistered analysis, and remains
`paper_result=false`.

## D108 Native family transfer is allocation-scoped and independently audited

F2C5 memory compatibility includes the structural family, workload bundle,
method namespace, and an allocation-scoped native runtime identity. That
runtime identity is derived from the Slurm allocation, local filesystem type,
Java major, frozen runtime-lock and staging-manifest hashes, and sorted
Neo4j/Fuseki product versions. Paths and loopback ports are excluded because
they are ephemeral, while the allocation ID deliberately prevents measurements
from one service lifecycle being treated as reusable observations in another.

The dedicated native mode loads and verifies the shared six-instance bundle,
measures both exact plans for each of four seed tasks, commits four append-only
records, reopens and freezes the store once, and lets both held-out instances
select from only that view. Selected plans execute before alternate-plan
evaluation shadows. The independent read-only auditor recomputes the runtime
and family context, binds each stored cost back to its seed result, validates
the memory and selection content hashes, rejects answer rows in memory, checks
that neither held-out task wrote, and separates the 16 calibration, four online,
and four shadow backend calls.

This is a mechanism acceptance design. The development Gower-KNN remains a
replaceable reference policy, the shadow order is confounded, and the workload
contains only one family with four seed and two held-out instances. A passing
CWRU run will therefore close native transfer plumbing only; it will not prove
transfer benefit, latency superiority, or paper readiness.

## D109 Build a bounded semantic solution space before binding relaxed execution

F2C6 treats semantic relaxation as a controlled optimizer input, not as an
unconstrained LLM generation step. The clarified entity identity, time lower
bound, and amount lower bound remain immutable. Risk level, transfer predicate,
and path shape may change only through cataloged transitions whose
transformation is declared by the typed query constraint, whose step count is
within that constraint's maximum, and whose evidence reference is explicit.
Every resulting binding is recompiled through the parameterized typed-DAG
contract; any structural family drift or hard-binding mutation fails closed.

The development deviation metric is the uniform mean of normalized relaxation
steps across relaxable dimensions. This transparent metric is sufficient to
test the mechanism but is not a frozen paper weighting. Equivalent semantic
signatures are merged before physical planning, and each equivalence class
keeps only the successful plan with minimum latency, then resource cost, then
plan ID. Standard three-objective Pareto reduction is followed by a
semantic-preserving epsilon rule: a semantically worse alternative is removed
when its latency and resource gains over a less-deviated alternative are both
below the configured minimum. Exact semantics are retained, and deterministic
cost extremes plus normalized max-min coverage bound the returned set to K.

The selected development catalog yields 12 raw interpretations and 12 semantic
classes for the HIGH-risk reference instance. Its ontology, mapping, and path
policy entries are fixtures, not runtime calls or an ontology dependency. This
milestone validates bounded enumeration, equivalence reduction, and frontier
cardinality only. It does not yet execute relaxed backend templates, validate
semantic answer quality, freeze epsilon/K/weights, or support a performance
claim; all outputs remain `paper_result=false`.

## D110 Accept native family transfer as a mechanism gate only

CWRU job `3787610` closes the F2C5 native mechanism gate at exact clean commit
`30214cb`. It completed on `compt298` in 69 seconds with exit code 0, preserved
the declared parameterized-family-transfer mode, removed its allocation-local
runtime, and reported no cleanup error. The dedicated independent read-only
auditor passed 278/278 checks with no failed IDs and no run-tree mutation.

The accepted evidence proves the native lifecycle, four exact seed commits,
one reopened frozen family-local memory view, two oracle-free held-out choices,
selected-before-shadow execution, exact post-execution answers, and separated
16 calibration, four online, and four shadow backend calls. It does not prove
that the selected plan was faster. In fact, the development KNN selected zero
of two post hoc observed latency winners: it chose parallel hash where the
later risk-first shadow was faster for Alice, and risk-first where the later
parallel shadow was faster for Bob. Both selected answers were exact. The
alternate execution is an order-confounded post-selection diagnostic, the KNN
is a replaceable development policy, and the workload contains one family with
only two held-out instances. The result must be preserved rather than tuned
against; no transfer-benefit or comparative paper claim is enabled.

## D111 Audit execution coverage before extending relaxed backend semantics

F2C7 first compiles a readiness matrix against the verified F2C3 bundle rather
than assuming every F2C6 interpretation is executable. For the selected HIGH
risk instance, one exact class is already materialized, one risk-only
HIGH-to-MEDIUM class is supported by the existing templates, data, and oracle
generator, and ten classes are blocked. Six classes require a versioned
payment-predicate mapping/data/oracle extension; eight require a multihop
semantic definition plus backend template, data, and oracle support, with four
classes blocked by both dimensions.

Only the readiness-approved risk class is materialized into a new overlay
bundle. The base bundle is immutable, its Neo4j and Fuseki load artifacts are
byte-identical in the overlay, and the new typed instance preserves person,
time, amount, predicate, and direct path while changing risk from HIGH to
MEDIUM. Its independently generated final oracle contains 11 rows. Unsupported
predicate and path classes are not materialized. This validates artifact
generation and oracle binding only; no relaxed backend query has executed, no
human semantic-quality judgment has occurred, and all artifacts remain
`paper_result=false`.

## D112 Isolate the first live relaxation gate from plan learning

F2C7B2 executes only the single readiness-approved HIGH-to-MEDIUM risk class.
It regenerates the verified base bundle, copies the exact development semantic
catalog into the run tree, materializes the overlay, and then loads the
overlay's seven-instance shared dataset into fresh allocation-local Neo4j and
Fuseki services. The fixture phase verifies all seven source-query pairs. The
semantic phase executes exactly one `risk_first_bind_join` plan, makes one
Fuseki and one Neo4j call, and compares the final answer with the independently
generated 11-row relaxed oracle only after execution.

The physical strategy is fixed as a mechanism-gate input. No KNN, memory,
ontology service, LLM, oracle-based selection, alternate-plan shadow, retry,
or comparative measurement is admitted. Plan metadata carries the positive
semantic deviation, semantic-class ID, base and relaxed query identities, and
overlay hash. A dedicated read-only auditor reconstructs the overlay and plan,
checks the native lifecycle and full artifact graph, and rejects answer, plan,
class, hash, call-trace, or cleanup drift. Local acceptance passes 814 tests
with 36 explicitly gated skips at implementation commit `0aefb87`.

CWRU job `3787648` then ran exact clean documentation commit `2197aef` on
`compt386` in 81 seconds. It preserved all three hard bindings, executed the
single HIGH-to-MEDIUM class with semantic deviation one-third, made exactly two
remote calls, moved 3,963 bytes, and returned the independently generated 11
rows. The dedicated audit passed 133/133 checks with no failed IDs or run-tree
mutation. This closes only the real-backend mechanism gate; semantic usefulness
has not been human-validated, no physical strategy was compared, and all
outputs remain `paper_result=false`.

## D113 Give predicate relaxation a versioned data family

F2C8 does not reinterpret every transfer edge as a payment edge and does not
add `payment_to_company` to the frozen F2C3 generator's global capabilities.
Either shortcut would make earlier readiness evidence false or turn a declared
ontology-sibling transition into an accidental synonym. Instead, F2C8A binds
the existing catalog transition to a separately versioned development mapping,
a closed Neo4j relationship type, and an independently generated payment-edge
family. The mapping evidence remains explicitly a development fixture; no
ontology service is called and no claim of domain truth is made.

The cumulative overlay preserves the base bundle externally and regenerates a
new runnable bundle whose Neo4j load is the exact frozen base prefix followed
by fixed 100-edge payment batches. Its Fuseki data, templates, and all six base
instance artifacts remain byte-identical. It materializes the three non-exact
direct classes: risk-only, predicate-only, and their combination. Together with
the base exact class, this binds all four direct interpretations and leaves all
eight bounded-multihop interpretations blocked. Person identity, time, and
amount bindings remain immutable in every class.

The bundle reuses the ordinary parameterized coordinator plans and fixture
boundary after its format-specific deterministic loader has verified every
file and manifest. Local doubles execute both physical plans for all three
added classes and return the 11-, 6-, and 9-row oracles. This proves artifact
and execution plumbing only. It makes no live backend, LLM, or ontology call,
does not measure semantic usefulness, and cannot authorize a CWRU job until a
dedicated native runner and independent auditor exist. All outputs remain
`paper_result=false`.

## D114 Execute predicate relaxation as a two-class mechanism gate

F2C8B executes only the predicate-only and risk-plus-predicate direct classes.
The risk-only class is not repeated because F2C7B2 already covers it, and all
multihop classes remain blocked. Both admitted classes bind the same declared
transfer-to-payment development transition and preserve person identity, time,
and amount. Each receives exactly one fixed `risk_first_bind_join` plan. This
requires two physical runs and four backend calls in deterministic
Fuseki/Neo4j order; it is not a physical-strategy comparison.

The runner constructs both plans and their execution contracts before opening
any answer oracle, then uses the 6- and 9-row oracles only for post-execution
validation. A failed plan stops the gate immediately; no second-class
execution, retry, service restart, memory read/write, LLM call, or ontology
call is allowed after failure. The native mode revalidates the cumulative
predicate overlay at the fixture boundary, starts fresh loopback-only services,
and delegates cleanup to the allocation wrapper.

A separate read-only auditor reloads the base bundle, catalog, mapping, and
overlay, reconstructs both expected plans and answers, and checks the complete
outer job, service, fixture, call trace, shutdown, and cleanup chain. Its local
synthetic run-tree test passes 150 checks and detects answer and plan-identity
tampering. Full local acceptance passes 834 tests with 36 environment-gated
skips.

CWRU job `3790680` then ran exact clean commit `2d39c3c` on `compt295` in
96 seconds. The predicate-only and risk-plus-predicate classes returned their
exact 6- and 9-row oracles in two calls each, moving 2,767 and 3,495 bytes.
The aggregate trace contains exactly four remote calls and 6,262 moved bytes.
The dedicated audit passed 150/150 checks with no failures or run-tree
mutation. This closes the live direct-predicate mechanism gate only; the fixed
strategy, development mapping, and post-execution oracle prevent semantic
utility, latency ranking, ontology-truth, or paper claims.

## D115 Select a capability-aware direct semantic frontier from sealed estimates

F2C9A exposes the mismatch between the declared semantic search space and the
current executor instead of silently treating every interpretation as
executable. The 12-class solution space is partitioned into four verified
direct classes and eight unavailable multihop classes. Only the direct classes
enter physical planning. Each receives both existing federated strategies, so
the candidate set contains eight physical plans and preserves the unavailable
class identities plus their explicit capability reason.

Online selection accepts only a complete, hash-bound estimate snapshot sealed
before execution. Its closed evidence kinds are controlled pre-execution
fixtures, family-memory predictions, and backend-observation predictions. The
contract rejects answer-oracle fields, observed-execution evidence, incomplete
or duplicate plan coverage, candidate/runtime-plan drift, and post-seal hash
changes. It first keeps the minimum predicted-latency plan per semantic class,
using predicted resource cost and plan ID only as tie breakers, then applies
the existing semantic-deviation/predicted-latency/predicted-resource Pareto,
5% epsilon, and maximum-K policy. Exact semantics must remain first.

The deterministic readiness fixture reduces eight candidates to four physical
representatives. All four are Pareto-optimal; the predicate-only class is then
removed because its 4% latency and 3% resource gains over exact semantics are
below epsilon, leaving three representatives under K=4. These values are
constructed estimates used to validate control flow, not measured costs or a
recommended semantic trade-off. The selector makes no backend, LLM, ontology,
or oracle call and remains `paper_result=false`. F2C9B must connect this sealed
frontier to one native execution gate before any live frontier claim exists;
multihop remains excluded until its hard-constraint semantics are author-owned.

## D116 Execute only the sealed direct frontier in the next native gate

F2C9B carries the F2C9A selector into the native lifecycle without learning
from the execution it is about to evaluate. A committed, versioned controlled
estimate source must cover all eight direct physical candidates exactly once.
The runner reconstructs the candidate set, binds and hashes the complete
estimate snapshot, applies physical/Pareto/epsilon/K reduction, and persists
all four artifacts before any answer oracle is opened or backend call is made.
Only the three returned semantic plans may execute, in deterministic rank
order. The first failed external call terminates the gate; automatic retry,
fallback, shadow execution, memory updates, LLM calls, and ontology calls are
forbidden.

The admitted local control executes exact, combined risk-plus-predicate, and
risk-only semantics with one risk-first physical representative each. It
therefore expects three plan runs, six backend calls in Fuseki/Neo4j pairs, and
post-execution oracle row counts 11, 9, and 11. The dedicated native mode and
Slurm wrapper use fresh loopback-only services, revalidate the cumulative
predicate fixture, and require guarded allocation-local cleanup. An
independent read-only auditor reconstructs the full frontier and answer chain;
its synthetic run tree passes 211 checks and detects frontier or answer
tampering.

This is a mechanism gate. The cost values are constructed pre-execution
predictions designed to exercise the selector, so even a successful CWRU run
cannot establish latency superiority, user semantic utility, or appropriate
epsilon/K values. Exactly one CWRU run is authorized. The eight multihop
classes remain unavailable until the user freezes their hard-constraint and
answer semantics.

## D117 Use family memory as the primary F2C10 prediction source

The author selected family-memory prediction for the first non-controlled
direct semantic frontier. F2C10 will predict latency and transferred bytes
from successful, exact, same-family training executions frozen before a held-
out query is opened. It will make no current-query profile, sample, explain,
ontology, or LLM call. Current-query backend observations remain a later
baseline rather than a hidden fallback, and the F2C5 development KNN remains
diagnostic rather than being promoted or tuned against its two held-out
results.

A zero-call compilation then exposed that the F2C9 four-class/eight-plan
contract is specific to HIGH and LOW base risk values. A MEDIUM base value has
two catalog-adjacent alternatives, HIGH and LOW, producing six direct classes
and twelve physical plans. The current development split contains a MEDIUM
instance in both seed and held-out partitions. F2C10 therefore remains gated
on an author-owned choice between preserving every adjacent interpretation and
generalizing F2C9, choosing one directional MEDIUM relaxation, or excluding
MEDIUM queries. No option is inferred from implementation convenience.

## D118 Preserve every catalog-adjacent direct interpretation in F2C10

The author selected the preserve-all cardinality policy. F2C10 must retain
every direct interpretation admitted by the frozen semantic catalog: HIGH and
LOW base risks each produce four semantic classes and eight physical plans,
while MEDIUM produces six semantic classes and twelve physical plans. The
implementation must not choose one MEDIUM direction for convenience or remove
MEDIUM queries from the predeclared population.

Candidate enumeration is therefore variable-cardinality and catalog-driven.
The existing F2C9 v1 four-class/eight-plan artifacts remain immutable evidence
for their HIGH-risk mechanism gate; F2C10 introduces a separately versioned
generalized contract. Candidate growth is bounded only after enumeration:
minimum predicted-cost physical reduction per semantic class, followed by the
already approved Pareto, epsilon-dominance, and maximum-K semantic selection.
Entity identity, time lower bound, and amount lower bound remain hard; all
multihop interpretations remain unavailable. This is a design decision, not a
semantic-utility or performance result.

## D119 Make F2C10 family memory a sealed, strategy-conditioned predictor

F2C10B implements the author-selected primary estimator without a hidden
current-query observation path. A complete training memory view admits every
training semantic task and both of its physical strategies only after each
raw repetition is successful and exact. Repetitions retain block and order
metadata and must be counterbalanced within each task. The frozen view rejects
held-out task IDs, answer rows, oracle inputs, incomplete plan coverage,
failed runs, duplicate records, and recomputed content drift.

For a held-out direct interpretation, the development predictor uses typed
amount, person, risk, date, and predicate features. Neighbors are restricted
to the same physical strategy; per-plan raw repetitions are reduced by the
median before inverse-distance weighted latency and transferred-byte
prediction. Weighted mean absolute deviation is persisted as uncertainty.
Every output binds the model configuration, complete ordered training memory,
target query/class/plan identity, and an empty oracle/current-query-observation
boundary. Cold start fails closed. The output covers all 12 MEDIUM plans and
all eight LOW plans before the unchanged Pareto/epsilon/K selector runs.

The local fixture contains constructed non-measurements solely to validate
the memory and prediction contracts. It executes no held-out query and cannot
support prediction accuracy, performance, or generalization claims. Native
training measurements remain blocked until an independent reconstruction
audit passes and the author freezes the F2C10D campaign protocol.

## D120 Seal and independently reconstruct F2C10 before native measurement

F2C10C makes the local family-memory boundary executable without weakening its
claim limits. The runner writes the complete training memory, all held-out
prediction sources, candidate sets, estimate snapshots, and Pareto/epsilon/K
frontiers, then seals the hash of every selection file before it opens runtime
oracle rows. Only returned plans execute. A failed external-like call stops the
run immediately; retry, fallback, profiling, sampling, explain, LLM, ontology,
and post-selection memory updates remain absent.

A separate read-only auditor regenerates the base and direct workloads,
controlled training fixture, memory, predictions, snapshots, and frontiers
from the copied inputs. It verifies the selected plan set, exact post-selection
answers, invocation multiset, manifest summaries, content hashes, and an
unchanged run-tree fingerprint. The clean-commit run passed 134 checks. This is
still deterministic mechanism evidence because the training values and backend
responses are constructed; native measurement authority belongs only to the
future author-frozen F2C10D protocol.

## D121 Correct the F2C9B audit path without rerunning the experiment

The F2C9B producer writes `direct-frontier-preflight` below the native service
run root, before either service starts. The original auditor and its synthetic
fixture incorrectly looked below the outer Slurm run root. CWRU job `3791375`
therefore executed successfully and returned three exact answers, while its
first audit reported 20 missing preflight checks. This is an auditor path
defect, not evidence that the producer omitted its seal.

The auditor now reads the production location and the fixture reproduces that
layout, preventing the mismatch from being hidden again. The failed audit is
retained as diagnostic evidence. The job and run tree must not be rerun or
modified; acceptance requires one new read-only audit output generated by the
corrected code against the existing immutable run.

## D122 Preserve the true per-query frontier in the F2C10D native pilot

The author selected the six-query development pilot and then explicitly
resolved its cardinality ambiguity in favor of the real query-level
Pareto/epsilon/K result. Training remains exactly 18 semantic tasks times two
strategies times four counterbalanced repetitions, or 144 plan runs. The two
held-out base queries each return one to K=4 semantic representatives, so the
online phase is bounded at 2--8 plans rather than forced to exactly four across
the session. The complete post-selection shadow phase remains exactly 20
plans times four repetitions, or 80 runs. Consequently the valid campaign
range is 226--232 plan runs and 452--464 plan backend calls.

This decision preserves the meaning of the optimizer output and guarantees
that neither held-out query disappears merely to satisfy a session-wide
count. The protocol compiler still supports an explicit exact-total mode for
future experiments, but F2C10D does not use it. The native clients use a
60-second timeout and the Slurm job is bounded at 45 minutes using the maximum
call count. There is no current-query profiling, automatic retry, selection
input from the shadow phase, confirmatory statistic, or paper claim. One
clean-commit native pilot plus one independent read-only audit is authorized;
expansion to 30--50 queries remains blocked on its validation.

## D123 Revalidate the enclosing direct workload at F2C10D fixture handoff

CWRU job `3791589` failed before fixture mutation with
`bundle schema_version is unsupported`. The direct-semantic compiler embeds a
predicate-extended parameterized workload whose schema is intentionally
different from the base F2C parameterized bundle. The native path had already
validated that extension through the enclosing direct-semantic loader, but
the generic fixture loader reopened the nested directory with its default base
loader and rejected it.

Do not widen the base loader's accepted schema and do not skip fixture-time
revalidation. The direct-family native boundary supplies a dedicated loader
that checks the requested nested root, reconstructs the full enclosing direct
workload against its base bundle, semantic catalog, predicate mapping,
deterministic artifacts, and hashes, and returns only the nested workload from
that reconstruction. The generic fixture load/verification logic remains
unchanged. Job `3791589` is immutable zero-plan-call diagnostic evidence;
automatic retry remains disabled and any validation run must be a new Slurm
job at a clean repair commit.

## D124 Freeze result-blind physical baselines before reading F2C10D outcomes

F2C11 defines the first comparison surface for the F2C10D physical prediction
mechanism before the replacement CWRU pilot result is available. It contains
exactly five methods: the sealed instance-aware family-memory predictor, a
no-instance-feature family strategy-median ablation, fixed parallel hash,
fixed risk-first bind, and an observed post-selection oracle upper bound. The
method list, aggregation, selection order, and metrics are a versioned policy;
the analysis may not add or remove a method after seeing the pilot.

The primary and ablation methods may use only the already sealed training
measurements and prediction artifacts. The two fixed methods use no learned
measurement. The observed oracle may use the four-repetition shadow medians
only as an evaluation upper bound. Shadow measurements cannot select any other
method, and online selected-plan results and answer-row values cannot enter
selection or metrics. Physical-winner accuracy and latency regret use the
latency-first observed oracle; byte regret uses a separately declared
byte-first reference so every reported regret is nonnegative rather than
conflating resource trade-offs with the latency winner.

Analysis is admitted only after a successful mutation-free F2C10D audit and
reruns that independent read-only reconstruction immediately before reading
the baseline inputs. This closes the time-of-check/time-of-use gap without a
backend, LLM, ontology, profile, sample, explain, retry, or run-tree write. The
baseline output must live outside the immutable source run. The six-query,
ten-held-out-semantic-task result remains exploratory development evidence,
uses no confirmatory statistic, and stays `paper_result=false` regardless of
which method wins. It isolates physical choice inside each semantic class; it
is not a semantic-frontier comparison and does not replace a later live
current-query-profiling baseline with acquisition overhead included.

## D125 Require an independent reconstruction audit for F2C11

The persisted F2C11 comparison is not accepted from its self-reported hash or
summary alone. A separate read-only auditor must rerun the complete F2C10D
source audit, reconstruct the five-method analysis from the frozen policy and
source measurements, and require exact equality with the persisted analysis.
Recomputing an analysis hash after changing a metric must therefore still
fail. Both the analysis and its audit output must remain outside the immutable
F2C10D run tree, and the auditor must prove that the source tree digest is
unchanged.

This additional admission step makes no backend, profile, sample, explain,
LLM, or ontology call. It checks the ten-task and five-method cardinalities,
the zero-call and results-blind boundaries, and the exploratory
`paper_result=false` claim. It does not make the development comparison
confirmatory or broaden it beyond physical strategy choice within an already
selected semantic class.

## D126 Compare family memory with a cost-inclusive current-query profiler

F2C12A freezes the live current-query observation baseline before any accepted
F2C10D or F2C11 metric is read. For each of the ten held-out direct semantic
tasks, the baseline seals both physical candidates, executes each complete
federated plan once as an acquisition profile, and selects by observed latency,
then transferred bytes, then plan ID. The selected plan executes once only
after that cost-only selection is sealed. Answer rows, answer oracles, online
results, and later shadow results are not selection inputs. Missing or failed
acquisition terminates the run; there is no fallback or automatic retry.

The acquisition operation is explicitly a complete black-box federated-plan
execution labeled as profiling. It is not Neo4j's engine-internal `PROFILE`
operator, and it does not assume Fuseki exposes a symmetric native explain or
profile API. This gives both candidate strategies the same observable
coordinator boundary and charges all four acquisition backend calls per task.
End-to-end method cost is acquisition plus the selected execution; the later
four-repetition, counterbalanced shadow matrix is evaluation-only and excluded
from method cost.

The development compiler covers 20 acquisition plan runs, ten selected-plan
runs, and 80 shadow runs: 110 plan runs and 220 backend calls. Acquisition
order is balanced five AB and five BA across tasks; every shadow strategy
occupies each within-task order position twice. Family memory, training data,
LLM calls, ontology-service calls, semantic-frontier comparison, and
cross-allocation comparison are forbidden. The compiler makes zero calls and
does not authorize a CWRU run. A live runner and independent auditor are
required before this protocol becomes executable evidence, and all outputs
remain exploratory with `paper_result=false`. Full local acceptance passes
911 tests with 36 explicitly environment-gated skips.

## D127 Preserve the accepted F2C10D/F2C11 result even though it is negative

CWRU repair job `3791600` completed at exact clean commit `08f1911` on
`compt303` in 220 seconds. The run executed 144 training plans, seven online
frontier plans, and 80 post-selection shadow plans: 231 plan runs and 462
backend calls with zero current-query profiles and zero retry. It returned
four MEDIUM-query and three LOW-query semantic representatives. The independent
read-only source audit passed 1,289 checks with no failure or run-tree
mutation, so the six-query development pilot is accepted as real-backend
evidence. It remains non-confirmatory and `paper_result=false`.

The pre-frozen F2C11 comparison then reconstructed all five methods over ten
held-out semantic tasks. Family memory selected six of ten observed latency
winners with 2.282 ms mean latency regret. The no-instance family median and
fixed parallel baseline both selected eight of ten winners with 1.276 ms mean
latency regret. Family memory reduced mean byte regret from 5,625.6 to 4,658,
while fixed risk-first achieved zero byte regret at 6.024 ms mean latency
regret. The latency oracle chose the same aggregate 8:2 strategy split as
family memory, but family memory assigned the two bind choices to the wrong
task identities often enough to lose accuracy. The independent F2C11 auditor
reconstructed the exact analysis and passed all 17 checks without source-tree
mutation.

This is an exploratory negative result for the current instance-conditioned
predictor, not a reason to tune it on these ten tasks. The next valid steps are
the independently frozen cost-inclusive current-query profiling comparator and
a larger multi-family population. The current result does not establish that
memory is generally ineffective, that fixed parallel is generally optimal, or
that byte cost should be ignored.

## D128 Bind F2C12 to one fail-closed native producer and reconstruction audit

F2C12B implements the already frozen F2C12A schedule without changing its
method, population, order, cost accounting, or metrics. The native producer
seals the 20 physical candidates before a backend call, executes the 20
full-federated-plan acquisition profiles, persists a cost-only estimate source,
and seals all ten selections before opening an answer oracle or starting a
selected or shadow execution. It then executes ten selected plans and the
80-run counterbalanced shadow matrix. A successful run therefore contains
exactly 110 plan runs and 220 backend calls in three contiguous phases. Both
backend clients use a 60-second timeout, the Slurm wrapper uses the frozen
30-minute bound, and the first failure terminates the run without retry or
fallback.

The acquisition profile remains a black-box execution of a complete federated
plan, not an engine-internal Neo4j `PROFILE` request. The producer records
answer rows for later exactness validation, but selection is reconstructed
solely from sealed latency, transferred bytes, and plan ID. It reports both
selected-plan regret and acquisition-plus-selected end-to-end cost; the shadow
matrix remains evaluation-only.

A separate read-only auditor accepts either the inner live result or the outer
native Slurm tree. It verifies the clean expected commit, outer/service status,
recompiles the schedule from the copied source inputs, checks the pre-service
schedule seal and every schedule/run identity hash, exact result and phase
cardinality, estimate reconstruction, deterministic selection,
selection-seal timing claims, exact analysis reconstruction, 220 invocation
events, and an unchanged run-tree digest. Altering analysis, profile costs, or
the sealed plan choice is explicitly rejected. Local controlled-double and
native-boundary tests pass, but no CWRU outcome or comparison with the earlier
allocation is claimed until one clean job and its independent audit succeed.
All F2C12 outputs remain exploratory and `paper_result=false`.

## D129 Accept F2C12B as allocation-local development evidence

CWRU job `3791649` completed at exact clean commit `64f750b` on `compt268`
in 305 seconds. Its three contiguous phases contain exactly 20 acquisition,
ten selected, and 80 shadow plan runs, or 220 backend calls in total. The
selection source contains only the sealed full-federated-plan acquisition
costs. The outer, service, and live statuses succeeded; cleanup removed the
allocation-local runtime. The independent outer-root reconstruction audit
passed 1,185 checks with no failed ID and no run-tree mutation.

Within this allocation, the current-query profiler selected the observed
latency winner for all ten held-out semantic tasks and therefore had zero
shadow-median latency regret. Its mean byte regret against the separately
defined byte winner was 5,625.6. Two acquisition plan executions per task cost
a median 61.816 ms and 14,082 transferred bytes; acquisition plus selected
execution had a median 84.279 ms and 23,791 bytes. These are descriptive
development observations, not evidence that the method beats family memory:
job `3791600` ran in another allocation, so its timing is not a paired
counterfactual. The accepted artifact remains non-confirmatory and
`paper_result=false`.

## D130 Freeze a same-allocation paired physical comparison before execution

F2C13A composes the frozen F2C10D training schedule and F2C12 acquisition and
shadow schedules without changing either source protocol. Eighteen training
semantic tasks execute both strategies four times (144 runs). Family-memory
choices for all ten held-out semantic tasks are then sealed from training
memory only, before the dual-profile method may execute either current-query
candidate. The profiler performs 20 acquisition runs and seals one choice per
task. Both methods subsequently execute one selected plan per task in a
five/five counterbalanced method order. Even when they choose the same plan,
their serving observations remain distinct. One shared 80-run shadow matrix is
opened only after both seals.

The paired campaign therefore contains exactly 264 plan runs and 528 backend
calls in one native allocation. Historical training, current-query
acquisition, selected serving, and evaluation-shadow costs are reported as
four distinct scopes; training is never silently amortized. The count-only
break-even reference is 72 future semantic tasks because 144 historical
training runs replace two acquisition runs per target task. Fixed strategies
and the observed oracle are evaluation-only controls reconstructed from the
shared shadows. Analysis is descriptive at ten held-out tasks and reports no
p-value. The gate isolates physical selection within an already chosen
semantic class; it makes no semantic-frontier, ambiguity-resolution, LLM, or
ontology claim. The compiler performs no external call, authorizes no CWRU
run, fails closed on protocol or source-contract drift, and remains
`paper_result=false`. Full local acceptance passes 931 tests with 36 explicit
environment or external-artifact skips.

## D131 Bind the paired comparison to one fail-closed native evidence chain

F2C13B implements the frozen F2C13A schedule without changing its tasks,
methods, order, counts, or descriptive claim boundary. Before starting either
backend, the native service writes an exact paired schedule and preflight
manifest. One fixture load and one runtime-compatibility identity are shared by
both methods. The live producer then executes 144 training runs, seals ten
family-memory choices before any current-query profile, executes 20 profile
acquisitions, seals ten profiler choices, runs 20 counterbalanced
method-specific selected executions, and finally runs 80 shared shadows. This
is exactly 264 plan runs and 528 backend calls. Both backend timeouts are 60
seconds; the Slurm limit is 45 minutes; the first failure is preserved and
stops the campaign with zero retry or fallback.

The producer persists candidate identities, training observations and memory,
prediction sources, both selection seals, cost-only profile estimates, all
results, invocation events, and the paired descriptive analysis. The separate
read-only auditor trusts none of the producer's aggregate claims: it recompiles
the schedule from the copied workload and four source contracts, reconstructs
the family memory and prediction suite, independently reselects both methods,
recomputes analysis, checks the exact phase and run identity for every call,
and verifies that the run tree did not change. Controlled failure and tamper
tests cover the main fail-closed boundaries. Full local acceptance passes 939
tests with 36 explicit environment or external-artifact skips. This authorizes
one clean CWRU development run and audit only; it adds no confirmatory,
semantic-frontier, LLM, ontology, or paper-performance claim, and all outputs
remain `paper_result=false`.

## D132 Precommit the compact paired summary before reading a CWRU result

F2C13C adds a deterministic summary builder that accepts only a successful
F2C13B outer-root audit with the exact supported schema, no failed checks, and
no run-tree mutation. It rejects a commit mismatch, unsuccessful status,
invalid validation, schedule-count drift, a changed method set, selection-seal
coverage or hash drift, analysis-hash drift, shadow leakage into selection, or
any artifact promoted beyond the frozen descriptive development boundary.

The summary reports the two methods side by side, their per-task and aggregate
profile-minus-memory regret deltas, selected-plan and selected-strategy
agreement, profile-acquisition cost, evaluation-only controls, and historical
training cost as a separate non-amortized ledger. It records that family
memory made zero current-query profile calls while the comparison method made
20, and that both made zero LLM and ontology-service calls. The output is
content-hashed and written outside the immutable source tree with a no-overwrite
CLI. Its claim boundary is exactly ten semantic tasks in one native allocation,
descriptive statistics only, with no generalization or semantic-frontier
claim and `paper_result=false`. This prevents post-result metric selection; it
does not authorize another CWRU job or choose the future multi-family domains.

## D133 A query family enters the benchmark only through an executable package

F2C14A replaces the stale label-oriented readiness view with a reconstructable
package boundary. A family package binds one typed semantic-operator DAG,
binding and hard/relaxable constraint schemas, output schema, registered
literal-free Cypher/SPARQL templates, a deterministic multi-instance workload,
per-instance source and final oracles, a direct semantic workload and split,
the physical candidate space, and a family-memory policy. The compiler checks
the SHA-256 of every source, regenerates both workload layers in temporary
storage, and compares their family, bundle, manifest, selection-view,
evaluation-registry, count, and operator identities with the registry before
emitting a plan.

The same registry explicitly declares the agent environment, black-box Neo4j
and Fuseki boundaries, semantic/coordinator/backend/memory tools, allowed
actions, and forbidden actions. Catalog, ontology, and LLM inputs remain
optional; compilation makes zero calls to them or to a backend. A held-out
family package is rejected if it exposes family-local training tasks, so cold
start cannot be relabeled after the fact. Distinct labels may not share one
family compatibility hash, hard constraints cannot be changed, arbitrary
native text cannot be emitted, and automatic retry remains forbidden.

The current financial-risk package now closes the old typed-DAG,
backend-template, workload, and oracle blockers with six base queries, 28
direct semantic tasks, and 56 physical candidates. It does not invent the
remaining domains. Paper readiness still requires at least three executable
families, an executable entirely held-out family, 30--50 base instances, and a
preregistered inferential analysis. F2C14A is an unexecuted deterministic
contract, authorizes no CWRU job, contains no measurement, and remains
`paper_result=false`.

## D134 Identity clarification and semantic proposals use different tools

M15-E1 routes partially bound semantic programs through the existing finite
goal loop. A fully bound program terminates without a tool call. A catalog may
produce bounded candidates for any hole, but an entity hole with zero or
multiple identities cannot be delegated to an ontology or LLM: it blocks until
an authoritative user-clarification tool selects exactly one bounded identity.
Predicate and type holes may use catalog, ontology, and an explicitly enabled
bounded LLM proposal in that order; source holes omit ontology. Multiple valid
non-entity candidates remain an interpretation set for deterministic
enumeration rather than being mislabeled as resolved ambiguity.

Every resolution tool reports its external-call, latency, and token costs
through the shared tool result. The M15 LLM role may make at most one external
call, may return only candidate IDs already present in its request, cannot mark
its choice authoritative, and cannot carry Cypher, SPARQL, GQL, or other native
query text in metadata. Hard semantic constraints are hashed before every call
and are not rewritten. A tool error ends the attempt without retry; unavailable
ontology/LLM tools are explicit optional observations and cannot erase the
bounded candidate set.

Reason:

Identity disambiguation changes which real-world entity the query denotes and
therefore needs user authority. Ontology and LLM evidence can organize bounded
semantic alternatives but cannot guarantee user intent. Keeping both paths in
the ordinary tool/trace/memory contract makes their latency and inference cost
visible and preserves the deterministic compiler boundary. E1 supplies local
providers and a tested control path only; adapting the existing live
OpenAI-compatible provider with repairs disabled is a separate E2 gate.

## D135 Give M15 semantic resolution a one-call candidate-ID provider

M15-E2A uses a dedicated OpenAI-compatible response contract for semantic-hole
candidate selection. It does not reuse the earlier `PathPatternQuery` schema.
For every invocation, the provider derives a strict JSON schema whose
`candidate_ids` enumeration is exactly the identifiers already admitted by the
deterministic catalog/ontology boundary. The response must be a nonempty unique
subset, capped at eight candidates. The frozen Qwen3-32B bundle permits at most
256 output tokens, one request with a 60-second deadline, and zero repair calls.

Entity ambiguity remains outside the model boundary. Entity requests, missing
credentials, and prompt/schema binding drift fail before any network call.
Transport errors, timeouts, malformed structured output, and out-of-set IDs
fail after exactly one charged external call; their latency and token evidence
remain visible in the shared tool result and execution memory. No failure path
retries, repairs, or silently substitutes a deterministic answer. Successful
model output is still non-authoritative and cannot contain Cypher, SPARQL, GQL,
or other native query text.

Reason:

The system needs the LLM as an optional bounded semantic-ranking tool, not as a
second query compiler or an unmetered recovery loop. A dynamic candidate enum
makes the model's action space identical to the deterministic interpretation
space, while costed failures prevent model latency from disappearing from the
optimizer's evidence. E2A is verified only with an offline transport and
authorizes no CWRU/model execution; the live lifecycle and independent audit
are a separate E2B gate.

## D136 The live resolution gate spends exactly one inference request

M15-E2B freezes one four-candidate predicate-resolution request before starting
Qwen3-32B. The sealed preflight binds the clean commit, CWRU deployment
contract, model bundle, prompt and schema hashes, typed semantic program, hard
constraints, dynamic candidate enum, exact request payload, and token budget.
Entity identity is already clarified and cannot enter this model call.

The Slurm allocation may poll `/v1/models` to observe readiness, but it performs
exactly one inference request through the M15 LLM tool. It does not run the
older generic structured-output smoke because that would spend a second
inference. The request has a 60-second provider deadline, 256 output-token cap,
zero repair calls, and zero automatic retries. A failure retains its spent
call, latency, and token cost, persists the failed goal, and ends the job.

A separate auditor reconstructs the preflight and validates the exact CWRU
runtime, H100, cached model revision, loopback endpoint, bounded
non-authoritative output, hard-constraint preservation, goal trace, execution
memory, invocation hashes, shutdown, and artifact inventory without changing
the run tree. Local tests use only a fake transport. The gate authorizes one
clean CWRU engineering run after its exact commit is published; it makes no
quality, optimizer, graph-answer, or paper claim.

## D137 Compile declared phrases before using artifact-backed resolution tools

M15-E3 introduces a deterministic frontend contract instead of asking an LLM
to create the initial semantic program. A versioned intake template declares
every accepted phrase, typed hole, hard or relaxable constraint, semantic
operator, capability, and root. Compilation uses Unicode-normalized exact
phrase matching with a longest-unique rule and fails closed when a required
phrase is missing or ambiguous. The template may instantiate only existing
semantic operators and cannot contain backend-native query text. This is a
bounded template compiler, not a general natural-language parser.

Catalog and ontology are separate versioned local tool providers. Catalog
lookup is exact normalized mention matching and refuses to truncate an
over-cap identity set. Ontology lookup may introduce only artifact-declared
predicate or type candidates by at most one hop; it rejects entity and source
holes. Both expose their raw artifact SHA-256 and evidence and report zero
external calls. A user clarification provider accepts only an explicit entity
selection already inside the bounded catalog set, marks it authoritative, and
charges one external interaction. No provider emits Cypher, SPARQL, GQL, or
other native query text, and no failure is retried.

The intake vocabulary includes a separate `constraint` hole kind. In the
development request, `密切` is not collapsed into the transfer predicate: the
catalog retains a qualifying-single-transfer threshold, a window-total amount
threshold, and a window-frequency threshold.
Ontology does not process this hole kind. A later executable-package bridge
must therefore expose which condition interpretations have registered
operators and templates instead of silently discarding the unsupported ones.

The controlled development request deliberately maps `Alice` to two identities.
Without explicit user input, the goal blocks immediately after its first
catalog observation and never consults ontology or a model. With the explicit
development selection it continues through predicate catalog/ontology and type
catalog lookup on the existing E1 goal loop. This validates routing,
provenance, hashing, costs, and memory only. The artifacts are not ontology
truth, the remaining semantic candidates are not declared user intent, no
backend or LLM is called, and every result remains `paper_result=false`.

## D138 Preserve every resolved meaning before checking executable capability

M15-E4 treats the E3 resolution commit as immutable input. It reconstructs the
commit hash, hard-constraint hash, authoritative entity choice, and artifact
identities before enumerating a bounded cross-product. Semantic equivalence is
content-addressed from the complete canonical meaning rather than list order.
Every interpretation survives capability checking; an unsupported class is
published with named missing capabilities and receives no physical candidate.

The controlled `密切` hole contains three meanings and the transfer-predicate
hole contains two, producing six classes. Window-total `SUM` and window-count
`COUNT/HAVING` are not equivalent to the existing per-edge amount filter, so
their four classes remain explicitly unavailable. The qualifying-single-edge
meaning is compatible with the parent F2C family. Two bridge-owned, hash-bound
Neo4j templates add the hard exclusive calendar-window upper bound to both the
full-query and bind-query forms. This extension is a registered black-box
interface artifact; it neither changes prior F2C evidence nor inspects backend
internals.

The two executable semantic classes map to exactly one registered semantic
task each and inherit only the registry's `parallel_hash_join` and
`risk_first_bind_join` strategies, yielding four unexecuted physical
candidates. Construction and selection use no oracle, backend, model, or
ontology-service call and emit no native query text in the portable bridge
plan. Offline oracles may be read only afterward to test exact execution. The
development result remains `paper_result=false`; live execution, cost
estimation, frontier selection, and aggregate capability are later gates.

## D139 Execute only registered resolved classes through a sealed native lifecycle

M15-E4B carries the E3/E4 semantic boundary into a real Neo4j-plus-Fuseki
allocation without redefining it. Before either service starts, the native
producer copies the bridge specification into the immutable run root,
reconstructs the controlled resolution, recompiles the six semantic classes,
materializes the direct workload, and seals the two executable tasks and four
physical candidates in a self-hashed preflight. The two single-transfer
classes retain both registered strategies. The four aggregate classes remain
unavailable and may not be approximated, dropped, or sent to a backend.

After service startup and one verified fixture load, the live runner executes
all four sealed plans in declared order. Each plan invokes exactly one Neo4j
fragment and one Fuseki fragment through their public interfaces, so a
successful run contains eight execute calls. It makes zero current-query
profile, model, ontology-service, repair, or retry calls and emits no portable
native query text. Exact answer oracles are reconstructed and opened only
after all selected executions; they validate results but cannot affect class
or plan selection. A first plan-level failure stops all later plans. Parallel
fragments already dispatched within that failed plan remain recorded as spent
calls rather than being erased.

A separate read-only auditor accepts the outer native run tree, recompiles the
bridge and workload from run-local inputs, reconstructs every exact answer and
backend-event pair, validates pre-service sealing, lifecycle, cleanup, and the
six/two/four/eight cardinality contract, and compares a complete run-tree digest
before and after auditing. Altered rows, hashes, candidate identities, call
counts, or unavailable-class execution are rejected. Focused cross-layer
acceptance passes 81 tests and full local acceptance passes 1,010 tests with 36
explicit environment or external-artifact skips. This authorizes one clean
CWRU engineering run and independent audit after publication. It adds no
semantic-quality, cost-frontier, generalization, or paper-performance claim;
all artifacts remain `paper_result=false`.

## D140 Preserve the same-allocation paired result without predictor retuning

CWRU job `3792343` executed the pre-frozen F2C13B schedule at exact clean
commit `cf3d430` on `compt292`. It completed 144 historical training, 20
current-query acquisition, 20 method-specific selected, and 80 shared-shadow
plan runs, or 264 plans and 528 backend calls. The allocation runtime was
removed cleanly. The independent read-only audit reconstructed the full chain
and passed 2,735 checks with no failed ID or run-tree mutation. The precommitted
F2C13C summary was then generated without another backend call.

Within these ten semantic tasks, family memory made zero current-query profile
calls and selected seven shadow-median latency winners. The dual-profile method
made 20 acquisition runs and selected five. Their mean latency regret was
2.733 and 2.808 ms respectively, so the observed paired profile-minus-memory
difference was only 0.075 ms. Profiling lowered mean byte regret from 4,658 to
3,346.4, at a mean acquisition cost of 35.154 ms and 14,056 bytes per task.
The evaluation-only fixed-parallel control selected nine winners with 0.289 ms
mean latency regret, while fixed risk-first had zero byte regret but 8.176 ms
mean latency regret. Historical training remains a separate 144-run ledger and
the 72-future-task break-even is count-based only.

This evidence is deliberately retained as a mixed development result. It does
not authorize tuning the family-memory predictor on the ten evaluation tasks,
does not turn the profiling method or fixed parallel into the system design,
and does not support a generalization or semantic-frontier claim. It strengthens
the motivation for the already frozen multi-family design gate: the next
scientific step is to choose structurally distinct query families and a cold-
start boundary before implementing or running the larger population. All
artifacts remain descriptive with `paper_result=false`.

## D141 Accept E4B from the immutable run after correcting the auditor schema

CWRU job `3792349` executed exact clean commit `8056ee4` on `compt292` and
completed in 94 seconds. Its outer lifecycle reports success, zero cleanup
error, and removal of the allocation-local runtime. The sealed E4B contract
therefore exercised four physical plans over two executable semantic classes,
eight black-box backend calls, four retained but unexecuted aggregate classes,
zero current-query profile/model/ontology-service calls, and zero retry.

The first independent read-only audit passed 150 checks and failed only
`service.plan.loopback_only`. That check read a `loopback_only` key invented by
the unit-test fixture but absent from the actual `NativeServicePlan` schema. It
was an auditor defect, not an experiment failure: the real plan records
`public_ports=false`, loopback service and health URLs, Fuseki's `--localhost`
argument, and a persisted Neo4j configuration whose default, Bolt, and HTTP
listen and advertised addresses are all `127.0.0.1`.

Fix `aed12e3` removes the synthetic fixture contract and derives the isolation
verdict from those real artifacts. A new tamper test proves that a non-loopback
endpoint is rejected. The same immutable job was then audited again under a
new output name; the v2 audit passed 152/152 checks with no failed ID and no
run-tree mutation. The original failed audit remains preserved, and the
experiment was neither retried nor rewritten. This closes E4B as real-backend
mechanism evidence only; it does not establish semantic quality, cost-frontier
quality, generalization, or paper performance, and remains
`paper_result=false`.

## D142 Separate unresolved interpretations from anchored relaxations

The author selected Option A from the M15-E5 interpretation–relaxation gate.
E5 will preserve unresolved interpretations as co-equal groups rather than
assigning one a zero-deviation status from list order, ontology proximity, or a
non-authoritative LLM subset. Physical latency and byte predictions remain the
responsibility of family memory and must use zero current-query profiling in
the target path.

Within each interpretation, E5 first retains the cheapest predicted physical
representative. A semantic-deviation Pareto/epsilon frontier is permitted only
for a declared relaxation whose reference interpretation has an authoritative
binding. An unresolved interpretation has nullable semantic deviation and
cannot dominate or be dominated by another unresolved interpretation on an
invented scalar. The cross-interpretation layer may return at most K
representatives or ask a clarification question under a separately frozen
impact rule.

This rejects both a single global provenance-weighted semantic-loss frontier
and a mandatory-clarification-before-any-frontier policy. The
clarification-impact rule remains author-owned and must be selected before E5
can close its offline mechanism gate. No CWRU run is authorized by this
decision, and every E5 artifact remains `paper_result=false`.

## D143 Use semantic structure, not predicted cost, to trigger clarification

The author selected R1 for E5. An unresolved set requires clarification when
its members differ in aggregation, path structure, quantification, answer
meaning, output contract, or executable capability. Family-memory latency and
byte estimates are forbidden from deciding among those meanings. For the
current example this means asking whether `密切` denotes one qualifying
transfer, cumulative window amount, or window frequency.

Differences that retain the same semantic-operator structure and output
contract remain bounded representatives. Thus `transferred_to` and `paid_to`
may coexist after the relationship-strength meaning is authoritatively bound;
each keeps only its cheapest predicted physical plan. Unresolved classes have
nullable semantic deviation, while Pareto/epsilon semantic pruning remains
limited to relaxations anchored at an authoritative base.

The offline selector must fail closed, preserve all unavailable classes, emit
no native query text, read no oracle or post-execution measurement, and make
zero backend-profile, LLM, or ontology-service calls. Without an authoritative
in-set structural selection it may publish predicted physical representatives
and one bounded question, but it may not authorize execution. This decision
does not authorize a CWRU job and remains `paper_result=false`.

## D144 Accept the first E5 hierarchical mechanism without a live run

The E5 implementation at `b2d89c4` introduces a separate hierarchical schema.
It validates the six-class E4 bridge, derives R1 structure signatures, predicts
all four executable physical candidates from a sealed same-family memory view,
and keeps one lexicographic latency/bytes/plan-ID representative within each of
the two executable interpretations. Every target feature record and neighbor
provenance is hash-bound. The current query contributes zero profile calls and
no backend, LLM, ontology service, oracle, or post-execution measurement.

Without an authoritative structural selection, the output preserves all six
classes, emits one three-option relationship-strength question, returns zero
semantic plans, and marks execution ineligible. A controlled explicit
`single-transfer` selection returns exactly two bounded predicate
representatives while retaining the four unavailable aggregate classes. A
non-authoritative candidate subset is recorded but cannot create semantic
authority or a zero-deviation class. Reordering E3 candidates preserves the
returned class identities.

Focused E5/F2C10 acceptance passed 18 tests before the compact evidence check;
the final full repository suite passes 1,021 tests with 36 explicit skips. The
hash-bound record is
`experiments/artifacts/m15_e5_local_hierarchical_interpretation_frontier_20260907.json`.
This accepts only the unresolved-interpretation/R1 mechanism. Anchored
relaxation frontiers remain unimplemented because no authoritative predicate
base or calibrated semantic-deviation contract exists. No CWRU run or paper
claim is authorized, and `paper_result=false` remains mandatory.

## D145 Require explicit predicate authority before ontology-anchored relaxation

E5B must not reinterpret the two same-structure predicate representatives as
an exact/relaxed pair until an explicit in-set authority source selects one of
them as the base. Structural R1 clarification and predicate-base authority are
separate events. Candidate order, an E2B model subset, family-memory cost, and
ontology proximity remain non-authoritative.

After that base exists, E5B may read only the exact ontology artifact already
sealed by E4 and may admit only a declared one-hop `sibling` relation between
active same-structure predicate classes. The base receives semantic deviation
0. A sibling receives the relation's declared deviation and complete
provenance; reverse traversal is legal only when the source relation is marked
bidirectional. In the controlled E3 artifact this yields deviation 0.25 from
`relation-predicate-001`. That value is a development fixture, not a calibrated
intent probability or an ontology-truth claim.

Physical reduction remains upstream and family-memory-only. E5B reuses one
physical representative per interpretation, then applies the frozen
semantic-deviation/latency/bytes Pareto rule, 5% semantic-preserving epsilon,
and K=4 bound within the anchored set. An exact `transferred_to` base retains
the cheaper relaxed `paid_to` trade-off; an exact lower-cost `paid_to` base
dominates the more expensive relaxed transfer class. All original E4 classes
remain visible, hard constraints remain hash-identical, and selection makes
zero current-query profile, backend, LLM, ontology-service, oracle, repair, or
retry calls.

The implementation commit is `3392889`; its compact record is
`experiments/artifacts/m15_e5b_local_anchored_interpretation_frontier_20260907.json`.
Focused E5 acceptance passes 20 tests and full repository acceptance passes
1,030 tests with 36 explicit skips. This closes a controlled local mechanism
only. It does not authorize a CWRU run, UI behavior, user-utility claim,
calibrated semantic metric, or paper result.

## D146 Use a resumable authority-event session between E5 and E4 execution

The author selected Option A for the clarification-to-execution transport.
E5C therefore represents interaction as a deterministic session reconstructed
from sealed optimizer inputs and an ordered authority-event log, not as mutable
chat history. Stage one asks the R1 relationship-strength question. Only an
explicit in-set user event bound to the session, sequence, hole, pending-
question hash, authority source, and its own content hash can select the
structure. Unsupported aggregate structures terminate without execution.
Stage two is reached only for the executable single-transfer structure and
separately selects the predicate base required by E5B anchored relaxation.

The ready handoff binds the session state, event chain, anchored frontier,
resolution commit, hard constraints, E4 bridge, returned set, and runtime-plan
hashes. It contains all and only E5B's returned physical representatives in
selection-rank order and exposes only the existing allowlisted
`runtime.execute_plan` interface. Its portable representation contains no
Cypher or SPARQL. Conversation text, candidate order, model output, cost, and
ontology proximity remain non-authoritative. There is no automatic semantic
choice and no retry.

Core implementation commit `5f87bcc` and the compact record
`experiments/artifacts/m15_e5c_local_clarification_transport_20260907.json`
establish the controlled local mechanism. The independent audit passes 13/13
checks, focused E4/E5 regression passes 43 tests, and full local acceptance
passes 1,044 tests with 36 explicit skips. This decision does not authorize a
CWRU run, make a UI part of the experiment acceptance path, or support a
performance, user-utility, calibrated-semantic, or paper claim.

## D147 Execute the selected frontier with one sealed finite goal

E5D is the only authorized live continuation of E5C. It must load the exact
historical family-memory view produced by accepted F2C10D job `3791600` and
verify its internal identity
`7ed39e1097e3138666b87ec9c8ea82ed135d77a8e12e9f2893931892ba0b7e57`.
The CWRU submission must also provide explicit authority for the executable
R1 `single-transfer` structure, one listed predicate base, and an authority
source ID. Defaults, candidate order, family-memory cost, model output, and
ontology proximity cannot synthesize those values.

The resolution bridge, historical memory, two authority events, E5B frontier,
execution handoff, source hashes, selected plan order, and expected call count
are reconstructed and sealed before Neo4j or Fuseki starts. The live phase is
one bounded `GoalLoop` whose only registered capability is
`runtime.execute_plan`. It executes all and only selected plans in rank order,
stops after the first failure, and performs no automatic retry. Selection uses
zero current-query profile, backend, LLM, ontology-service, answer-oracle, or
post-execution observation calls. Exact oracles open only after every selected
execution succeeds.

An independent read-only auditor must recompile the complete E4/E5C chain,
verify the real service isolation configuration, and match the goal trace,
memory, results, and exactly two execute calls per plan without changing the
run tree. Local tests establish implementation readiness only. One clean CWRU
run and one successful audit are required before E5D is accepted. Full local
acceptance passes 1,054 tests with 36 explicit skips. The result remains
mechanism evidence with `paper_result=false`; it makes no performance,
semantic-quality, user-utility, or ontology-truth claim, and the UI remains a
separate adapter. Implementation commit `8fb1999` and
`experiments/artifacts/m15_e5d_local_live_selected_session_readiness_20260907.json`
bind this local readiness boundary.

## D148 Use author-selected interpretation A for the one E5D development run

The author explicitly selected interpretation A for the pending E5D CWRU
mechanism gate. For this run only, `密切` means a single transfer whose amount
is at least 50,000, represented by
`constraint:single-transfer-at-least-50000`; the authoritative predicate base
is `predicate:transferred_to`. The ontology-declared `predicate:paid_to`
sibling may remain a bounded relaxed interpretation, but it is not the exact
base.

This decision supplies the two authority events required by E5C/E5D. It is not
a parser rule, system default, learned preference, calibrated semantic label,
or claim about how other users interpret the phrase. The live run must persist
the selected IDs and an explicit author authority-source ID, and its auditor
must reconstruct the same event chain. No optimizer cost, model output,
candidate order, or ontology proximity may replace this decision.

## D149 Carry UI authority through a script-scoped remote envelope

The UI go/no-go prerequisites are now satisfied, but the existing remote
executor could submit only fixed Python/module settings. A visual
clarification choice could not reach the E5D Slurm wrapper through the typed
tool and would otherwise tempt the UI to construct a shell command. E6A closes
that control-plane gap before any page is built.

`submit_job` may now accept an explicit per-job environment object. The
executor validates each key against the exact allowlisted Slurm script and
passes normalized values as an argv vector. Only the E5D selected-session
wrapper accepts its six non-secret memory/session/authority keys. Those keys
are rejected for every other wrapper; commas, whitespace, newlines, equals
signs, unsafe characters, and values over 1,024 characters fail before a
remote call. Fixed runtime settings remain separate. No credential, API-key,
token, password, arbitrary environment, native query, or shell fragment is
accepted.

The thin UI remains a local working surface and adapter over this tool. It is
not an experiment runner, semantic authority source, direct vLLM client, or
direct Neo4j/Fuseki client. Paper jobs continue to use frozen CLI protocols and
immutable artifacts. Full-repository acceptance passes 1,055 tests with 36
explicit skips. This establishes local control-plane readiness only; no SSH,
Slurm, backend, or model call was made by that validation.

## D150 Keep the UI projection subordinate to E5C authority

E6B introduces no new semantic state machine. The local UI adapter accepts only
a typed, hash-valid E5C clarification session; displays its bounded question;
and delegates an explicit candidate-ID choice to the existing E5C authority
event builder. It does not accept free text as authority, infer a default from
option order, rank interpretations, compile plans, or expose backend-native
query text.

Only a terminal `ready_for_execution_handoff` session may produce an E5D
submission preview. The adapter reconstructs the structural and predicate IDs
from the two authority events, requires one shared explicit authority source,
binds the historical-memory hash to the E5C source contract, and emits a typed
`submit_job` payload for the one E5D wrapper with exactly the six E6A fields.
The page cannot edit arbitrary environment variables or construct a shell
command. Submission still requires an explicit confirmation and execution
still belongs to the remote tool.

E6B is a local presentation/control adapter, not the interactive page and not
an experiment result. Full-repository acceptance passes 1,061 tests with 36
explicit skips. No SSH, Slurm, graph-backend, ontology-service, or model call
was made by validation; `paper_result` remains false.

## D151 Accept one live E5D selected-interpretation mechanism gate

CWRU job `3793365` ran the only authorized E5D development session at exact
commit `52fe4d8d626604e40bdcc1c3f336c22e2eb61313`. It reconstructed the explicit
author choice `constraint:single-transfer-at-least-50000` plus
`predicate:transferred_to`, verified the accepted F2C10D memory identity, and
sealed two selected semantic plans before starting native services.

The job completed on `compt351` with exit `0:0` in 82 seconds. The finite goal
made two `runtime.execute_plan` calls, corresponding to two physical plan runs
and four backend calls. Final row counts were 11 and 6 and total bytes moved
were 17,784. Selection made zero current-query profile, LLM, and
ontology-service calls and performed no automatic retry. The independent
read-only audit passed all 127 checks with no failed check and no run-tree
mutation.

This accepts E5D as an end-to-end live mechanism result only. The two-plan
execution is not a performance comparison, the observed rows are not a user
study, ontology proximity is not treated as truth, and the result remains
`paper_result=false`. The immutable run and audit must not be overwritten or
resubmitted.

## D152 Keep the interactive clarification surface local and contract-bound

E6C implements the optional UI as a local researcher working surface, not as a
new agent, semantic state machine, or experiment runner. Its Python service
binds only to `127.0.0.1`, reconstructs E5C from the sealed resolution artifact,
accepted historical-memory view, fixed policies, and a content-hashed
authority-event store, and refuses to start when the displayed request does not
match the resolution question hash. The page is not deployed.

Every clarification mutation must include the current session hash, pending
question hash, one in-set candidate ID, and explicit confirmation. Authority-
source identity remains server-owned. The browser never receives the typed
remote payload, remote memory path, environment values, credentials, native
query text, or a generic command/filesystem/backend/model interface. A terminal
session exposes only a sanitized handoff preview. Remote submission is disabled
by default; if the local operator explicitly enables it, one confirmed action
may call only `remote.executor` with the fixed E5D script and six-field E6A
allowlist. Any result ambiguity consumes the one attempt and is never retried.

Visible buttons and the page's two model-context tools call the same local
actions; the tools do not gain additional authority. Source-level tool
registration is implemented, but no supported browser runtime was used to
validate registration in this gate. Focused E6C acceptance passes 34 tests,
full repository acceptance passes 1,075 tests with 36 explicit skips, and the
frontend production build passes. This is local engineering readiness only: no
CWRU submission, backend/model/ontology call, user study, performance result,
or paper claim is accepted, and `paper_result=false` remains mandatory.

## D153 Select a controlled primary population plus external validation

The author selected F2C14B Option C on 2026-09-07. Three controlled financial
query structures will form the primary population and a smaller standard-
workload slice will be reported separately as external validation. This closes
population decision 1 only; it does not accept the original P1 data source,
freeze the statistical protocol, or authorize a paper run.

The existing `financial_risk_dev` world is a toy development fixture. It remains
useful for deterministic regression, failure injection, and mechanism audits,
but it cannot support paper-scale performance or generalization claims. The
primary paper-candidate path must instead use a traceable public artifact while
retaining the controlled direct, temporal-path, and aggregate DAG differences.
The current recommendation is a transparently named FinBench-derived
heterogeneous Neo4j/Fuseki workload, with GrailQA as a separate semantic track,
an optional pinned FIBO mapping, and a cutoff-bounded FedShop validation slice.

The schedule is governed by the SIGMOD 2027 Round 4 deadlines: abstract and
COIs on 2026-10-10 and paper on 2026-10-17, both 11:59 PM AoE. Work therefore
switches immediately from extending the toy world to public-artifact ingestion
and correctness. The target is a local FinBench SF0.01 proof within 48 hours, a
first CWRU paper-candidate pilot within 72 hours, and an author-approved
confirmatory protocol immediately afterward. Pilots retain
`paper_result=false` and cannot be relabeled after inspection.

## D154 Partition the complete FinBench v0.1.0 snapshot before query admission

The first public-data boundary uses every one of the 18 snapshot tables in the
pinned SF0.01 archive. Limiting ingestion to the eight tables needed by one
direct-transfer example would recreate the toy-family bias that D153 is meant
to remove and would make later path, withdrawal, loan, investment, and
aggregate families depend on a second undocumented data boundary.

Neo4j is authoritative for graph structure, transactions, ownership, loans,
guarantees, investments, and numeric flow. Fuseki is authoritative for entity
types and semantic/control classifications. Stable entity identity is
replicated explicitly so the coordinator can align sources; control attributes
are not copied into Neo4j. The generator verifies the pinned archive, rejects
unsafe members, duplicate entity IDs, invalid numeric literals, and orphan
relationships, and writes the complete bundle atomically without overwrite.

The real SF0.01 local admission processed 36,881 rows with zero orphan
endpoints and emitted 160 batched Cypher statements plus 28,374 Turtle triples.
This closes only deterministic source placement. It does not validate backend
load time, query correctness, scale, benchmark conformance, or any paper claim;
no backend, model, ontology service, or answer oracle was called and
`paper_result=false` remains fixed.

## D155 Admit one reviewable 36-query FinBench development population

The first non-toy F1--F3 population is compiled from the verified SF0.01
archive and complete D154 partition. It contains 12 instances per structural
family. F1 and F2 each reserve stratified positions 3, 6, 9, and 12 as
held-out instances; their other 16 combined instances are the only family-
memory training population. F3 is entirely held out and uses the predeclared
`aggregate_first_hash` cold-start fallback.

Parameter curation is deterministic, documented, and independent of method
latency or bytes, but it intentionally requires nonempty exact answers for the
SF0.01 development pilot. This avoids an all-empty smoke test while making the
selection effect explicit. It is not yet the confirmatory sampling protocol.
Public instances contain no source or final oracle rows; a separately hashed
oracle artifact is inaccessible to selection until the plan seal exists.

The real local compilation contains 36 nonempty queries and has workload
SHA-256 `6cf2aa7a09bebbae7e0ff244e0d2c8f850bd44393461c8b8c22e4ea2f68b5647`.
It makes zero backend, model, or ontology-service calls. This decision admits
native execution testing only and remains author-reviewable before paper
protocol freeze; `paper_result=false` is mandatory.

## D156 Use one shared federated runtime for all three FinBench families

The F1--F3 correctness gate must exercise XGAP's common coordinator rather
than a benchmark-specific evaluator. The runtime therefore adds only the
general operations missing from the existing federated DAG: collection-aware
semi-join, grouped aggregation, and deterministic ordered limit. F1, F2, and
F3 each compile to two exact physical routes over the same black-box Neo4j and
Fuseki interfaces. The control-first routes use real bound-query pushdown;
the graph/aggregate-first routes exchange and combine source results at the
coordinator.

Plan compilation reads only the public instance and hash-verified templates.
All 72 plans are sealed before fixture loading. Oracle bytes are hashed only
to verify artifact identity; their JSON content may be parsed only after every
selected plan has executed. A
local replay against the real SF0.01 oracle verified exact results for all 36
queries and both routes without a backend call. This accepts compiler and
coordinator correctness only. The next gate is one native CWRU execution of
the same 72 plans; scale, latency comparison, predictor quality, and any paper
claim remain disabled and `paper_result=false` is mandatory.

## D157 Keep public-data acquisition and correctness evidence independently verifiable

The first CWRU preparation attempt stopped before Slurm submission because the
official dataset host returned HTTP 403 to Python's default request identity.
No archive, backend, query, or experimental result was produced. The fetcher
now sends one fixed, truthful XGAP user agent and requests identity transfer
encoding. It retains the exact approved HTTPS host, redirect-host check,
single-attempt policy, temporary-file isolation, pinned byte count and SHA-256,
and no-overwrite cache behavior. A real local fetch of the official SF0.01 URL
then verified 6,516,867 bytes, the pinned digest, 18 tables, and 36,881 rows.

The native correctness gate also receives a separate read-only auditor. The
auditor recompiles the public query population and all physical plans,
reconstructs every final answer and paired-equivalence check from the sealed
oracle after the run, verifies the outer/service/live status and Git identity,
and hashes the run tree before and after inspection. Its output is forbidden
below the source run. Producer job `3793654` completed all 72 plans and 144
backend calls; after repair of an auditor-only path-serialization defect, the
auditor passed 363/363 checks without mutating the source run. This accepts the
development correctness gate but does not turn it into a paper result.

## D158 Admit SF0.1 as the next development scale gate, not as a paper result

The official FinBench v0.1.0 SF0.1 archive is pinned separately from the
SF0.01 correctness artifact. A real local official-archive inspection verified
66,710,298 bytes, SHA-256
`f0359b5c4515cd5d86349b4a11a7470f6f153e42c5ac21c59e70f5c0d0b37a60`,
the same 18 snapshot tables, and 365,181 rows. The corresponding three-family
population compiles 36 queries with the same 16 training, eight held-out
instance, and 12 held-out-family roles. It is a scale-specific population;
identifiers and content hashes are not reused from SF0.01.

At batch size 2,000, a local full partition emitted 194 Cypher statements,
282,426 Turtle triples, a 91,934,990-byte Neo4j load file, and a
30,972,563-byte Fuseki load file in nine seconds. This makes SF0.1 the smallest
useful server load/latency gate while keeping the request count close to the
SF0.01 path. The native entry point accepts only the two committed lock/spec
pairs and a bounded batch size; the SF0.1 wrapper fixes 16 GiB, 90 minutes, and
batch size 2,000. SF0.3 or SF1 will not be selected until this gate reports
actual load time, query time, memory pressure, and failures.

This is an engineering-scale admission, not an author-approved confirmatory
protocol. The SF0.01 native correctness run and independent audit have now
passed, so the SF0.1 gate may be submitted once its pinned archive is present
and verified on CWRU. All generated artifacts retain `paper_result=false`.

## D159 Make FinBench family memory leakage-safe before native measurement

The primary zero-profile method may use only selection features published in
the frozen workload at ingestion time. For F1 this is structural degree; for
F2 it is start-account out-degree. Each of the 16 training queries contributes
both declared physical strategies with at least four successful, exact, AB/BA
counterbalanced repetitions. The immutable memory retains those raw
repetitions and their per-plan medians so later audits can reconstruct both
admission and aggregation. Held-out observations, answer rows, current-query
profiles, post-execution measurements, retries, and oracle inputs are rejected.

For the eight held-out-instance queries, the development predictor uses
within-family normalized Manhattan distance, exact-feature matches when
present, otherwise three inverse-distance neighbors, and separately predicts
latency and transferred bytes for both strategies. Strategy selection is
lexicographic by predicted latency, bytes, and stable strategy ID; the
predicted physical Pareto set remains observable. A constant training feature
does not make a different held-out value an exact match: such a dimension
contributes unit distance.

F3 remains an entirely held-out family. It receives no invented prediction or
frontier and uses only the aggregate-first fallback declared before native
measurement. Its cold-start results must be reported separately from
known-family accuracy and regret. This decision freezes a development
mechanism, not the confirmatory statistical design; no native observation has
yet entered the memory and `paper_result=false` remains mandatory.

## D160 Freeze a same-allocation FinBench development comparison before observations

The first public-data comparison schedule is compiled only from the 36-query
FinBench workload, the family-memory policy, and an explicit development
protocol. It contains 128 counterbalanced training measurements, 40
current-query dual-profile acquisitions, 40 paired selected-plan serving
slots, and 160 post-selection shadow measurements: 368 complete federated
plan runs and 736 backend calls in one allocation. Every phase, query order,
route order, method order, timeout, retry rule, and expected count is
content-bound before a backend or answer oracle is opened.

For the eight held-out instances from known families, the primary is
`family_memory_zero_profile`. For the 12 queries from the entirely held-out F3
family, the corresponding primary slot is explicitly
`predeclared_family_fallback`; those queries must not be relabeled as memory
predictions. Both are paired with the cost-inclusive
`current_query_dual_profile` comparator. The primary and comparator each serve
one selected plan per held-out query in a deterministic balanced order. Their
selection seals are distinct, and the later four-repetition shadow matrix may
evaluate but never alter either choice.

Known-family and cold-start results are reported separately. Family-global,
fixed-route, and observed-oracle methods are analysis controls over the shared
measurements, not additional online systems. This is a result-blind
development protocol; it does not freeze confirmatory statistics, authorize a
paper run, or turn the pending SF0.1 scale gate into performance evidence.
`paper_result=false` remains mandatory.

## D161 Treat the first SF0.1 load failure as diagnostics, not a scale result

CWRU job `3793681` ran the dedicated SF0.1 wrapper at exact clean commit
`6d9925f` and failed after 10 minutes 21 seconds on `compt268`. Both native
services reached healthy state and the complete 36-query/72-plan catalog was
sealed, but Neo4j returned HTTP 500 on fixture statement 46 of 194 after 45
successful statements. No federated plan ran, the oracle remained unopened,
Fuseki fixture loading had not begun, and automatic retries remained zero.
Peak batch-step RSS was approximately 2.06 GB against a 16-GB request, so the
Slurm evidence does not support an allocation-level OOM diagnosis.

The previous Neo4j client retained only urllib's generic `HTTP Error 500`
text. It now parses and bounds the Neo4j JSON error response, retaining status,
Neo4j error code, and message without persisting credentials. Fixture failure
evidence also records the failed statement index, operation kind, byte length,
and SHA-256 without copying statement text. The saved console log contains a
normal Neo4j 5.26.30 start and request-initiated shutdown, but no crash or OOM;
the saved configuration used a 512-MiB maximum heap and 256-MiB page cache.
Deterministic generator order places statement 46 at the first 2,000-row
`account_transfer_account` relationship batch. These observations constrain
the failure location but do not establish whether parsing, transaction memory,
or another server condition caused the HTTP 500. It is engineering failure
evidence only and `paper_result=false` remains mandatory.

## D162 Replace scale-load query expansion with sealed parameter batches

The repair does not rerun or mutate job `3793681`. FinBench source partitions
now use schema v2 and stream one hash-bound JSON record per Neo4j operation.
Each data record carries a fixed Cypher template, a `$rows` parameter, expected
affected-row count, source-table identity, and zero-retry declaration. The
loader verifies every record before invocation, sends data only through the
backend parameter interface, requires Neo4j's returned count to match, and
stops on the first discrepancy. Relationship and node operations use `CREATE`
only because every native run owns a newly created empty database and the
partition generator already proves unique entities and complete endpoints.
Legacy schema-v1 partitions remain readable for independent audits.

The SF0.1 wrapper also selects an explicit scale resource profile: 1-GiB
initial heap, 2-GiB maximum heap, and 1-GiB page cache inside the unchanged
16-GiB Slurm allocation. Development fixtures retain the 256/512/256-MiB
profile. The selected profile is persisted in the service plan, environment,
and Neo4j configuration, and the correctness auditor requires the SF0.1
profile plus the parameterized zero-retry load evidence. This is a repair gate,
not a performance result; a new exact clean commit and independent audit are
required before any scale or campaign conclusion, with `paper_result=false`.
The complete local acceptance suite subsequently passed 1,123 tests with 36
intentional live/external skips; shell syntax and whitespace checks also
passed. This authorizes publication of the repair commit and one CWRU
correctness submission, not the 736-call comparison campaign.

## D163 Implement the frozen FinBench campaign without weakening its scale gate

The D160 schedule is now connected to one fail-closed native producer and a
separate read-only reconstruction auditor. This does not authorize premature
execution. The producer requires a successful external FinBench correctness
run and its mutation-free audit for the exact workload identity; it copies no
answer rows from that gate and uses it only to admit training exactness.

All 72 physical candidates and all 368 scheduled runs are fixed before fixture
loading. The producer then executes 128 training plans, builds the family
memory, and seals the zero-current-query-profile choices before it performs any
of the 40 profile acquisitions. A second seal fixes the profile comparator
before the 40 paired serving runs. The 160 shadow runs are evaluation-only,
and the answer oracle is parsed only after all 368 plan runs and 736 backend
calls complete. The first failure stops the campaign and automatic retries
remain zero.

The persisted comparison reports family memory, explicitly separate F3
cold-start fallback, family-global ablation, both fixed routes, the
cost-inclusive dual-profile method, and an observed oracle upper bound.
Known-family prediction error, physical-winner accuracy, latency and byte
regret, predicted/observed physical-frontier overlap, and
selection-plus-serving cost are reconstructed independently. Full local
acceptance passes 1,125 tests with 36 intentional live/external skips. CWRU
job `3793698` is the only pending repaired SF0.1 correctness gate; the campaign
must not run until that job terminates successfully and its independent audit
passes. All resulting artifacts remain development-only with
`paper_result=false`.

## D164 Separate the development campaign from a result-blind paper promotion gate

CWRU job `3793698` completed successfully at exact producer commit `bc57a9d`.
Its independent reconstruction audit passed 368/368 checks, reported no failed
check ID, and did not mutate the run tree. This accepts SF0.1 as a development
correctness substrate. It does not convert any existing measurement into a
paper result. The already frozen development family campaign was consequently
submitted exactly once as job `3793702` at clean commit `c00c389`; its result
and independent audit remain pending.

The next boundary is a separate result-blind confirmatory-protocol compiler.
It binds the FinBench source lock, population, development schedule, and
family-memory policy; fixes the primary family-memory-versus-dual-profile
contrast, inferential unit, cost scope, counterbalancing, timeout, zero-retry
policy, statistics, seeds, and failure handling; and makes zero backend, LLM,
or ontology calls. It independently reconstructs the accepted correctness and
campaign audits when their external paths are supplied.

The gate refuses authorization while any physical author decision,
development audit, implementation requirement, or approval receipt is
missing. In particular, the current 36-query development population is not a
valid default confirmatory population because its admission used answer
properties. The recommended replacement is a 48-instance, answer- and
cost-independent cross-fit population with query instance as the inferential
unit. GrailQA and cutoff-bounded FedShop remain separate paper-completeness
gates and do not block implementation of the primary physical experiment.
The committed readiness record is deliberately `paper_result=false`.
The post-gate repository acceptance suite passes 1,138 tests with 36
intentional live/external skips.

## D165 Treat the first family-campaign audit exit as auditor failure only

CWRU job `3793702` completed the frozen 368-plan, 736-call development
campaign at exact producer commit `c00c389` with a successful outer status,
zero automatic retry, and complete runtime cleanup. Its first independent
audit reconstructed the run but failed while rendering its terminal JSON:
the `loads.backends` check retained Python set values, the file writer hid
them behind `default=str`, and the final strict `json.dumps` raised a
serialization error. This is an auditor-output defect, not evidence that the
producer failed or that the audit passed.

The repair canonicalizes sets and frozensets as deterministically sorted JSON
arrays and removes the writer's string-conversion fallback. The original run,
first audit artifact, and stdout are immutable diagnostic evidence. A new
`audit-v2` path must independently reconstruct the old producer run at commit
`c00c389`; only a zero exit, no failed check, and no run-tree mutation can
admit the campaign for development interpretation. No campaign is resubmitted,
and `paper_result=false` remains mandatory.

The repaired auditor at commit `455b47b` subsequently reconstructed the
original producer tree into a new output. It exited zero, passed 92/92 checks,
reported no failed ID, and confirmed `run_tree_mutated=false`. Job `3793702`
is therefore accepted as development evidence. It is not retroactively a
confirmatory run and no metric is promoted to a paper result.

## D166 Compile every population-size option before the author chooses one

The answer-independent FinBench population compiler materializes all three
declared total sizes—36, 48, and 60 query instances—in one registry rather
than compiling only a size chosen after observations. Each option allocates
equally across the three primary families and four structural strata. F1 and
F2 use stable four-fold cross-fit assignments derived from stratum and
within-stratum sampling rank; F3 remains an entirely held-out family. The
options are nested by candidate identity, and no option is selected by code.

Sampling uses only public source identifiers, graph structure, timestamps,
and the source risk-level parameter domain. Blocked labels, answer rows,
observed latency or bytes, winner labels, and current-query profiles are not
sampling inputs. The compiler makes zero backend, LLM, ontology, or profiling
call and fixes `paper_result=false`. A dedicated CPU-only CWRU job records the
clean producer commit and source identities, while a separate auditor reloads
the verified SF0.1 archive, recompiles the complete registry, compares it
exactly, and checks that the source run tree was unchanged. Local readiness
does not choose the confirmatory population or authorize a paper run; the
real SF0.1 compiler job and audit must pass first.

The complete repository acceptance suite passed 1,147 tests with 36
intentional live/external skips; shell syntax and whitespace checks also
passed. This establishes local implementation readiness only.

## D167 Accept the result-blind population gate and bind later compilation to author authority

CWRU job `3793727` compiled all three answer-independent SF0.1 population
options at exact clean commit `10b5600` on `compt393` in 15 seconds. The
independent auditor reloaded the verified archive, reconstructed the registry,
passed 29/29 checks, reported no failed check ID, and confirmed that the run
tree was unchanged. The available public sampling frames contain 3,038 F1,
15,452 F2, and 90 F3 candidates. Sampling read no blocked label, answer row,
observed cost, current-query profile, backend, model, or ontology service. This
accepts the population compiler as real-artifact evidence; it does not select
36, 48, or 60 instances and remains `paper_result=false`.

The next compiler therefore cannot accept an unbound size string. It requires
an explicit author approval record bound to the registry hash and the selected
option hash. That approval may authorize workload compilation but explicitly
does not authorize confirmatory execution. The compiler retains empty-answer
queries, writes public instances and exact oracles to separate files, reuses
the common black-box Neo4j/Fuseki plans, and makes zero external calls. A new
cross-fit prediction core constructs four fold-specific family memories,
excludes the evaluation fold and the query's own observations from every F1/F2
prediction, and keeps F3 as a separately labeled cold family.

The paper-protocol draft also closes two specification gaps before author
approval: its 36-instance choice now refers to the new answer-independent
cross-fit option rather than the invalid answer-filtered development split,
and training repetitions are an explicit author decision. No value is selected
by code. Live scheduling, confirmatory statistics, and the independent campaign
auditor remain implementation blockers. Full repository acceptance passes
1,152 tests with 36 intentional live/external skips.

## D168 Freeze author Option A before implementing or running confirmatory measurement

The author explicitly selected Option A on 2026-09-07. The selection fixes the
48-instance answer-independent cross-fit population, SF0.1 as the primary
scale, seven repetitions for training, selected serving, and shadow plans, and
one infrastructure-only replacement. SF1 remains a deadline-gated robustness
scale: include it only if it is ready by 2026-09-12. GrailQA is the primary
semantic track, and FedShop is included only if ready by 2026-09-24. Query
timeouts remain method outcomes and are never replacement eligible.

The choice is stored as a content-addressed author-selection artifact bound to
the pre-measurement protocol draft. Applying it selects all nine author-owned
decisions and signs the resulting protocol subject, but explicitly does not
authorize confirmatory execution. For the primary SF0.1 run, the frozen design
contains 32 seen-family inferential query instances, 16 cold-family queries,
448 cross-fit training runs, 96 dual-profile acquisition runs, 672 paired
selected-serving runs, and 672 post-selection shadow runs: 1,888 plan runs and
at most 3,776 black-box backend calls. Repetitions remain within-query
measurements, not independent samples.

A CPU-only freeze job now replays the accepted population audit, binds the
selection to the exact registry and 48-query option hashes, materializes the
public workload and separately sealed oracle, and freezes all 22 measurement
blocks. Its independent auditor reconstructs the approval, workload, and
schedule without modifying the producer tree. Both keep
`confirmatory_execution_authorized=false` and `paper_result=false`; live
measurement still requires the runner, statistics analyzer, and final campaign
auditor to pass their implementation gates. Full repository acceptance passes
1,156 tests with 36 intentional live/external skips.

## D169 Make the query instance—not repeated executions—the confirmatory unit

The confirmatory analysis contract is now executable independently of the live
runner. A content-addressed measurement ledger requires exactly one valid
method outcome for every identity in the frozen 1,888-plan schedule. The
executed physical strategy must match the pre-execution family or profile seal,
all 22 blocks must have a completed attempt, and a replacement is allowed only
after an infrastructure attempt produced zero valid measurements. A query
timeout is retained at the predeclared 60-second analysis boundary and cannot
trigger a replacement; missing byte counts remain missing rather than being
imputed.

RQ-P1 uses only the 32 cross-fit F1/F2 query instances. Seven serving
repetitions are reduced to a within-query median. Family-memory end-to-end cost
has zero current-query acquisition, while the dual-profile comparator includes
both acquisition plans plus its selected serving median. The primary effects
are the geometric mean within-query latency ratio and paired median latency
difference, with a fixed-seed 10,000-resample query-cluster bootstrap and a
100,000-draw two-sided paired sign-flip test. Repetitions contribute no
independent sample count.

RQ-P2 reconstructs winner accuracy, latency and byte regret, serving-only and
end-to-end latency, prediction error, and predicted/observed frontier overlap
for family memory, leakage-safe family-global, both fixed routes, dual profile,
and the postexecution oracle. Secondary paired tests use Holm adjustment. RQ-P3
keeps all 16 F3 queries in a distinct cold-start report and never labels their
predeclared fallback as family memory. Offline training cost and amortization
are reported outside the primary end-to-end estimand. Synthetic acceptance
passes together with the existing protocol, population, workload, cross-fit,
schedule, and freeze regressions. The analysis still requires a live block
runner and independent evidence reconstruction before any output can set
`paper_result=true`. The compact local readiness record is
`experiments/artifacts/m15_finbench_confirmatory_analysis_readiness_v1.json`;
full repository acceptance passes 1,160 tests with 36 intentional skips.

## D170 Admit pre-oracle costs by semantic contract and delay the answer oracle

Confirmatory family-memory training may use successful cost observations before
the current 48-query answer oracle is opened. This is permitted only through a
content-addressed selection-admission record that independently replays the
accepted real SF0.1 correctness audit, binds its external CWRU receipt and
source archive, and proves that the F1/F2 physical alternatives retain the
same hard-constraint and semantic plan-family contracts. It is not a claim
that current-query answers have already been checked. The final confirmatory
oracle remains authoritative.

Training reduction is block paired. A query contributes a strategy comparison
only when both physical alternatives completed successfully in the same block;
at least four shared successful blocks are required and no missing value or
timeout is imputed. Current-query profile selection may use result-blind costs
with `exact_answer=null`. All current confirmatory outcomes retain that value
until the delayed oracle gate verifies that 22 accepted blocks cover the exact
1,888-run schedule.

Method timeouts are fixed 60-second outcomes, not infrastructure failures.
Neo4j and Fuseki enforce that deadline server-side while the HTTP transport has
a 65-second grace. A replacement is possible only for one independently
audited, zero-measurement infrastructure failure and must explicitly reference
the failed attempt. Backend/plan failures, partial blocks, and query timeouts
cannot enter that path. These rules add no execution authority and keep
`paper_result=false`. The staged coordinator and final campaign auditor now
pass local acceptance; their exact clean commit must still be bound into the
request before the author is asked to authorize the campaign.

## D171 Make the confirmatory campaign a one-way staged dependency graph

The 22-block Option-A campaign is coordinated through immutable files and
Slurm dependencies, not a long-running controller that can silently mutate its
plan. Seven sequential training blocks and one profile block must complete and
pass independent per-block reconstruction before selection is assembled.
Seven serving and seven shadow blocks are then compiled from the sealed
selection state. The delayed oracle job runs only after both arrays complete,
and the final audit runs after the oracle job has terminated.

Every normal dependency is fail-closed and automatic retries are zero. A
failed block therefore pauses the campaign. The only replacement path is an
explicit operator action that first reruns the independent block auditor and
accepts attempt 2 only when attempt 1 made zero measurements and was classified
as infrastructure failure. Method timeout, backend or plan failure, partial
measurement, and any second failure cannot be replaced.

The campaign producer always writes `paper_result=false`. A separate read-only
auditor reconstructs the complete campaign tree and the recorded Slurm
dependency contract; only its successful admission of a successful campaign
may emit `paper_result=true`. This implementation does not itself authorize a
remote run. The exact execution request and a later explicit author authority
record remain mandatory inputs to initialization.

## D172 Separate inferential analysis from paper presentation

The delayed oracle owns all confirmatory statistics. The paper-report layer may
only project those immutable values after the final independent campaign audit
has admitted the source result; it may not rerun, tune, filter, or replace an
analysis. Its JSON and Markdown outputs bind the campaign result, oracle,
analysis, audit, runner commit, and complete source-tree digest.

The primary RQ-P1 table keeps 32 seen-family queries as the inferential units
and explicitly states the direction of the family-memory/profile latency ratio
and paired difference. RQ-P2 reports method-level winner accuracy, latency and
byte regret, end-to-end latency, prediction error, frontier overlap, and the
predeclared Holm-adjusted comparisons. RQ-P3 keeps the 16 held-out F3 queries
descriptive, never labels their fallback as family memory, and performs no
inferential test. Offline training and failure accounting remain separate.

Admission of this FinBench report supports the heterogeneous physical-plan
optimization comparison only. It cannot support the semantic-ambiguity,
ontology, or general KGQA claims, which require their separate GrailQA and
external-validation evidence.

## D173 Audit live semantic preflights independently of process success

A successful CWRU process exit is necessary but not sufficient evidence for
the GrailQA interpretation preflight. A separate read-only auditor must bind
the clean producer commit, H100 and vLLM environment, model and prompt bundle,
deployment contract, exact frozen 18-query set, and the query-local catalog and
reachability hash chain. It must reconstruct the generation/repair call ledger,
enforce the declared one-to-three candidate boundary on every schema-valid
provider response, and recompute the overall and jointly reachable-subset
metrics from row-level artifacts.

The auditor does not impose a recall threshold. It reports provider failures
separately and marks whether they confound the observed Candidate Recall, so a
transport or structured-output failure cannot be presented as evidence about
model capability. Its output is outside the immutable source run tree and
retains `paper_result=false`; the 18-query run remains a development gate and
does not authorize the 150-query pilot or support a paper claim by itself.

## D174 Freeze the semantic estimand before reviewing the live preflight

The GrailQA paper track now has a result-blind protocol compiler rather than a
direct path from the 18-query engineering run to the 150-query experiment. The
draft binds the existing outcome-independent 150-query population, the frozen
Qwen3-32B/vLLM bundle, Top-20 retrieval, Top-4 per-slot prompt visibility, the
three-candidate cap, one repair call, and no backend or native-query execution.
It cannot read live preflight results and cannot authorize a full run.

The proposed primary comparison reuses one generated, validated, and grounded
candidate set for both methods: ontology-bounded `c_sem`/epsilon ranking versus
model-confidence Top-1. The primary outcome is exact canonical structural
interpretation match. Candidate Recall@3, feasible coverage, hard-constraint
violations, frontier cardinality, provider/repair/token/latency cost, and the
jointly prompt-reachable stratum are reported separately. Catalog reachability
is a diagnostic rather than a semantic baseline. Gold-simulated clarification
may be an explicitly labelled post-inference oracle upper bound, never the
treatment or evidence of real user interaction.

The query is the inferential unit. The draft predeclares exact paired McNemar
testing for correctness, a fixed-seed 10,000-resample paired query bootstrap,
Holm adjustment for secondary comparisons, no imputation, and completer-only
analysis as diagnostic. Provider, malformed-output, grounding, and empty-set
failures remain query outcomes under the recommended all-query estimand.
Five scientific choices remain author-owned. Even after their approval, the
18-query independent audit and author review, query-local pilot150 catalog,
paper runner, analyzer, auditor, and a separate full-run authority remain
mandatory. The draft therefore stays `paper_result=false` and makes zero LLM,
backend, or ontology-service calls.

## D175 Match primary return cardinality in the GrailQA semantic analysis

The primary paired correctness event compares exactly one candidate from each
method over the same generated, validated, and grounded candidate list. XGAP's
primary candidate is rank 1 after semantic admission, epsilon filtering,
semantic-equivalence merging, and the fixed candidate cap. The comparator's
primary candidate is its declared rank 1 over that same shared list. A correct
candidate anywhere else in the XGAP frontier does not make the primary XGAP
outcome correct. Candidate Recall@3, full-frontier cardinality, and the
gold-simulated clarification upper bound remain secondary diagnostics.

The analyzer requires exactly the frozen 150 unique query IDs together with
the predeclared 120/30 split and 83/56/11 Q-bucket distribution. It content-
binds the outcome ledger, protocol, author selection, and source run; treats
the query as the inferential unit; uses exact paired McNemar and the fixed
10,000-resample paired query bootstrap; preserves failures without imputation;
and reports completer-only results as diagnostic. Invalid provider/repair call
accounting, cardinality, grounding, hard-constraint, population, or schema
state fails closed.

This implementation resolves an engineering blocker, not any of the five
author-owned scientific choices. It makes zero model, backend, or ontology-
service calls, cannot authorize the 150-query run, requires a later independent
reconstruction auditor, and remains `paper_result=false`.

## D176 Reconstruct the semantic analysis outside the producer

The GrailQA paper analysis is accepted only when a separate read-only auditor
reconstructs it from the frozen row-level outcome ledger. The auditor does not
import or invoke `grailqa_semantic_analysis`; it separately validates the exact
150 unique query IDs, 120/30 split, 83/56/11 Q-bucket distribution, provider
and repair accounting, candidate schema, hard constraints, source-run identity,
protocol identity, and author-selection identity. It then independently
recomputes grounded candidates, the matched-cardinality XGAP and comparator
rankings, exact McNemar statistic, fixed-seed 10,000-resample paired bootstrap,
Holm-adjusted secondary tests, failure and cost summaries, and every per-query
record before comparing the complete reconstructed analysis hash.

The audit is deliberately compact: a mismatch records hashes and named checks,
not a second in-memory copy of a potentially large diagnostic diff. It snapshots
all inputs before and after reconstruction and fails if any changed. Tests prove
that it rejects source-ledger mutation, duplicate populations, source-run drift,
symbolic-link evidence, and a modified analysis whose own self-hash was
recomputed. The auditor makes zero LLM, backend, or ontology-service calls,
cannot infer any of the five author-owned choices, cannot authorize inference,
and always remains `paper_result=false` until a later live run and its separate
authority boundary exist.

## D177 Constrain the admitted FinBench claim to what the baselines identify

The independently admitted FinBench campaign has now been rendered into the
paper-report projection without rerunning statistics. On the 32 seen-family
query units, zero-profile family memory is substantially faster end to end than
current-query dual profiling: the geometric-mean latency ratio is 0.3096 with a
95% query-level interval of 0.2509--0.3683 and paired randomization
p=9.9999e-06. It achieves 0.9375 physical-winner accuracy and mean
predicted/observed frontier Jaccard 0.96875. Those are valid artifact-scoped
confirmatory observations.

The same campaign also shows that the family-global ablation and fixed route A
make the same choices, have the same winner accuracy and regret, and are not
distinguished from XGAP by the predeclared Holm-adjusted comparisons. Therefore
this experiment identifies the benefit of avoiding current-query profiling in
this population, but it does not independently identify an instance-specific
family-memory advantage. The 16 F3 cold-family cases remain descriptive and
cannot support a cold-start generalization claim. The physical experiment says
nothing about semantic ambiguity, ontology use, general KGQA, or interaction.
Paper text and figures must preserve those boundaries rather than presenting
the significant profile comparison as proof of every XGAP mechanism.

## D178 Require authority and a durable inference seal for the GrailQA run

The GrailQA production path is a state machine, not a direct model-to-analysis
script. First, a non-authorizing request binds the exact 150 IDs, all five
author-selected decisions, runner commit, query-local catalog, reachability
identities, model bundle, and provider-call limits. Second, the author must issue
a separate decision named `authorize_exact_150_query_semantic_execution` for
that exact request. The CWRU wrapper refuses to start the model without both
artifacts.

During execution, the runner writes one immutable inference state for every
query, allows at most one repair and two external calls per query, and writes a
content-addressed inference seal only after all 150 states exist. Reference
interpretations, workload buckets, and gold-derived reachability rows are parsed
only after that seal. Provider, malformed-output, generation, entity/relation
grounding, semantic, ranking, and empty-set failures are retained in the outcome
ledger without retry or imputation. No backend is executed and no native query
text is emitted.

A separate read-only run auditor deliberately does not import the producer. It
reconstructs the request/authority/seal/ledger hash chain, exact ID population,
per-query and aggregate call limits, forbidden-gold-key absence, phase order,
file inventory, and run-tree immutability. Statistical analysis remains a later
producer-plus-independent-auditor pair. Implementation readiness does not
authorize the model run: real pilot150 catalog evidence, preflight review, the
five author choices, and exact-run authority remain mandatory.

## D179 Independently reconstruct the pilot150 query-local catalog

The 150-query semantic run may not rely only on the catalog producer's own
validation. A separate read-only auditor must bind the exact frozen pilot IDs
and question-only file, the pinned Freebase source-manifest identity, every
declared content hash, the independently recomputed catalog identity, SQLite
integrity, JSONL/SQLite equality, per-query Top-50 candidate isolation, exact
normalized lexical evidence, and the complete reachability artifact hash chain.
It must also require the frozen relation-endpoint contract and a passing
20-percent joint prompt-reachability engineering gate.

This audit deliberately reads only the small source inventory manifest and
records zero Freebase bytes rescanned. The original builder remains responsible
for its verified 964-shard, 32,476,432,840-byte scan; the independent auditor
checks that identity rather than creating an unplanned second 32 GB pass. The
audit writes outside the immutable catalog tree, snapshots it before and after,
makes no model, backend, or ontology-service call, and always leaves
`paper_result=false`. Passing it is necessary but not sufficient for the later
150-query execution authority.

## D180 Treat ignored GrailQA bodies as an explicit runtime prerequisite

The compact GrailQA manifests are versioned, but the dataset bodies they bind
are intentionally ignored by Git. A clean checkout therefore proves source
identity, not runtime availability. The failed CWRU pilot150 catalog job
`3795066` demonstrated this distinction: it stopped before scanning Freebase
because `datasets/grailqa_pilot_v1/inference_questions.jsonl` was absent even
though the protocol and repository tests were green.

The local-catalog Slurm wrapper must now run frozen-artifact verification
before opening the 32 GB Freebase source. Missing bytes fail with an actionable
preparation command rather than a downstream Python traceback. A separate
CPU-only preparation job downloads or rebuilds the pinned public GrailQA,
ontology, and query-independent catalog artifacts, verifies every frozen hash,
and emits a content-addressed runtime receipt. It starts no Qwen process,
backend, or ontology service and performs no Freebase parquet scan.

Manual transfer remains permitted when the transferred directories pass the
same frozen-spec verification. The recovered local backup has been checked
against all five declared pilot hashes and the expected catalog identity.
Neither transfer nor preparation authorizes the pilot150 catalog, the semantic
model run, or a paper claim; those retain their independent audit and
author-authority boundaries.

## D181 Require an evidence-bound GrailQA preexecution admission

The 150-query semantic authority may not assert preflight review with an
unverifiable Boolean. Before an execution request can be created, a separate
preexecution admission must embed and validate four exact records: the
successful independent pilot150 catalog audit, the successful independent
18-query preflight audit, an explicit author review receipt bound to that exact
preflight audit, and the author selection containing all five scientific
choices. The review decision explicitly forbids tuning those choices from the
preflight outcomes.

The admission binds the protocol, author selection, catalog, reachability, both
audits, and review receipt through content hashes. It makes no LLM, backend, or
ontology-service call and remains non-authorizing with `paper_result=false`.
The later execution request and exact-run authority both bind the admission
hash; the H100 runner copies the admission into its immutable control tree and
the independent run auditor reconstructs the complete admission/request/
authority/seal/ledger chain without importing the producer. No review receipt,
author selection, admission, or execution authority is created on the author's
behalf.

## D182 Admit a GrailQA paper result only after two independent reconstructions

Successful H100 inference is measurement evidence, not yet a paper result. The
150-query producer always writes `paper_result=false`. A dependent CPU-only
finalizer first runs the producer-independent run auditor, then the frozen
query-level analyzer, then the independent analysis reconstruction auditor.
Only a fourth, non-measuring admission step may set `paper_result=true`, and
only when all four artifacts bind the same protocol, author selection,
preexecution admission, execution request, execution authority, source run,
and outcome ledger identities. The final claim remains limited to the frozen
GrailQA population; it cannot assert backend performance or general KGQA
generalization.

The server submission helper performs the complete authority-chain and
gold-blind readiness check before requesting an H100, records a single-use
submission lease, and submits exactly one CPU finalizer with an `afterok`
dependency. It does not retry a failed model run. The five scientific choices
are created only through an explicit author-selection command requiring all
five values; recommendations are never silently copied into authority. No
catalog/preflight audit, author review, author selection, request, authority,
or successful final paper artifact may be inferred from a Slurm exit code.

## D183 Test executable handoffs and distinguish evidence integrity from readiness

The GrailQA production pipeline must be tested across the actual submission,
GPU wrapper, generic CWRU launcher, and CPU finalizer scripts with deterministic
process doubles. Syntax and string assertions alone do not prove that these
stages share interpreter, protocol, and artifact paths. Prelaunch control and
cleanup use the configured core Python; environment capture remains inside the
activated vLLM environment. Submission resolves relative paths against the
submission directory without hiding symlinks. An accepted GPU job ID is saved
before dependent submission; failures do not silently create retries. A source
override cannot finalize an unrelated request or authority.

Audit `3795103` demonstrates a separate distinction: all 101 integrity checks
can pass while all 18 measured queries have zero validated candidates. This
preserves a negative development result; it does not establish an operationally
usable semantic pipeline or authorize 150-query inference. Existing provider
envelopes and exact prompt views may be replayed offline to identify the first
rejection without changing the source artifacts. Any repaired diagnostic must
remain separate from the frozen audit, and implementation fixes must not be
presented as new live results. No scientific choice is selected from these
outcomes, and no fresh model invocation is implicit in diagnosis.

Future preflight failure rows may include an optional
`original_inference_failure` copied from the inference state before reporting
classification. This preserves the existing original schema, question ID,
category, and message; it does not add failure rows or change the existing
top-level classification. Metrics and interpretation decisions must remain
identical when the extra field is stripped. It is retained producer diagnostic
data, not a new independently reconstructed causal claim. Existing immutable
run files are never rewritten to add it, and no inference is rerun merely to
obtain the additional field.

## D184 Align normalized GrailQA provider parsing without weakening grounding

Hash-matched raw envelopes from preflight `3795067` demonstrate a concrete
implementation mismatch: the frozen prompt/schema allow omitted selector and
restrictor defaults, but the provider invokes the legacy parser before the
normalized GrailQA runner can supply those existing defaults. The failed
query's generation and repair bodies both omit the fields, are identical, and
both pass the existing normalized parser. They still fail grounding on an
out-of-set type anchor; this correction must not be presented as a recovered
valid interpretation or new live result.

Expose an explicit response parser at the existing provider/factory/wrapper
boundary. Its default stays the legacy parser; only the GrailQA entrypoints
that already normalize downstream select that same normalized parser during
provider validation. Keep raw responses unchanged, the validator hook intact,
and the existing generation/repair bound. Do not broaden exception handling,
silently fall back between parsers, accept malformed semantics, or alter the
frozen model/prompt/schema files.

The other recorded failures remain valid rejections under the current contract:
16 responses omit top-level anchors for candidate-optional hops, and structural
component references are invalid in 26 of the 47 retained candidates. These
overlapping diagnostics do not authorize inferred anchors or variable-to-path
aliases. Making the distinction between top-level anchor completeness and
per-candidate optional realizations explicit, or changing which failures enter
model repair, requires a separately versioned, reviewed interface contract.
The original 18-query negative result and all scientific gates remain intact.

The corrected runner must not bypass the existing implementation hash gate.
Preserve the v1 paper draft and its readiness artifact byte-for-byte; create
a separately numbered, still-unapproved draft v2 with a new protocol ID, the
corrected runner hash, and regenerated freeze/readiness hashes. All scientific,
source, model, prompt/schema, and unselected author fields remain identical.
Current defaults may select that new implementation-bound draft, but old
selection/review/request/authority receipts do not migrate automatically.
This mechanical implementation rebind is distinct from a future prompt or
grounding-policy revision and never authorizes a model run.

## D185 Clarify the GrailQA output contract in an inactive, separately hashed draft

The complete top-level anchor inventory and optional per-candidate realizations
are distinct existing rules. Every supplied query slot needs an anchor even
when a candidate does not use that optional hop. Every actual relation leaf
must still map to its corresponding hop in structural traversal order.
`component_ref` names the actual pattern component, not a variable or label
field. Query anchors and candidate realized terms remain separate semantic
inputs; clarifying syntax must not force their equality.

A new `qwen3_32b_vllm_cwru_grailqa_contract_v1` bundle appends these instructions
without replacing the original prompt. Its schema bytes, model, sampling,
candidate limits, token/time budgets, repair bound, and deployment contract
remain unchanged. A separately identified preflight spec preserves all 18
queries and every scientific field. The existing grounder, normalization,
relation-endpoint exception, and downstream relation-label consistency checks
are not modified. Synthetic offline cases exercise the real parser/grounder;
they are not model-generation or benchmark evidence.

The review record pins both proposed and preserved files. Existing preflight
and paper shell defaults and paper protocol v2 are unchanged, so an old receipt
or invocation cannot silently activate the new prompt. The proposal grants no
execution authority and does not choose the five paper decisions. Actual input
token lengths remain unmeasured locally; fixed context-reservation arithmetic
is not a substitute for checking the pinned tokenizer/chat-template output.
Any fresh small run needs explicit interface review and exact execution scope.
Neither the original negative preflight nor admitted FinBench evidence is
rewritten or reclassified.

## D186 Measure assembled requests and distinguish refused from attempted calls

Context reservations are not token measurements. A separate opt-in boundary
must count the complete text messages with an explicitly pinned, local chat
tokenizer/template before any generation or repair is transmitted. Preserve
the model, output reservation and input/context limits; unavailable counting,
changed tokenizer identity, unsupported rendering parameters, and oversized
requests fail explicitly. Do not truncate, approximate, download a fallback,
or enlarge an experimental budget. A local count alone cannot certify parity
with the actual vLLM service.

The frozen provider records requests before transport, so the independent
adapter must keep actual delegate attempts separate from token-check receipts.
Only its exact typed local refusal may remove the one unsent trailing request
from the public call ledger, after exact prefix/count reconciliation. Sent
transport failures remain charged, and raw responses, usage and elapsed time
are preserved. Refusing a repair does not erase the first call or create another
repair. Concurrent/reentrant invocation is rejected rather than mixing ledgers.

An offline inventory assembles the original full question population using the
existing catalog/view/request builders and requires no credentials or model
call. Missing inputs retain explicit unavailable rows. Token-fit success stays
separate from readiness, server parity, scientific effectiveness and authority.
Old implementations, shell defaults, model/spec/review artifacts, and audited
results are not rewritten. A future reviewed live integration must explicitly
bind the adapter and record its checks; this implementation does not activate it.

## D187 Isolate guarded development execution and journal before transmission

The request guard integrates through a new explicit GrailQA development
entrypoint, not a silent replacement of frozen preflight/paper behavior. Each
query gets a fresh adapter. Token checks are durable before transport;
transport returns and complete provider invocations are retained before
downstream grounding/evaluation. A fatal accounting or journal error stops the
run, preserves the partial evidence, and leaves incomplete totals unknown.
Local refusals remain distinct from transmitted failures and legacy semantic
failure classifications. Neither a completed protocol nor a successful
artifact audit implies a positive semantic result.

Current runner/job/host and frozen spec/model/prompt/endpoint/budget records
must bind before transmission. The explicit local tokenizer snapshot must
belong to the recorded model, but matching records cannot prove actual serving
tokenizer/template parity. Execution therefore defaults to refusal. A separate
explicit development-only unverified-parity acknowledgement is available as
an engineering interface, not a selected scientific mode, an authority receipt,
or a substitute for the still-missing parity evidence. No existing author
receipt is migrated and no new run is authorized. All outputs retain
`paper_result=false` and `remote_serving_parity_verified=false`.

The initial manifest is immutable, final status is separate, and references
remain evaluation-only after all inference. The old parser/grounder/metric
behavior, query population, budgets and one-schema-repair limit are unchanged.
Provider latency already includes its guard/journaling work; initialization and
whole-inference timing are reported separately without double counting.

## D188 Compare server preprocessing per request and account for the extra probes

An explicitly selected development mode compares the pinned local tokenizer's
ordered token IDs against the running job-local vLLM tokenization endpoint
before generation and each actual bounded repair. Local budget refusal causes
neither probe nor inference. A mismatched sequence, context limit or local
identity, unavailable endpoint or unsafe response refuses inference without
retry. Tokenizer identity is rechecked after the network wait. The probe is a
real extra external action: preserve its attempt/result/error receipts and
cost even when no model generation follows. Provider elapsed time already
includes its guard; separate probe timing must not be added twice. Startup
health polling is outside the per-query inference-plus-probe call total.

This observes exact payload preprocessing at probe time, not model weights,
process identity or atomic immunity to restart before inference. Keep global
serving-parity claims false and keep the distinct explicit unverified mode.
Neither mode supplies author authority. All new outputs remain non-paper;
old scientific selections, prompts, specs, audits and evidence do not migrate.

Only the new development runner receives inference and probe transports that
reject proxies and redirects on exact numeric loopback routes. The public
literal `local` placeholder is not treated as a secret on those routes; actual
credential values keep their protections without short-key heuristics.
New launchers require explicit spec/hash/runner and frozen serving interpreter,
validate before model startup, recheck after capture, and exclusively create a
fresh output. They neither alter old launchers nor auto-submit a run.

Persistence failure remains a failed run even if a completion-event or final
status prefix is readable. A separate best-effort exclusive failure marker
preserves this distinction without overwriting prior status. Successful CLI
exit, complete final status and absence of a failure marker are required;
global storage failure leaves completion unknown, never implicitly successful.

## D189 Apply materialization eligibility before query-local entity Top-K

The query-local selector must rank eligible entities, not let high-scoring
alias-only hits consume the quota and delete them afterward. A separately
identified `canonical_eligible_topk_v2` builder therefore completes a disk-backed
name/alias scan, records each query/MID's best lexical hit and English canonical
eligibility, then joins and takes Top-K. Preserve lexical scoring, candidate
bounds, per-query isolation, ontology and grounding. Break only otherwise exact
name/alias ties deterministically in favor of the name. This synthetic defect
does not establish the cause of the real preflight's catalog misses.

Canonical eligibility and second-pass materialization must agree with the
existing final SQLite integrity predicate: ordinary-space-only or empty NAMEs
do not qualify, but a valid NAME for the same MID does. Do not rewrite labels,
extend whitespace rules, promote aliases to canonical names, invent a missing
identity or silently shrink on a cross-pass metadata failure. Completeness of
the input source remains a separately verified prerequisite.

Preserve v1 and every frozen launcher by default. V2 requires explicit fresh
output, distinct CLI workload/artifact names, and no force, reuse or automatic
retry. Check raw paths before symlink resolution. Publish a validated private
copy into an exclusively claimed directory, manifest last; retain incomplete
output on failure, never remove unrelated or historical data. This does not
promise an atomic whole-tree rename or power-loss durability.

Bind deterministic diagnostics, selection/anchor policy and semantic exports
into v2 catalog identity. Keep measured timing/resources outside deterministic
content. Since SQLite byte hashes are not the portable semantic identity,
reconcile its runtime data with the canonical exported views and selection
records; one semantic hash must not conceal divergent runtime labels. A local
consistency validator is not proof of source-wide Top-K completeness, recall,
model effectiveness or historical paper admission. V2 stays development-only.

SQLite cache and buffered-row bounds are not an overall memory or disk quota.
Full-source construction resources and v1/v2 coverage still need separate
measurement. Public schema-label enrichment, retrieval/packing changes, actual
Qwen contract validation, and both datasets' missing original EQ1–EQ5 work
remain independent obligations; this repair grants no new external execution.

## D190 Measure catalog coverage independently of the output-contract repair

Make the next development handoff two independent measurements. Keep the old
preflight18 catalog for the revised output-contract GPU run; construct the
eligibility-first catalog separately on CPU from the complete same frozen
source. Do not change the model output contract and candidate population in
one purported isolated comparison. User submission remains explicit; pushing
verified code is not a remote job submission or full150 authority.

Validate small source/question/ontology/anchor bindings before the expensive
build. Compare the complete identical question population with both actual
catalog retrievers. Persist both retrievals and seal their inference-only
inputs before reading or hashing references. Evaluate query-local component
coverage with full denominators and report regressions alongside gains, not
only recovered examples. Construction resource records remain original
observations, not an independently paired performance benchmark.

After opening selected evaluation references, parse and type-check their
controlled query structure before extracting requirements. An invalid
operator must not turn into an empty relation requirement and a false coverage
gain; do not modify the historical extractor or repair the reference itself.

Preserve old catalogs and runs. New outputs are fresh, symlink/overlap checked
and non-overwriting; failures remain visible with no automatic retry. Require
successful completion and absence of a failure marker. The new comparison
does not create old reachability admission files or license v2 model execution.
Coverage is not answer accuracy and offline backfill is not measured GrailQA
effectiveness. Both development outputs remain non-paper; existing FinBench
physical admission and missing cross-dataset EQ1–EQ5 obligations are unchanged.

## D191 Share catalog record identity across module and import entrypoints

CWRU CPU job `3796878` showed that importing the builder in unit tests does
not cover executing it with `python -m`. Records defined in an executable
module acquire a second class identity when a collaborating selector imports
that same module canonically. Valid inference questions were rejected before
the full-source scan. This is a code-boundary defect, not grounds to edit the
frozen input data or loosen the validator.

Define `InferenceQuestion` and `LocalCandidateMatch` in a shared non-entrypoint
module. Preserve the old import names through re-exports, field definitions,
serialization and question hashes. Keep strict record, field and budget checks;
do not use duck typing, class-name comparisons or `sys.modules` aliases to
mask the defect. Exercise the actual module CLI with a tiny offline source,
real materialization/retrieval, malformed-input refusal and a frozen-version
red reproduction. Frozen scientific inputs and old evidence do not migrate.

Keep this repair separate from schema ranking, semantic validation and model
contract interventions. Preserve the failed CPU output and the in-flight GPU
producer. Verified code may be pushed under the existing authority, but no
automatic server retry, checkout switch, experiment expansion or admission
follows from that push.

## D192 Version canonical AST grounding without changing historical results

The GrailQA canonical-ID path needs an explicit additional check: declaring a
visible class for `source` cannot make a different or absent AST label correct.
Compare actual typed AST class/relation/property terms to slot realizations;
check all additional schema terms against the visible prompt, preserving the
existing exact endpoint-role-derived type exception. Entity-identity literals
in endpoint/edge properties and nested AND/OR/NOT conditions must be visible,
declared nonempty IDs. Do not rewrite the candidate or force legitimate
ontology relaxation back to its query anchor. Native mapping grounding remains
the separate unchanged M12 boundary.

Use a separately frozen development spec and the opt-in
`grailqa_canonical_ast_grounding_v1` policy. Legacy remains the default. Invalid
shared anchors, envelope IDs and candidate cardinality fail the whole response;
grounding failures within a parsed candidate do not discard valid siblings.
Provider JSON/AST parsing and existing bounded schema repair are unchanged;
this is not partial acceptance of malformed provider JSON and adds no calls.

Preserve every generated row and rejection. Only validated, grounded candidates
enter the new candidate/component/semantic metrics. Keep all questions,
including refusals, in recall/coverage denominators; report generated, rejected
and unassessed counts. Bind the policy in the spec, query states, metrics and
launch lifecycle, and refuse mixed policies before evaluation reference reads.
The two migrated source modules in D185's historical prompt-only review are
verified at its recorded base commit; do not rewrite that record's hashes.
All other byte-pinned model/protocol/grammar artifacts remain unchanged.

This milestone does not separate semantic validity from the old M5 OUT-only
lowering capability: IN paths still have that explicit limitation. Nor does
it repair catalog/retrieval coverage, add public aliases, change prompts,
increase budgets, authorize full150, or establish model quality. The next
live step is the separately verified CPU-only catalog comparison; new GPU
execution and independent result admission remain separate boundaries.

## D193 Separate typed interpretation validity from logical execution capability

An IN path failing the M5 lowerer is not, by itself, a malformed semantic
interpretation. Add a closed typed path-validation profile above the unchanged
M5 algebra/lowerer, and a separate logical-capability assessment. Do not remove
directions, manufacture a plan, or treat a caught lowerer failure as success.
Known unsupported directions/regex nodes are enumerated by component location;
unexpected lowering failures are errors rather than invented capability facts.
Every report distinguishes logical availability from unverified backend
execution. Existing M10 validation and D192 defaults remain unchanged.

Semantic validation must still enforce variable types, selectors, recursion
budgets, finite constants and recursively all condition-reference bounds.
Numeric condition references require a fixed-length path under this profile;
first/last endpoints remain meaningful on variable-length paths. This is a
bounded contract, not an expansion to full GPC or a claim of nonempty/correct
answers. The GrailQA canonical grounding boundary remains additional and strict.

Expose the separation only through the separately frozen
`grailqa_canonical_semantic_grounding_v2` development policy. Preserve every
candidate's capability outcome and retain failed questions in metric
denominators. Typed/grounded validity, ontology admissibility, logical-plan
availability and actual backend execution are separate claims. Keep the
existing no-backend/18-query budget, all old scientific inputs, and historical
evidence intact; no new GPU/full150 execution follows from code publication.

Read-only replay of job 3796877 identifies four typed, grounded candidates,
three with available M5 plans and one unavailable IN path. That is neither
new model evidence nor measured answer accuracy. Real directed execution,
catalog/retrieval coverage, provider quality and the original cross-dataset
EQ1–EQ5 comparisons remain required. CPU comparison 3796968 at e39b98e was
reported FAILED (`1:0`, 3m18s): the selected xgap-core interpreter lacks
PyArrow, before Parquet record iteration. This is an environment prerequisite
failure, not evidence of retrieval quality. Preserve the run and require an
explicit interpreter dependency check before any new manual submission.

Offline acceptance: 2318 passed, 36 skipped (598.46 seconds), three examples,
guarded CLI help and CPU handoff syntax pass. This publishes the separated
contract, not a new live result or authority to widen the experiment.

## D194 Opt-in typed/grounded feedback shares the existing single repair

A schema-valid response can still contain no valid grounded candidate. Make
contract-error feedback a separately frozen opt-in policy; do not silently
change the historical provider/default or use answer recall as a repair trigger.
Assess only the exact prompt-bound canonical candidates and D193 typed
semantics. If any candidate passes, retain it and its siblings without repair.
IN/lowering unavailability, semantic-score thresholds, ranking and gold cannot
trigger repair. A wholly invalid response may use the already configured one
repair, shared with parser/schema repair, never a third model attempt.

Persist feedback before any corresponding repair send. Keep original raw
responses and full assembled repair payloads; bound diagnostic strings only
with explicit truncation. Apply the existing token/server checks to the full
payload, charge actual attempts and preserve guard refusals. Journal failures,
internal assessment errors and transport failures are not repairable model
outcomes. Retain existing extra provider validators. Freeze/bind the policy
through prelaunch, inference, outcome and evaluation records; reject mixed
policies before reference reads. Do not change hard semantics, model/prompt,
catalog, budgets or historical accepted evidence.

Read-only uploaded-response diagnosis identifies 15/17 structured envelopes
without a valid candidate and two with four valid candidates. This is a
trigger diagnosis with zero new calls, not measured repair success or answer
accuracy. CPU job 3796988 was manually submitted at e39b98e after the user
installed/import-verified PyArrow 25.0.1 in the exact xgap-core interpreter;
its completion and coverage result remain unavailable. New GPU/full150 runs
remain separately gated. See `docs/report/grailqa_candidate_feedback_v1.md`.

Acceptance: 334 focused tests and the full offline suite (2360 passed,
36 skipped, 595.67 seconds), three offline examples, guarded CLI help and
shell/diff checks pass. No new GPU/backend run occurred during validation.

## D195 Compile typed fixed directed native rows without redefining M5

Add an explicit `typed_fixed_directed_rows_v1` compiler for fixed Rel/Seq
OUT/IN paths, ALL row selection and conjunctive scalar/identity/length
conditions. Preserve positional source/target/intermediate bindings by
orienting each native edge, never by swapping only final answer columns,
rewriting the semantic query, or reversing the stored dataset. M5 lowering,
legacy compiler entrypoints and the path-algebra vocabulary remain unchanged.
Keep recursive restrictor behavior distinct from fixed-path constraints:
bare Rel/Seq does not acquire implicit SIMPLE/TRAIL restrictions. Explicit
node inequalities from the canonical normalizer remain binding.

Cypher emits separate MATCH clauses so a fixed walk may reuse a relationship;
SPARQL emits explicit oriented triples with a mandatory dataset-owned mapping.
Neither output is represented as PathSet. RDF predicate columns do not provide
cross-backend edge identity. Scalar encodings, dataset identity, native engine
version and final-answer normalization remain execution-admission obligations.
Unsupported features and missing capabilities return explicit failures, not
approximations or fabricated empty rows.

Expose the compiler through the existing runtime fragment/plugin/scheduler
contracts, without switching a frozen GrailQA runner to backend execution.
Bind pattern/profile/mapping identities and require exact output columns.
Independent RDFLib execution tests compare all 1–4-hop directions to an
input-triple traversal oracle and cover conditions, repeated edges and safe
literal handling. Preserve supplementary Unicode rather than JSON surrogate
escapes. The stricter opt-in semantic validator checks reference kinds before
legacy NodeNotEquals handling; do not alter the legacy API.

Read-only compilation of the four previously grounded uploaded candidates
succeeds, including the OUT/IN/OUT candidate. This is compilation evidence,
not a new model result, loaded Freebase mapping or executed answer. Required
real-engine admission, broader target structures and original two-dataset
EQ1–EQ5 remain open. Acceptance and limitations are recorded in
`docs/report/directed_native_rows_v1.md`; no CWRU action or new authority is
created by this local milestone.

Acceptance: 301 focused tests and the full offline suite (2479 passed,
36 skipped, 617.48 seconds), three existing offline examples, formatting and
diff checks pass. RDFLib 7.1.4 is a test-only optional dependency; absence
produces explicit skips, not fabricated independent-engine acceptance.

## D196 Preserve resource and RDF-term identity through the answer boundary

The resumed worktree contained an unfinished RDF representation/client draft.
Complete it as a separately selected dataset encoding, without changing legacy
compiler/client defaults, frozen protocols, or audited algebra semantics.
`RdfRowEncoding` declares the class-membership predicate, logical identity
property and resource namespace. Identity equality compiles to RDF term
equality; inequality requires a mapped resource with a valid canonical local
identifier, so literals and foreign resources do not acquire an invented ID.
The encoding is content-hashed alongside the existing mapping/profile/pattern.

Explicit encoded directed artifacts request `rdf_terms_v1` responses and exact
SELECT columns through the ordinary runtime fragment adapter. Fuseki preserves
URI/literal/datatype/language information. Malformed SELECT envelopes and
unscoped blank-node federation are explicit execution errors, not empty
answers. Blank-node labels cannot be joined across result objects until their
scope is represented. The old string-valued client mode remains unchanged.

Answer projection requires an explicit column; property-graph node answers
also require a declared identity mapping. Failed or untyped RDF executions
cannot be normalized to successful empty answers. Exact comparison uses RDF
term sets, retaining numeric lexical differences; it is not a GrailQA official
value-equivalence metric or arbitrary answer serializer.

An independent RDFLib engine executes compiled Freebase-style reverse paths
behind a local HTTP server through the actual Fuseki client, then projects and
checks answers. Tests include misleading literal IDs, custom type predicates,
mapped identity inequality, Unicode, incomplete responses, real empty results,
and coordinator joins. Focused acceptance is 153 passed / 1 gated live skip;
final full regression and existing examples are recorded in engineering_state.

This is local executable identity/answer infrastructure. Real Fuseki has a new
read-only opt-in VALUES test; actual dataset loading, Neo4j identity parity,
GrailQA full answers and general semantic-DAG compilation remain separate
milestones. No live run or research-result admission follows from these tests.

## D197 Materialize inline grounding choices without changing semantic trees

Add an explicitly selected `inline_grounding_v1` wire contract. The model
continues to supply the full PathPatternQuery tree and shared query anchors;
slot selections attach to their actual node, edge, property or condition.
Program code generates structural component paths, copies existing term IDs,
and collects identity literals already present. It never guesses a missing
anchor or semantic choice. Preserve expression association, direction,
conditions, selectors/restrictors and endpoint focus; do not flatten paths or
redefine the frozen interpretation equivalence relation.

Keep semantic defects candidate-local so an invalid sibling cannot discard
a valid candidate or spend an unnecessary repair. Malformed wire structures
still fail the shared response boundary. The existing canonical grounder,
typed validator and at-most-one repair remain authoritative. Retain original
wire content in the invocation, persist separately hashed materializations and
their call/source/payload links, and recompute successful materializations
during read-only replay. Reject validator mutation as an internal failure.
This replay is a parsing/grounding diagnostic, not full protocol admission.

Select this behavior only through matching model metadata and schema
annotation. Add a separate Qwen3-32B bundle and 18-question development spec;
old identities/defaults and all scientific inputs remain unchanged. Differences
in the actual request are confined to the system prompt and wire schema.
No live model/backend run is part of local acceptance. The hypothesis that
serialization simplification improves candidate validity remains unmeasured;
it does not resolve query-anchor self-alignment or establish NL correctness.

The 297-test focused regression covers original/derived evidence, shared repair
and token limits, invalid siblings, actual guarded inference/evaluation,
schema validity, source-bound replay and unchanged old bundle/spec identities.
The historical prompt-only review test reads the evolved provider source from
its original declared commit; it does not replace the review's frozen hashes.
Full regression and all acceptance examples are recorded in
`docs/engineering_state.md` and
`experiments/artifacts/d197_inline_grounding_local_20260909.json`.
Before a real comparison, restore the existing CWRU session, inspect catalog
job 3796988 without duplicating it, select and freeze one catalog, and establish
actual vLLM schema/request-fit and result-verification gates. Do not conflate
catalog changes with the interface effect or advance to full150.

## D198 Recompute the complete inline provider history before admitting evidence

Add a separate read-only provider evidence gate. Reconstruct every inline
materialization, deterministic validation/grounding feedback, and repair body
from retained original responses and inference context. Check all call, token
receipt, transport, invocation, ledger, and consumed-response bindings; preserve
valid failure evidence. Rehashing a changed derived body or omitting an earlier
failed response cannot satisfy this gate. Use the explicitly selected bundle
without ambient environment overrides, and perform no external calls.

The new gate admits only the retained provider subset. It cannot admit a
frozen scientific population or a complete experiment, recompute semantic
metrics/token counts, prove remote server identity, or establish NL accuracy.
Initial token refusals retain zero-call evidence but lack a reconstructable
full request. Their limitation is explicit. The whole-run admission gate
remains a separate next step; old protocols, artifacts and launch defaults
are unchanged. See `docs/report/grailqa_inline_evidence_v1.md`.

## D199 Preserve the real catalog comparison's zero-gain result

The completed CWRU job 3796988 compares eligibility-first entity selection with
the preserved v1 catalog on the same 18 questions. Launch/log/status/report
identities agree. All 15 stage/component coverage cells have zero gains and
losses, and per-query entity IDs/order are unchanged at catalog, retrieval and
prompt stages. Recomputing from the report rows gives joint counts 10/18,
6/18 and 5/18 respectively. The same 8/4/1 information-stage losses remain.

Do not repeat this intervention as if its coverage benefit were still unknown,
promote catalog v2 as an observed improvement, or combine it with the inline
output change and attribute a future effect to either one. Hold the preserved
v1 catalog fixed for that development comparison. Diagnose mention/alias and
ranking exclusions separately; evaluation-derived missing MIDs never become
inference input or execution-fact selection rules.

This is a bounded real development observation. It reads the complete report
through the authenticated portal and preserves a compact per-query receipt,
but does not independently replay retrieval, recompute every source hash,
rescan Freebase, or provide complete local raw-file custody. Construction
resource differences are unpaired observations, not speedup evidence. No new
model/backend call, code change or paper authority follows from the receipt.
See `docs/report/grailqa_catalog_comparison_3796988.md`.

## D200 Reconstruct a complete guarded development observation, then run it

Complete the D198 component with explicit source/catalog/tokenizer inputs,
fresh retrieval and prompt reconstruction, pure typed candidate validation,
independent local token counts, ordered probe/transport/query lifecycle and
metric reconstruction. Open reference content only after inference history is
reconstructed. Missing or changed inputs fail closed; ordinary model failures
remain valid evidence and all 18 questions remain in the denominator.

Actual offline runner integration exposed a prelaunch comparison bug: JSON
integer temperature/top_p values 0/1 were rejected against normalized float
values 0.0/1.0. Accept numeric equivalence for these two continuous fields,
while rejecting booleans, strings and different values. Frozen spec/model
bytes, call budgets, semantic definitions and populations do not change.

Local acceptance: 184 focused passes; 2700 passed, 37 skipped in 625.92s for
the full suite; harness and 19 acceptance examples pass. Tests use synthetic
external transports, and cannot establish live schema acceptance, model
effectiveness, serving-process identity or answer correctness. Actual remote
admission remains pending. See the D200 report and acceptance receipt.

The September 10 user discussion requires a priority correction: catalog is
a grounding adapter, and its current batch scanner does not perform a 3-hop
fact traversal. The unchanged v2 result closes that intervention. Hold v1
fixed and advance real inline18 execution and the graph-answer bridge. Any
future metadata indexing or recall change needs a separate bounded diagnosis;
do not substitute recurring scans or more audit infrastructure for answers.

## D201 Separate typed fact ingestion from catalog metadata extraction

The historical archival adapter intentionally filters predicates and drops
ordinary/datatype-bearing literals. Keep that compatibility behavior intact.
Add a separate six-column typed reader and finite-budget N-Triples exporter
for all facts in explicit source-manifest shard selections. There is no
question, gold/reference, entity-candidate, predicate filter or hop-expansion
input. Preserve lexical/datatype/language/resource identity and duplicate
occurrences; invalid terms and exceeded budgets fail with retained partial
output, never a silently truncated complete snapshot.

The first frozen shard was selected before data inspection, downloaded once
and verified against its original 14,984,726-byte identity. All 3,247,670 rows
were exported to 13 parts / 420,940,219 bytes. Independent Arrow source and
RDFLib N-Triples term streams agree, including 10,530 date/year literals. The
initial independent checker mishandled RDFLib's implicit language datatype;
its failed trace and corrected v2 are preserved without changing the exporter
or rebuilding data. Construction and verification are separate local
observations, not comparative performance or question-answer measurements.

Local acceptance: 203 focused passes/one live skip; 2752 full passes/37 skips
in 609.22s; harness, 19 acceptance examples and a new offline demo pass. The
actual HTTP/compiled-query integration uses synthetic data and integer years.
Real date/gYear semantics, Neo4j/Fuseki dataset mappings, loads and generated
federated answers remain H4 work. Reuse completed snapshots. No old catalog,
frozen inference inputs, path-algebra semantics or scientific population was
changed. See `docs/report/freebase_typed_fact_snapshot_v1.md`.

## D202 Execute typed fact queries with explicit resource/literal placement

Preserve the complete RDF snapshot in Fuseki. Mirror every URI-object fact in
Neo4j using absolute IRI resource identities and a relationship predicate
property; MERGE gives RDF set semantics. Keep literal values in RDF form rather
than coercing multivalued or typed terms into scalar property-graph fields.
This declared overlap permits a full-Fuseki correctness baseline for federation.

Use the existing directed compiler and coordinator bound-query node. Add an
explicit finite SPARQL IRI VALUES profile to the Fuseki client so downstream
bindings actually constrain native execution. Reject invalid identifiers,
excess binding bytes/counts and result-overflow sentinels. Unbound existing
queries keep their previous behavior; no logical algebra operator is added.

The real local gate uses the locked Neo4j/Fuseki products on installed Java 21,
without changing CWRU's Java-17 allocation contract. All 3,247,670 first-shard
occurrences were loaded; native distinct counts and 103 entity/name answers
match independent source checks. Both owned services stopped normally. This is
a typed query on a partial source, not a real model prediction or a controlled
performance experiment. Additional book/person queries reuse the same database
state and agree with independent source evaluation at 6/202 English-name pairs.
Full regression passes 2,782 tests with 38 skipped in 596.81s; focused validation,
harness and all 19 acceptance examples also pass. Preserve the first
prelaunch help-validator failure and the numbered successful diagnostic.
See `docs/report/freebase_native_answer_bridge_v1.md` for actual evidence.

## D203 Preserve goal constraints when grounding becomes native execution

Keep candidate grounding and execution-goal admission separate. The existing
typed/canonical contracts can accept a candidate that declares entity IDs but
does not use them in its AST. A goal requiring a named-entity anchor now checks
positive identity equalities at actual node positions; optional exact bindings
remain explicit caller inputs. Never auto-select a prompt entity or reinterpret
a global-class query as the answer to an anchored question. Preserve all raw
candidate outcomes and the old semantic metrics.

Compile the admitted fixed directed path into the existing Freebase resource
mirror and RDF store. Preserve classes, explicit inequalities, supported scalar
predicates and answer position. Transfer whole URI path tuples through an
opt-in correlated runtime/SPARQL binding profile. Do not independently bind
per-position value sets. Scalar encodings must be declared and checked on every
reached path; no coercion of multivalued, nonfinite or type-invalid RDF data.
Do not silently apply implicit restrictors or relax depth/answer budgets.

Five actual native positive/empty fixtures agree with full-Fuseki and independent
source evaluation; a deliberately numeric constraint on a string field fails.
All reused databases shut down normally. Historical 3796877 preparation retains
18 questions/49 candidates and refuses all four remaining typed/grounded
candidates for absent entity equality. This is a controlled execution milestone,
not a new model accuracy or speed result. No new algebra, catalog rebuild,
frozen protocol change or automatic external retry occurred. Focused validation
and harness/examples pass; broad regression passes **2,827 tests with 38 skipped
in 643.80s**. See the [D203 report](report/grounded_candidate_execution_v1.md).

## D204 Preserve the frozen experiment across an offline source transfer

The restored OnDemand session exposed GitHub HTTPS authentication failure
before the pending inline18 experiment could be submitted. Keep the original
6b32b97 runner, model, catalog and experiment unchanged. A self-contained Git
bundle, independently cloned and checked against the exact commit/tree,
provides the same source without server GitHub credentials. The new package
checks its bundle hash and replaces only the clone source; it retains original
prelaunch checks, exclusive output creation and the single-submission guard.
Do not alter browser permissions, overwrite conflicting checkouts, repeat
authentication attempts, or claim a job before an actual submission response.
The user later enabled file upload; the offline ZIP was transferred and its
hash verified on Pioneer. Concurrently the user's original HTTPS launch
authenticated, cloned and checked out exact 6b32b97. The original helper
subsequently submitted job 3799513 once; latest authoritative
state is PENDING / Resources. The actual experiment result remains pending. See
[D204 deployment evidence](report/grailqa_inline18_remote_execution_20260910.md).
