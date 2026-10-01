# Native total Boolean conditions

2026-09-11. Design frozen before implementation; implementation and acceptance complete.

Goal: execute existing AND/OR/NOT Selection semantics through modern native
path compilation and semantic Match/Traverse, including missing properties and
outer conditions on shortest paths. The legacy M9 compiler remains a frozen
limited strategy; no algebra definition, graph identity or historical gold is
changed. New fixtures use the same graph structure with a separate explicit
scalar-property overlay, leaving the original graph/loaders/gold frozen.

Atomic conditions are total booleans under the existing reference evaluator.
Missing property equality and inequality are both false. Therefore NOT(x=value)
can be true on a missing property, while x!=value remains false. OR must not
require all property leaves to exist. Cypher must totalize atomic comparisons
before applying NOT. SPARQL must keep property bindings local to EXISTS tests,
not promote each disjunct's property triple to a mandatory graph pattern.

Preserve existing scalar equality: the reference uses Python scalar equality,
including True=1 and False=0; numeric ordering excludes booleans and non-finite
numbers. Modern leaf rendering must keep equality/inequality consistent inside
and outside Boolean combinations. This is not a redefinition of equality.
The native portable profile still excludes null query constants, unsupported
literal types and unsafe identifiers/mappings. Scalar RDF mappings represent
one logical scalar property, not arbitrary multivalued property aggregation.

Every Boolean leaf undergoes the existing literal, reference, primitive and
mapping checks. Negative/disjunctive label conditions are never hoisted into
mandatory labels. Positive structural constraints may still bound traversal.
Explicit backend feature exclusions remain effective below Boolean nodes.

For SHORTEST, only conditions depending on endpoints commute with local
minimum selection. Standalone length conjuncts may use the existing final
length filters. Boolean expressions involving length or internal positions
must remain outside shortest selection, using the accepted scoped planner and
full-path intersection when a single native candidate query is insufficient.
Inspect the complete condition tree before choosing that placement.

Allowed files: modern directed/bounded/Match condition rendering, condition
placement checks, fixture helpers/harness, independent Boolean/type fixtures,
focused tests and current architecture/status reports. Preserve the dependent
Freebase split adapter's existing conjunctive boundary explicitly when the
shared shape validator broadens; no large-dataset work is implied. No model, catalog
build, GPU, large benchmark or change to existing algebra is required.

Gates: independent NL/gold query/logical plan/native target/typed answer chains
covering nested AND/OR/NOT, absent properties, equality versus inequality,
boolean/numeric/string distinctions, node/edge labels and properties, negative
conditions on zero paths, and shortest-before-outer-filter witnesses. Test
Match and Traverse plus normal planning/observation/serving, then real
Neo4j/Fuseki/independent references and the retained two-engine slice, followed
by one final shared-core broad regression and examples after source stabilizes.

Acceptance:20 complete path chains (40/40 dual-backend executions and40/40
independent references),4 Match programs (8/8 execution and8/8 references),
3/3 planning programs/6/6 candidate answers and original federated slice pass.
Match admission follow-up passes;48/48 final compiled plans are identical to
successful native records. Daily401 pass; final broad3246 pass/38 skip and all24
harness/example entries pass. Failure history and version boundaries remain in
[the report](../report/toy_backbone_t1_boolean_conditions.md). This accepts only
the stated modern scalar/Boolean profile, not complete T1/T2/T3 or the Goal.
