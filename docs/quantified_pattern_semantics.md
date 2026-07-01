# M6 Bounded Focused Quantified Pattern Semantics

## 1. Purpose

M6 adds a bounded, QGP-inspired quantified-pattern fragment to XGAP.

The M6 fragment is designed for focus-oriented graph queries such as:

- a focus node has at least `k` matching neighbors;
- at least a ratio `r` of its relevant neighbors satisfy a branch;
- all relevant neighbors satisfy a branch;
- no neighbor satisfies a branch.

M6 is additive to the existing M5 path-pattern pipeline. It introduces a sibling structured query representation and does not change the semantics or canonical lowering of `PathPatternQuery`.

```text
FocusedQuantifiedPatternQuery
  -> type_check_focused_quantified_pattern
  -> validate_quantifier_bounds
  -> lower_focused_quantified_pattern
  -> LogicalPlan
  -> validate_plan
  -> reference evaluation
```

M6 is not full QGP and is not full GPC. It adopts the edge-level counting intuition, pattern-level anti-existence, and bounded-quantifier principle of quantified graph patterns, but defines a smaller XGAP-specific execution fragment.

## 2. Relationship to Existing XGAP Layers

The existing path algebra remains unchanged:

```text
Nodes
Edges
Selection
Union
Join
Recursive
GroupBy
OrderBy
Projection
```

M6 adds a separate minimal focused binding layer:

```text
BindNode
BindEdge
BindingJoin
BindingProject
QuantifiedCheck
AntiSemiJoin
FocusProjection
```

The focused binding operators are not claimed to come from the path-algebra paper. They provide the minimum correlated-binding substrate needed to evaluate bounded quantified tree patterns.

`GroupBy`, `OrderBy`, and `Projection` remain selector-style `SolutionSpace` operators. They are not used to implement `COUNT(DISTINCT child)`.

## 3. Structured Query Model

An M6 query is a focused quantified pattern:

```text
Q = (x_o, V_Q, E_Q, node_desc, edge_desc, quantifier)
```

where:

- `x_o` is the single query-focus node variable;
- `V_Q` is a finite set of declared node variables;
- `E_Q` is a finite set of quantified atomic pattern edges;
- `node_desc(u)` is the local descriptor of node variable `u`;
- `edge_desc(e)` is the local descriptor of pattern edge `e`;
- `quantifier(e)` is the counting quantifier attached to `e`.

Each quantified pattern edge has the form:

```text
(parent_var)-[edge_descriptor]->(child_var) : quantifier
```

M6 supports only atomic directed `OUT` edges.

### 3.1 Rooted-tree restriction

The structural pattern graph must be a rooted tree whose root is `x_o`.

The following conditions are required:

- the focus variable is declared as a node variable;
- the focus has structural in-degree zero;
- every non-focus node has exactly one structural parent;
- all declared nodes are reachable from the focus;
- the structural graph is acyclic;
- node variables are not reused to create cross-branch joins;
- sibling branches are interpreted conjunctively.

A focus-only query with no edges is valid and returns focus nodes that satisfy the focus descriptor.

### 3.2 Query output

The answer is the deduplicated set of graph nodes bound to `x_o`.

The logical pipeline represents each answer node as a zero-length `Path` through `FocusProjection`.

## 4. Binding Semantics

M6 uses set-valued binding semantics.

A binding row is a finite, kind-correct mapping:

```text
variable -> graph node or graph edge
```

Shared variable names enforce identity equality during `BindingJoin`.

Distinct pattern variables are not implicitly required to bind distinct graph objects. M6 does not impose a global all-different or bijective-subgraph-isomorphism condition.

This is an intentional XGAP design decision. The QGP source model defines conventional matches through a bijective mapping, whereas M6 uses a smaller rooted-tree binding model aligned with deterministic logical-plan execution. Therefore, M6 must be described as QGP-inspired rather than semantically equivalent to full QGP.

## 5. Local Descriptors and Scalar Predicates

A focused node descriptor contains:

- a node variable;
- an optional label;
- zero or more local property predicates.

A focused edge descriptor contains:

- an optional edge variable;
- an optional label;
- zero or more local property predicates.

The predicates listed in one descriptor are conjoined.

Supported scalar comparators are:

```text
=
!=
<
<=
>
>=
```

### 5.1 Scalar comparison domain

`=` and `!=` may compare supported scalar property values.

`<`, `<=`, `>`, and `>=` are defined only for finite numeric values and exclude booleans.

A missing property makes the atomic property predicate false.

