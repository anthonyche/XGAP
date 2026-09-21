# Operator Semantics

> Current controller: [unified lookahead](decisions/unified_lookahead_migration_20260921.md).
> Lambda/epsilon use the [finite structured-intent distance](decisions/finite_intent_discrepancy_v1.md)
> with independent mandatory validations. Old Exact/Performance runs remain historical.
> This is not an answer-error bound. Fixed fields/hard coordinates and all audited
> algebra semantics below remain unchanged. Earlier `metric_deferred` profiles
> remain historical and are not the current default.

The opt-in [progressive binding](decisions/progressive_binding_v1.md) candidate
composes existing entity semijoin restrictions. It preserves original joins,
filters and aggregates; it introduces no algebra operator or approximate semantics.


`timestamp_ms` now compares equivalent local-calendar millisecond forms with zero
to three fractional digits, while invalid calendar/timezone/submillisecond values
remain false. See [the bounded v2 contract](decisions/financial_timestamp_v2.md).

Semantic edge Match now composes Selection(Edges(G)) with binding projection; it does not add
an algebra operator. Explicit row field/time comparisons, finite literals and no-limit ordering
are specified in [financial binding semantics](decisions/financial_binding_semantics_v1.md).
Legacy path numeric predicates retain their truth conditions.

Match named constraints may explicitly use the binding-row DSL on Match's own
declared output columns. Such constraints execute after row normalization through
the existing coordinator Filter; path constraints retain native path semantics.
This finite composition does not add a path-algebra operator or coerce the two
comparison rules. See [Match row semantics](decisions/match_row_constraints_v1.md).

The M15 Semantic Graph Program and federated runtime operators are typed
planning/execution contracts above the logical algebra. `Match`, `Traverse`,
semantic `Join`, `ResolveEntity`, `RemoteQuery`, and `CoordinatorJoin` do not
rename or redefine the audited operators documented below. Their contracts are
specified in `docs/agentic_architecture.md` and
`docs/m15_agentic_federated_core.md`.

M15-E3 deterministic intake does not add an operator. It instantiates only the
existing semantic operator kinds declared by a versioned template. Catalog,
ontology, and user clarification are typed agent tools whose outputs are
candidate IDs and provenance; they do not alter the algebra vocabulary.

XGAP contains two deterministic logical support layers:

1. the path algebra, whose primary objects are `PathSet` and
   `SolutionSpace`;
2. the M6 focused binding layer, whose object is `BindingRelation`.
<!-- 
The focused binding layer consumes path-algebra results but does not
change the semantics of the existing path operators.

XGAP's logical operator vocabulary is path-based. The primary data object is PathSet. The secondary data object is SolutionSpace, used only by selector-style extended algebra operators.

The logical algebra is organized into:

Core path algebra
Recursive path algebra
Extended path algebra -->

## Data Objects
## Path

A Path is an alternating sequence:
node, edge, node, edge, ..., node
A zero-length path contains a single node.
A one-length path contains:
source, edge, target
The length of a path is the number of edges.

## PathSet

A PathSet is a deduplicated set of Path objects.

Core and recursive operators consume and produce PathSet.

## SolutionSpace

A SolutionSpace is the secondary data object used by the extended algebra.

It represents:

SS = (S, G, P, α, β, △)

where:

S is a PathSet.
P is a set of partitions.
G is a set of groups.
α : S -> G assigns each path to a group.
β : G -> P assigns each group to a partition.
△ : S ∪ G ∪ P -> positive integer assigns a rank to every path, group, and partition.

SolutionSpace is used by GroupBy, OrderBy, and Projection.

## Nodes(G)

Implemented.

Returns a `PathSet` containing one zero-length `Path` for every node in graph `G`.

## Edges(G)

Implemented.

Returns a `PathSet` containing one one-length `Path` for every edge in graph `G`. Each path has the form `source, edge, target`.

## Reverse(P) — XGAP orientation extension

`ReverseOp` consumes and returns a PathSet. It reverses each alternating
traversal sequence without changing graph storage, edge identity or properties.
A reversed one-edge path is `stored target, edge, stored source`. Zero-length
paths stay unchanged. This explicit XGAP extension does not redefine Edges(G)
or claim an additional operator in the original paper algebra. See
[the versioned semantic decision](decisions/path_orientation_v1.md).

Reversal is involutive and preserves lengths; it distributes over Union and
reverses the input order of Join. Node/edge position references outside Reverse
refer to the resulting traversal sequence. It accepts PathSet only; it does not
reverse SolutionSpace ranks or BindingRelation rows.

