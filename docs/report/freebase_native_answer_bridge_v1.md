# D202: real Freebase facts to federated typed answers

Status: LOCAL SOFTWARE AND REAL NATIVE ANSWER ACCEPTANCE COMPLETE. Parent milestone: H4. This is an execution/data bridge,
not another catalog build or an NL-accuracy experiment.

## Frozen scope and acceptance

Reuse D201's complete first-shard snapshot. Load its original N-Triples into
Fuseki, and mirror every URI-object fact into Neo4j as resource nodes with an
absolute `iri` identity and `RDF_RESOURCE_EDGE` relationships whose `predicate`
property is the exact predicate IRI. MERGE supplies RDF set semantics. Literal
values remain in Fuseki; they are never flattened into Neo4j scalar properties.
This explicit overlapping layout supports a single-Fuseki correctness baseline
and federated resource-path/literal-lookup plans over the same fact population.

Add bounded IRI VALUES binding at the SPARQL client boundary, then compile a
typed anchored resource path and literal projection into the existing runtime.
The Neo4j fragment uses the existing directed compiler. The coordinator binds
its resource IRIs into the Fuseki fragment and projects typed entity/answer rows.
Invalid bindings, backend failures and result-budget overflow fail explicitly.
No new algebra operators or changes to historical query behavior are allowed.

Allowed: new fact snapshot loading/query adapters, an explicitly local native
runner/example, the opt-in SPARQL binding client path, focused tests and docs.
Forbidden: old catalog/model/spec edits, source filtering using gold/questions,
invented Slurm allocations, automatic external retries, global Java changes,
silent literal coercion/truncation, or synthetic/partial data promoted to paper
or GrailQA answer accuracy. Existing CWRU Java-17 gates remain unchanged.

Acceptance:

1. Offline independent RDF execution and backend-boundary tests cover typed
   binding, OUT/IN paths, multiple literal values, empty results and failures.
2. The exact locked Neo4j 5.26.30 and Fuseki 5.6.0 distributions run locally,
   on loopback, with explicit heap/storage/time budgets and retained logs.
   This local environment uses the installed Java 21.0.10; it is not a CWRU run.
3. The retained 3,247,670-row source snapshot is consumed completely. Loader
   receipts separate RDF occurrences from distinct graph triples/edges.
4. A predeclared development query asks for English names of resources having
   `type.object.type = type.property`. The federated answer, full-Fuseki answer
   and source-data result must agree. This is a source-partial mechanism test.
   No catalog, model, reference answers or source rescan for candidate selection.
5. Focused tests, broad offline regression, harness and examples pass. Report
   actual answers, calls, bytes and limitations; shut down owned services.

