Implement M6 only: Bounded Focused Quantified Pattern Semantics.

Do not implement M6.5, backend capability profiles, compilers,
optimizer functionality, cost estimation, LLM planning,
disambiguation, or KGQA evaluation.

Read first:

- AGENTS.md
- docs/architecture.md
- docs/roadmap.md
- docs/status.md
- docs/operator_semantics.md
- docs/decisions.md
- docs/pattern_lowering_audit.md
- the existing M1-M5.5 source, tests, examples, and acceptance script

Inspect the current repository before editing. Preserve existing public
APIs and all M0-M5.5 behavior unless an additive backward-compatible
extension is explicitly required below.

Do not modify the semantic claims, test results, or audited file list in
docs/pattern_lowering_audit.md. It is a historical M5.5 audit record.

============================================================
1. M6 GOAL
============================================================

Add a bounded, QGP-inspired, focus-oriented quantified pattern fragment.

The new deterministic pipeline must be:

FocusedQuantifiedPatternQuery
  -> type_check_focused_quantified_pattern()
  -> validate_quantifier_bounds()
  -> lower_focused_quantified_pattern()
  -> LogicalPlan
  -> validate_plan()
  -> reference evaluation

This is a sibling pipeline to the existing M5 PathPatternQuery pipeline.
Do not change the meaning or canonical lowering of PathPatternQuery.

M6 must support:

- one query-focus node;
- rooted, connected, acyclic tree-shaped patterns;
- atomic directed OUT edges;
- conjunction across sibling branches;
- local node and edge descriptors;
- local scalar property comparisons;
- existential quantification;
- numeric count quantification;
- ratio quantification;
- universal quantification;
- pattern-level negation;
- static path-wise quantifier bounds;
- deterministic lowering;
- logical-plan validation;
- in-memory reference evaluation.

M6 must not be described or implemented as full QGP or full GPC.

============================================================
2. NON-NEGOTIABLE SCOPE BOUNDARIES
============================================================

Do not implement:

- arbitrary conjunctive graph patterns;
- cyclic pattern graphs;
- query-level arbitrary joins;
- multiple focus outputs;
- full GPC assignment semantics;
- general GPC BindingRelation semantics;
- Maybe or group-variable runtime semantics;
- bag semantics;
- null semantics;
- quantifiers over Rel/Seq/Alt/Plus/Star;
- path counting;
- edge-instance counting;
- unbounded quantifier nesting;
- reverse or undirected M6 edge lowering;
- backend compilation or execution;
- optimizer rules;
- cost estimation;
- LLM code;
- disambiguation;
- KGQA evaluation;
- M6.5 audit reports or audit claims.

All unsupported features must fail explicitly. Do not approximate them.

============================================================
3. ADDITIVE STRUCTURED PATTERN MODEL
============================================================

Add an M6-specific structured query model. Prefer additive files such as:

- src/xgap/pattern/quantified_ast.py
- src/xgap/pattern/quantified_typecheck.py
- src/xgap/pattern/quantified_lowering.py

Adapt filenames to the existing repository style when necessary, but
keep the M5 and M6 implementations visibly separate.

Use the existing Var and Direction abstractions where appropriate.

Provide the semantic equivalents of these public concepts:

ScalarComparator:
- EQ
- NE
- LT
- LE
- GT
- GE

PropertyPredicate:
- non-empty property key
- scalar comparator
- scalar literal

FocusedNodePattern:
- NODE variable
- optional non-empty label
- zero or more local property predicates

FocusedEdgePattern:
- optional EDGE variable
- optional non-empty label
- zero or more local property predicates

QuantifierKind:
- EXISTS
- COUNT
- RATIO
- NONE

QuantifierComparator:
- EQ
- GE

CountingQuantifier:
- kind
- optional comparator
- optional threshold

Provide canonical constructors or equivalent APIs:

- exists()
- count_eq(k)
- count_ge(k)
- ratio_eq(r)
- ratio_ge(r)
- all_matches()
- none()

Canonical meanings:

exists()       = count of distinct child matches >= 1
count_eq(k)    = count of distinct child matches = k
count_ge(k)    = count of distinct child matches >= k
ratio_eq(r)    = numerator / denominator = r
ratio_ge(r)    = numerator / denominator >= r
all_matches()  = ratio_eq(1)
none()         = no complete child-branch witness exists

Use exact rational thresholds, preferably Fraction or an equivalent
immutable exact representation. Do not make quantifier semantics depend
on binary floating-point equality.

A count threshold must be a positive integer. Use none() for zero.

A ratio threshold must be in the interval (0, 1].

QuantifiedPatternEdge:
- parent NODE variable
- child NODE variable
- FocusedEdgePattern
- Direction
- CountingQuantifier

FocusedQuantifiedPatternQuery:
- focus NODE variable
- declared focused node patterns
- quantified pattern edges

The query graph must be validated as a rooted tree from the focus.

============================================================
4. TYPE CHECKING AND STRUCTURAL VALIDATION
============================================================

Implement type_check_focused_quantified_pattern().

It must reject, before logical-plan construction:

- missing focus variables;
- undeclared parent or child variables;
- duplicate node declarations;
- conflicting NODE and EDGE variable use;
- duplicate edge-variable declarations;
- empty labels;
- empty property names;
- invalid scalar literals;
- non-numeric literals for LT/LE/GT/GE predicates;
- bool values used as numeric values;
- invalid count thresholds;
- invalid ratio thresholds;
- disconnected nodes;
- cycles;
- a non-focus node with zero or multiple structural parents;
- incoming edges to the focus;
- Direction.IN;
- Direction.UNDIRECTED;
- any topology that is not a rooted tree;
- unsupported quantified regular-path constructs.

Sibling branches mean conjunction.

Node variables may not be reused to create a cross-branch join. Every
non-focus node is introduced exactly once as the child of one structural
edge.

============================================================
5. QUANTIFIER BOUNDS
============================================================

Add an explicit immutable QuantifierBounds configuration or equivalent.

The initial default M6 bounds are:

- max_non_existential_per_root_to_leaf_path = 2
- max_negated_edges_per_root_to_leaf_path = 1

A quantifier is non-existential when it is not canonical EXISTS.

The bound is path-wise, not a global query count.

Therefore:

- multiple quantified sibling branches are allowed;
- multiple negated sibling branches are allowed;
- three nested non-existential quantifiers on one path are rejected;
- two nested NONE branches on one path are rejected.

Implement validate_quantifier_bounds() separately and call it from
lower_focused_quantified_pattern() after structural type checking and
before plan construction.

Do not claim that these bounds make general QGP matching polynomial.
Do not copy general QGP complexity claims onto this restricted
implementation.

============================================================
6. LOCAL SCALAR PREDICATES
============================================================

Extend the existing condition system additively to support:

- =
- !=
- <
- <=
- >
- >=

Preserve all existing equality-condition APIs and behavior.

Ordering comparisons are valid only for numeric operands and must
exclude bool.

A missing or non-numeric property does not satisfy a numeric ordering
comparison.

Local scalar conditions lower to Selection over Nodes(G) or Edges(G).

Examples:

edge.amount >= 1000
node.risk_score > 0.8
edge.status != "Cancelled"

These are not counting quantifiers.

Keep the following semantic separation explicit in code, docs, and
tests:

local scalar predicate
  != counting quantifier
  != pattern-level negation

============================================================
7. MINIMAL BINDING DATA MODEL
============================================================

Add a minimal set-valued BindingRelation data object.

Prefer an additive module such as:

- src/xgap/algebra/bindings.py

The exact internal representation may follow repository conventions, but
the semantic contract is mandatory:

- ordered immutable schema;
- schema records variable names and binding kinds;
- M6 supports NODE and EDGE bindings;
- immutable rows;
- no duplicate rows;
- deterministic iteration and formatting order;
- no bag multiplicity;
- no null bindings;
- no general path bindings;
- no arbitrary GPC assignment features.

Avoid an algebra-to-pattern circular import. If binding kinds are needed,
define an algebra-level binding kind and map pattern variable types to it
during lowering.

Add OutputKind.BINDING_RELATION or the repository-equivalent metadata.

============================================================
8. MINIMAL FOCUSED BINDING OPERATORS
============================================================