IN relations lower to Reverse of the corresponding filtered OUT relation.
UNDIRECTED relations lower to the Union of both orientations. Self-loop paths
deduplicate, parallel edge IDs remain distinct, and existing recursive modes
apply unchanged to the resulting sequences. Traversing one edge in opposite
directions repeats that edge identity and therefore violates TRAIL.

## Selection

Evaluates a child operator and keeps only paths that satisfy a scalar
condition.

Supported references include:

- node labels
- edge labels
- node properties
- edge properties
- `first`
- `last`
- indexed nodes and edges
- path length

`NodeNotEquals(left, right)` compares graph-node identity at two fixed path
positions. Invalid positions evaluate false in the reference evaluator, while
`PathPatternQuery` type checking rejects out-of-range positions before
lowering. Numeric positions require a fixed-length path expression. It lowers
through `Selection`; it is not property-value inequality and does not add an
all-different rule for unrelated variables.

Supported scalar comparisons are:

- `=`
- `!=`
- `<`
- `<=`
- `>`
- `>=`

Ordering comparisons are defined only for numeric values and exclude
boolean values. A missing or non-numeric property does not satisfy a
numeric ordering comparison.

Conditions may be composed with boolean `AND`, `OR`, and `NOT`.

These scalar comparisons are different from M6 counting quantifiers.
For example, `edge.amount >= 1000` is evaluated by `Selection`, while
“at least three matching edges” is evaluated through
`QuantifiedCheck`.


## Union

Implemented.

Evaluates both children and returns the deduplicated set union of their paths.

## Join

The federated runtime can place existing path concatenation and Recursive over
materialized native PathSets in `CoordinatorPathCompose`. It does not evaluate
against a hidden local graph or add a logical operator. Nested scopes are kept
before enclosing filters and selectors; see
[scoped execution](decisions/scoped_path_execution_v1.md).

Implemented.

Evaluates both children and concatenates every pair of paths `p1`, `p2` where `p1.last() == p2.first()`. The shared node appears once in the concatenated path.

## Recursive

Implemented.

Evaluates Kleene-plus recursive path construction over a child `PathSet`.

Depth 1 includes paths from the child `PathSet`. Depth `k` extends the previous frontier by joining with the child `PathSet`. Outputs are deduplicated `PathSet` values. `max_depth` counts the number of child paths concatenated, not necessarily the number of graph edges in the resulting path.

Modes:

- `WALK`: allows repeated nodes and repeated edges. Requires an explicit positive `max_depth`.
- `TRAIL`: rejects paths with repeated edges. Repeated nodes are allowed. Without `max_depth`, evaluation terminates by deduplication and frontier exhaustion on finite graphs.
- `ACYCLIC`: rejects paths with repeated nodes. Without `max_depth`, evaluation terminates by deduplication and frontier exhaustion on finite graphs.
- `SIMPLE`: rejects repeated nodes except that the first node may equal the last node as the closing repeat of a cycle. Without `max_depth`, evaluation terminates by deduplication and frontier exhaustion on finite graphs.
- `SHORTEST`: returns shortest paths per source-target pair, where shortest means minimum `Path` length. If multiple paths tie for shortest length for the same source-target pair, all tied shortest paths are kept. If `max_depth` is provided, search is bounded by it; otherwise evaluation still terminates on finite graphs.

The higher-level finite Bounded regex reuses this operator with max_depth=1
over a union of exact child powers: the repetition range is constructed first,
then mode filtering/shortest selection runs once. Optional is Union(Nodes,child).
These are lowering compositions, not new algebra operators. A zero-length child
path inside positive SHORTEST recursion competes with positive cycles; the
separate Nodes branch for Star/Bounded(min=0) lies outside that competition.
See [finite repetition semantics](decisions/finite_regex_repetition_v1.md).

## GroupBy

Implemented.

GroupBy(key, child) evaluates child to a PathSet and transforms it into a SolutionSpace.

GroupBy does not remove paths.

GroupBy does not impose ordering.

GroupBy initializes every rank to 1.

Supported grouping keys:

# NONE

One partition and one group.

partition key = ()
group key = ()

# SOURCE

One partition per source node.

One group per partition.

partition key = (first(path),)
group key = ()

# TARGET

One partition per target node.

One group per partition.

partition key = (last(path),)
group key = ()

# LENGTH

One partition.

One group per path length.

partition key = ()
group key = (len(path),)

# SOURCE_TARGET

One partition per source-target pair.

One group per partition.

partition key = (first(path), last(path))
group key = ()

# SOURCE_LENGTH

One partition per source node.

One group per path length inside that source partition.

partition key = (first(path),)
group key = (len(path),)

# TARGET_LENGTH

One partition per target node.

One group per path length inside that target partition.

partition key = (last(path),)
group key = (len(path),)

# SOURCE_TARGET_LENGTH

