# Deterministic Lowering from Ontology-aligned Interpretation to Logical Plan

## Scope and terminology

This report describes the implementation currently present in XGAP. The
implemented deterministic boundary is:

```text
controlled candidate JSON
  -> PathPatternQuery
  -> type_check_path_pattern
  -> lower_path_pattern
  -> AlgebraOp root
  -> validate_plan
  -> optional reference evaluation
```

There is no class named `Interpretation` and no ontology-alignment component in
the current repository. The closest planner-side wrapper is `PlannerCandidate`,
which contains a natural-language question, one `PathPatternQuery`, optional
confidence and rationale, and metadata. Only its `pattern_query` field enters
lowering. Consequently, a paper may call the lowering input an
"ontology-aligned interpretation" only if ontology alignment is understood as
an upstream process that has already resolved labels and property names into a
`PathPatternQuery`; the current object does not record or verify that
provenance.

Similarly, `LogicalPlan` is used as an architectural term in the documentation,
but the code has no concrete `LogicalPlan` container class. A logical plan is
represented by the root of an immutable `AlgebraOp` operator structure.

## 1. Object being lowered

### 1.1 PathPatternQuery

The exact M5 input object is the frozen dataclass:

```text
PathPatternQuery(
    path_var: Var | None,
    source: NodePattern,
    expr: RegexExpr,
    target: NodePattern,
    selector: Selector,
    restrictor: RecursiveMode,
    condition: Condition | None,
    max_depth: int | None,
)
```

It can be summarized as

```text
I = (p, source, expr, target, selector, restrictor, condition, max_depth).
```

The object is path-centric. It does not contain arbitrary lists of pattern
vertices and pattern edges.

| Component | Implemented representation | Role in lowering |
| --- | --- | --- |
| Path variable | Optional `Var` in `path_var` | Used for static type inference only; it is not emitted as a runtime binding. |
| Pattern vertices | `source` and `target`, each a `NodePattern` | Endpoint labels and properties become positional `Selection` conditions over `first` and `last`. |
| Interior vertices | Implicit at `Seq` concatenation boundaries | Enforced by path endpoint equality in `Join`; there are no explicit interior `NodePattern` objects in M5. |
| Pattern edges | `EdgePattern` values at `Rel` leaves | An unconstrained edge becomes `Edges`; label and property descriptors become `Selection` over `edge(1)`. |
| Vertex constraints | Optional label plus a property-equality mapping | Conjoined into scalar conditions. Source and target constraints use `NodeRef.first()` and `NodeRef.last()`. |
| Edge constraints | Optional label, property-equality mapping, variable, and direction | Only `OUT` lowers. Labels and properties compile to scalar conditions; the variable is type metadata. |
| Path expression | `Rel`, `Seq`, `Alt`, `Plus`, or `Star` | Recursively determines the core path-algebra structure. |
| Selector | `ALL`, `ANY`, `ANY_K`, `ANY_SHORTEST`, `ALL_SHORTEST`, `SHORTEST_K`, or `SHORTEST_K_GROUP` | Compiled into `GroupBy`, optional `OrderBy`, and `Projection`. |
| Restrictor | `WALK`, `TRAIL`, `ACYCLIC`, `SIMPLE`, or `SHORTEST` | Attached to generated `Recursive` calls. It has no effect when the expression has no `Plus` or `Star`. |
| Global condition | Optional scalar `Condition` AST | Becomes a `Selection` immediately before selector lowering. |
| Recursion bound | Optional positive `max_depth` | Attached to generated `Recursive` calls. Unbounded `WALK` is rejected. |

The scalar condition language supports label equality, property equality and
inequality, finite numeric ordering comparisons, path-length equality, and
Boolean `AND`, `OR`, and `NOT`. References are positional (`first`, `last`,
one-based node position, or one-based edge position), rather than
variable-based.

`OptionalExpr` and `Bounded` exist as AST placeholders but fail explicitly
during lowering. `IN` and `UNDIRECTED` directions can be represented and pass
the lightweight type checker, but lowering rejects them.

### 1.2 Interpretation data versus logical semantics

The following fields belong to the candidate interpretation boundary but are
not represented in the M5 logical plan:

