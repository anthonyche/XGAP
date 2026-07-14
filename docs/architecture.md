# XGAP Architecture

XGAP is an ambiguity-aware natural-language-to-graph-query planner. Its pipeline is:

```text
Natural language question
  -> candidate structured query intent
  -> PathPatternQuery | FocusedQuantifiedPatternQuery
  -> deterministic type checking and lowering
  -> LogicalPlan
  -> OptimizedPlan
  -> GQL / Cypher / SPARQL
  -> optional backend execution and evaluation
```

The path-query core is aligned with the path algebra from
"Path-based Algebraic Foundations of Graph Query Languages". XGAP does
not rename or replace the path-algebra operators.

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
- `xgap.experiments`: backend smoke harnesses and result normalization.
- `xgap.llm`: M10 planner-facing schemas, controlled candidate JSON
  parsing, provider protocol, mock provider, and deterministic candidate
  validation helpers. It does not connect a live LLM by default.
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
The M9 SPARQL compiler targets Fuseki RDF mappings through documented
`xgap:` predicate and RDF type assumptions.

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

## Current Execution Boundary

M0-M6 are executable, and the M7 backend infrastructure harness can run
already-authored native smoke queries against configured backends.

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

M8 capability-profile and compiler-boundary preflight is completed.
Full compilers, logical optimization, learned cost estimation, LLM
planning, disambiguation, semantic-deviation scoring, ontology
reasoning, and KGQA evaluation remain future milestones.
