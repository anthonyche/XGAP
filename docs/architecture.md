# XGAP Architecture

The toy-first semantic compiler now admits explicit native/read/coordinator
requirements using runtime nodes owned by the requesting semantic operator,
after native compilation and before observation or execution. Requirements
cannot borrow another operator's capability; native profile/encoding/shape
checks remain necessary. This static admission is separate from live health
and arbitrary domain-specific semantic admission. See
[the capability decision](decisions/semantic_capabilities_v1.md).

XGAP is a cost-aware agentic federated graph-query system over heterogeneous
black-box engines. Its mainline architecture is specified in
[`docs/agentic_architecture.md`](agentic_architecture.md).

For current implementation and measured acceptance, use
[engineering_state.md](engineering_state.md) and
[the M15 core record](m15_agentic_federated_core.md). The M0–M13 sections below
describe each layer at its historical milestone; statements such as “future”
or “outside the current execution boundary” in those sections do not supersede
later M15 two-engine measurements or the separately selected D195–D197 work.

The agentic pipeline is:

```text
User goal + session
  -> optional versioned deterministic intake template
  -> partially bound Semantic Graph Program
  -> bounded observation / decision / tool-action loop
  -> semantic resolution and source binding when required
  -> backend fragment compilation
  -> federated execution plan
  -> remote backend calls + coordinator exchange/join/merge
  -> observation, memory update, and optional replanning
  -> answer, clarification, explicit failure, or budget exhaustion
```

The existing M0-M13 pipeline remains a compatibility and experiment substrate.
Its deterministic path-query core is aligned with the path algebra from
"Path-based Algebraic Foundations of Graph Query Languages". XGAP does
not rename or replace the path-algebra operators.

The XGAP `ReverseOp` orientation extension now connects IN to logical reference
execution while retaining the existing directed Edges(G) source. UNDIRECTED
uses Union of both orientations, with shared PathSet identity/recursion rules.
The bounded native compiler expands those orientations within its branch budget;
older M9 still rejects unsupported Reverse. See the independent
[semantic decision](decisions/path_orientation_v1.md) and
[orientation gate](report/toy_backbone_t1_orientation.md). The historical D195
wording below describes the earlier native-only boundary.

An explicit `compile_directed_rows` entrypoint also consumes the typed
PathPatternQuery directly for fixed Rel/Seq OUT/IN fragments. Its
`DirectedRowFragmentCompiler` adapter produces the ordinary runtime RemoteQuery
contract without claiming that M5 has gained reverse-path lowering. It emits
native row bindings with traversal-position columns, not PathSet, and leaves
dataset identity and answer normalization explicit. This local extension does
not enable backend execution in a frozen semantic-only experiment. Independent
SPARQL-engine checks and the still-required real-backend boundary are documented
in [the directed-row report](report/directed_native_rows_v1.md).

Semantic query/dataflow operators, agent/control actions, and federated runtime
operators live above this algebra in separate typed namespaces. For example,
`ResolveEntity` is an agent action and semantic `Traverse` may carry a
`PathPatternQuery`; neither is a new path-algebra operator.

The bounded path planner now expands Rel/Seq/Alt and root finite Plus/Star into
native candidates, then runs the existing SolutionSpace selector semantics in
the coordinator. `compile_bounded_path_plan` emits both stages explicitly and
requires dataset identity/domain mappings. See [T1 coverage](report/toy_backbone_t1_bounded_paths.md)
for the all-eighteen toy execution evidence and remaining logical/scale limits.

`compile_semantic_program` now composes Match/Traverse and the existing semantic
row operators into a federated execution DAG. Source placement and backend
identity/domain mappings are explicit inputs. Shared ancestors compile once;
Match uses Nodes/Selection native compilation and Traverse calls the bounded
path planner. It does not perform semantic-hole resolution or automatic source
optimization itself. The separate planning entrypoints below connect candidate
generation and cost selection. See [the semantic DAG gate](report/toy_backbone_t1_semantic_dag.md).

That selection boundary now has a separate `enumerate_semantic_plans` and
`run_semantic_plans` connection: one typed program plus logical source/snapshot
replica declarations produces finite placement candidates, deduplicated registered
observations, explicit exchanges, existing cost selection and selected execution.
The direct compiler still takes explicit placement. This does not infer source
completeness, discover arbitrary sources or split Traverse internals; see
[the candidate planning gate](report/toy_backbone_t1_candidate_planning.md).