- the original natural-language question;
- candidate ID, confidence, rationale, raw provider output, and metadata;
- ontology or schema-alignment provenance;
- `path_var`, source/target variable names, and edge variable names.

Variable names are checked for kind consistency (`PATH`, `NODE`, or `EDGE`),
but M5 does not produce assignment rows and does not preserve variable names in
the lowered path plan. Reusing a variable name therefore must not be described
as a general runtime equality join in the current M5 implementation.

The following interpretation components do determine logical operators or
operator parameters:

- regular path-expression structure;
- edge, source, and target descriptors;
- the path-level scalar condition;
- recursive restrictor and depth;
- selector kind and optional `k`.

There is no general aggregation clause, arbitrary ordering expression, or
field-projection list in `PathPatternQuery`. Selector lowering uses
`GroupBy`/`OrderBy`/`Projection`, but those operators implement path-selection
semantics, not SQL-style aggregation and column projection.

### 1.3 Sibling M6 input

The repository also implements `FocusedQuantifiedPatternQuery` as a separate,
additive M6 input. It represents a focus node and a bounded rooted tree of
quantified atomic `OUT` edges. It lowers through the focused binding operators
listed below. It is not an extension of `PathPatternQuery`, and its semantics
must not be used to overstate the M5 path-pattern fragment.

## 2. Logical plan representation

### 2.1 Code-level representation

Every logical operator is a frozen dataclass derived from `AlgebraOp`. An
operator call contains:

- its operator-specific parameters, such as a condition, recursive mode,
  grouping key, ordering key, selector limits, or binding variables;
- direct references to zero, one, two, or three child operators;
- metadata methods `operator_name()`, `children()`, and `output_kind()`.

The output kinds are `PATH_SET`, `SOLUTION_SPACE`, and `BINDING_RELATION`.
`validate_plan` recursively checks that each child produces the kind required
by its parent and checks implemented operator-specific invariants.

### 2.2 Relational view L = (Omega, D)

The code does not materialize an explicit DAG object, node identifiers, or an
edge set. For a root operator `r`, a formal plan can nevertheless be derived as:

```text
Omega = the set of AlgebraOp instances reachable from r
D     = {(c, o) | c is returned by o.children()}
```

An edge `(c, o)` means that the output of child call `c` is a data-flow input to
parent call `o`. Normal lowering creates a rooted operator tree because it
constructs fresh child objects. The representation can be viewed as a DAG if a
caller manually shares the same child instance between parents, but there is no
explicit DAG management, common-subexpression identity, or topological
scheduler.

### 2.3 Language independence

The logical representation is language-independent: operator nodes contain no
Cypher, SPARQL, or GQL syntax. The in-memory reference evaluator executes the
same operators over `PropertyGraph`.

M9 compilers are downstream consumers. They accept an `AlgebraOp` or a
`PathPatternQuery`, perform validation and backend capability checks, and emit
a language-specific `QueryArtifact`. Current Cypher and SPARQL compilation is
limited to a fixed-length `OUT` fragment containing `Nodes`, `Edges`,
`Selection`, and path-chain `Join`; this backend limitation does not redefine
the logical operator semantics.

## 3. Implemented logical operator vocabulary

### 3.1 Path-algebra operators

These are the operators that `PathPatternQuery` lowering may emit.

| Operator | Input | Output | Semantics | Corresponding pattern construct |
| --- | --- | --- | --- | --- |
| `Nodes` | Graph `G` (implicit evaluator context) | `PathSet` | One zero-length path per graph node. | Epsilon branch of `Star`; also used by the separate M6 focus layer. |
| `Edges` | Graph `G` (implicit evaluator context) | `PathSet` | One directed one-edge path per graph edge. | Unconstrained `Rel`. |
| `Selection` | `PathSet` | `PathSet` | Retains paths satisfying a scalar condition. | Edge descriptors, source/target descriptors, and global path condition. |
| `Union` | `PathSet x PathSet` | `PathSet` | Deduplicated set union. | `Alt`; combines `Nodes` and non-empty recursion for `Star`. |
| `Join` | `PathSet x PathSet` | `PathSet` | Concatenates paths when the left endpoint equals the right start point. | `Seq`. |
| `Recursive` | `PathSet` | `PathSet` | Kleene-plus closure under `WALK`, `TRAIL`, `ACYCLIC`, `SIMPLE`, or `SHORTEST`. | `Plus`; non-empty branch of `Star`. |
| `GroupBy` | `PathSet` | `SolutionSpace` | Partitions/groups paths by a fixed endpoint/length key; does not aggregate, order, or remove paths. | Selector preparation. |
| `OrderBy` | `SolutionSpace` | `SolutionSpace` | Updates partition, group, and/or path ranks using path length; preserves membership and assignments. | Shortest selectors. |
| `Projection` | `SolutionSpace` | `PathSet` | Selects bounded numbers of ranked partitions, groups, and paths with deterministic tie-breaking. | All supported selectors, including unbounded `ALL`. |

