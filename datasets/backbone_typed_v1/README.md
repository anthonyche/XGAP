# Typed binding values, tiny development fixture v1

Five persons, eight identity-preserving edges. This is a separate overlay of the
accepted Boolean toy graph; the original graph, queries and gold files remain
unchanged. No LLM, catalog, GPU or large dataset is needed.

`cases.json` independently specifies 15 NL requests, semantic DAGs, zero-length
Match path subqueries with logical plans and node answers, expected runtime
operator sequences, target-query paths, and typed final answers. Gold plans and
answers were authored directly, without importing the production compiler or
evaluator. Runtime operator order follows dependency traversal, not JSON list
order. The native runner also retains the original T18 two-engine vertical slice.

Coverage: exact integer SUM above 2^53, exact RDF decimal SUM, COUNT(*) and
COUNT(field)/DISTINCT, numeric-equivalent grouping, bool/string distinction,
mixed ordering with explicit null placement, MIN/MAX, Filter→Aggregate,
cross-engine value joins, Union, DISTINCT sum promotion, empty input/all-null
aggregates, and a real property-source join followed by decimal aggregation.

`sources.json` explicitly declares logical views and equivalent replicas:

- `core`: both Neo4j and Fuseki; original properties plus integer amount.
- `credit`: Fuseki only, containing Person identities and decimal credit.

The compiler does not infer arbitrary source completeness. Only operators that
read a declared view may use its listed replicas. `load.cypher` omits credit;
`load.ttl` carries both views. Each view has its own content version. This does
not claim Neo4j supports arbitrary-precision decimal properties or automatic
graph partition discovery.

Reference Cypher/SPARQL is separately written, not copied from generated plans.
SPARQL term DISTINCT is not XGAP numeric-value DISTINCT. For this fixture's
integral numeric score values (1 and 1.0), references explicitly cast through
FLOOR to integer to make term identity equal. FLOOR also avoids RDFLib 7.1.4's
failed direct decimal/double-to-integer lexical conversion. The amount and
credit arithmetic is not truncated. V10 projects each source in deterministic
person order; the first numeric representative is Alice's integer 1. References
emit that integer representation explicitly. These choices do not redefine the
general runtime scalar contract, and are not performance or NL-accuracy results.

Local RDFLib tests label their two replicas as RDF, never as actual Neo4j.
Native acceptance uses pinned Neo4j 5.26.30 and Fuseki 5.6.0, all legal candidate
placements and independent targets. Observation, serving, and extra validation
calls are recorded separately; reference answers are not inputs to the planner.