`run_agentic_semantic_query` connects the existing resolver/GoalLoop to this
planner through `bind_semantic_query`. Typed registered values replace explicit
slots in actual query meaning and logical-source assignments. Entities require
one authoritative identity and an enforcing descriptor/predicate. Named
structured constraints are conjoined with existing Match/Traverse/Filter
conditions; unsupported or unused requirements stop before database calls.
Physical costs only compare placements of one bound meaning. The entry accepts
a prepared semantic template; NL model quality and complete catalog lifecycle
acceptance remain separate. See [the binding gate](report/toy_backbone_t1_semantic_binding.md).

M15-E3's deterministic intake compiler is likewise a frontend compilation
step, not an operator. It may instantiate only the semantic DAG, holes, and
constraints declared by its versioned template. Its artifact catalog,
ontology, and user clarification capabilities are agent tools; they do not add
logical-algebra operations or backend-native text.

M15-E4 is the deterministic boundary between that resolution output and an
executable family. It first enumerates semantic equivalence classes, then asks
whether every required capability has hash-bound evidence. Capability checking
is distinct from semantic resolution and physical strategy selection:
unsupported meanings remain explicit, while supported meanings alone receive
registry-backed runtime candidates. Bridge-owned native templates are ordinary
black-box interface artifacts and cannot redefine the semantic or path
algebras.

