# T1: all eighteen toy queries execute through production plans

Native gate passed: **18 queries × 2 real engines = 36/36 exact complete path
sets**. The separate two-engine T18 slice also passed. This bounded-path step
is accepted: full offline regression **3,006 passed / 38 skipped in 669.07s**,
original session11810 exit0, plus all24 harness/example entrypoints. The overall
system and full T1 are not declared complete.

## Implementation and semantics

`compile_bounded_paths` compiles typed Rel/Seq/Alt alternatives and root
Plus/Star with explicit finite depth into native queries. Depth counts child
path repetitions, not edges. Each branch goes through the production directed
compiler, retains edge identity and traversal direction, and joins at shared
nodes. Native Union deduplicates whole paths. Separate Cypher MATCH clauses
allow repeated use of an edge where WALK permits it. TRAIL, ACYCLIC and SIMPLE
restrictions compare native edge/node identities; SIMPLE allows the closing
repeat of its first node.

`compile_bounded_path_plan` places native candidate generation on the chosen
backend and an explicit `CoordinatorPathSelect` in the existing scheduler.
The coordinator normalizes declared entity identities and calls the same
GroupBy/OrderBy/Projection functions used by the reference evaluator, through
the existing selector lowering. This is a physical runtime adapter, not a new
path-algebra operator. Runtime latency and input/output sizes include its work.
The native query alone is a candidate query when a selector is present; it is
not advertised as producing the final selected answer by itself.

SHORTEST keeps all minimum-length paths per endpoint pair. Length conditions
remain above that operation. Star's zero paths remain separate from its
positive-length recursive paths, so a zero path does not erase a shortest
positive cycle. Extra tests verify both cases, selector variants beyond the
frozen eighteen, repeated-edge WALK, duplicate Union alternatives, and a
two-edge recursive child whose depth is measured in repetitions.

No compiler reads fixture IDs, expected answers or reference target files.
The fixture adapter supplies only the gold semantic input and declared dataset
representation before execution; it compares gold results afterward. RDF node
domain classes distinguish Nodes(G) from edge resources and metadata, retaining
isolated nodes. Stable canonical local IDs and explicit resource namespaces
align results across the two encodings.

## Operator-by-layer coverage

| Operator / feature | Frozen cases | Reference / logical layer | Production execution evidence |
|---|---|---|---|
| Nodes, zero path, isolated node | T01 | Existing Nodes/Union/Selection | Native node-domain query on both engines; 5 paths |
| Edges and edge identity | T02–T03 | Existing Edges/Selection | 8 edges; both a→b identities retained |
| Numeric Selection, endpoint inequality, empty | T04, T16–T17 | Existing Selection | Native predicates; 1, 5 and 0 exact paths |
| Join / Seq | T05 | Existing path concatenation | Native shared-node joins; 6 exact paths |
| Union / Alt | T06 | Existing set union | Native Union; 9 exact paths |
| Recursive WALK/TRAIL/ACYCLIC/SIMPLE | T07–T10 | Existing recursive modes | Bounded native expansion/restrictions; 19/18/10/13 paths |
| Recursive SHORTEST | T11 | Existing per-pair all-ties semantics | Native candidates + coordinator minimum; 7 paths |
| GroupBy / OrderBy / Projection | T12–T14 | Existing SolutionSpace semantics | Shared production coordinator stages; 7/3/5 paths |
| IN direction | T15 | Typed semantic Traverse; **M5 lowerer gap remains** | Native IN expansion; both reverse paths returned |
| Federated property filtering | T18 | Declared two-source placement | Neo4j path + Fuseki property + coordinator join; Alice→Cara |

All eighteen were executed as complete **single-backend plans on each engine**;
the additional T18 run is the actual two-backend federation check. This does not
mean every query has yet been partitioned across engines by a general optimizer.
The reference expected logical trees still match 17/18 through the M5 lowerer;
IN's distinct semantic/native route must not be relabeled as a fixed M5 lowerer.

## Evidence and limits

The complete acceptance script passed its harness, full suite and20 examples.
Three newer examples were run separately once (session32275 exit0) and are now
included in the script. Native source/fixture hashes still match; only this
future acceptance wiring and documents changed after the measured production
code. No repeat of accepted checks was needed.

- Native session **91427**, exit 0: real Neo4j 5.26.30 and Fuseki 5.6.0 on fresh
  owned toy stores, Java 21, 36/36 complete matches plus the two-call federated
  slice. Both services stopped normally, without escalation or retries.
- Focused final session **25002**, exit 0: **266 passed / 1 skipped in 10.97s**.
  The skip is the separately gated live RDF-answer test. This native gate
  independently exercised typed RDF path results through the real client.
- First local run: 26 pass / 1 fail. A generated Union containing the constant
  `FILTER(false)` returned an unwanted branch in RDFLib; the semantically
  equivalent `FILTER(1 = 0)` removed it. The production emitter now uses explicit
  constant comparisons. Gold/data were not changed.
- First expanded focused run: 265 pass / 1 fail / 1 skip. Extracting shared
  SolutionSpace functions changed legacy validation order; that behavior was
  restored. Both initial logs remain, and neither failure triggered an external
  retry.

Raw native results, all generated plans, actual entity rows and lifecycle are
in `/Users/anthonyche/xgap-data/t1-bounded-native-20260910/`. The compact durable
[receipt](../../experiments/artifacts/toy_backbone_t1_bounded_20260910.json)
contains complete gold/actual paths, executable plans, source/fixture hashes and
verification records. No frozen toy file changed.

Current native limits are explicit: root finite recursion over Rel/Seq/Alt,
default at most 128 branches and 64 edges per expanded path; SHORTEST requires
equal-length child alternatives. Nested recursion and unbounded native recursion
remain unsupported, not truncated. General boolean-condition compilation and
arbitrary logical-algebra trees retain their prior limits. The bounded expansion
strategy can grow combinatorially and selectors currently materialize candidate
rows at the coordinator; no scale/performance advantage is claimed.

Next T1 work is orientation-aware logical/reference coverage and integration
with general semantic/federated plan construction. T2 Interpretation, explicit
offline catalog freeze/runtime-only lookup and failure replay remain required.
Large benchmarks, real model quality, baseline comparisons and the full system
Goal remain open. These are toy correctness results, not paper evaluation.
