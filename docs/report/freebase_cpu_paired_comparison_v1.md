# D208: fixed-semantics CPU paired comparison

Status: implementation and validation in progress; no new measurements yet.

The September 10 user assessment requires genuine execution experiments to
continue without an LLM. This milestone compares the existing Neo4j→Fuseki
resource/literal plan with the complete single-Fuseki plan using the same
runtime and typed answer-normalization timing boundary. It does not change
the planner, algebra, data, catalog, frozen model experiment or FinBench result.

Allowed changes: a reusable experiment runner, focused tests, and reports.
Acceptance: separate warmup/measurement, balanced AB/BA order per query,
pre-execution request/attempt recording, explicit row/time budgets, no external
retry, retained failures/mismatches, equal actual answers against the already
retained independent source oracle, focused/full/examples acceptance, and
normal cleanup of owned services.

## Predeclared development protocol

Reuse the complete first-shard database from D202 without reloading. Use all
three previously exposed type/name queries: type.property, book.book and
people.person, in that declaration order. Each is an IN type.object.type
resource step followed by type.object.name restricted to English. This is a
three-query development diagnostic on partial Freebase, not a new population,
GrailQA question sample, held-out evaluation or confirmatory paper experiment.

Compile each existing query once before timing. Both strategies use the same
FederatedScheduler and Project boundary; measure dispatch through typed answer
normalization with a monotonic performance clock. Compilation, registry setup,
evidence serialization and oracle checking are excluded and documented.
The existing backend server/transport deadline is 120 seconds per request;
the experiment has a 600-second between-call deadline. The outer owned-service
driver has a 900-second wall-clock alarm. Keep 100,000 result rows and 16 MiB
IRI binding budgets for both plans where applicable; excess rows fail.

Two warmup rounds and eight measurement rounds give 60 planned executions:
12 warmups and 48 measurements. Rotate query order and alternate AB/BA so
each query has four measured pairs in each order. Predetermined repetitions
are measurements, not retries; the first failure or answer mismatch stops
the campaign and retains all attempted and unrun counts. No after-the-fact
removal, replacement round, or automatic rerun.

Report complete answer agreement, per-query/per-strategy median and observed
range, backend calls, result rows and canonical UTF-8 JSON row-encoding bytes.
The latter are not network bytes. Do not substitute the runtime Exchange-only
zero counter for traffic. Reuse the three independently obtained Arrow answer
files only after all timed runs; they never select queries/plans or source data.
This already exposed diagnostic is not suitable for inferential p-values or
general workload claims, irrespective of its repeated measurements.

The native driver reuses exact Neo4j 5.26.30/Fuseki 5.6.0 binaries, Java 21 and
owned D202 stores. It verifies its own ports are free, writes new logs/results,
and stops only its own processes. No GPU or remote job is required.
