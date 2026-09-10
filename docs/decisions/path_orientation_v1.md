# Path orientation extension v1

2026-09-10. Status: accepted. Native18/18 compiled and18/18 independent targets plus the
retained slice pass; final broad3117/38 and all24 harness/example entries pass.

## Problem and scope

The directed graph source `Edges(G)` returns each stored source/edge/target
sequence. Selection, endpoint concatenation and recursive closure cannot turn
such a sequence into its inverse. Rejecting IN in M5 while the native path
compiler executes IN leaves the deterministic reference chain incomplete.

Add one explicit XGAP logical extension `Reverse(P) : PathSet -> PathSet`,
defined as `{ reversed(p.sequence) | p in P }`. This is an XGAP extension,
not a claim that a new symbol belongs to the original audited paper algebra.
Existing Edges(G), PathSet set identity and all other operators are unchanged.
No reverse edges are inserted into the graph, IDs are not replaced and the
graph's stored source/target metadata remains unchanged.

Reverse is an involution, preserves lengths and edge/node identities, reverses
endpoint positions, distributes over Union, and reverses concatenation order:
Reverse(Join(A,B)) = Join(Reverse(B),Reverse(A)). Zero paths stay unchanged.
Conditions outside Reverse refer to traversal positions; edge-property filters
inside a one-edge Reverse still inspect that same stored edge. Reverse only
accepts PathSet input; it does not reverse SolutionSpace ranks or row bindings.

Lower a labeled/propertied OUT relation as before. Lower IN to Reverse of that
filtered relation. Lower UNDIRECTED to Union of the filtered relation and its
Reverse. Set semantics merge the duplicate orientation of a self-loop while
preserving parallel edges with distinct IDs. Existing recursive WALK/TRAIL/
ACYCLIC/SIMPLE/SHORTEST rules apply to the resulting traversal paths, including
edge identity reuse when an edge is crossed in both directions. This adds no
new recursion mode or implicit depth limit.

Candidate assessment advertises the versioned logical profile
`m5_path_algebra_orientation_v1`, matching the actual lowerer. Logical availability
never sets backend_execution_verified. Old reports retain their recorded profile
and measured outcomes; new code does not manufacture historical backend results.

The bounded native compiler expands an undirected edge into its two OUT/IN
alternatives within the existing branch budget, then uses the existing native
compiler and coordinator deduplication/selectors. M9's older logical compiler
continues to reject unsupported Reverse; it must never treat it as OUT. This
does not claim full M9 or unbounded/nested native recursion coverage.

## Allowed edits and acceptance

Allowed: this design/semantics documentation, logical AST/evaluator/validation,
pattern lowering, native bounded direction expansion, compiler feature rejection,
tiny development fixtures/runners and related tests. Forbidden: silently changing
Edges(G), graph storage, original gold answers, published baseline artifacts,
identity policy, or benchmark/model/catalog construction.

Keep backbone_toy_v1 frozen. T15's original logical text is a semantic-level
placeholder, not an executable M5 plan. Add a separate versioned, hand-authored
logical expectation for T15; explicitly opt the development harness into that
expectation. Its old text and complete expected answers remain untouched.

Acceptance: original18 answer chains and updated logical expectations; tiny
mixed/undirected/recursive identity witnesses; Reverse algebra laws and typed
input rejection; independent native targets and both real backends on the same
five-node/eight-edge graph; retained federated slice; focused checks and a shared
core acceptance run. Passing a supported profile does not complete T1/T2/T3.
