# INT-1: resource-triple encoding reaches ordinary planning and execution

2026-09-11. Parent91aa3f189160cdc2aaceb1f4ef0f184a864b10ed.
Research gates: R-E/E1 independent real answers and R-C/E2 same-meaning cost
comparisons. This closes the storage representation gap diagnosed at INT-0.
It is prototype correctness evidence, not an effectiveness or speedup result.

## Implemented behavior

An explicit `RdfResourceTripleEncoding` now connects the existing raw default RDF
graph and Neo4j resource mirror to ordinary `SemanticBackend`/Traverse/P1 execution.
Fixed one-to-three-hop resource paths produce complete node/predicate rows, then
one shared decoder constructs PathSet identities from stored triples. IN and OUT
retain the same stored-edge identity, duplicate triples fold, distinct predicates
remain distinct edges, and node/endpoint projection preserves canonical identities.

The source encoding carries snapshot/namespace/identity and row-budget provenance.
It cannot silently override another mapping. Unsupported scalar/edge-property
conditions, implicit unsupported restrictors, Match sources and edge projection
fail explicitly. This gate does not rewrite the graph, invent an algebra operator,
change P1's objective or turn answer-only legacy rows into paths.

Compilation is polynomial in explicit local alternatives and description size,
including canonical sorting. No joint placement enumeration is added. The
[contract](../decisions/freebase_resource_path_encoding_v1.md) states the supported
fragment and complexity; neither these bounds nor P1 certificates bound actual
backend latency.

## Directed verification

- 23 new decoder cases passed in0.13s: identity, direction, duplicates, lengths,
  malformed/literal/blank-node rows and overflow before deduplication.
- 5 new compiler/interface cases have passing evidence: independent RDF execution
  through ordinary P1, correct first-node answer, mapping/edge-projection rejection,
  and unsupported constraints. Initial collection imported PathMode from the wrong
  module; corrected. Tests initially used the wrong exception type/result nesting;
  only affected cases were corrected and rerun. The system execution itself had
  already succeeded before the result-assertion correction.
- 3 affected existing cases passed in0.28s: ordinary semantic DAG/fan-out,
  existing reified-path duplicate semantics and scoped admission. No broad suite
  and no A1/A2/A3 rerun.

The28 unique new cases are not presented as one clean first-pass pytest run.
Compiler evidence was1pass/4fail, then3pass/1fail on affected cases, then1pass
for the remaining assertion correction. This preserves the development record.

Read-only review found a real identity-inequality discrepancy: SPARQL restricted
logical ID inequality to the canonical namespace/ID domain, whereas the new Neo4j
branch initially omitted that guard. The guard was fixed before any native run.
The saved counterexample is now the fifth native program; both return an empty
answer on an external-IRI source, with no hidden type filter.

## One tiny native gate

Gate67378 exit0; Neo4j5.26.30 and Fuseki5.6.0, Java21, fresh owned loopback stores.
Five programs execute once on each backend, with independently authored complete
PathSet and endpoint gold:

| Program | Condition | Neo4j | Fuseki |
|---|---|---|---|
| RT01 | One-hop OUT; duplicate triple and same endpoints/different predicates | matches | matches |
| RT02 | IN; same stored edge identity, reversed endpoints | matches | matches |
| RT03 | Two-hop mixed WALK, including return to start | matches | matches |
| RT04 | Three-hop mixed SIMPLE with all-pairs inequalities | matches | matches |
| RT05 | Identity inequality excludes an external-namespace resource | matches empty | matches empty |

**12 backend calls total:2 loads +10 query executions**, no retries/model/catalog.
Raw reports, source triples/hash, independent gold, compiled programs and results:
`/Users/anthonyche/xgap-data/int1-resource-native-20260911/result.json` and `gate/`.
All334 source fingerprints matched after completion. Owned Fuseki23588 stopped
with SIGTERM/143 and Neo4j23552 with exit0; both shutdown receipts successful.
The compact [evidence receipt](../../experiments/artifacts/resource_triple_encoding_20260911.json)
binds source hashes, all ten native outcomes, test history and shutdown evidence.
The client-injected reusable gate is `scripts/check_resource_triple_native.py`;
the concrete owned-service invocation is saved as `runner.py` in the raw directory.

## Real inputs and remaining work

The original two INT-0 controlled-reference programs2100061004000 and2100063002000
now compile to both targets:4/4 compiler checks. The
[replay record](../../experiments/replays/resource_triple_int0_compilation_91aa3f1.json)
explicitly declares an unbound, compile-only fact snapshot. No actual answer is
claimed, and no gold was sent into interpretation or cost preparation.

The storage adapter is implemented for this resource-path fragment. Remaining
integration work is to recover/load query-independent real fact artifacts and
FinBench's original workpack, connect independent answer evaluation and prepared
forecast/cost provenance, and complete model LINK. Scalar-comparison paths remain
explicitly unsupported by this new representation adapter; legacy scalar handling
already exists and must be reused if required by the frozen evaluation profile.
Keep all GrailQA150/FinBench48 IDs and failures; do not narrow formal denominators
to this successful fragment or use toy results as the requested new paper results.
The earlier reference/official-SPARQL anchor-type difference still needs independent
fact-level verification. Job3804011 has no newly confirmed state in this gate.