A non-numeric property makes an ordering predicate false.

`!=` requires the property to exist; it is not defined as Boolean negation of a possibly missing equality predicate.

The underlying condition algebra may continue to support Boolean `AND`, `OR`, and `NOT`. The M6 focused descriptor API in this milestone lowers its property-predicate tuple as a conjunction of atomic predicates.

### 5.2 Semantic separation

The following concepts are distinct:

```text
edge.amount >= 1000
```

is a local scalar property predicate.

```text
at least three matching target nodes
```

is a counting quantifier.

```text
no target node satisfies the complete branch
```

is pattern-level anti-existence.

M6 must not lower these three concepts through the same rule.

The term numeric count in M6 does not mean `SUM`, `AVG`, `MIN`, or `MAX` over property values.

## 6. Counting Quantifiers

Each pattern edge has exactly one quantifier.

Supported quantifier kinds are:

```text
EXISTS
COUNT
RATIO
NONE
```

Supported quantifier comparators are:

```text
=
>=
```

Canonical constructors are:

```text
exists()
count_eq(k)
count_ge(k)
ratio_eq(r)
ratio_ge(r)
all_matches()
none()
```

Their meanings are:

| Constructor | Meaning |
| --- | --- |
| `exists()` | at least one distinct complete child witness |
| `count_eq(k)` | exactly `k` distinct complete child witnesses |
| `count_ge(k)` | at least `k` distinct complete child witnesses |
| `ratio_eq(r)` | the exact witness-to-domain ratio is `r` |
| `ratio_ge(r)` | the witness-to-domain ratio is at least `r` |
| `all_matches()` | canonical `ratio_eq(1)` |
| `none()` | no complete child witness exists |

### 6.1 Threshold validity

A count threshold must be a positive integer. Boolean values are not integers for this purpose.

Use `none()` instead of `count_eq(0)`.

A ratio threshold must be in:

```text
0 < r <= 1
```

Ratio thresholds are stored canonically with exact rational semantics.

If a public constructor accepts a floating-point value, it must convert through its decimal string representation, such as `Fraction(str(value))`, and must not use `Fraction(value)` directly.

### 6.2 Quantifier canonicalization

Canonicalization occurs before bound checking and plan construction.

Required canonicalization includes:

- `count_ge(1)` becomes `exists()`;
- `ratio_eq(1)` and `all_matches()` have the same canonical form;
- because M6 guarantees that the numerator is a subset of the denominator, `ratio_ge(1)` also canonicalizes to `all_matches()`.

`count_eq(1)` does not canonicalize to `exists()` because exactly one is different from at least one.

A quantifier is classified as non-existential only after canonicalization.

## 7. Recursive Focused-Branch Semantics

Let `c` be a candidate binding row that contains the focus variable and the current parent variable `u`.

Consider an M6 quantified edge:

```text
e = (u -> v)
```

### 7.1 Edge domain

The edge domain is:

```text
D_e(c)
```

the set of distinct graph nodes `v_data` for which at least one graph edge:

- starts at `c[u]`;
- ends at `v_data`;
- satisfies the edge direction;
- satisfies the edge label;
- satisfies all edge-local property predicates.

The child-node descriptor and child subtree are not applied when constructing `D_e(c)`.

If multiple parallel edge instances connect `c[u]` to the same target and satisfy the edge descriptor, that target appears once in `D_e(c)`.

### 7.2 Complete child witnesses

The witness set is:

```text
N_e(c)
```

the set of distinct nodes `v_data` in `D_e(c)` such that:

- `v_data` satisfies the local descriptor of child variable `v`;
- every quantified branch rooted at `v` is satisfied under the extended candidate context.

Therefore:

```text
N_e(c) subset_of D_e(c)
```

A child node is counted once even when:

- multiple parallel matching edges reach it;
- multiple witness rows contain it;
- multiple internal subtree matches support it.

### 7.3 Sibling conjunction

All outgoing quantified branches of a pattern node must be satisfied.

Branch evaluation filters candidate rows and returns the same candidate schema. Variables introduced to construct one sibling branch do not leak into the candidate schema used by another sibling branch.

### 7.4 Positive quantifiers

For a candidate row `c`:

```text
EXISTS:
  |N_e(c)| >= 1

COUNT >= k:
  |N_e(c)| >= k

COUNT = k:
  |N_e(c)| = k
```

For ratio quantifiers:

```text
RATIO >= r:
  |D_e(c)| > 0
  and |N_e(c)| / |D_e(c)| >= r

RATIO = r:
  |D_e(c)| > 0
  and |N_e(c)| / |D_e(c)| = r
```

