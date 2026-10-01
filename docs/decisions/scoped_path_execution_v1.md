# Scoped finite path execution

2026-09-11. Accepted after independent targets, scoped planning and final
regression gates. Design was frozen before implementation. Evidence and the
retained local failures are in [the report](../report/toy_backbone_t1_scoped_paths.md).

Goal: make finite nested regex scopes executable through the normal semantic
Traverse/planner/runtime entry, including TRAIL, ACYCLIC, SIMPLE and SHORTEST.
No existing path-algebra operator or meaning changes. Existing fully native
bounded plans remain available. This adds a coordinator placement of existing
path concatenation and Recursive, not backend-internal physical operators.

The finite native compiler can flatten WALK scopes. Other nested scopes cannot
be erased: Seq(Restricted(P),Q) restricts P, not the concatenated path. A child's
SHORTEST must be determined before enclosing filters or concatenation. In
particular, removing a short child path by an outer length filter must not
promote a longer child path to shortest.

When one native candidate query cannot express the scope, the planner builds
an explicit finite execution DAG. Maximal supported native subexpressions run
without enclosing endpoint/condition filters or selectors. Their normalized
PathSets feed coordinator concatenation, Union and Recursive stages following
the existing regex lowering. Shared subexpressions execute once. The runtime
uses the existing graph-independent path functions, not a locally loaded graph
or fixture/gold evaluator. Every remote call, transferred row and coordinator
stage remains visible and charged by the existing scheduler/planner.

An independently compiled WALK over-approximation of the full finite regex
applies the original source/target descriptors and outer conditions. A final
full-path-identity semi-join intersects that candidate set with the scoped
result, then applies the original selector. This avoids pushing outer filters
into local shortest scopes. When no outer filters exist the intersection is
unnecessary. The over-approximation also enforces existing native profile,
identity/domain mappings and 128-branch/64-edge budgets before any execution.
Original query semantics are validated before replacing its mode/selector for
the superset; the replacement cannot legalize invalid original input.
Unsupported native predicates or mappings cannot bypass this boundary.

This is an explicit executable coordinator strategy, potentially more costly
than a wholly native plan. It does not claim scalable optimization or general
cross-source partitioning. Native observations and candidate costs include all
generated fragments. The new coordinator stage has an explicit Cartesian/power
row-growth cost proxy instead of inheriting a unary-stage estimate; it remains
uncalibrated and can overestimate heavily pruned closure. Non-finite native recursion and an unbounded minimum>=2
without a query depth remain separate gaps. No automatic external retry occurs.

Allowed files: finite path compiler/planner, materialized-path runtime helpers,
scheduler/contracts/capability names, independent tiny fixtures, tests, harness
and current design/status documentation. Existing graph/gold and historical
benchmark artifacts remain frozen. No LLM, catalog build, GPU or large dataset
is needed. No new logical algebra operator is introduced.

Acceptance: independently authored complete tiny NL/gold query/logical tree/
native target/typed answer chains for nested modes, nullable/zero branches,
variable-length child SHORTEST, outer-filter ordering and shared scopes;
module and semantic-DAG tests, normal planning/observation/serving accounting,
real Neo4j/Fuseki comparison and the retained two-engine slice, followed by one
shared-core broad regression and existing examples.