The path-algebra vocabulary remains limited to:

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive`
- `GroupBy`
- `OrderBy`
- `Projection`

M6 adds a separate minimal focused binding layer for bounded
QGP-inspired quantification. These operators are not claimed to be part
of the path algebra:

- `BindNode`
- `BindEdge`
- `BindingJoin`
- `BindingProject`
- `QuantifiedCheck`
- `AntiSemiJoin`
- `FocusProjection`

The focused binding layer consumes results from the path algebra but
does not redefine the existing path operators or their semantics.

## Logical Algebra Layers

XGAP's logical algebra is organized into three semantic layers.

## Core path algebra

The core algebra operates only over PathSet.

Nodes(G)      -> PathSet
Edges(G)      -> PathSet
Selection     PathSet -> PathSet
Union         PathSet x PathSet -> PathSet
Join          PathSet x PathSet -> PathSet

This layer supports fixed-length path construction, filtering, set union, and path concatenation.

## Recursive path algebra

The recursive algebra also operates over PathSet.

Recursive     PathSet -> PathSet

RecursiveOp corresponds to Kleene-plus path construction. Kleene-star is represented later by combining Nodes(G) with RecursiveOp through Union.

Supported recursive modes are:

WALK
TRAIL
ACYCLIC
SIMPLE
SHORTEST

These modes correspond to path restrictors: they decide how paths are computed.

## Extended path algebra

The extended algebra introduces SolutionSpace, a secondary data object used for selector-style semantics.

GroupBy       PathSet -> SolutionSpace
OrderBy       SolutionSpace -> SolutionSpace
Projection    SolutionSpace -> PathSet

A SolutionSpace organizes paths into partitions and groups and assigns ranks to paths, groups, and partitions.

The extended algebra supports selector-style query plans such as:

Projection
  OrderBy?
    GroupBy
      Recursive
        core path algebra expression

For example, an ANY SHORTEST TRAIL style plan is represented as:

Projection [*, *, 1]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      Recursive [mode=TRAIL]
        Selection [label(edge(1)) = "Knows"]
          Edges

In this plan:

Recursive [mode=TRAIL] computes trail paths.
GroupBy [SOURCE_TARGET] groups paths by their endpoints.
OrderBy [PATH] ranks paths inside each group by path length.
Projection [*, *, 1] returns one path per group.


## Focused quantified binding layer

M6 introduces a minimal binding layer for bounded, focus-oriented
quantified tree patterns.

BindNode          PathSet -> BindingRelation
BindEdge          PathSet -> BindingRelation
BindingJoin       BindingRelation x BindingRelation -> BindingRelation
BindingProject    BindingRelation -> BindingRelation
QuantifiedCheck   candidates x witnesses x optional-domain
                  -> BindingRelation
AntiSemiJoin      BindingRelation x BindingRelation -> BindingRelation
FocusProjection   BindingRelation -> PathSet

This layer supports edge-level existential, count, ratio, universal, and
negative conditions.

It is deliberately narrower than a general relational graph algebra.
It does not implement arbitrary assignments, query-level joins,
cyclic conjunctive patterns, bag semantics, or null semantics.

## Data Objects
# Path

A Path is an alternating sequence:

node, edge, node, edge, ..., node

A zero-length path contains a single node.

A one-length path contains:

source, edge, target
# PathSet

PathSet is the primary data object. Core and recursive operators consume and produce PathSet.

# SolutionSpace

SolutionSpace is the secondary data object. It is used only by the extended algebra.

A SolutionSpace represents:

SS = (S, G, P, α, β, △)

where:

S is a PathSet.
P is a set of partitions.
G is a set of groups.
α : S -> G assigns each path to a group.
β : G -> P assigns each group to a partition.
△ assigns a positive integer rank to each path, group, and partition.


# BindingRelation

`BindingRelation` is the tertiary data object introduced by M6.

A binding relation has:

- an ordered schema of variables and binding kinds;
- a deduplicated set of immutable rows;
- deterministic row ordering for formatting and reference evaluation.

M6 bindings contain node and edge values. General path bindings,
nullable bindings, bags, and arbitrary GPC assignments are outside the
M6 scope.

`BindingRelation` is used only by the focused quantified binding layer.
It does not replace `PathSet` or `SolutionSpace`.

## Layer Separation

Entity grounding is outside the logical algebra.

Mentions, entity candidates, schema matching, confidence scores, ambiguity grounding, and disambiguation belong before deterministic lowering.

Once XGAP lowers a candidate structured query to a logical plan, the plan must contain only audited deterministic operators.

A `PathPatternQuery` lowers only to the path-algebra operators.

A `FocusedQuantifiedPatternQuery` may additionally lower to the minimal
focused binding operators introduced by M6. It must not emit backend,
optimizer, LLM, or undeclared future operators.

LLMs may propose candidate interpretations in later milestones, but
type checking, bound validation, lowering, plan validation, and
reference evaluation remain deterministic.

## Module Layout

- `xgap.semantic`: typed backend-independent Semantic Graph Programs,
  operator/value kinds, hard or relaxable constraints, and unresolved holes.
- `xgap.tools`: typed tool effects/results, deterministic registries, and
  pluggable black-box backend operations.
- `xgap.agent`: explicit goals, observations, traces, memory, policies, and the
  bounded observation-decision-action loop.
- `xgap.runtime`: per-backend fragment compilation, federated execution DAGs,
  parallel remote calls, alignment, exchange accounting, coordinator joins,
  merge, and normalized runtime results.
- `xgap.algebra`: path data model, graph representation, condition AST,
  path-algebra operators, minimal M6 binding data objects and operators,
  evaluator, validation, optimizer placeholder, and pretty printing.
- `xgap.pattern`: M5 GPC-Lite path-pattern AST and M6 bounded focused
  quantified-pattern AST, together with their separate type checkers and
  deterministic lowering interfaces.
- `xgap.compilers`: target compiler interfaces for GQL, Cypher, and
  SPARQL. M9 implements a minimal Cypher and SPARQL compiler for a
  bounded row-oriented path/GPC fragment after M8 capability checks.
  GQL remains an explicit unsupported compiler boundary.
- `xgap.infrastructure`: JSON-serializable backend descriptors,
  runtime records, dataset specs, query artifacts, execution reports,
  and run records.
- `xgap.backends`: descriptor registry, native-query client protocol,
  minimal Neo4j/Fuseki clients for already-authored Cypher/SPARQL
  smoke artifacts, M8 capability profiles, and static compatibility
  checks.
- `xgap.planning`: M11 immutable physical-state contracts, versioned
  ontology/alignment boundary, deterministic logical-plan indexing, bounded
  physical search, feature extraction, Gaussian-process cost snapshots,
  current compiler adapter, Nash selection, and test-only exhaustive oracle.
- `xgap.experiments`: backend smoke harnesses, result normalization, the M11
  controlled physical-planning runner, and M12 versioned dataset/model/spec,
  semantic-deviation, metric, execution, manifest, and run-layout contracts.
  The same M12 runner selects the M12-A controlled path or the M12-B bounded
  live/runtime path by configuration. M12-B adds lexical/alias ontology
  retrieval, prompt-schema views, runtime query slots, grounding artifacts,
  and a file-backed alignment provider. M12-C adds a separate calibration
  runner, repeated native-query measurements, backend-local D0 artifacts,
  calibrated RBF GP snapshots, and an across-task posterior lifecycle. M12-D
  adds explicit method/ablation policies, frozen candidate replay, the online
  task runner, deterministic experiment matrices, checkpoint/resume,
  aggregation, and environment readiness/freeze manifests.
- `xgap.llm`: M10 planner-facing schemas, controlled candidate JSON
  parsing, provider protocol, mock provider, deterministic candidate
  validation helpers, and the M12-B generic OpenAI-compatible structured
  provider. Live network use remains configuration- and credential-gated.
- `xgap.datasets`: KGQA dataset loader and evaluation placeholder.

## Backend Infrastructure Layer

The backend infrastructure layer is outside the logical algebra. It
records backend descriptors, connection settings, native-query runtime
status, native smoke query artifacts, execution reports, and run logs.

The Neo4j and Fuseki clients execute native Cypher and SPARQL query
artifacts only. They do not compile `LogicalPlan` objects, do not alter
path/GPC semantics, and do not participate in deterministic lowering.

In M7, backend capability fields are descriptive feature metadata for
graph model, path/GPC fragment, and result model support. They are not
yet a full compiler capability checker and do not introduce new logical
operator vocabulary.

M8 upgrades those fields into program-checkable capability profiles.
The profile layer must answer whether Neo4j or Fuseki can theoretically
support a particular XGAP path/GPC logical fragment, before any future
compiler tries to emit native Cypher or SPARQL.

M8 also defines the compiler boundary: validated XGAP logical input,
native query artifact output, and explicit unsupported-feature reports.
It does not implement logical-plan-to-native-query compilation.

## Experiment Artifact Layer

M12 places a versioned experiment layer around the deterministic pipeline:

```text
DatasetBundle + ModelBundle + ExperimentSpec
  -> mock candidate + controlled evidence
     OR bounded context + live structured candidate + runtime alignment
  -> deterministic M10 validation + frozen M12 semantic deviation
  -> M11 physical planner
  -> frozen runs/<run_id>/ artifact tree