Ratio comparison uses exact rational arithmetic or equivalent integer cross-multiplication.

### 7.5 Universal quantification

`all_matches()` is the canonical form of:

```text
RATIO = 1
```

It succeeds exactly when:

```text
|D_e(c)| > 0
and N_e(c) = D_e(c)
```

M6 uses non-vacuous universal semantics. A parent with an empty edge domain does not satisfy `all_matches()`.

### 7.6 Pattern-level negation

`none()` succeeds exactly when:

```text
|N_e(c)| = 0
```

Its logical lowering must use anti-existence:

```text
candidate rows
  AntiSemiJoin
candidate rows having at least one complete branch witness
```

`none()` is not lowered as Boolean `NOT` over an already matched edge.

For a nested negative branch, a violating witness is a child that satisfies the edge descriptor, child descriptor, and complete child subtree.

## 8. Correlation Semantics

`QuantifiedCheck` and `AntiSemiJoin` evaluate each branch relative to an explicit candidate context.

In canonical M6 lowering:

- `correlation_vars` are the full ordered schema of the candidate relation being filtered;
- the witness relation retains those candidate variables plus branch-local variables;
- the domain relation retains those candidate variables plus the child variable;
- `QuantifiedCheck` and `AntiSemiJoin` return the original candidate rows unchanged.

This prevents witness rows belonging to different candidate contexts from being mixed.

At the root, the candidate schema initially contains only the focus variable.

Inside a nested branch, the candidate schema contains the ancestor context needed by deterministic recursive lowering.

## 9. Structural Quantifier Bounds

M6 uses an immutable `QuantifierBounds` configuration.

The default M6 bounds are:

```text
max_non_existential_per_root_to_leaf_path = 2
max_negated_edges_per_root_to_leaf_path = 1
```

For each structural root-to-leaf path:

- at most two canonical quantifiers may be non-existential;
- at most one quantifier may be `NONE`.

The bounds are path-wise, not global.

Therefore:

- multiple quantified sibling branches are allowed;
- multiple negative sibling branches are allowed;
- three nested non-existential quantifiers are rejected;
- two nested `NONE` branches are rejected.

The source QGP model bounds non-existential and negated edges on simple paths. M6 adapts that principle to outward rooted-tree quantifier nesting. The M6 root-to-leaf bound is an XGAP design boundary, not a claim of exact equivalence to the source QGP syntax.

These bounds do not establish a polynomial-time complexity result for M6. No QGP complexity theorem is inherited without a separate proof for the M6 fragment and evaluator.

## 10. Minimal BindingRelation

`BindingRelation` is the M6 binding data object.

It has:

- an ordered immutable schema;
- a binding kind for every schema variable;
- immutable rows;
- set semantics;
- no duplicate rows;
- deterministic iteration and formatting order.

M6 supports:

```text
NODE bindings
EDGE bindings
```

M6 does not support:

- bag multiplicity;
- null bindings;
- general path bindings;
- arbitrary GPC assignments;
- cross-query correlation.

Stable ordering must use a deterministic repository-level value key and must not depend on raw set or dictionary iteration order.

## 11. Focused Binding Operators

### 11.1 BindNode

```text
BindNode(var, child): PathSet -> BindingRelation
```

The child must contain zero-length paths.

Each zero-length path containing node `n` produces:

```text
{var -> n}
```

Duplicate rows are removed.

### 11.2 BindEdge

```text
BindEdge(source_var, edge_var?, target_var, child)
  : PathSet -> BindingRelation
```

The child must contain one-length paths.

Each path:

```text
source, edge, target
```

produces bindings for the source, optional edge variable, and target.

Duplicate rows are removed.

### 11.3 BindingJoin

```text
BindingJoin(left, right)
  : BindingRelation x BindingRelation -> BindingRelation
```

This operator performs an internal natural join over shared variables.

Two rows are compatible when every shared variable has the same kind and the same graph value.

The output schema is the stable union of the input schemas.

This internal operator does not constitute support for arbitrary user-visible query-level joins.

### 11.4 BindingProject

```text
BindingProject(vars, child)
  : BindingRelation -> BindingRelation
```

It retains the requested variables in the requested stable order and removes duplicate projected rows.

Unknown variables are validation errors.

### 11.5 QuantifiedCheck

```text
QuantifiedCheck(
    candidates,
    witnesses,
    domain?,
    correlation_vars,
    child_var,
    quantifier
) -> BindingRelation
```

