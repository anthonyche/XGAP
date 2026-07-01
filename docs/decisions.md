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