# XGAP bounded core query profile v1

2026-09-11. This is the finite first-system language contract requested by the
user, separate from operational budgets and benchmark selection. Its rules are
specified before any new evaluation. It does not define membership as “whatever
the compiler happens to accept”. Compiler failures on valid included inputs
remain defects to investigate. No large benchmark question is removed here.

## Language, data and result meaning

Inputs are finite read-only labeled property graphs and RDF graph encodings.
Each source has an explicit snapshot identity, schema mapping and identity
namespace. A logical source may declare complete equivalent replicas; different
property views may be assigned to different sources. RDF paths require explicit
node-domain classes and edge identity so parallel edges survive translation.
Endpoint availability alone is not evidence of source completeness.

A query is a finite, statically typed semantic DAG built from:

`Match`, `Traverse`, `Filter`, `Project`, `Join`, `Union`, `Aggregate`,
`OrderLimit`, and `Align`.

- Match binds node identity and declared scalar properties. Traverse evaluates
  a path pattern, optionally constrained by input endpoint bindings.
- Path expressions use labeled/unlabeled Rel, Seq, Alt, Optional, finite Bounded,
  and Plus/Star with explicit finite repetition depth. OUT/IN/UNDIRECTED and
  finite nested scopes are included. A Bounded expression in this first profile
  has an explicit upper repetition count; no unbounded repetition is promised.
- The audited WALK/TRAIL/ACYCLIC/SIMPLE/SHORTEST and ALL/ANY/ANY_K/ANY_SHORTEST/
  ALL_SHORTEST/SHORTEST_K/SHORTEST_K_GROUP rules apply. Depth counts child
  repetitions where specified; actual expanded-edge length is a separate bound.
- Path predicates include supported identity, label, property, numeric comparison
  and length atoms combined with AND/OR/NOT. Numbered path positions require
  fixed-length expressions. Missing-property and shortest-before-outer-filter
  semantics follow the audited algebra, not whichever native syntax is easiest.
- Binding predicates have scalar equality/inequality, numeric ordering, null
  tests and AND/OR/NOT. Projection exposes fields or declared path positions/
  length. Union is set union; Join is equality join; Align uses explicit mappings.
- Aggregate supports grouping and COUNT(*), COUNT(field), SUM, MIN/MAX with
  optional DISTINCT. OrderLimit uses declared scalar fields, asc/desc, null
  placement and a positive limit. The exact integer/decimal, finite floating,
  numeric equivalence, Boolean distinction and empty/null behavior are in
  [typed binding values](decisions/typed_binding_values_v1.md).
- Native predicate literals must fit the explicitly supported backend scalar
  range. Exact coordinator sums may exceed a backend integer-property range.
  RDF decimal storage is a declared source capability; it is not inferred for
  Neo4j. Unknown RDF terms keep identity; no temporal arithmetic is implied.

Schemas and input/output kinds must agree at every edge. Each node must be
reachable from a query root. Unresolved entity/schema/source/constraint holes
belong to Interpretation/resolution; only a resolved program enters deterministic
planning. Named hard constraints must have supported executable predicates and
must reach the plan. They cannot be silently ignored or relaxed.

Historical focused-binding and PathSet layers keep their own audited contracts.
For example PathSet atomic Boolean/numeric equality and binding-value equality
are distinct contracts. Predicate rewrites between these layers require a proven
equivalence. This profile does not introduce such a rewrite.

## Explicit exclusions

General relational LEFT OUTER JOIN, arbitrary correlated NOT EXISTS/OPTIONAL,
bag/UNION ALL semantics, windows, arbitrary functions/UDFs, unrestricted graph
algorithms, temporal interval algebra and unlimited recursion are outside this
first language profile. Optional path repetition does not implement relational
outer joins. Unsupported operators in historical reference APIs are not silently
admitted into the modern native DAG.

Automatic discovery of arbitrary graph partitions, streaming/cancellation and
cost-model calibration concern broader system execution. They remain system
work; declaring a query-language bound does not claim these are implemented.

## Resource bounds are independent

A caller must choose finite repetition/expanded-edge bounds and finite
branch/candidate/observation/remote-call budgets. The current compiler has a
64-edge implementation ceiling and128 default expansion branches; normal
enumeration defaults to64 candidates,128 unique observations and16 execution
calls per plan. A budget failure is distinguished from an unsupported language
form and from an incorrect answer. Smaller development settings, such as actual
expanded length L=3, do not change the meaning of an admitted query or silently
truncate it. This document installs no new global3-hop limit.

The current runtime does not yet provide a universal intermediate-row/memory
bound or general streaming. LIMIT only constrains output, not all intermediate
work. A correctness claim is not a performance or bounded-memory theorem.

## Operator-by-layer evidence

The table links independently authored semantics/gold with the actual compiler,
runtime and native checks. It is a coverage map, not a proof of every possible
nesting or a replacement for a future benchmark coverage denominator.

| Capability | Independent meaning/gold | Compiler/runtime checks | Native evidence |
|---|---|---|---|
| Match, typed properties | semantic S04–S07; Boolean Match; typed V01–V15 | node_match; semantic_dag_compiler; native_boolean_conditions; typed_binding_execution tests | semantic, Boolean and typed milestone reports |
| Traverse/identities/directions | original T01–T18; orientation fixtures | lowering/reference; reified_directed_compiler; path_orientation tests | original36 and orientation18 query executions |
| Repetition, modes, scopes/selectors | original18; repetition13; scoped15 | finite_regex_repetition; scoped_path_execution; native_boolean_conditions tests |26 repetition,30 scoped,40 Boolean path executions |
| Filter/Project/Join | S01/S02/S07/S08; V08/V09/V13 | semantic_dag_compiler; typed_binding_execution tests | independent Cypher/SPARQL and candidate-placement checks |
| Union/shared input | S04; V10 | semantic_dag_compiler; typed_binding_execution tests | native S04/V10 candidates |
| Aggregate/OrderLimit | S02/S05; V01–V08/V11–V15 | typed_binding_values; typed_binding_execution tests |15 typed programs/32 candidate answers/27 independent targets |
| Align | S06 | semantic_dag_compiler and m15_federated_runtime tests | native S06 in accepted semantic-DAG gate |
| Binding/constraints | B01–B05 independent expected bindings and answers | semantic_binding_execution; m15_artifact_resolution tests |5 agent goals/18 candidate answers/10 independent targets |
| Source selection/cost boundary | semantic and capability fixtures, explicit typed core/credit views | semantic_planning; semantic_capabilities tests |28 original candidate answers; capability16; typed32 |

Evidence reports: [semantic DAG](report/toy_backbone_t1_semantic_dag.md),
[candidate planning](report/toy_backbone_t1_candidate_planning.md),
[binding](report/toy_backbone_t1_semantic_binding.md),
[orientation](report/toy_backbone_t1_orientation.md),
[repetition](report/toy_backbone_t1_repetition.md),
[scopes](report/toy_backbone_t1_scoped_paths.md),
[Boolean](report/toy_backbone_t1_boolean_conditions.md),
[typed values](report/toy_backbone_t1_typed_bindings.md).
Counts overlap and must not be added as independent research samples. Current
and historical source-version boundaries remain in each report.

Use this finite contract for subsequent core bug triage and T2 integration.
T1 has the mapped native capability baseline; full compositional closure is not
asserted as a theorem. Keep module isolation and the permanent vertical slice.
Interpretation quality, catalog lifecycle, general replay, real-model/mini
integration, UI and the final EQ1–EQ5 evaluation remain separate system gates.