```

Dataset-specific schema, aliases, entities, mappings, optional gold labels,
and backend-load files stay in `DatasetBundle` artifacts. They do not add
dataset-specific branches to logical lowering or physical planning.

M12-B splits inference artifacts from evaluation-only gold. Runtime retrieval
receives ontology, aliases, entities, mappings, and schema snapshots but no
gold answers, logical forms, alignments, or evaluation labels. It emits a
bounded, content-hashed prompt view. Query-side anchors and candidate-side
ontology realizations remain separate inputs to the frozen `c_sem` scorer.

The OpenAI-compatible provider performs one candidate-generation call and at
most one syntax/schema repair. It returns only controlled grounded
`PathPatternQuery` JSON. Type checking, lowering, logical validation,
mapping checks, semantic deviation, physical search, and compilation remain
deterministic and outside the model.

M12-A includes an offline controlled development path only. Backend results,
real D0 observations, GPU/CUDA metadata, and metrics requiring exhaustive or
execution ground truth remain explicitly `not_available` until collected by
later milestones.

M12-C implements the later cost-calibration boundary without changing M11
search. Deterministic controlled complete plans in the M9 compiler fragment
are compiled and repeatedly executed through the existing Neo4j and Fuseki
clients. Raw milliseconds and `log(execution_ms)` are persisted in separate
`D0_neo4j` and `D0_fuseki` artifacts. One existing-family RBF GP is calibrated
per backend and exposed through an immutable registry. Hyperparameters and
feature normalization are frozen during evaluation; a task receives one
posterior snapshot and successful execution observations are appended only as
one atomic post-task batch. Cross-backend movement cost remains explicitly
unavailable because there is no distributed measurement runtime.

M12-D orchestrates these unchanged components. For task q it freezes a
backend-local registry snapshot derived from `D_(q-1)`, generates or replays
candidate artifacts, performs deterministic validation/alignment/planning,
executes selected complete native artifacts, and atomically commits the whole
successful observation batch to produce D_q. No task can update its own
planning posterior. A `no_online_update` run records execution evidence but
restarts every task from D0.

Physical-planning methods share immutable question/model/candidate,
ontology/alignment, backend, D0, feature, execution-protocol, budget, and seed
inputs unless the named ablation changes one of those dimensions. The direct
text-to-graph-query baseline is intentionally separate: it emits exactly one
native query for one backend and bypasses `PathPatternQuery`, `c_sem`, M11,
the GP, and Nash ranking.

Execution success is cardinality-aware: nonempty success, empty success, and
execution error are distinct statuses. An empty result is neither a backend
failure nor evidence of answer correctness. Configured controlled queries may
be marked expected-nonempty and audited separately from general execution.
The DatasetBundle backend mapping is authoritative for RDF native identifiers;
M9 resolves compiler tokens through that mapping and never owns a
dataset-specific namespace.

Experiment matrices expand into immutable concrete specs and deterministic
run IDs. Per-task atomic records are the recovery source for checkpoints and
resume. Development, pilot, and paper modes share the same runner, but paper
mode requires Python 3.10+, clean/hashable artifacts, and identified pinned
backend versions/images. Digest references are the preferred immutable image
identity. These controls establish a paper-artifact freeze boundary; they do
not imply that final benchmark artifacts or results already exist.

The compatibility checker is a static profile lookup. It does not
compile plans, execute native queries, call the reference evaluator, or
invoke optimizer, planner, LLM, ontology, cost, or evaluation code.

## M9 Minimal Compiler Layer

M9 adds the first native-query compiler slice. It is outside the logical
algebra and does not introduce new logical operator names.

The supported M9 fragment is limited to row-oriented compilation of:

- `Nodes(G)`;
- `Edges(G)`;
- `Selection`;
- path-chain `Join`;
- ALL-selector `PathPatternQuery` fragments over fixed `OUT` paths.

Before emitting native text, the compiler checks the target M8
capability profile. Conditional backend support is accepted only for
the documented M9 fragment. Unsupported features raise a
`CompilerFailureSpec` through `UnsupportedCompilationError`.

The M9 Cypher compiler targets Neo4j labeled-property-graph mappings.
The M9 SPARQL compiler targets Fuseki RDF mappings supplied by the active
DatasetBundle. Canonical/compiler tokens resolve to mapped RDF class,
predicate, and property IRIs; a missing or ill-typed mapping is explicitly
unsupported. M9 contains no dataset-specific namespace constant.

M9 native output is a `QueryArtifact` with row bindings. It does not
claim full native `PathSet` preservation, selector semantics,
recursive path restrictors, M6 quantified-pattern compilation,
optimization, planning, LLM use, ontology reasoning, or KGQA
evaluation.

## M10 LLM Planner Boundary

M10 defines the interface for future natural-language planning without
connecting a concrete model.

The LLM boundary may return only controlled structured JSON that parses
into `PathPatternQuery`. It must not emit native Cypher, SPARQL, GQL, or
logical operators. It must not participate in deterministic type
checking, lowering, validation, compilation, backend execution,
optimization, semantic-deviation scoring, ontology reasoning, or KGQA
evaluation.

The deterministic flow after parsing is:

```text
PathPatternQuery
  -> type_check_path_pattern
  -> lower_path_pattern
  -> validate_plan
  -> M9 compiler
