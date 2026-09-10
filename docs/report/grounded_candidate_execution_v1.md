# D203: grounded candidate execution with preserved constraints

Status: COMPLETE for controlled software/native acceptance. Parent milestone H4 remains open. This milestone connects actual
grounded planner objects to the D202 dataset representation and backend runtime.

## Scope frozen before implementation

Inputs are the controlled planner response, its exact inference request/view,
an explicit Freebase resource/literal mapping and execution requirements from
the caller's goal. No reference answers or inferred/gold entity IDs are inputs.
Re-run the existing pure typed/grounding contracts, preserve every candidate's
outcome, and lower accepted fixed OUT/IN Rel/Seq paths without dropping class,
identity, inequality or supported scalar constraints. Native relation/type
facts come from the D202 resource-edge mirror; literal predicates stay in RDF.

The execution goal explicitly declares whether an entity anchor is required.
Declared candidate entity IDs alone cannot satisfy it: a positive identity
equality must occur in the actual query. An optional bounded provider feedback
callback reports missing anchors using only prompt-visible IDs; it never
inserts an entity, chooses among ambiguous IDs, changes old policies or repairs
a valid query merely because a backend capability is unavailable.

Add finite correlated URI-row VALUES binding so all visited path positions
reach the RDF fragment together. Do not substitute independent per-column
sets, which would lose path correlation. Resource-only constraints execute in
Neo4j; literal checks execute in Fuseki. A scalar-property contract must be
explicit and checked on reached paths before scalar filtering; multivalued or
incompatible data is an unavailable/error outcome, not silent coercion. Keep
date ordering and unsupported graph constructs explicit rather than approximate.

Allowed: additive dataset/candidate execution and feedback adapters, an opt-in
correlated binding path in the existing runtime/SPARQL boundary, tests, examples
and documentation. Forbidden: new algebra operators, old catalog/source/model
or frozen experiment edits, reference leakage, silent constraint erasure,
automatic external retries, changed historical metrics or claims of a fresh
Qwen run. Reuse the retained native databases; no source rebuild/reload.

Acceptance:

1. Independent RDF execution tests preserve OUT/IN paths, endpoint/intermediate
   constraints, explicit identity, scalar behavior and answer projection.
   Correlated bindings, malformed inputs, overflows and failures are covered.
2. The saved 3796877 request/view/response source is read-only and hash-bound.
   All 18 questions and all candidate outcomes remain visible. No unanchored
   candidate is dispatched as an answer to an entity-anchored question.
3. The accepted execution interface runs against the retained actual native
   stores. Positive engineering fixtures remain labeled as controlled fixtures;
   replayed historical candidates remain historical, not fresh model accuracy.
4. Focused tests, full offline suite, harness and examples pass. Retain actual
   endpoint results, complete failures and normal owned-service shutdown.

## Observed input defect

The uploaded `/Users/anthonyche/Downloads/query_states.jsonl` still matches
SHA-256 `f207a5d4e3563e391274ebc0109ce2906a5ea2a007b27f4b362823c1bd887c18`.
Reconstructing the existing request/view and typed grounding retains four
candidates for two questions, as previously reported. All four have empty
source/target property maps and no positive entity-ID equality in their AST;
their declared entity-ID arrays are not query constraints. For example, the
American Airlines question has a generic airline→hub candidate. Therefore the
next gate must check execution-goal anchoring rather than silently assigning
one of the four declared IDs or presenting a global-class result as its answer.

## Implemented behavior

`prepare_candidate_batch` consumes the exact request and prompt view, reruns
the existing normalization and canonical grounding, preserves candidate order
and every failure, and returns separately executable programs. It never ranks
or selects a candidate. Input, grounded candidate, pattern, plan, mapping and
goal requirements remain linked in the result. Unsupported constructs remain
unavailable; old lowerer availability does not reject supported IN paths.

The dataset compiler retains positive entity bindings, node classes, explicit
node inequalities, length, fixed OUT/IN steps and declared scalar predicates.
SIMPLE requires the existing parser's explicit node inequalities. Other implicit
restrictors and a fixed path exceeding the stated depth are rejected. Class
checks use actual `type.object.type` resource edges in the Neo4j mirror.

Resource-only intent makes one Neo4j execution call. Scalar intent makes three
calls: resource paths, reached-data scalar validation, then literal filtering.
The latter two use correlated URI tuples for every path position. Guards must
account for every input tuple; missing rows, multivalued fields, wrong datatypes,
invalid lexical forms and nonfinite numeric values fail explicitly. Result and
binding counts/bytes have finite limits; LIMIT + 1 is an overflow sentinel.
The baseline runs only after successful federation, using complete Fuseki RDF.
Raw backend reports are retained even when the scalar guard rejects their data.