There are no implemented logical operators named `NodeScan`, `EdgeExpand`,
`PathExpand`, `Filter`, `Aggregate`, `Rank`, or `Project`. The corresponding
implemented XGAP terms are `Nodes`, `Edges`, `Recursive`, `Selection`,
selector-style `GroupBy`/`OrderBy`, and `Projection`, with the narrower
semantics stated above.

Although `GroupByOp` has an `aggregates` dataclass field, current validation,
lowering, and evaluation do not implement aggregate computation. Likewise,
`ProjectionOp.fields` exists as a placeholder but validation, formatting, and
evaluation explicitly reject field-based projection.

### 3.2 Focused binding operators

These operators are implemented for the sibling M6 quantified-pattern
pipeline, but `PathPatternQuery` lowering does not emit them.

| Operator | Input | Output | Semantics | Corresponding pattern construct |
| --- | --- | --- | --- | --- |
| `BindNode` | `PathSet` of zero-length paths | `BindingRelation` | Binds one node variable per path. | Focused node descriptor. |
| `BindEdge` | `PathSet` of one-edge paths | `BindingRelation` | Binds source, optional edge, and target variables. | Atomic quantified edge descriptor. |
| `BindingJoin` | `BindingRelation x BindingRelation` | `BindingRelation` | Set-valued natural join on shared variables. | Correlation of a rooted-tree branch. |
| `BindingProject` | `BindingRelation` | `BindingRelation` | Keeps selected variables and deduplicates rows. | Ratio-domain construction. |
| `QuantifiedCheck` | Candidate, witness, and optional domain relations | `BindingRelation` | Filters candidates by existential, count, ratio, or universal conditions over distinct child nodes. | Non-`NONE` edge quantifier. |
| `AntiSemiJoin` | `BindingRelation x BindingRelation` | `BindingRelation` | Keeps candidates with no correlated complete witness. | `NONE` edge quantifier. |
| `FocusProjection` | `BindingRelation` | `PathSet` | Converts distinct focus-node bindings to zero-length paths. | Focused query result. |

This layer is QGP-inspired and deliberately bounded. It is not a general
relational graph algebra or arbitrary user-visible query-level join facility.

## 4. Deterministic lowering rules

### 4.1 Regular path expressions

Let `lower(e, m, d)` denote lowering expression `e` under recursive mode `m`
and optional maximum depth `d`.

| Pattern construct | Logical operator structure |
| --- | --- |
| `Rel(EdgePattern())` | `Edges` |
| `Rel(EdgePattern(label, properties))` | `Selection(conjunction(label(edge(1)), properties(edge(1))), Edges)` |
| `Seq(a, b)` | `Join(lower(a), lower(b))` |
| `Alt(a, b)` | `Union(lower(a), lower(b))` |
| `Plus(a)` | `Recursive(mode=m, max_depth=d, child=lower(a))` |
| `Star(a)` | `Union(Nodes, Recursive(mode=m, max_depth=d, child=lower(a)))` |
| `OptionalExpr(a)` | Explicit `LoweringError` |
| `Bounded(a, min, max)` | Explicit `LoweringError` |

Only `Direction.OUT` is accepted by `_lower_rel`.

### 4.2 Descriptor and condition wrapping

For a lowered regular-expression base `B`, `lower_path_pattern` applies
wrappers in one fixed order:

```text
B0 = lower_regex(expr, restrictor, max_depth)
B1 = Selection(source constraints over first, B0)   if constrained
B2 = Selection(target constraints over last, B1)    if constrained
B3 = Selection(global condition, B2)                 if present
L  = apply_selector(B3, selector)
```

