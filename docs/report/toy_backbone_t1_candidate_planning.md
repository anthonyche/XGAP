# T1: semantic candidate generation, cost selection and native execution

2026-09-10. **8/8** semantic programs pass the native planning/execution gate;
all **28/28** generated placement candidates match independent complete gold
answers. The original two-engine slice still passes. Focused checks: **106 pass
in 2.68s**. Broad acceptance passed in original session **6473**, exit0:
**3,069 passed / 38 skipped in657.30s**, all24 harness/example entrypoints pass.
This candidate-planning connection is accepted. The overall T1/T2/T3 Goal is incomplete.

## Implemented connection

`enumerate_semantic_plans` receives one typed program, its logical source
bindings, versioned source-replica declarations and backend configuration. It
generates combinations of declared equivalent placements and invokes the
production semantic compiler for each. Distinct plans carry one shared semantic
equivalence key. Unsupported compilations remain recorded rejections; supported
placements remain usable. Exceeding the finite enumeration/observation budget
fails before external actions, rather than silently narrowing the search.

The declaration means complete replicas of the same logical source snapshot;
endpoint availability does not establish equivalence. Different namespaces are
not silently aligned. A source with one declared backend stays on that backend.
Partitioned sources still require explicit semantic decomposition; this entry
does not invent cross-shard completeness or split arbitrary Traverse internals.

Generated native artifacts receive observation keys bound to backend, source
version and artifact content. Identical observations across placement candidates
are collected once through the existing registered backend tools. The small
`BackendObservationCatalog` here is an in-memory allowlist of compiled queries,
not a GrailQA entity index or corpus build. Explicit Exchange stages account for
candidate-result transfer, while existing coordinator stages retain their cost.

`run_semantic_plans` collects missing source observations, uses the existing
FederatedPlanSelector and sends only its winner to FederatedExecutionTool. A
supplied compatible snapshot avoids fresh observations. The result separates
enumeration, acquisition, selection and serving, counts all current remote
calls, and includes the selected plan and actual typed answer. A snapshot with
another dataset version cannot satisfy the generated observation keys.

The new filter/path/row-normalization estimates expose row/width fractions;
default estimates preserve input rows/width and charge linear coordinator work.
Global aggregation estimates one output row even when its input is empty.
These remain proxy assumptions, not calibrated cardinalities or proof of a
real minimum-latency winner. Native observations use actual Neo4j PROFILE and
Fuseki wall-clock execution; no benchmark performance claim is made.

## Native results

The frozen five-node/eight-edge data and all original path/semantic gold files
are unchanged. The tiny stores contain declared complete replicas. For each
program, planning runs once; afterward the chosen result is reused and every
other candidate executes once solely to check answer equivalence.

| Program | Candidates correct | Selected placement in this run | Observation + serving calls |
|---|---:|---|---:|
| S01 path/property join | 4/4 | paths Fuseki; people Fuseki | 4+2 |
| S02 count and order | 4/4 | paths Fuseki; people Neo4j | 4+2 |
| S03 bound traversal | 4/4 | anchor Fuseki; paths Neo4j | 4+2 |
| S04 shared source/Union | 2/2 | people Neo4j | 2+1 |
| S05 empty global count | 2/2 | people Fuseki | 2+1 |
| S06 explicit alignment | 4/4 | external Neo4j; left Fuseki | 4+2 |
| S07 colliding columns | 4/4 | both sources Fuseki | 4+2 |
| S08 S01 meaning/fixture variant | 4/4 | paths Fuseki; people Neo4j | 4+2 |

The eight planning runs made **28 observation calls + 14 serving calls = 42**.
Candidate validation added **38** calls outside planning/serving timing; the
retained original slice adds two further calls. Store loading is setup. S01/S08
selected different placements because observations were taken at different times;
that is not evidence of a meaningful performance difference on this tiny graph.

The timing split is useful as an engineering observation: S01 spent416.4ms in
enumeration/acquisition/selection and24.3ms serving; S08 spent66.0ms planning and
12.8ms serving. In this one pass, preparing the decision cost more than running
the selected query. These mixed cold/warm timings are not a controlled performance
comparison. They motivate testing observation reuse/selective acquisition while
retaining all acquisition cost; a smaller serving time alone is insufficient.

Native original session **55823**, exit0, Neo4j5.26.30/Fuseki5.6.0 with Java21.
Both owned services stopped normally, no automatic retry. Raw:
`/Users/anthonyche/xgap-data/t1-planning-native-20260910/result.json`.
Durable results: [receipt](../../experiments/artifacts/toy_backbone_t1_planning_20260910.json).

## Failures exposed by the local harness

The first test run failed because test replica mappings retained the original
backend ID and compiler capability exceptions were not classified as rejected
placements (12 fail/6 pass). The next run exercised two RDFLib parsers concurrently
and corrupted their shared parsing state (38 fail/39 pass). Serialize only the
offline test adapter's parser; actual backend concurrency is preserved.

That exception also exposed a production failure boundary: an exception from a
backend plugin escaped the scheduler future. The scheduler now records one
attempt and a typed failed node, preserving accounting and skipped descendants.
A dedicated test reproduces a plugin crash without a database. No automatic
retry or new fallback is introduced. A subsequent 91-test run passed; final
focused session21349 passed106, including cost changes that switch placement,
unchanged gold answers, stale snapshots, finite budgets and failure propagation.
Logs `/tmp/xgap-t1-planning-initial.log`, `focused.log`, `focused2.log` and
`focused-final.log` retain these steps (the latter three share the same prefix).
One additional test command referenced a nonexistent file and ran no tests;
its `focused3.log` is retained. It is not an implementation test result.

## Remaining work

This completes a declared-source placement connection, not general source
discovery, all physical rewrites, streaming, a calibrated optimizer or a learned
information-acquisition policy. Candidate acquisition currently profiles all
unique remote fragments if a snapshot is absent, so its cost can outweigh any
serving benefit. Reusable observations and selective acquisition need independent
experiments. Admission/control for unresolved meanings, M5 IN logical/reference
coverage, broader path semantics, Interpretation, frozen catalog/runtime boundaries
and failure replay remain open. The next work stays on the same tiny graph;
GrailQA/GPU work does not block these system connections.

Current supplied-snapshot matching binds native query and logical data identity;
freshness and changed hardware/load are not proven by that match. Future reusable
observations need explicit deployment/freshness policy before paper-level reuse
or robustness claims. No such benefit is attributed to this development gate.
