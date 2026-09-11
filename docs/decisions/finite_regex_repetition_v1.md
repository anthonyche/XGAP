# Optional and finite regex repetition

2026-09-11. Accepted after independent reference, real Neo4j/Fuseki and full
regression gates. See [the acceptance report](../report/toy_backbone_t1_repetition.md).
Scope/semantics were frozen before implementation.

Optional(E) denotes Nodes(G) union E. It does not introduce a new recursive
restrictor scope: child recursion retains its own mode. In particular, an
ordinary Seq does not acquire a new TRAIL check because it is optional.

Bounded(E,m,n) counts concatenated child paths, not graph edges. For finite n,
form the union of exact powers E^k for max(1,m) <= k <= n, then apply the
requested path mode to that positive candidate set. Existing Recursive(P,mode,
max_depth=1) already expresses that operation: it filters paths for the four
path-validity modes or selects all shortest paths per endpoint pair. This is
not a new algebra operator and does not change Recursive's existing definition.
When m=0, union Nodes(G) outside this positive selection, matching Star's
existing treatment of zero paths. For n=0 return Nodes(G). Every child is
lowered compositionally, retaining its own recursive scopes.

This avoids two incorrect rewrites: edge length is not repetition count when
the child has variable length, and selecting unrestricted shortest paths before
applying a repetition lower bound can lose every valid answer. Nullable child
paths may give one physical path several valid repetition decompositions;
PathSet still deduplicates by complete sequence.

An omitted upper bound with m=0 or1 retains Star/Plus behavior. With m>=2,
an explicit query.max_depth supplies a finite upper bound; otherwise the
minimum-constrained unbounded closure remains an explicit logical gap. A finite
Bounded upper bound governs that node; query.max_depth continues to govern
unbounded descendants. Negative, boolean or fractional counts are invalid.

Native scope: Optional in Rel/Seq/Alt alternatives; root finite Bounded in
addition to root finite Plus/Star. Nested finite Bounded may flatten only under
WALK, where no local restrictor scope is erased. Nested non-WALK recursion and
variable-child Plus/Star SHORTEST remain explicit backend gaps; finite Bounded
SHORTEST enumerates its full admitted powers before selection. Native expansion keeps
existing branch/edge budgets and uses existing coordinator selectors. Finite
range SHORTEST is selected across all admitted positive repetition counts,
before outer length predicates. If a nullable child yields zero-length paths
inside positive repetition, those participate in shortest selection and can
suppress positive cycles. This differs from the separate zero-repetition Nodes
branch of Star/Bounded(min=0), which does not suppress positive closure cycles.
The native selector records this distinction explicitly. Original gold stays frozen.

Allowed changes: pattern lowering/type checking, native finite expansion,
capability scanner, fixtures, tests and harness. Forbidden: changing existing
algebra meanings, pretending unsupported combinations are implemented, altering
historical benchmark data/results, building catalogs or requiring a model.

Gates: independent tiny NL/gold query/logical plan/target/answer chains for zero,
one and several repetitions, variable child lengths, mixed direction, self-loop,
parallel edges, path modes and lower-bound SHORTEST; local reference/RDF replay,
real Neo4j/Fuseki and retained two-engine slice, then shared-core regression.
