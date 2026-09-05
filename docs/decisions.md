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