```

`xgap.llm` includes a provider protocol and a mock provider for tests.
There is no default live LLM provider in M10.

## M11 Ontology-Bounded Physical Planning

M11 keeps one interpretation's logical plan fixed. Its deterministic main
flow is:

```text
M10 PlannerCandidate
  -> OntologyAlignmentProvider
  -> mapping-sufficiency check
  -> SemanticDeviationScorer
  -> existing deterministic PathPatternQuery lowering
  -> stable logical-plan index
  -> bounded BnB over backend placement and configured exchanges
  -> one discovered representative per interpretation
  -> strict positive-utility Nash ranking
  -> top K
  -> existing M9 compiler or explicit unsupported boundary
```

The search state is `(L_I, Pi, Delta)`. `L_I` never changes inside the
search tree. `Pi` records backend placement decisions for stable logical
operator occurrences, and `Delta` records configured exchange decisions for
cross-backend dependencies. No new logical operator is introduced.

Ontology/schema identity, source mappings, aliases, sufficiency evidence,
and semantic-deviation inputs enter through a versioned external provider.
The controlled artifact implementation reads supplied values and performs no
ontology reasoning. Missing, unsupported, unknown, or insufficient evidence
cannot enter physical search.

`OPEN` is ordered by a conservative lower estimate and stable state ID. One
budget unit is charged per processed `ExtractMin`. The incumbent is the
discovered complete plan with the smallest conservative upper estimate. A
finite budget does not imply global true-cost optimality.

The log-cost GP uses deterministic state features, positive observations from
complete plans only, and one immutable posterior snapshot per task. The
standard-library implementation is intentionally scoped to small M11
planning datasets because the repository has no scientific-computing
dependency. Optional backend/cardinality statistics remain external and are
represented as missing unless supplied.

A complete physical description and current executability are separate.
Single-backend fragments inside M9 compile through the existing compiler.
Unsupported M9 constructs and multi-backend runtime orchestration return
structured boundaries. M11 adds neither selector/recursive/M6 compiler
coverage nor distributed execution.

The main planner returns a plan only when `C_bar < T_max` and both semantic
and execution utilities are strictly positive. It retains at most one plan
per interpretation, ranks by the Nash product, applies deterministic ties,
and does not add threshold relaxation or a Pareto stage.

## GPC-Lite Pattern Layer

M5 implements a path-centric GPC-Lite structured pattern layer. It is not a full GPC implementation.

The deterministic pattern flow is:

```text
PathPatternQuery
  -> type_check_path_pattern
  -> lower_path_pattern
  -> LogicalPlan
  -> validate_plan
  -> reference evaluation