For each candidate row `c`, define:

```text
N(c) =
  distinct child_var values in witness rows correlated with c

D(c) =
  distinct child_var values in domain rows correlated with c
```

`D(c)` is used only for ratio quantifiers.

The operator returns qualifying candidate rows unchanged. It does not emit count or ratio values.

For ratio evaluation, the reference evaluator must verify:

```text
N(c) subset_of D(c)
```

A malformed manually constructed plan that violates this invariant must raise an explicit evaluation error rather than silently producing a ratio greater than one.

For non-ratio quantifiers, `domain` must be absent.

For ratio quantifiers, `domain` is required.

`NONE` is not accepted by `QuantifiedCheck`.

### 11.6 AntiSemiJoin

```text
AntiSemiJoin(left, right, on)
  : BindingRelation x BindingRelation -> BindingRelation
```

It keeps a left row only when no right row agrees on every variable in `on`.

M6 lowering uses the full left candidate schema as `on` for a negative branch.

### 11.7 FocusProjection

```text
FocusProjection(focus_var, child)
  : BindingRelation -> PathSet
```

The focus variable must have binding kind `NODE`.

The operator emits one zero-length path for each distinct focus-node value.

## 12. Static Logical-Plan Validation

M6 extends validation beyond output kinds with deterministic binding-schema inference.

Validation must infer the output binding schema of a plan without executing it.

At minimum, validation checks:

- every operator input kind;
- `BindNode` and `BindEdge` output schemas;
- shared-variable kind compatibility in `BindingJoin`;
- requested variables in `BindingProject`;
- anti-join key presence and kind compatibility;
- `QuantifiedCheck` candidate, witness, and domain schemas;
- correlation-variable presence in all required inputs;
- `child_var` has kind `NODE`;
- ratio-domain presence;
- non-ratio-domain absence;
- `NONE` is rejected by `QuantifiedCheck`;
- `FocusProjection` uses a node binding.

The inferred schemas must be available to lowering and pretty printing without invoking reference evaluation.

## 13. Deterministic Lowering

M6 lowering follows this order:

```text
type check
  -> quantifier canonicalization
  -> bound validation
  -> canonical plan construction
  -> logical-plan validation
```

Lowering never calls the evaluator, backend code, compiler code, optimizer, LLM, or cost estimator.

### 13.1 Root candidates

The focus descriptor lowers to:

```text
BindNode [focus]
  Selection [focus descriptor]
    Nodes
```

This relation is the initial candidate relation.

Starting from focus candidates is required for queries whose outgoing branches are all negative.

### 13.2 Recursive branch lowering

Conceptually:

```text
lower_node(node_var, candidates):
    result = candidates

    for edge in canonically_sorted_children(node_var):
        domain_or_atomic_rows =
            result
            join matching edge bindings

        child_rows =
            domain_or_atomic_rows
            join matching child-node bindings

        complete_witnesses =
            lower_node(edge.child, child_rows)

        if edge.quantifier is NONE:
            result =
                AntiSemiJoin(
                    result,
                    complete_witnesses,
                    on = schema(result)
                )

        elif edge.quantifier is RATIO:
            domain =
                project(
                    schema(result) + edge.child,
                    domain_or_atomic_rows
                )

            result =
                QuantifiedCheck(
                    candidates = result,
                    witnesses = complete_witnesses,
                    domain = domain,
                    correlation_vars = schema(result),
                    child_var = edge.child,
                    quantifier = edge.quantifier
                )

        else:
            result =
                QuantifiedCheck(
                    candidates = result,
                    witnesses = complete_witnesses,
                    domain = absent,
                    correlation_vars = schema(result),
                    child_var = edge.child,
                    quantifier = edge.quantifier
                )

    return result
```

Every branch filter returns the original candidate schema.

### 13.3 Canonical branch order

Branch order must not depend on input tuple order, set order, or dictionary order.

The canonical branch key must use stable structural fields, including at least:

- parent variable name;
- child variable name;
- edge label;
- edge variable name;
- canonical quantifier kind;
- canonical comparator;
- canonical threshold;
- canonical local-predicate representation.

M6 does not perform cost-based join ordering.

### 13.4 Final result

After all focus branches have been applied:

```text
FocusProjection [focus]
  filtered focus candidates
```

returns the answer as a `PathSet` of zero-length paths.

## 14. Reference Evaluation

The in-memory reference evaluator defines executable M6 semantics.

It must evaluate:

- `BindNode`;
- `BindEdge`;
- `BindingJoin`;
- `BindingProject`;
- `QuantifiedCheck`;
- `AntiSemiJoin`;
- `FocusProjection`.

Evaluation uses:

- set semantics;
- exact ratio comparison;
- distinct child-node counting;
- deterministic row and result ordering;
- explicit errors for malformed plans.

The reference evaluator is not a production graph engine.

## 15. Determinism Contract

For the same valid `FocusedQuantifiedPatternQuery`:

- type checking returns the same inferred types;
- quantifier canonicalization returns the same canonical forms;
- bound validation returns the same result;
- lowering returns the same logical-plan structure;
- `format_plan()` returns the same text;
- reference evaluation returns the same deduplicated answer.

Determinism must not depend on:

- LLM output during lowering;
- backend capabilities;
- optimizer choices;
- reference-evaluation feedback;
- unordered Python container iteration;
- binary floating-point equality for ratio thresholds.

## 16. Examples

### 16.1 Numeric count

```text
Find accounts with at least two distinct HighRisk transfer targets.
```

Pattern intent:

```text
(x:Account)-[:TRANSFER]->(y:Account) : COUNT >= 2
y has label HighRisk
```

The count is over distinct bindings of `y`, not edge instances.

### 16.2 Ratio

```text
Find accounts for which at least 80% of transfer targets are HighRisk.
```

For each candidate account `x`:

```text
domain =
  all distinct targets reached by matching TRANSFER edges

witnesses =
  domain targets that are HighRisk
  and satisfy the complete child subtree
```

The condition is:

```text
|witnesses| / |domain| >= 4/5
```

An account with no matching transfer target does not satisfy the condition.

### 16.3 Universal

```text
Find accounts whose transfer targets are all HighRisk.
```

This is:

```text
RATIO = 1
```

with a non-empty domain.

### 16.4 Pattern-level negation

```text
Find accounts with no transfer target that is Blocked.
```

M6 starts from matching account candidates, constructs violating branch witnesses, and removes candidates having at least one violation through `AntiSemiJoin`.

## 17. Unsupported Features

M6 does not support:

- full QGP;
- full GPC;
- bijective subgraph-isomorphism matching;
- arbitrary conjunctive graph patterns;
- cyclic pattern graphs;
- node-variable reuse for cross-branch joins;
- arbitrary user-visible query-level joins;
- multiple focus outputs;
- `Direction.IN`;
- `Direction.UNDIRECTED`;
- quantifiers over `Rel`, `Seq`, `Alt`, `Plus`, `Star`, or any regular-path expression;
- path counting;
- edge-instance counting;
- `SUM`, `AVG`, `MIN`, or `MAX` over property values;
- bag semantics;
- null semantics;
- general GPC assignment semantics;
- `Maybe`;
- group-variable runtime semantics;
- backend compilation or execution;
- optimizer rules;
- cost estimation;
- LLM planning;
- disambiguation;
- KGQA evaluation.

Unsupported features must fail explicitly rather than being approximated.

## 18. Claim Boundary

After M6 is implemented and tested, XGAP may claim:

- a bounded QGP-inspired focused quantified-pattern fragment;
- rooted tree-shaped quantified patterns with one focus node;
- existential, numeric-count, ratio, universal, and negative branches;
- distinct child-node counting;
- exact ratio comparison;
- non-vacuous universal semantics;
- pattern-level anti-existence through `AntiSemiJoin`;
- deterministic lowering, validation, and reference evaluation;
- static path-wise bounds on nested quantification and negation.

XGAP must not claim:

- full QGP;
- full GPC;
- general conjunctive graph-pattern matching;
- QGP-equivalent bijective matching;
- quantified regular-path semantics;
- a complexity bound inherited from general QGP matching;
- scalable or parallel QGP evaluation;
- backend compilation or execution.

## 19. M6 Acceptance Invariants

M6 acceptance requires:

- all M0-M5.5 tests remain unchanged and pass;
- all existing examples continue to run;
- existing `PathPatternQuery` formatting and semantics remain unchanged;
- focused quantified AST and type checking are covered;
- structural bounds are covered;
- binding operators are covered;
- count, ratio, universal, and negative semantics are covered;
- exact ratio and empty-domain cases are covered;
- parallel-edge and duplicate-witness cases count each child once;
- nested branches and sibling conjunction are covered;
- repeated lowering is deterministic;
- the quantified-pattern demo runs;
- the repository acceptance script passes.

M6 acceptance does not constitute the M6.5 semantic audit.