Labels and property mappings within one descriptor are conjoined in the fixed
order label first, followed by the mapping's iteration order.

### 4.3 Selector lowering

| Selector | Logical operator structure |
| --- | --- |
| `ALL` | `Projection(*, *, *) -> GroupBy(NONE) -> B3` |
| `ANY` | `Projection(*, *, 1) -> GroupBy(SOURCE_TARGET) -> B3` |
| `ANY_K(k)` | `Projection(*, *, k) -> GroupBy(SOURCE_TARGET) -> B3` |
| `ANY_SHORTEST` | `Projection(*, *, 1) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET) -> B3` |
| `ALL_SHORTEST` | `Projection(*, 1, *) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH) -> B3` |
| `SHORTEST_K(k)` | `Projection(*, *, k) -> OrderBy(PATH) -> GroupBy(SOURCE_TARGET) -> B3` |
| `SHORTEST_K_GROUP(k)` | `Projection(*, k, *) -> OrderBy(GROUP) -> GroupBy(SOURCE_TARGET_LENGTH) -> B3` |

Here `*` means no limit, not field projection.

### 4.4 Validation sequence

The public lowering function performs:

```text
type_check_path_pattern(I)
  -> structural lowering
  -> validate_plan(L)
  -> return L
```

Static type checking rejects conflicting variable kinds, incompatible
alternative-branch schemas, edge variables inside repeated expressions,
invalid selector limits, invalid recursion depths, and unbounded recursive
`WALK`. Plan validation then checks data-object compatibility, recursive
invariants, selector limits, and recursively supported operator types.
Unsupported cases fail explicitly rather than returning an empty result.

### 4.5 Why the transformation is deterministic

For a fixed `PathPatternQuery` value, lowering is a pure structural traversal:

- each supported AST class has one lowering rule;
- `Seq` and `Alt` preserve left/right child order;
- descriptor wrappers and selector wrappers have fixed placement;
- no graph statistics, optimizer, backend, evaluator, model call, random
  choice, or clock value is consulted;
- operator dataclasses are immutable and have structural equality;
- `format_plan` traverses `children()` in fixed order.

Thus the implementation realizes a function

```text
lower: PathPatternQuery -> AlgebraOp
```

such that repeated lowering of the same input produces structurally equal
plans and identical formatted plans. This is tested directly in
`tests/test_pattern_lowering_audit.py`, in addition to canonical-shape,
selector-mapping, validation, and reference-evaluation tests.

The claim is about the same structured input. Two semantically equivalent
inputs with differently ordered property mappings are not explicitly
canonicalized into identical condition order, although their conjunction has
the same reference semantics.

## 5. Expressiveness analysis

| Capability | Current support | Qualification |
| --- | --- | --- |
| Node matching | Operator-level support | `Nodes` enumerates graph nodes and `Selection` can constrain them. M5 `PathPatternQuery` has no standalone node-only expression; M6 supports a focus-only query. |
| Edge traversal | Supported | `Edges` plus edge `Selection` supports directed one-edge paths. M5 lowering is `OUT` only. |
| Path navigation | Supported for the audited fragment | `Seq`, `Alt`, `Plus`, and `Star` express fixed composition, alternation, and regular transitive navigation with path restrictors. |
| Filtering | Supported | Positional node/edge labels, property comparisons, length equality, and Boolean condition composition are executable. |
| Joins between matched variables | Restricted | Path `Join` is endpoint-based path concatenation, not a general variable-binding join. M6 `BindingJoin` is internal to bounded focused rooted-tree lowering. |
| Aggregation | Not generally supported | Selector `GroupBy` does not compute aggregates. M6 `QuantifiedCheck` performs bounded distinct-child counting but does not emit aggregate values. |
| Ordering | Selector-specific only | `OrderBy` ranks paths/groups/partitions by path-length-derived keys. There is no arbitrary `ORDER BY` expression in `PathPatternQuery`. |
| Projection | Selector-specific only | `Projection` chooses ranked paths and returns a `PathSet`. Arbitrary field/variable projection is not implemented. |
| GQL-like graph pattern semantics | Partial, path-centric | The logical layer captures the essential directed path matching, path navigation, restrictor, and selector semantics supported by the XGAP fragment. It is not full GQL. |
| GPC/path-pattern semantics | GPC-Lite | It captures regular path expressions plus audited restrictor and selector behavior, but not full GPC assignment or general graph-pattern composition. |