One partition per source-target pair.

One group per path length inside that source-target partition.

partition key = (first(path), last(path))
group key = (len(path),)

# Empty input

If the child PathSet is empty, XGAP returns an empty SolutionSpace with no partitions, no groups, and no mappings.

## OrderBy

Implemented.

OrderBy(key, child) evaluates child to a SolutionSpace and returns a new SolutionSpace.

OrderBy preserves:

- paths
- partitions
- groups
- path-to-group assignment α
- group-to-partition assignment β

OrderBy only updates the rank function △.

Helper definitions:

MinL(group) = minimum len(path) among paths assigned to the group
MinL(partition) = minimum len(path) among paths assigned to groups inside the partition

Supported order keys:

# PARTITION
rank(partition) = MinL(partition)
rank(group) = unchanged
rank(path) = unchanged
# GROUP
rank(partition) = unchanged
rank(group) = MinL(group)
rank(path) = unchanged
# PATH
rank(partition) = unchanged
rank(group) = unchanged
rank(path) = len(path)
# PARTITION_GROUP
rank(partition) = MinL(partition)
rank(group) = MinL(group)
rank(path) = unchanged
# PARTITION_PATH
rank(partition) = MinL(partition)
rank(group) = unchanged
rank(path) = len(path)
# GROUP_PATH
rank(partition) = unchanged
rank(group) = MinL(group)
rank(path) = len(path)
# PARTITION_GROUP_PATH
rank(partition) = MinL(partition)
rank(group) = MinL(group)
rank(path) = len(path)

## Projection

Implemented.

Projection(num_partitions, num_groups, num_paths, child) evaluates child to a SolutionSpace and returns a PathSet.

Each projection parameter is either:

None, representing *
a positive integer limit

Projection proceeds in three levels:

1.Sort partitions by (rank, stable_partition_key).
2.Retain the first num_partitions partitions, or all partitions if num_partitions is None.
3.For each retained partition, sort its groups by (rank, stable_group_key).
4.Retain the first num_groups groups, or all groups if num_groups is None.
5.For each retained group, sort its paths by (rank, stable_path_key).
6.Retain the first num_paths paths, or all paths if num_paths is None.
7.Return the retained paths as a deduplicated PathSet.

Stable tie-breakers are used for reproducible reference evaluation.

Examples:

Projection(None, None, None, child)

corresponds to:

π(*, *, *)
Projection(None, None, 1, child)

corresponds to:

π(*, *, 1)
Projection(None, 1, None, child)

corresponds to:

π(*, 1, *)

## Focused Quantified Binding Algebra

The following operators are introduced by M6. They are not part of the
path-algebra vocabulary.

# BindNode

Implemented in M6.


BindNode(var, child): PathSet -> BindingRelation

The child must contain zero-length paths.

For each zero-length path containing node v, BindNode emits one row:

{var -> v}

Duplicate rows are removed.

# BindEdge

Implemented in M6.

BindEdge(source_var, edge_var?, target_var, child)
  : PathSet -> BindingRelation

The child must contain one-length paths.

For each path:

source, edge, target

the operator emits bindings for source_var, target_var, and
edge_var when an edge variable is present.

Duplicate rows are removed.

# BindingJoin

Implemented in M6.

BindingJoin(left, right)
  : BindingRelation x BindingRelation -> BindingRelation

BindingJoin performs a natural join over shared variables.

Two rows are compatible if every shared variable has the same bound
value. The output schema is the stable union of the two input schemas.
Duplicate output rows are removed.

# BindingProject

Implemented in M6.

BindingProject(vars, child)
  : BindingRelation -> BindingRelation

Keeps only the requested variables and removes duplicate projected rows.

# QuantifiedCheck

Implemented in M6.

QuantifiedCheck(
    candidates,
    witnesses,
    domain?,
    correlation_vars,
    child_var,
    quantifier
) -> BindingRelation

For every candidate row c, the operator finds witness rows that agree
with c on correlation_vars and computes the set of distinct values
bound to child_var.

Let:

N(c) = distinct child values in witnesses correlated with c

For a ratio quantifier, let:

D(c) = distinct child values in domain correlated with c

The operator keeps c when:

EXISTS       |N(c)| >= 1
COUNT >= k   |N(c)| >= k
COUNT = k    |N(c)| = k
RATIO >= r   |N(c)| / |D(c)| >= r
RATIO = r    |N(c)| / |D(c)| = r
ALL          |N(c)| / |D(c)| = 1

ALL is a canonical alias of RATIO = 1.

Ratio comparison uses exact rational arithmetic or equivalent
cross-multiplication. It must not depend on binary floating-point
rounding.

If D(c) is empty, every positive ratio condition, including ALL,
is false.

