# XGAP Architecture

XGAP is an ambiguity-aware natural-language-to-graph-query planner. Its pipeline is:

```text
Natural language question
  -> PathPatternQuery
  -> LogicalPlan
  -> OptimizedPlan
  -> GQL / Cypher / SPARQL
  -> optional backend execution and evaluation
```

The logical algebra is path-based and is aligned with the path algebra from "Path-based Algebraic Foundations of Graph Query Languages". XGAP does not introduce a separate graph algebra vocabulary. The logical operator vocabulary is limited to:

- `Nodes(G)`
- `Edges(G)`
- `Selection`
- `Union`
- `Join`
- `Recursive` with modes `WALK`, `TRAIL`, `ACYCLIC`, `SIMPLE`, `SHORTEST`
- `GroupBy`
- `OrderBy`
- `Projection`

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
## Data Objects
## Path

A Path is an alternating sequence:

node, edge, node, edge, ..., node

A zero-length path contains a single node.

A one-length path contains:

source, edge, target
## PathSet

PathSet is the primary data object. Core and recursive operators consume and produce PathSet.

## SolutionSpace

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
## Layer Separation

Entity grounding is outside the logical algebra.

Mentions, entity candidates, schema matching, confidence scores, ambiguity grounding, and disambiguation belong before deterministic lowering.

Once XGAP lowers a candidate path-pattern query to a logical plan, the plan must contain only the path-algebra operators listed above.

LLMs may propose candidate interpretations in later milestones, but algebraic correctness must be enforced by deterministic validation, lowering, and reference evaluation.

## Module Layout

- `xgap.algebra`: path data model, graph representation, condition AST, logical operators, evaluator, validation, optimizer placeholder, and pretty-print placeholder.
- `xgap.pattern`: GPC-Lite path-pattern query AST, type checking, and deterministic lowering interface.
- `xgap.compilers`: target compiler interfaces for GQL, Cypher, and SPARQL.
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

## Current Execution Boundary

M0-M5 are executable:

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

Backend capability profiles, compilers, logical optimization, learned cost estimation, LLM planning, disambiguation, and KGQA evaluation remain future milestones.
