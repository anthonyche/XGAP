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