Add only the operators required by M6:

BindNode
BindEdge
BindingJoin
BindingProject
QuantifiedCheck
AntiSemiJoin
FocusProjection

Keep the existing path-algebra operator names and semantics unchanged.

Do not reuse selector-style GroupBy for counting.

Required type flows:

BindNode:
  PathSet -> BindingRelation

BindEdge:
  PathSet -> BindingRelation

BindingJoin:
  BindingRelation x BindingRelation -> BindingRelation

BindingProject:
  BindingRelation -> BindingRelation

QuantifiedCheck:
  candidate BindingRelation
  + witness BindingRelation
  + optional domain BindingRelation
  -> BindingRelation

AntiSemiJoin:
  BindingRelation x BindingRelation -> BindingRelation

FocusProjection:
  BindingRelation -> PathSet

Operator semantics:

BindNode(var, child):
- child paths must have length zero;
- bind the sole node to var;
- deduplicate rows.

BindEdge(source_var, optional_edge_var, target_var, child):
- child paths must have length one;
- bind source, optional edge, and target;
- deduplicate rows.

BindingJoin(left, right):
- natural join over shared variables;
- shared bindings must agree;
- stable union of schemas;
- set semantics.

BindingProject(vars, child):
- keep requested variables;
- reject unknown variables;
- deduplicate projected rows.

AntiSemiJoin(left, right, on):
- keep a left row only when no right row agrees on all variables in on;
- validate that all join variables exist in both schemas.

FocusProjection(focus_var, child):
- focus_var must be a NODE binding;
- emit one zero-length Path per distinct focus node.

============================================================
9. QUANTIFIEDCHECK SEMANTICS
============================================================

QuantifiedCheck must filter candidate rows without emitting aggregate
values.

For each candidate row c:

N(c) =
  the set of distinct child_var node values in witness rows correlated
  with c on correlation_vars

For ratio quantifiers:

D(c) =
  the set of distinct child_var node values in domain rows correlated
  with c on correlation_vars

Keep c when:

EXISTS:
  |N(c)| >= 1

COUNT GE k:
  |N(c)| >= k

COUNT EQ k:
  |N(c)| = k

RATIO GE r:
  |D(c)| > 0 and |N(c)| / |D(c)| >= r

RATIO EQ r:
  |D(c)| > 0 and |N(c)| / |D(c)| = r

ALL:
  the canonical RATIO EQ 1 case

Use exact rational arithmetic or cross multiplication.

Parallel edges to the same child node count once.

Multiple complete witness rows for the same child node count once.

Different paths or submatches reaching the same child node count once.

For non-ratio quantifiers, domain must be absent.

For ratio quantifiers, domain is required.

NONE must lower through AntiSemiJoin rather than being treated as an
ordinary positive QuantifiedCheck.

============================================================
10. FOCUSED PATTERN SEMANTICS
============================================================

The answer starts from all focus nodes that satisfy the focus-node local
descriptor.

This is essential for queries whose only outgoing branches are NONE
branches.

For a quantified edge e = (u, v), a branch witness for candidate parent
binding u is a distinct child node v such that:

1. an atomic graph edge matches the edge direction, label, and local
   edge predicates;
2. the child node matches its node label and local predicates;
3. every quantified subtree branch rooted at the child is satisfied.

Sibling branches are conjunctive.

For COUNT and EXISTS, count the distinct complete child-branch witnesses.

For a ratio edge:

Numerator:
- distinct child nodes satisfying the edge descriptor;
- child-node descriptor;
- complete child subtree.

Denominator:
- distinct child nodes reachable through the edge descriptor;
- include direction, edge label, and edge-local predicates;
- do not apply child-node label predicates;
- do not apply child-node property predicates;
- do not apply child-subtree predicates.

An empty denominator makes every positive ratio condition false,
including ALL.

For NONE:

- construct the relation of candidates with at least one complete branch
  witness;
- remove those candidate rows through AntiSemiJoin.

NONE means NOT EXISTS for the complete branch. It is not boolean NOT
over a scalar property.

============================================================
11. DETERMINISTIC LOWERING
============================================================

Implement lower_focused_quantified_pattern().

It must:

1. run type_check_focused_quantified_pattern();
2. run validate_quantifier_bounds();
3. construct a canonical LogicalPlan;
4. call validate_plan() on the completed plan;
5. return the plan without executing it.

Lowering must not call:

- the reference evaluator;
- backend code;
- compiler code;
- optimizer code;
- LLM code;
- cost estimation.

Use a stable canonical branch order independent of unordered container
iteration. Define and document a stable branch key using structural
fields such as:

- parent variable
- child variable
- edge label
- edge variable
- canonical quantifier representation

Do not use cost-based join ordering in M6.

Recommended recursive lowering strategy:

A. Root candidates

- lower the focus node descriptor to Selection over Nodes(G);
- use BindNode to produce the initial candidate BindingRelation.

B. Atomic branch relation

For edge e = (u, v):

- lower the edge descriptor to Selection over Edges(G);
- use BindEdge to bind u, optional edge variable, and v;
- join with the current candidate relation on u;
- join with the filtered child-node binding for v.

C. Nested branches

- recursively apply every child branch to the child candidate relation;
- preserve all ancestor candidate variables so correlation is explicit.

D. Positive quantifier

- witnesses are the child candidate rows remaining after the complete
  child subtree has been evaluated;
- for COUNT or EXISTS, call QuantifiedCheck without a domain;
- for RATIO or ALL, construct the edge-domain relation before applying
  child-node and subtree filters, and pass it as the domain;
- correlation_vars should identify the full candidate context being
  filtered;
- child_var is the target node variable.

E. NONE

- construct the complete child-branch witness relation;
- use AntiSemiJoin to remove candidate rows with at least one witness.

F. Result

- after all focus branches have been applied, use FocusProjection to
  return a PathSet of zero-length focus paths.

The same query must always produce the same format_plan() output.

============================================================
12. VALIDATION, METADATA, AND PRETTY PRINTING
============================================================

Extend logical-plan validation to cover every new operator and
BindingRelation type flow.

Validate at minimum:

- input OutputKinds;
- requested variables exist;
- shared-variable kinds agree;
- BindingProject schemas;
- AntiSemiJoin key variables;
- QuantifiedCheck correlation variables;
- QuantifiedCheck child_var is a NODE binding;
- ratio domain presence;
- non-ratio domain absence;
- focus projection uses a NODE binding.

Extend operator metadata and format_plan().

Formatting must be stable and readable. It must expose enough fields to
audit semantics, including:

- bound variables;
- projection variables;
- anti-join keys;
- quantifier type;
- comparator;
- threshold;
- correlation variables;
- child variable;
- whether a ratio domain is present.

Do not change existing M0-M5.5 formatted plans.

============================================================
13. REFERENCE EVALUATOR
============================================================

Add deterministic in-memory evaluation for:

- BindNode
- BindEdge
- BindingJoin
- BindingProject
- QuantifiedCheck
- AntiSemiJoin
- FocusProjection

The evaluator is the M6 semantic reference, not a production query
engine.

Use set semantics throughout.

Do not rely on Python set or dict iteration order for user-visible
formatting or result ordering.

============================================================
14. REQUIRED TESTS
============================================================

Add focused test modules, preferably including:

- tests/test_quantified_pattern_ast.py
- tests/test_quantifier_bounds.py
- tests/test_binding_algebra.py
- tests/test_quantified_lowering.py
- tests/test_quantified_evaluation.py

Do not name these M6.5 audit tests.

Cover at least:

AST and type checking:
- valid focused rooted tree;
- missing focus;
- undeclared variables;
- variable-kind conflict;
- duplicate node declaration;
- duplicate edge variable;
- disconnected graph;
- cycle;
- multiple parents;
- reverse direction rejected;
- undirected direction rejected;
- invalid count thresholds;
- invalid ratio thresholds;
- invalid scalar comparison literals.

Bounds:
- two nested non-existential quantifiers accepted;
- three rejected;
- one negated edge on a path accepted;
- two rejected;
- multiple quantified sibling branches accepted;
- multiple negated sibling branches accepted.

Binding operators:
- zero-length node binding;
- one-length edge binding;
- natural join;
- incompatible shared bindings;
- projection deduplication;
- anti-semi-join;
- focus projection;
- validation failures.