```

GPC-Lite supports node descriptors, edge descriptors, variables, directions, regular path expressions, selectors, and restrictors. The AST can represent `OUT`, `IN`, and `UNDIRECTED` edge directions, but M5 lowering supports only `OUT`.

M13-C adds one generic scalar condition, `NodeNotEquals`, for identity
inequality between two fixed path-node positions. Type checking requires a
fixed-length expression and in-range positions. Deterministic lowering uses
the existing `Selection` operator, and the reference evaluator and M9
compilers implement the same identity predicate. GrailQA conversion, ontology
normalization, mappings, and ambiguity artifacts remain in the experiment
layer; there is no dataset-specific core branch or new logical operator.

M13-E1 adds an experiment-layer canonical interpretation profile without
changing `PathPatternQuery` or lowering. For the bounded fixed-path profile,
an omitted selector/restrictor normalizes to `ALL`/`SIMPLE`; once SIMPLE and a
fixed `Rel`/`Seq` topology are known, pairwise `NodeNotEquals` constraints are
generated deterministically. Variable spelling and commutative condition
child order are representation details. Entity IDs, type constraints,
relation sequence, direction, topology, explicit comparison predicates, and
source/target focus remain semantic and must still match after normalization.

The M13-E1 live boundary consumes a query-independent public Freebase catalog,
bounded entity/type and per-hop relation pools, and optional hop-2/hop-3 prompt
slots. Optional slots permit one-, two-, and three-hop candidates to share one
bounded view without importing gold path length. Gold reference reachability
is computed only by the offline readiness/evaluation layer and can prevent a
paid provider call; it is never serialized into the model request.

M13-E2 keeps that inference boundary unchanged and adds a deployment layer for
CWRU Pioneer. A ModelBundle may name optional environment variables for the
OpenAI-compatible base URL and served model. Provider-owned extra parameters
carry Qwen3's request-local non-thinking setting and are persisted in the exact
request artifact. A Slurm wrapper owns vLLM startup, loopback readiness,
structured serving smoke, environment capture, experiment invocation, and
process cleanup. Slurm/GPU objects do not enter `PathPatternQuery`, logical
plans, `c_sem`, M11, or the GP feature model.

M13-E3A keeps the Catalog-v2 and inference boundaries unchanged while adding
an experiment-layer Freebase source adapter. Source selection is explicit:
`google_rdf_gzip` parses the existing N-Triples contract, while
`hf_archival_parquet` streams immutable shards and row groups from the frozen
archival transport into the same internal triple tuples. Exact source
manifests, not downstream query logic, own repository revision, shard identity,
size, checksum, and schema validation. The archival transport remains
Freebase; it is not an ontology or knowledge-graph substitution.

Supported regex nodes are `Rel`, `Seq`, `Alt`, `Plus`, and `Star`. Future regex nodes such as `OptionalExpr` and `Bounded` are declared but lower with explicit `LoweringError`.

Selectors lower to the audited extended algebra:

- `ALL`
- `ANY`
- `ANY k`
- `ANY SHORTEST`
- `ALL SHORTEST`
- `SHORTEST k`
- `SHORTEST k GROUP`

M5 does not implement assignment semantics, `BindingRelation`, query-level joins, conjunctive graph query semantics, `Maybe`, group variables, bag semantics, null semantics, full GPC label expressions, parsers, backend compilation, backend execution, optimizer rules, LLM logic, disambiguation, cost estimation, or KGQA evaluation.

M5.5 audits this layer without adding new functionality. The audited contract is that GPC-Lite is a structured path-pattern layer above the logical algebra, lowering is deterministic and type-checked before plan construction, and the emitted plan remains inside the path-algebra operator vocabulary. Natural-language planning remains future work.

M6 adds `FocusedQuantifiedPatternQuery` as a sibling of
`PathPatternQuery`. It does not change the M5 AST or M5 lowering rules.

The M6 flow is:

FocusedQuantifiedPatternQuery
  -> type_check_focused_quantified_pattern
  -> validate_quantifier_bounds
  -> lower_focused_quantified_pattern
  -> LogicalPlan
  -> validate_plan
  -> reference evaluation

A focused quantified pattern has:

one focus node;
a rooted, connected, acyclic tree of atomic directed pattern edges;
local node and edge descriptors;
one counting quantifier on every pattern edge;
conjunction across sibling branches.

Supported quantifiers are:

EXISTS
COUNT = k
COUNT >= k
RATIO = r
RATIO >= r
ALL, represented as RATIO = 1
NONE, represented through pattern-level anti-existence

For a quantified edge from parent variable u to child variable v,
M6 counts distinct bindings of v that satisfy the edge descriptor,
the child-node descriptor, and the complete subtree rooted at v.

For ratio quantifiers, the denominator counts distinct target nodes
reachable through the edge descriptor before child-node and subtree
filters are applied.

M6 uses non-vacuous ratio semantics. An empty denominator does not
satisfy a positive ratio or universal quantifier.

NONE is lowered through AntiSemiJoin. It is not represented as
boolean NOT over an already matched edge.

Every root-to-leaf structural path may contain at most two
non-existential quantifiers and at most one negated edge.

M6 does not support regular-path quantification, arbitrary conjunctive
patterns, cyclic patterns, full GPC, general assignments, bag/null
semantics, or multiple focus outputs.

## Legacy M0–M13 Execution Boundary

M0-M6 reference semantics are executable, the M7 backend infrastructure
harness can run already-authored native smoke queries, and the M11 controlled
planner can produce physical-planning artifacts without live services.

The executable path-pattern boundary includes:

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive`
- `GroupBy`
- `OrderBy`
- `Projection`
- GPC-Lite `PathPatternQuery` type checking and lowering

The executable bounded quantified-pattern boundary additionally includes:

- `BindingRelation`
- `BindNode`
- `BindEdge`
- `BindingJoin`
- `BindingProject`
- `QuantifiedCheck`
- `AntiSemiJoin`
- `FocusProjection`
- `FocusedQuantifiedPatternQuery`
- quantifier type checking and structural-bound validation
- deterministic quantified-pattern lowering
- reference evaluation

M6 does not constitute full QGP or full GPC support.

M8 capability profiles, the M9 minimal compiler slice, the M10 structured
candidate boundary, M11 ontology-bounded physical planning, and the M12-B
generic live structured-provider/runtime-alignment path are implemented.
M12-C calibration, M12-D experiment orchestration, the M13-E1 offline
reachability/contract boundary, and the M13-E2 CWRU/vLLM deployment boundary
are implemented. The M13-E3A archival source adapter is implemented. The
comprehensive Freebase catalog-v2 build and guarded live
v2 preflight are not yet measured.
Full compiler coverage, logical rewrite optimization, automated ontology
reasoning, distributed cross-backend execution/movement measurement, final
benchmark integration, and KGQA evaluation remain outside the current
execution boundary.
