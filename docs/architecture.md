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
  SPARQL.
- `xgap.llm`: planner-facing schemas and LLM planner placeholder.
- `xgap.datasets`: KGQA dataset loader and evaluation placeholder.

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

M0-M6 are executable.

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

The M6.5 semantic audit, backend capability profiles, compilers,
logical optimization, learned cost estimation, LLM planning,
disambiguation, and KGQA evaluation remain future milestones.