## Actual native observations

The retained D202 stores were reused without loading or changing source facts.
Neo4j 5.26.30 and Fuseki 5.6.0 again ran on local Java 21. The controlled input
recording `m.0x8z059` was selected from a documented first-shard fixture: the
first sorted track with a string track number `1`, recording/release edges and
the track class. This is development fixture selection after source inspection,
not a sampled benchmark population or a model prediction. No reference answers
were read.

| Controlled intent | Actual outcome | Federated calls | Independent agreement |
| --- | --- | ---: | --- |
| Recording ← track → release, track number string `"1"` | 1 release: `g.11b6c7l7m9` | 3 | Full Fuseki and source Arrow |
| Same path, track number string `"2"` | Successful empty set | 3 | Full Fuseki and source Arrow |
| Same resource path without the literal predicate | Same 1 release | 1 | Full Fuseki and source Arrow |
| Same path, declared numeric track number `1` | Explicit scalar-encoding failure | 2; filter/baseline not dispatched | Actual source stores strings |
| Recording ← track, target class `music.release_track`, string number `"1"` | 1 track: `g.11b6brdn9b` | 3 | Full Fuseki and source Arrow |
| Same target, class changed explicitly to `book.book` | Successful empty set | 3 | Full Fuseki and source Arrow |

The source path is exactly
`m.0x8z059 → g.11b6brdn9b → g.11b6c7l7m9` in traversal order. The first edge is
stored in the opposite direction. The class counterexample confirms that the
native compiler actually applies class constraints. Both native sessions shut
down their owned services normally (Neo4j 0, Fuseki SIGTERM/143; no SIGKILL).

All inputs, plans, complete native rows, failures and independent source checks
are retained in [the native receipt](../../experiments/artifacts/d203_native_candidate_execution_20260910.json).
Raw local runs are `~/xgap-data/d203-native-candidates-20260910` and
`~/xgap-data/d203-native-types-20260910`. The source Parquet hash remains
`f1b21a5869da41938818a3f0f2ef2ead92fd5df978c2d5bf6fbaad31d3f650b1`;
the manifest hash remains
`efbd5e914e12f5263ffaf38e42dfecfcb16066c378989692f66b5538851e0b9f`.

## Historical model output: what now prevents an answer

Read-only preparation retains all **18 questions / 49 raw candidates** from
3796877. One question had a provider failure and no candidate. Among the 49,
38 have candidate-local grounding failures, 7 share a grounding-envelope
failure, and 4 pass typed/canonical grounding but lack an actual positive
entity equality. Under the explicitly declared entity-anchored execution goal,
**zero are dispatched**. The latter 4 belong to the airline-hub and patent/
invention questions; declared entity arrays alone do not narrow their queries.

The [historical receipt](../../experiments/artifacts/d203_historical_candidate_execution_20260910.json)
contains every question/candidate outcome and the unchanged source hash. This
adds an execution-goal result, not a rewrite of old semantic metrics, a fresh
LLM run, or a claim that the intended answers are absent from Freebase.

## Validation and next gate

Focused regression: **268 passed / 1 skipped in 2.61s**, including 45 new
offline tests. The tests execute emitted SPARQL using an independent RDFLib
engine and cover correlation, direction, type/identity/scalar constraints,
projection, malformed bindings, guard completeness and failure propagation.
Native runs above additionally test emitted Cypher and the real plugin/runtime
chain. Full offline regression: **2,827 passed / 38 skipped in 643.80s**
(`/tmp/xgap-d203-full.log`, original session 39813 completed exit 0). Harness
plus 21 examples pass, 22/22 entrypoints, including both new Freebase demos.
The first focused run had four assertions using the wrong runtime metric key;
the actual executions already matched. The assertions were corrected to
`total_remote_calls`; no production execution behavior changed in response.
The demo's initial field-name error was also fixed before native use.

This completes the controlled candidate-to-native-answer connection. The next missing evidence is a real model-generated,
anchored candidate producing a correct answer on inference-owned execution
facts. The existing fixed-v1 inline18 CWRU package still awaits a job ID. Its
frozen prompt/model/catalog/protocol are unchanged. An optional new anchor
feedback policy was not added in this slice: report the missing binding rather
than silently choosing an ID or changing the pending experiment.

Partial-source coverage, date ordering, general multivalued graph semantics,
variable-length constructs, candidate ranking and comparative performance are
not established here. Scalar validation adds a backend round trip; these local
single measurements are correctness evidence, not a speed claim. This result
also does not implement chunk retrieval, passage citations or RAG synthesis.
