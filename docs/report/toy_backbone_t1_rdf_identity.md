# T1 progress: RDF edge identity in production compilation

The first T1 repair is verified. **T1 as a whole remains incomplete.** The frozen
five-node/eight-edge graph and all eighteen gold query chains are unchanged.

The directed compiler now accepts an explicit `RdfEdgeEncoding`: edge class,
source/target/label predicates, and either logical-string or mapped-IRI labels.
It emits one edge resource binding per path position, including IN traversal,
and compiles edge-property predicates against that resource. The existing
fragment adapter passes this dataset representation to the compiler. Typed RDF
results retain entity kinds and identity through the existing client/scheduler.
Node ID mapping remains independent. Ordinary predicate-based RDF is unchanged
when the new encoding is absent; no reification is inferred or built at runtime.

The encoding assumes stable edge IRIs and functional source, target, label and
scalar properties. It does not manufacture IDs for ordinary RDF triples or
assert cross-engine identity without a dataset-owned alignment. The toy result
adapter compares declared RDF resource IDs with Neo4j entity `id` properties.

## Actual production-compiled native results

| Query | Expected complete paths | Neo4j | Fuseki |
|---|---:|---:|---:|
| T02 all edges | 8 | 8 | 8 |
| T03 Alice one step | 3 | 3 | 3 |
| T04 numeric filter | 1 | 1 | 1 |
| T05 Alice two steps | 6 | 6 | 6 |
| T15 IN from Bob | 2 | 2 | 2 |
| T16 unequal endpoints | 5 | 5 | 5 |
| T17 empty result | 0 | 0 | 0 |
| T18 path with filter | 1 | 1 | 1 |

All **16/16 executions match the complete gold path sets**, not just counts.
Each executes the actual `DirectedRowFragmentCompiler` artifact through the
existing scheduler and one real backend call. The separate two-engine T18 slice
still returns `a/e4/c` with two calls. No independently hand-authored native target
is substituted for compiler output in this run. No LLM/catalog/large data/GPU is
used. This is correctness evidence, not latency or natural-language evaluation.

Original native session 60008 exited 0. Raw result, query text, rows, source and
fixture hashes, and lifecycle are retained under
`/Users/anthonyche/xgap-data/t1-rdf-native-20260910/`. Neo4j 5.26.30 and Fuseki
5.6.0 use fresh owned tiny stores, Java 21, and the existing five-minute driver
bound. Both services stopped normally without kill escalation; no retries.

## Local validation and next work

- Compiler/typed-answer/toy checks: **185 passed / 1 skipped in 9.82s**, session
  62974. The skip is the separately gated live RDF-answer test; new compiled
  native paths were tested by the explicit real-service run above.
- Existing Freebase fact/candidate and M9 fragment compatibility: **99 passed
  in 2.63s**, session 49131. These are offline checks, not a new large-data run.
- The fast daily toy command now includes reified compiler tests. Tests cover
  parallel edges, mixed IN/OUT, edge reuse, self-loop reuse, edge-property
  position, explicit label representation and legacy behavior.

The T0 broad regression remains historical evidence. A new whole-repository
regression is not claimed for this partial T1 step; daily targeted tests and the
tiny vertical slice follow the user's time/token-saving development rules.

Native coverage is now evidenced for eight of eighteen fixtures. The M5 IN
lowerer gap remains, although directed native execution of IN is now verified.
Node-only/Union, bounded recursive path modes and selectors still require
production compilation and execution. General partitioning, full Interpretation,
catalog build/runtime separation and failure replay remain open. Continue T1
from these unchanged fixtures; do not declare unsupported rows implemented.