Runtime compatibility sources: [Neo4j requirements](https://neo4j.com/docs/operations-manual/current/installation/requirements/)
list Java 17/21 for 5.26; [Jena 5.6 source build](https://github.com/apache/jena/blob/jena-5.6.0/pom.xml)
targets Java 17. Actual startup/query behavior on this Java 21 environment is
still required, not inferred from build metadata.

## Actual results — September 10, 2026

The locked native distributions ran on the local Mac with Homebrew OpenJDK
21.0.10. The complete retained first-shard snapshot was loaded once. Neo4j
resource-edge results were passed through the existing coordinator's bound
query node into Fuseki's new explicit IRI VALUES profile. The complete
entity/English-name answer sets agree across both native execution strategies
and a separate direct Arrow source evaluation of the predeclared query.

| Observation | Actual value |
|---|---:|
| Source/export occurrences consumed | 3,247,670 |
| Distinct RDF facts stored in Fuseki | 3,233,752 |
| URI-object occurrences consumed by Neo4j mirror | 541,677 |
| Distinct resource edges stored in Neo4j | 541,675 |
| Literal occurrences retained in Fuseki | 2,705,993 |
| Fact-loading operations, including checks/constraint/counts | 159 |
| Fact-loading elapsed time | 64.39 s |
| Resource matches / final entity-name pairs | 103 / 103 |
| Federated query backend calls | 2 |
| Single-Fuseki baseline backend calls | 1 |
| Federated coordinator elapsed time | 204.83 ms |
| Single-Fuseki client elapsed time | 16.76 ms |
| Neo4j result JSON row encoding | 9,044 bytes |
| Fuseki result JSON row encoding | 17,924 bytes |

These are single ordered development observations. The baseline runs after the
federated query; cache state and end-to-end timing boundaries differ. They show
no performance advantage and are not a controlled timing comparison. JSON row
sizes describe coordinator representations, not measured HTTP/network bytes.
The plan has no standalone Exchange nodes, so its existing `total_bytes_moved`
counter is zero; it must not be described as zero network transfer. The bound
node separately records 9,044 input bytes and 103 resource bindings.

Examples of actual answers include:

| Freebase resource | English name |
|---|---|
| `american_football.football_player.footballdb_id` | footballdb ID |
| `astronomy.astronomical_observatory.discoveries` | Discoveries |
| `automotive.body_style.fuel_tank_capacity` | Fuel Tank Capacity |
| `automotive.engine.engine_type` | Engine Type |
| `automotive.trim_level.max_passengers` | Maximum Number of Passengers |

The source Arrow evaluation scanned all 3,247,670 rows, found 103 resources and
103 answer pairs, and agreed exactly with the retained native answer. A separate
Arrow grouping over normalized RDF identity confirms both native distinct
counts: 13,918 duplicate input occurrences, including two resource duplicates.
This verifies the count difference is set deduplication, not partial loading.
It is not a full native RDF-term-stream equality proof. The distinct grouping
used 2,327,035,904 bytes peak process RSS on macOS and took 2.30 seconds; it is
an independent development check, not a streaming-load resource metric.

Both services terminated normally (Fuseki SIGTERM/143, Neo4j SIGTERM/0), with
no kill escalation. Owned database state remains reusable on disk (about 1.3 GiB).
The final native run took 87.85 seconds including staging/start/load/query/stop.

Two additional exploratory queries were declared before execution, then run by
restarting the same owned databases without loading any data again. They cover
actual entity classes rather than only schema resources:

| Class constraint | Resource matches | Entity/English-name pairs | Three-way answer agreement |
|---|---:|---:|---|
| `book.book` | 7 | 6 | Neo4j→Fuseki = full Fuseki = Arrow source |
| `people.person` | 2,234 | 202 | Neo4j→Fuseki = full Fuseki = Arrow source |

The smaller answer counts reflect the required English-name fact within this
partial shard, not truncation or missing loads. Actual book results include
`Dina's Book`, `The malediction` and `Tu, mio`; all six retained entity IDs and
names are in the receipt. Each federated query makes two calls. One ordered
observation per query records 460.87/554.45 ms for federation and 12.36/46.42 ms
for the subsequent single-Fuseki baseline. These additional checks are
exploratory mechanism observations, not a frozen benchmark population or
controlled performance study. Both services again stopped without escalation.

## Implementation, validation and preserved failures

- `sparql_bindings.py` and the opt-in Fuseki client path safely render finite,
  validated absolute resource IRIs into a declared VALUES column. Existing
  queries without that declaration keep their prior behavior.
- `freebase_backend_loading.py` verifies the existing snapshot parts and loads
  empty owned targets. It records each operation and preserves partial failures.
- `freebase_native_answers.py` compiles typed OUT/IN resource paths using the
  existing Neo4j directed compiler and constructs the existing bounded runtime
  plan. Literal projection retains language/datatype and multiple values.
  LIMIT + 1 is an overflow sentinel; excess rows are rejected, not accepted as
  a complete truncated answer. Empty paths short-circuit only the bound call.
- `freebase_local_native.py` is an explicitly local runner. It reuses archive
  verification and process lifecycle primitives, not the CWRU allocation gate.
  No Slurm allocation or remote server identity is fabricated.
- Focused validation: **241 passed, 2 skipped in 4.15s**, including 30 new offline
  tests and one separately gated live test. The actual local native runner above
  provides live evidence; the default pytest suite does not start services.
- Harness and all 19 prior acceptance examples pass (20/20 entrypoints).
- The broad offline suite completed in original session 43688:
  **2,782 passed, 38 skipped in 596.81 seconds**. All source hashes in the
  receipt were checked unchanged after the actual experiment and regression.

Two initial CLI invocations stopped at preparation/staging opt-in checks before
their corresponding action. The authorized preparation then downloaded each
locked archive once, verified exact bytes/digest, and succeeded. The CWRU staging
CLI was not enabled locally; the local runner uses generic safe archive staging.

The first local attempt stopped before service startup because the exact
Fuseki jar prints CLI help and then exits via `TerminationException` (exit 1).
The help validator was corrected to recognize that explicit help termination
and inspect its advertised options. A numbered diagnostic used the unchanged
verified archives; it was the first actual backend startup/load/query attempt.
The earlier failure, help output and later success are all retained.

RDFLib's resource-mirror parser emits conversion warnings for some BCE date
literals that Python's date implementation cannot represent. The original
N-Triples are uploaded unchanged to Fuseki, and literal values are not used by
the Neo4j mirror parser. Parsed occurrence counts, distinct source/native counts
and the 103 English-name answers pass. This run does not validate date-filter
semantics or exact preservation of every literal term inside the native store.

## Evidence custody and next gate

Actual native outputs, plans, logs and all 103 answers:
`/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/`.
Independent source answers:
`/Users/anthonyche/xgap-data/d202-source-query-20260910.json`.
First prelaunch diagnostic:
`/Users/anthonyche/xgap-data/d202-local-native-20260910/`.
Verified reusable archives:
`/Users/anthonyche/xgap-data/native-cache/`.
Additional book/person queries and independent source answers:
`/Users/anthonyche/xgap-data/d202-domain-queries-20260910/`.
The durable [experiment receipt and complete answers](../../experiments/artifacts/d202_native_freebase_answers_20260910.json)
contains the actual three answer sets, source/native identities, distinct counts,
timing/call/row-size observations, lifecycle results and validation log hashes.

The snapshot remains partial Freebase, selected before query inspection. The
query is a declared typed development request, not an LLM-produced GrailQA
prediction. H4 still needs inference-candidate lowering, broader semantic
operators/date constraints, target-data coverage and end-to-end real model
answers. Do not rebuild this snapshot/catalog or relaunch this successful
development measurement just because work continues.
