# T1 semantic DAG to native federated execution

2026-09-10. The native gate passed: **36/36** original path-query executions
through SemanticGraphProgram, **8/8** composed semantic cases, **8/8** independent
Cypher references, and the retained original two-engine slice. Focused checks:
**137 passed in 9.80s**. Broad shared-runtime acceptance passed in original
session **42090**, exit 0: **3,049 passed / 38 skipped in 657.66s**, plus all
24 harness/example entrypoints. This semantic composition step is accepted;
full T1 and the overall system Goal remain open.

## What now executes

`compile_semantic_program` turns a fully bound typed DAG into ordinary runtime
nodes. Match uses existing Nodes/Selection lowering and native compilation;
Traverse invokes the bounded path planner. Filter, Project, Join, Union,
Aggregate, OrderLimit and Align compose above those sources. No query-ID-specific
native template is used. The compiler consumes meaning and declared placement,
never fixture answers, an LLM response service, a catalog builder or a database.

Source placement is separate from meaning. Shared DAG ancestors execute once.
Matched entities and projected path keys use explicitly qualified global IRIs,
so equal local IDs in different namespaces do not become an accidental join.
Typed node properties retain numeric/boolean distinctions. Right-side column
collisions are renamed deterministically before joining. Row projection retains
ordering after OrderLimit. Global row count over empty input returns one row
with zero, through an explicit opt-in to the existing aggregate runtime.

These are runtime implementations of the existing semantic vocabulary, not new
path-algebra operators. Existing scheduler budgets, accounting, backend plugins,
failure propagation and skipped descendants remain in use.

## Independent tiny cases and actual results

The original five-node/eight-edge graph and all eighteen path gold chains are
unchanged. New fixtures contain seven different DAGs plus one placement swap,
with NL, typed programs, logical operator order, expected runtime stages,
independent Cypher/SPARQL target queries and manually authored complete answers.
All eight SPARQL references also match under an independent RDFLib evaluator.

| Case | Behavior | Actual complete answer (IRI prefix omitted here) | Native calls |
|---|---|---|---:|
| S01 | Neo4j paths, Fuseki age filter, Join/Project | person c, edge e4 | 2 |
| S02 | Preserve parallel edges, Join, count by target, order/limit | ordered (b,2), (c,2) | 2 |
| S03 | Fuseki Bob binding drives Neo4j traversal | b/e2/c and b/e8/d | 2 |
| S04 | One Match feeds two filters, Union and Project | b,c,d,z | 1 |
| S05 | Empty Match followed by global count | count=0 | 1 |
| S06 | Explicit synthetic key alignment before Join | a | 2 |
| S07 | Join equal-valued colliding property columns | left_age=30, right_age=30 | 2 |
| S08 | S01 with both backend placements swapped | person c, edge e4 | 2 |

S06 exercises a supplied mapping; it is not evidence that Bob and Alice are the
same real entity. S03 currently fetches native candidates and applies endpoint
binding at the coordinator; it does not claim binding pushdown. Six of the eight
cases actually call both engines; S04 and S05 intentionally use one source.

## Verification and limitations

- Native original session **92465**, exit 0, real Neo4j 5.26.30 and Fuseki 5.6.0
  on fresh owned toy stores. Both services stopped normally; no automatic retry.
- Raw results and complete generated plans:
  `/Users/anthonyche/xgap-data/t1-semantic-native-20260910/result.json`.
- Compact durable receipt:
  [`toy_backbone_t1_semantic_20260910.json`](../../experiments/artifacts/toy_backbone_t1_semantic_20260910.json).
- Focused log `/tmp/xgap-t1-semantic-focused.log`: 137 pass / 0 skip. The process
  had already terminated when this continuation read its final summary; no
  session identifier is fabricated. Initial 35-test local check also passed.
- The daily toy harness now includes semantic-DAG checks. Native execution is
  optional via `scripts/run_toy_backbone_native.py --semantic-dag` and uses only
  prepared binaries plus the frozen tiny graph.

This closes executable composition for the declared profile, not every possible
semantic program. Source placement is explicit; the existing cost selector still
needs candidate-generation integration with this entrypoint. Holes must first be
bound; opaque constraints and additional capability requirements need typed
resolution/admission. Rejecting those unsupported inputs is not their completion.
Path recursion retains the bounded compiler limits. M5 IN reference lowering,
nested/unbounded native recursion and wider condition coverage remain open.
Decimal RDF values retain their tags and exact filtering; general tagged RDF
aggregate/order semantics have not been established. Coordinator materialization
and lack of binding pushdown prevent any current scale/performance claim.

Next work uses the same tiny fixtures: join this compiler to existing candidate
planning/control, reconcile orientation with the logical/reference layer, then
T2 Interpretation, offline catalog freeze/runtime lookup and failure replay.
No GrailQA build, GPU wait or large benchmark was needed. These are development
correctness results, not NL accuracy, SOTA comparisons or paper evaluation.

The next small integration check can reuse S01/S08: generate the two equivalent
placements from one program, attach explicit source observations, choose through
FederatedPlanSelector, and execute the chosen plan against the same gold. Give
candidates distinct plan IDs and retain coordinator work in estimates; the
selector's current generic pass-through row estimate is not a calibrated model
for the new filter/path stages. This is a concrete connection task, not a new
large experiment or a claim that either placement is always faster.
