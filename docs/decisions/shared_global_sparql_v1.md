# Shared grounded meaning to global SPARQL v1

Milestone: complete the common NL evaluation connection, not a new baseline
optimizer. Allowed files: bounded semantic-to-global compiler, NL frontend/worker
integration, the missing ordinary RDF estimator type admission, targeted tiny
checks and evidence. No author engine code, gold-query substitution, model/weight
tuning, new financial cohorts or repeated accepted gates.

The compiler accepts an already grounded semantic DAG, never a question ID or
family name. Reuse existing semantic validation and canonical Match lowering;
compose relational operators into one unresolved SELECT, without SERVICE, endpoint
addresses, plan cost selection, execution or XGAP coordinator work around a baseline.
The selected interpretation is compiled once, and the original external method
executes that query itself, including aggregation and sorting. Native unsupported
forms and failures remain failures. Compiler failures are our integration category,
not native baseline limitations. Do not simplify/tune emitted queries after seeing
method outcomes.

Initial bound: one root, at most64 semantic operators/128KiB input; Match sources,
Filter, set Union/Project/Join, SUM/COUNT, and final OrderLimit. Compact1..3-hop paths
are already lowered to these operators. No unresolved holes, Align, opaque
constraints, unlowered Traverse, internal OrderLimit or path-valued projections.
Data contract is the published FinBench scalar mapping: canonical global identity,
single-valued properties, finite typed numbers, strings, booleans and nullable
fields; timestamp_ms compares valid millisecond strings. Each ordered column has a
homogeneous scalar kind; declared keys determine any observed top-K boundary.
Heterogeneous RDF term ordering and MIN/MAX are outside this first bridge.
Native floating SUM is assessed under the already frozen three-decimal answer
normalization, not claimed byte-identical to coordinator decimal accumulation.

Every relation preserves necessary set boundaries; independent child scopes prevent
accidental joins on same-named variables. Identity outputs become strings matching
existing normalized global IDs. Missing properties remain unbound/null; joins never
match null keys. Root ordering makes nulls first/last explicit. No extra source
choice or facts are supplied to an external engine.

Before inlining, compute saturated DAG expansion counts (maximum4096 emitted
relations); reject rather than silently truncate. Each emitted query is capped at
1MiB, with at most two bounded child strings per composition. With input size L,
N runtime nodes and output byte budget B, validation plus construction is polynomial
O(poly(L)+N*B) time and O(L+N*B) space, bounded before repeated DAG expansion.
This is a compilation resource bound, not a planner approximation guarantee.

Shared NL baseline frontend uses the same frozen model/compact grammar/catalog as
precision mode (K3), grounds admitted candidates, chooses the highest declared
quality proxy with stable ID tie-break, and compiles that choice once. No estimated
cost or execute-all selection, automatic fallback to another meaning, retry or
repair. Each measured system invocation pays its own actual model call; offline
replay remains explicitly offline. Ordinary XGAP retains its two estimated modes.

Acceptance first: three independently authored tiny compact meanings compiled and
queried against the corrected union, duplicate/alias/null/time and expansion risks,
plus ordinary-instance admission and frontend selection/cost accounting. Then only
the newly connected actual NL/external boundary, preserving its first outcome.