The strongest supportable paper claim is:

> The intermediate logical plan captures the essential path-centric graph
> pattern semantics supported by XGAP's GPC-Lite fragment, including directed
> labeled edge matching, endpoint filtering, regular path composition,
> path-mode restrictions, and selector-style path choice.

The implementation does not support a claim of strict equivalence to full GQL
graph pattern queries or full GPC. In particular, M5 variables are statically
typed annotations rather than runtime assignment columns, and path `Join`
expresses sequence concatenation rather than arbitrary conjunction over shared
variables.

The reference evaluator gives the operator vocabulary executable semantics over
a directed labeled property graph. It evaluates `Nodes`, `Edges`, scalar
selection, set union, endpoint join, recursive modes, and selector operators.
`PathSet` deduplication and deterministic selector tie-breaking make test
results reproducible. This executable semantics supports validation of the
lowering rules independently of any backend query language.

## 6. Limitations and future-work boundary

### Supported now

- controlled JSON parsing into `PathPatternQuery`;
- static path/node/edge variable-kind checking;
- `Rel`, `Seq`, `Alt`, `Plus`, and `Star`;
- directed `OUT` edge matching;
- endpoint and positional path filtering;
- `WALK`, `TRAIL`, `ACYCLIC`, `SIMPLE`, and `SHORTEST` recursion modes;
- all seven implemented selector kinds;
- deterministic plan construction, validation, formatting, and reference
  evaluation;
- a separate bounded focused quantified-pattern layer;
- minimal downstream Cypher/SPARQL compilation for a fixed-length subset.

### Not supported by PathPatternQuery lowering

- ontology loading, ontology reasoning, or proof that labels/properties are
  ontology-aligned;
- runtime assignment semantics for path, node, and edge variables;
- equality constraints induced merely by repeated variable names;
- arbitrary conjunctive or cyclic graph patterns;
- general joins over matched variables;
- reverse or undirected edge lowering;
- optional path-expression runtime semantics;
- bounded-repeat lowering;
- bag, null, or general group-variable semantics;
- general aggregation;
- arbitrary ordering expressions;
- arbitrary field or variable projection;
- optimizer rewrites or cost-based plan selection.

### Downstream compiler limitations

The logical plan is more expressive than the M9 backend compilers. Current
Cypher/SPARQL emission supports only a fixed-length `OUT` fragment using
`Nodes`, `Edges`, `Selection`, and path-chain `Join`, with backend-specific
predicate restrictions. It rejects `Union`, `Recursive`, selector-style
`GroupBy`/`OrderBy`/`Projection`, and all M6 binding operators. GQL compilation
is explicitly unsupported.

### Appropriate future work

Future milestones may add ontology-alignment provenance, runtime variable
assignments, broader graph-pattern composition, optimizer and cost models,
fuller backend compilation, and broader GQL/GPC coverage. Until those features
exist, the paper should present XGAP's deterministic lowering as a verified
translation for a path-centric GPC-Lite fragment, with a separate bounded
focused quantified extension, rather than as a full graph-query compiler.

## Implementation and test evidence

Primary implementation:

- `src/xgap/pattern/ast.py`
- `src/xgap/pattern/typecheck.py`
- `src/xgap/pattern/lowering.py`
- `src/xgap/algebra/ops.py`
- `src/xgap/algebra/validation.py`
- `src/xgap/algebra/evaluator.py`
- `src/xgap/algebra/pretty.py`
- `src/xgap/llm/parser.py`
- `src/xgap/llm/schemas.py`
- `src/xgap/compilers/features.py`

Primary correctness tests:

- `tests/test_pattern_typecheck.py`
- `tests/test_lowering.py`
- `tests/test_pattern_lowering_audit.py`
- `tests/test_validation.py`
- `tests/test_recursive.py`
- `tests/test_solution_space.py`
- `tests/test_llm_boundary.py`
- `tests/test_cypher_compiler.py`
- `tests/test_sparql_compiler.py`