Counting:
- EXISTS;
- COUNT >= k;
- COUNT = k;
- no matching children;
- one matching child with multiple parallel edges counts once;
- one child with multiple complete witness rows counts once;
- multiple distinct children count separately.

Ratio:
- exact 1/4, 4/5, and 5/5 cases;
- ratio equality;
- ratio lower bound;
- ALL;
- empty denominator is false;
- denominator includes edge-local filters;
- denominator excludes child-node and child-subtree filters.

Negation:
- no violation retains the focus;
- one violation removes the focus;
- multiple violations still remove once;
- complete negative subtree semantics;
- multiple sibling NONE branches;
- all-negative query still begins from focus-node candidates.

Nested semantics:
- a child is counted only when its complete subtree passes;
- sibling branches are conjunctive;
- nested quantifier correlation is correct.

Scalar conditions:
- edge numeric >= and <=;
- node numeric > and <;
- !=;
- missing/non-numeric property behavior;
- scalar NOT remains different from pattern NONE.

Determinism:
- repeated lowering has identical format_plan() output;
- unordered input construction cannot change canonical output;
- deterministic reference results.

Regression:
- every existing M0-M5.5 test continues to pass;
- every existing example continues to run;
- existing PathPatternQuery output remains unchanged.

============================================================
15. DEMO AND ACCEPTANCE
============================================================

Add:

- examples/quantified_pattern_demo.py

The demo should construct a small property graph and show at least:

1. COUNT >= 2;
2. RATIO >= 80%;
3. ALL with a non-empty denominator;
4. NONE through pattern-level negation;
5. one local numeric edge predicate;
6. deterministic formatted logical plans;
7. reference-evaluated focus answers.

Update scripts/run_acceptance.sh to run the new demo while preserving all
existing checks.

Run:

python -m pytest
python examples/quantified_pattern_demo.py
./scripts/run_acceptance.sh

Do not hard-code an expected total pytest count in documentation or the
completion report. Report the actual result produced by the final run.

============================================================
16. DOCUMENTATION
============================================================

Update:

- docs/roadmap.md
- docs/architecture.md
- docs/decisions.md
- docs/operator_semantics.md
- docs/status.md

Add:

- docs/quantified_pattern_semantics.md

Do not create docs/quantified_pattern_audit.md in M6.

Do not rewrite docs/pattern_lowering_audit.md. It records M5.5 only.

Roadmap changes:

- M6 = Bounded Focused Quantified Pattern Semantics
- M6.5 = Quantified-Pattern Semantic Audit
- old M6 Backend Capability Profiles becomes M7
- old M7 Compilers becomes M8
- old M8 Optimizer becomes M9
- old M9 LLM Planner becomes M10
- old M10 Disambiguation becomes M11
- old M11 KGQA Evaluation becomes M12

Architecture must distinguish:

- path algebra;
- focused binding layer.

Do not claim the new binding operators come from the path-algebra paper.

Documentation must clearly distinguish:

- local scalar property comparison;
- counting quantifier;
- pattern-level negation.

After implementation and successful acceptance, status.md should state:

- M6 completed;
- M6.5 next;
- minimal BindingRelation implemented;
- full QGP and full GPC remain unsupported;
- latest acceptance passed using actual command results.

Search the repository for stale current-state statements, including:

- "M6 Backend Capability Profiles"
- "M0-M5 are executable"
- "M0-M5.5 acceptance"
- "only the path-algebra operators"
- "BindingRelation is not implemented"
- "Next milestone"

Update current architecture/roadmap/status references when appropriate.
Do not alter historical milestone audit claims.

============================================================
17. COMPLETION REPORT
============================================================

At the end, provide:

1. a concise summary of the implemented M6 semantics;
2. the exact files added and modified;
3. the public AST and logical operators added;
4. the static bounds implemented;
5. the unsupported-feature boundary;
6. every command run and its actual result;
7. confirmation that all previous tests and examples still pass;
8. confirmation that no M6.5 or M7+ functionality was added.

Do not claim full QGP, full GPC, backend support, optimization, or
natural-language planning.