QuantifiedCheck returns qualifying candidate rows unchanged. It does
not emit aggregate values.

# AntiSemiJoin

Implemented in M6.

AntiSemiJoin(left, right, on)
  : BindingRelation x BindingRelation -> BindingRelation

Keeps a left row only when no right row agrees with it on every variable
in on.

M6 uses this operator to implement a NONE quantified branch:

candidate rows
  minus
candidate rows with at least one complete branch witness


# FocusProjection

Implemented in M6.

FocusProjection(focus_var, child)
  : BindingRelation -> PathSet

Extracts the distinct nodes bound to focus_var and converts each one
to a zero-length Path.
The output is the focus-node answer set for an M6 quantified query.


## Selector-style examples
# ANY
Projection [*, *, 1]
  GroupBy [SOURCE_TARGET]
    Recursive [...]
      ...
# ANY k
Projection [*, *, k]
  GroupBy [SOURCE_TARGET]
    Recursive [...]
      ...
# ANY SHORTEST
Projection [*, *, 1]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      Recursive [...]
        ...
# ALL SHORTEST
Projection [*, 1, *]
  OrderBy [GROUP]
    GroupBy [SOURCE_TARGET_LENGTH]
      Recursive [...]
        ...
# SHORTEST k
Projection [*, *, k]
  OrderBy [PATH]
    GroupBy [SOURCE_TARGET]
      Recursive [...]
        ...
# SHORTEST k GROUP
Projection [*, k, *]
  OrderBy [GROUP]
    GroupBy [SOURCE_TARGET_LENGTH]
      Recursive [...]
        ...


## BindingRelation

Implemented in M6.

A `BindingRelation` is a set-valued relation with:

- an ordered binding schema;
- immutable binding rows;
- no duplicate rows;
- stable deterministic formatting order.

Each schema entry associates a variable with a binding kind. M6 supports
node and edge bindings.

`BindingRelation` does not support:

- bag multiplicity
- null bindings
- arbitrary path bindings
- general GPC assignments
- cross-query correlation


## M15 Federated Runtime Operators

These coordinator operators consume JSON-row relations. They are execution
nodes, not additions to the path algebra and not aliases for backend-internal
physical operators.

`RemoteQuery(backend, artifact)` invokes one complete native artifact through
the selected black-box backend plugin.

`RemoteBindQuery(input, backend, artifact, bind_field, parameter,
max_bindings)` extracts non-null JSON-scalar values from `bind_field`, removes
duplicates deterministically, and injects the bounded list into the named
artifact parameter. It fails before invocation when the input is malformed or
exceeds `max_bindings`. An empty binding set succeeds without a remote call.

`Exchange(input)` marks rows as crossing the backend/coordinator boundary and
charges their encoded byte size exactly once at that node.

`CoordinatorJoin(left, right, left_on, right_on)` is a deterministic equality
hash join. Conflicting right fields receive the declared right prefix and
duplicate output rows are removed.

`CoordinatorSemiJoin(left, right, left_on, right_on)` returns each distinct
left row whose key occurs in the right input; it never adds right-side fields.

`CoordinatorPathSelect(input, identity_encoding, selector)` reconstructs
complete paths from declared native position bindings and applies the existing
GroupBy/OrderBy/Projection semantics. For a bounded recursive SHORTEST stage it
first keeps all tied shortest positive paths per endpoint pair, preserving
Star's separate zero paths, then applies deferred length filters and selectors.
Its output is JSON rows containing alternating-ID `path` arrays. Missing or
incompatible identities are errors, not empty answers. This is a physical
adapter over existing path/SolutionSpace values, not a new path-algebra operator.

`Align`, `Merge`, and coordinator `Project` retain the M15-B semantics. Any
error causes all transitive descendants to be marked skipped. A plan validates
its DAG, maximum remote calls, and parallelism before execution.


## Modern native Boolean condition placement

The modern fixed/bounded path and semantic Match compilers share the existing
AND/OR/NOT truth rules. Atomic property equality and inequality are false when
the property is absent; outer NOT complements that result. Python scalar
equality retains True=1 and False=0; numeric ordering excludes booleans and
non-numeric data. RDF properties use explicitly mapped single scalar values.
Property tests stay local to EXISTS so a missing disjunct does not remove the
whole row. These rules do not change the audited Selection operator.

Only endpoint predicates commute with local SHORTEST. Standalone length
conjuncts use the final length filter; Boolean length trees retain their outer
placement through the finite scoped planner. Original semantic reference
validation still applies, including the fixed-length numeric-position boundary.
See [the native Boolean decision](decisions/native_boolean_conditions_v1.md)
and [its measured report](report/toy_backbone_t1_boolean_conditions.md).
